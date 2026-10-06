"""Resource ownership, execution epochs and the single command authority.

Atomicity: ``reserve`` never awaits, so under single-threaded asyncio it is atomic by construction.
A ``threading.RLock`` additionally guards the lease table so a future threaded transport cannot
interleave two reservations.
"""

import logging
import math
import threading
import uuid
from collections.abc import Iterable

from robot_framework.core.clock import Clock
from robot_framework.core.errors import (
    ContractValidationError,
    ResourceConflictError,
    StaleEpochError,
)
from robot_framework.spec import CommandAcknowledgement, CommandEnvelope, ControlMode, ResourceLease

log = logging.getLogger(__name__)

RETIRED_LEASE_MEMORY = 1024
"""How many retired lease ids are remembered to explain command rejections."""

LEASE_LIVE = "live"
LEASE_UNKNOWN = "unknown_lease"
LEASE_EXPIRED = "lease_expired"
LEASE_RELEASED = "lease_released"
STALE_EPOCH = "stale_epoch"


class ResourceManager:
    def __init__(self, clock: Clock, known_resources: frozenset[str]) -> None:
        self._clock = clock
        self._known = known_resources
        self._leases: dict[str, ResourceLease] = {}
        self._retired: dict[str, str] = {}
        self._epoch = 0
        self._epoch_history: tuple[tuple[int, str], ...] = ()
        self._lock = threading.RLock()

    @property
    def current_epoch(self) -> int:
        return self._epoch

    @property
    def known_resources(self) -> frozenset[str]:
        return self._known

    @property
    def epoch_history(self) -> tuple[tuple[int, str], ...]:
        return self._epoch_history

    def reserve(
        self,
        owner_id: str,
        resources: Iterable[str],
        control_mode: ControlMode,
        ttl_s: float,
        epoch: int | None = None,
    ) -> ResourceLease:
        """All-or-nothing reservation; raises ``ResourceConflictError`` listing current owners.

        With ``epoch`` set, the reservation is refused (``StaleEpochError``) unless that epoch is
        still current — checked under the same lock, so no reset can slip in between.
        """
        requested = frozenset(resources)
        unknown = sorted(requested - self._known)
        if unknown:
            raise ContractValidationError(
                f"unknown resource(s) {unknown}", details={"unknown": unknown}
            )
        _check_ttl(ttl_s)
        with self._lock:
            if epoch is not None and epoch != self._epoch:
                raise StaleEpochError(
                    f"reservation for epoch {epoch} refused; current epoch is {self._epoch}",
                    details={"epoch": epoch, "current_epoch": self._epoch},
                )
            self._sweep()
            conflicts = {
                resource: lease.owner_id
                for lease in self._leases.values()
                for resource in lease.resources
                if resource in requested
            }
            if conflicts:
                raise ResourceConflictError(
                    f"resources held by other owners: {conflicts}",
                    details={"conflicts": conflicts, "owner_id": owner_id},
                )
            lease = ResourceLease(
                lease_id=f"lease_{uuid.uuid4().hex[:12]}",
                owner_id=owner_id,
                resources=tuple(sorted(requested)),
                control_mode=control_mode,
                epoch=self._epoch,
                expires_at_monotonic=self._clock.monotonic() + ttl_s,
            )
            self._leases = {**self._leases, lease.lease_id: lease}
        log.info(
            "lease acquired",
            extra={"lease_id": lease.lease_id, "owner_id": owner_id, "epoch": lease.epoch},
        )
        return lease

    def release(self, lease_id: str) -> bool:
        """Idempotent. Returns True when a live lease was released by this call."""
        with self._lock:
            self._sweep()
            if lease_id not in self._leases:
                return False
            self._retire((lease_id,), LEASE_RELEASED)
        log.info("lease released", extra={"lease_id": lease_id})
        return True

    def renew(self, lease_id: str, ttl_s: float) -> ResourceLease:
        _check_ttl(ttl_s)
        with self._lock:
            self._sweep()
            lease = self._leases.get(lease_id)
            if lease is None:
                raise ResourceConflictError(
                    f"lease {lease_id} is not live",
                    details={"lease_id": lease_id, "reason": self._status_unlocked(lease_id)},
                )
            renewed = lease.model_copy(
                update={"expires_at_monotonic": self._clock.monotonic() + ttl_s}
            )
            self._leases = {**self._leases, lease_id: renewed}
        return renewed

    def get(self, lease_id: str) -> ResourceLease | None:
        with self._lock:
            self._sweep()
            return self._leases.get(lease_id)

    def is_live(self, lease_id: str) -> bool:
        return self.get(lease_id) is not None

    def lease_status(self, lease_id: str) -> str:
        with self._lock:
            self._sweep()
            return self._status_unlocked(lease_id)

    def owner_of(self, resource: str) -> str | None:
        return next(
            (lease.owner_id for lease in self.live_leases() if resource in lease.resources), None
        )

    def live_leases(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            self._sweep()
            return tuple(self._leases.values())

    def bump_epoch(self, reason: str) -> int:
        """Start a new execution epoch: every lease is released, every older command is stale."""
        with self._lock:
            self._retire(tuple(self._leases), STALE_EPOCH)
            self._epoch = self._epoch + 1
            self._epoch_history = (*self._epoch_history, (self._epoch, reason))
            epoch = self._epoch
        log.warning("epoch bumped", extra={"epoch": epoch, "reason": reason})
        return epoch

    def _status_unlocked(self, lease_id: str) -> str:
        if lease_id in self._leases:
            return LEASE_LIVE
        return self._retired.get(lease_id, LEASE_UNKNOWN)

    def _sweep(self) -> None:
        now = self._clock.monotonic()
        expired = tuple(i for i, lease in self._leases.items() if lease.expires_at_monotonic <= now)
        if expired:
            self._retire(expired, LEASE_EXPIRED)
            log.warning("leases expired", extra={"lease_ids": expired})

    def _retire(self, lease_ids: tuple[str, ...], reason: str) -> None:
        retired = {**self._retired, **{lease_id: reason for lease_id in lease_ids}}
        overflow = len(retired) - RETIRED_LEASE_MEMORY
        self._retired = dict(list(retired.items())[overflow:]) if overflow > 0 else retired
        self._leases = {i: lease for i, lease in self._leases.items() if i not in lease_ids}


def _check_ttl(ttl_s: float) -> None:
    if not math.isfinite(ttl_s) or ttl_s <= 0:
        raise ContractValidationError(f"lease ttl must be positive and finite, got {ttl_s}")


class CommandAuthority:
    """The single gate every command passes before it reaches a backend."""

    def __init__(self, resources: ResourceManager) -> None:
        self._resources = resources

    def check(self, envelope: CommandEnvelope) -> CommandAcknowledgement:
        reason = self._rejection_reason(envelope)
        if reason is not None:
            log.warning(
                "command rejected",
                extra={"envelope_id": envelope.envelope_id, "reason": reason},
            )
        return CommandAcknowledgement(
            envelope_id=envelope.envelope_id, accepted=reason is None, reason=reason
        )

    def _rejection_reason(self, envelope: CommandEnvelope) -> str | None:
        if envelope.epoch != self._resources.current_epoch:
            return STALE_EPOCH
        lease = self._resources.get(envelope.lease_id)
        if lease is None:
            return self._resources.lease_status(envelope.lease_id)
        if lease.epoch != envelope.epoch:
            return STALE_EPOCH
        if envelope.issuer_id != lease.owner_id:
            return "issuer_not_lease_owner"
        if not set(envelope.target_resources) <= set(lease.resources):
            return "resource_not_leased"
        if envelope.control_mode is not lease.control_mode:
            return "control_mode_mismatch"
        return None

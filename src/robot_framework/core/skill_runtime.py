"""Skill runtime: validate → resolve → assess → reserve → recheck → start → monitor → verify → commit.

Lifecycle semantics are specified in ``specification/semantics/lifecycle.md``. Two rules dominate:
cancel is a request and stop is an observation (``CANCELED`` only after the provider confirms),
and a provider's ``SUCCESS`` is not task success (only ``VERIFIED`` effects reach ``SUCCEEDED``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from robot_framework.core.errors import (
    ContractValidationError,
    ExtensionRequiredError,
    FrameworkError,
    ResourceConflictError,
    StaleEpochError,
)
from robot_framework.core.interfaces import ExecutionHandle, LoadedExtension, SkillProvider
from robot_framework.core.validation import param_problem, provider_fits
from robot_framework.spec import (
    AssessmentContext,
    AssessmentReport,
    AssessmentStatus,
    Condition,
    Fact,
    FailureCategory,
    FailureDiagnosis,
    LifecycleState,
    ProviderOutcome,
    ProviderStatus,
    ResourceLease,
    SkillContract,
    SkillInvocation,
    SkillNode,
    SkillResult,
    VerificationStatus,
    WorldSnapshot,
    bind_args,
)

if TYPE_CHECKING:
    from robot_framework.core.context import FrameworkContext

log = logging.getLogger(__name__)

CANCEL_REQUESTED = "cancel_requested"
"""Stop reason for an external cancel; every other stop reason is internal (a failure)."""

_STOP_CATEGORY: dict[str, FailureCategory] = {
    CANCEL_REQUESTED: "cancelled",
    "provider_timeout": "provider_timeout",
    "hold_violated": "hold_violated",
    "lease_lost": "lease_lost",
}

_State = LifecycleState
_Verdict = tuple[VerificationStatus, tuple[Fact, ...], tuple[str, ...]]


def _diag(category: FailureCategory, detail: str) -> FailureDiagnosis:
    return FailureDiagnosis(category=category, detail=detail)


@dataclass(frozen=True)
class _Watch:
    """What monitoring observed. ``outcome is None`` means the provider never confirmed a stop."""

    invocation: SkillInvocation
    outcome: ProviderOutcome | None
    stop_reason: str | None = None
    provider_done: asyncio.Future[ProviderOutcome] | None = None


class SkillRuntime:
    def __init__(self, ctx: FrameworkContext) -> None:
        self._ctx = ctx
        self._invocations: dict[str, SkillInvocation] = {}
        self._unsettled: dict[str, asyncio.Future[ProviderOutcome]] = {}
        self._background: set[asyncio.Future[Any]] = set()

    def invocation(self, invocation_id: str) -> SkillInvocation:
        try:
            return self._invocations[invocation_id]
        except KeyError:
            raise ContractValidationError(f"unknown invocation '{invocation_id}'") from None

    def provider_may_be_active(self, invocation_id: str) -> bool:
        """True while a provider that never confirmed its stop could still be acting."""
        pending = self._unsettled.get(invocation_id)
        return pending is not None and not pending.done()

    async def invoke(
        self, node: SkillNode, epoch: int | None = None, cancel: asyncio.Event | None = None
    ) -> SkillResult:
        stop = cancel if cancel is not None else asyncio.Event()
        contract = self._contract(node.skill_id)
        inv = self._validated(node, contract)
        stale = self._stale_epoch(epoch)
        if stale is not None:
            return self._finish(inv, _State.FAILED, diagnosis=stale)
        selected = await self._select_provider(inv, contract)
        if isinstance(selected, SkillResult):
            return selected
        provider, inv = selected
        unmet = self._check_conditions(inv, contract.preconditions)
        if unmet is not None:
            return self._finish(inv, _State.FAILED, diagnosis=unmet)
        lease = self._reserve(inv, contract, provider, epoch)
        if isinstance(lease, SkillResult):
            return lease
        try:
            inv = self._on_reserved(inv, lease)
            unmet = self._check_conditions(inv, contract.preconditions, time_sensitive_only=True)
            if unmet is not None:
                return self._finish(inv, _State.FAILED, diagnosis=unmet)
            return await self._execute(inv, contract, provider, lease, stop)
        finally:
            self._release(lease)

    async def reconcile(self, previous: SkillResult) -> SkillResult:
        """Re-observe the expected effects of a finished invocation before any retry.

        Effects already present → ``SUCCEEDED`` (``reconciled_success``, never re-executed);
        definitively absent → ``FAILED`` (safe to retry); inconclusive → unchanged. While a
        provider that never confirmed its stop may still be acting, nothing is concluded.
        """
        inv = self.invocation(previous.invocation_id)
        contract = self._contract(inv.skill_id)
        if self.provider_may_be_active(inv.invocation_id):
            self._ctx.recorder.record(
                "reconcile_blocked",
                {"invocation_id": inv.invocation_id, "reason": "provider stop not confirmed"},
            )
            return previous
        if not contract.verification.required:
            return previous
        status, facts, refs = await self._verify(inv, contract, phase="reconcile")
        if status is VerificationStatus.UNKNOWN:
            return previous
        verified = status is VerificationStatus.VERIFIED
        if verified:
            self._commit(inv, contract, facts)
        payload = {"invocation_id": inv.invocation_id, "node_id": inv.node_id}
        self._ctx.recorder.record(
            "reconciled_success" if verified else "reconciled_absent", payload
        )
        absent = _diag("verification_failed", "reconciliation: expected effects absent")
        return previous.model_copy(
            update={
                "state": _State.SUCCEEDED if verified else _State.FAILED,
                "verification_status": status,
                "observed_effects": facts,
                "evidence_references": (*previous.evidence_references, *refs),
                "failure_diagnosis": None if verified else absent,
                "reconciled": True,
            }
        )

    # -- step 1: validate --------------------------------------------------------------------

    def _contract(self, skill_id: str) -> SkillContract:
        if skill_id not in self._ctx.skills:
            raise ContractValidationError(f"skill '{skill_id}' is not registered")
        return self._ctx.skills.get(skill_id)

    def _validated(self, node: SkillNode, contract: SkillContract) -> SkillInvocation:
        needed = {p.name for p in contract.inputs if p.required} | contract.referenced_ports()
        problems = [
            *(f"missing parameter '{name}'" for name in sorted(needed - set(node.params))),
            *(
                f"unknown parameter '{name}'"
                for name in sorted(set(node.params) - {p.name for p in contract.inputs})
            ),
            *(
                problem
                for port in contract.inputs
                if port.name in node.params
                for problem in (param_problem(port, node.params[port.name]),)
                if problem is not None
            ),
        ]
        if problems:
            raise ContractValidationError(
                f"node '{node.node_id}' cannot invoke {contract.skill_id}: {'; '.join(problems)}",
                details={"node_id": node.node_id, "problems": problems},
            )
        inv = SkillInvocation(
            invocation_id=f"inv_{uuid.uuid4().hex[:12]}",
            node_id=node.node_id,
            skill_id=contract.skill_id,
            bound_params=dict(node.params),
            created_at=self._ctx.clock.now(),
        )
        self._remember(inv)
        self._record_state(inv, None)
        return self._transition(inv, _State.VALIDATED)

    def _stale_epoch(self, epoch: int | None) -> FailureDiagnosis | None:
        current = self._ctx.resources.current_epoch
        if epoch is None or epoch == current:
            return None
        return _diag("stale_epoch", f"mission epoch {epoch} is stale (current {current})")

    # -- steps 2-3: resolve and assess ---------------------------------------------------------

    def _candidates(self, contract: SkillContract) -> tuple[SkillProvider, ...]:
        fitting = [
            provider
            for provider in self._ctx.providers.items().values()
            if provider_fits(provider.manifest, contract, self._ctx.robot)
        ]
        preferred = self._ctx.profile.execution.provider_preference.get(contract.skill_id, ())
        rank = {provider_id: index for index, provider_id in enumerate(preferred)}
        return tuple(sorted(fitting, key=lambda p: rank.get(p.manifest.provider_id, len(rank))))

    async def _select_provider(
        self, inv: SkillInvocation, contract: SkillContract
    ) -> tuple[SkillProvider, SkillInvocation] | SkillResult:
        candidates = self._candidates(contract)
        if not candidates:
            detail = f"no eligible provider for '{contract.skill_id}'"
            return self._finish(inv, _State.FAILED, diagnosis=_diag("unsupported", detail))
        skipped: tuple[str, ...] = ()
        for provider in candidates:
            candidate = inv.model_copy(update={"provider_id": provider.manifest.provider_id})
            refusal = await self._assess(candidate, provider)
            if refusal is None:
                self._remember(candidate)
                self._ctx.recorder.record(
                    "provider_selected",
                    {"invocation_id": inv.invocation_id, "provider_id": candidate.provider_id},
                )
                return provider, candidate
            skipped = (*skipped, refusal)
        detail = "no feasible provider: " + "; ".join(skipped)
        return self._finish(inv, _State.FAILED, diagnosis=_diag("infeasible", detail))

    async def _assess(self, inv: SkillInvocation, provider: SkillProvider) -> str | None:
        """Return a refusal reason, or ``None`` when every extension allows this provider."""
        world = self._ctx.world.snapshot()
        for extension in self._ctx.extensions:
            report = await self._run_extension(extension, inv, provider, world)
            payload = {
                "invocation_id": inv.invocation_id,
                "extension_id": extension.extension_id,
                "report": report.model_dump(mode="json"),
            }
            self._ctx.recorder.record("assessment", payload)
            prefix = f"{provider.manifest.provider_id} via {extension.extension_id}"
            if report.status is AssessmentStatus.INFEASIBLE:
                return f"{prefix}: infeasible ({report.reason})"
            if report.status is AssessmentStatus.UNKNOWN:
                step = report.recommended_next_step
                if step is not None:
                    return f"{prefix}: unknown, recommends '{step.skill_id}' ({step.reason})"
                self._ctx.recorder.record("assessment_unknown", payload)
        return None

    async def _run_extension(
        self,
        extension: LoadedExtension,
        inv: SkillInvocation,
        provider: SkillProvider,
        world: WorldSnapshot,
    ) -> AssessmentReport:
        try:
            return await extension.plugin.assess(inv, provider.manifest, world)
        except Exception as exc:
            if extension.required:
                raise ExtensionRequiredError(
                    f"required extension '{extension.extension_id}' failed: {exc}",
                    details={"extension_id": extension.extension_id},
                ) from exc
            log.warning("optional extension failed", extra={"extension_id": extension.extension_id})
            self._ctx.recorder.record(
                "extension_warning",
                {"extension_id": extension.extension_id, "error": str(exc)},
            )
            return AssessmentReport(
                status=AssessmentStatus.NOT_APPLICABLE,
                reason=f"optional extension failed: {exc}",
                context=AssessmentContext(
                    world_snapshot_id=world.snapshot_id,
                    robot_state_revision=world.revision,
                    provider_id=provider.manifest.provider_id,
                ),
            )

    def _check_conditions(
        self,
        inv: SkillInvocation,
        conditions: Iterable[Condition],
        *,
        time_sensitive_only: bool = False,
    ) -> FailureDiagnosis | None:
        """First violated condition as a diagnosis: missing/old evidence is ``perception_stale``."""
        snapshot = self._ctx.world.snapshot()
        now = snapshot.time
        for condition in conditions:
            if time_sensitive_only and condition.max_age_s is None:
                continue
            args = bind_args(condition.args, inv.bound_params)
            label = f"{condition.predicate}({', '.join(args)})"
            fact = snapshot.lookup(condition.predicate, args)
            too_old = fact is not None and (
                fact.is_stale(now)
                or (
                    condition.max_age_s is not None
                    and now - fact.observation_time > condition.max_age_s
                )
            )
            if fact is None or too_old:
                return _diag("perception_stale", f"{label} is missing or too old")
            if fact.value != condition.expected:
                return _diag("precondition_unmet", f"{label} is {fact.value!r}")
        return None

    # -- step 4: reserve -----------------------------------------------------------------------

    def _reserve(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        provider: SkillProvider,
        epoch: int | None,
    ) -> ResourceLease | SkillResult:
        """Reserve atomically; the mission epoch is re-checked inside the reservation itself."""
        try:
            return self._ctx.resources.reserve(
                owner_id=inv.invocation_id,
                resources=contract.required_resources,
                control_mode=provider.manifest.control_mode,
                ttl_s=self._ctx.profile.execution.lease_ttl_s,
                epoch=epoch,
            )
        except ResourceConflictError as exc:
            return self._finish(inv, _State.FAILED, diagnosis=_diag("resource_conflict", str(exc)))
        except StaleEpochError as exc:
            return self._finish(inv, _State.FAILED, diagnosis=_diag("stale_epoch", str(exc)))

    def _on_reserved(self, inv: SkillInvocation, lease: ResourceLease) -> SkillInvocation:
        self._ctx.recorder.record(
            "lease_acquired",
            {"invocation_id": inv.invocation_id, "lease": lease.model_dump(mode="json")},
        )
        return self._transition(inv, _State.RESERVED, lease_id=lease.lease_id, epoch=lease.epoch)

    def _release(self, lease: ResourceLease) -> None:
        released = self._ctx.resources.release(lease.lease_id)
        self._ctx.recorder.record(
            "lease_released", {"lease_id": lease.lease_id, "was_live": released}
        )

    # -- steps 6-7: start and monitor ----------------------------------------------------------

    async def _execute(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        provider: SkillProvider,
        lease: ResourceLease,
        stop: asyncio.Event,
    ) -> SkillResult:
        if stop.is_set():
            detail = "cancel requested before the provider started; nothing was commanded"
            return self._finish(inv, _State.CANCELED, diagnosis=_diag("cancelled", detail))
        try:
            handle = await provider.start(inv, lease, self._ctx.backend)
        except FrameworkError as exc:
            diagnosis = _diag("unsupported", f"provider refused to start: {exc}")
            return self._finish(inv, _State.FAILED, diagnosis=diagnosis)
        except Exception as exc:
            log.exception("provider start raised", extra={"invocation_id": inv.invocation_id})
            detail = (
                f"provider start raised {type(exc).__name__}: {exc}; commands may have been sent"
            )
            return self._finish(inv, _State.OUTCOME_UNKNOWN, diagnosis=_diag("other", detail))
        inv = self._transition(inv, _State.RUNNING)
        provider_done = asyncio.ensure_future(handle.wait())
        try:
            watch = await self._monitor(inv, contract, handle, provider_done, lease, stop)
        except asyncio.CancelledError:
            wind_down = self._wind_down(inv, contract, handle, provider_done, lease)
            await asyncio.shield(asyncio.ensure_future(wind_down))
            raise
        return await self._conclude(watch, contract)

    async def _wind_down(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        handle: ExecutionHandle,
        provider_done: asyncio.Future[ProviderOutcome],
        lease: ResourceLease,
    ) -> SkillResult:
        """The invoking task was cancelled: stop the provider (bounded) before giving up."""
        watch = await self._stop(inv, contract, handle, provider_done, lease, CANCEL_REQUESTED)
        return await self._conclude(watch, contract)

    async def _conclude(self, watch: _Watch, contract: SkillContract) -> SkillResult:
        settled = self._settle(watch, contract)
        if settled is not None:
            return settled
        assert watch.outcome is not None
        return await self._verify_and_commit(watch.invocation, contract, watch.outcome)

    async def _monitor(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        handle: ExecutionHandle,
        provider_done: asyncio.Future[ProviderOutcome],
        lease: ResourceLease,
        stop: asyncio.Event,
    ) -> _Watch:
        poll_s = self._ctx.profile.execution.monitor_poll_s
        deadline = self._ctx.clock.monotonic() + contract.failure_semantics.timeout_s
        stop_requested = asyncio.ensure_future(stop.wait())
        waiters: set[asyncio.Future[Any]] = {provider_done, stop_requested}
        try:
            while True:
                done, _ = await asyncio.wait(
                    waiters,
                    timeout=poll_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if provider_done in done:
                    return _Watch(inv, _outcome_of(inv, provider_done), None, provider_done)
                reason = self._stop_reason(inv, contract, lease, stop, deadline)
                if reason is not None:
                    return await self._stop(inv, contract, handle, provider_done, lease, reason)
                lease = self._renew(lease, ttl_s=None)
        finally:
            stop_requested.cancel()

    def _stop_reason(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        lease: ResourceLease,
        stop: asyncio.Event,
        deadline: float,
    ) -> str | None:
        if stop.is_set():
            return CANCEL_REQUESTED
        if not self._ctx.resources.is_live(lease.lease_id):
            return "lease_lost"
        if self._ctx.clock.monotonic() >= deadline:
            return "provider_timeout"
        if self._check_conditions(inv, contract.hold_conditions) is not None:
            return "hold_violated"
        return None

    def _renew(self, lease: ResourceLease, ttl_s: float | None) -> ResourceLease:
        """Renew at half-life (``ttl_s=None``) or unconditionally for an explicit ``ttl_s``."""
        default_ttl = self._ctx.profile.execution.lease_ttl_s
        remaining = lease.expires_at_monotonic - self._ctx.clock.monotonic()
        if ttl_s is None and remaining > default_ttl / 2:
            return lease
        try:
            renewed = self._ctx.resources.renew(lease.lease_id, ttl_s or default_ttl)
        except ResourceConflictError:
            return lease
        self._ctx.recorder.record(
            "lease_renewed",
            {"lease_id": renewed.lease_id, "expires_at_monotonic": renewed.expires_at_monotonic},
        )
        return renewed

    async def _stop(
        self,
        inv: SkillInvocation,
        contract: SkillContract,
        handle: ExecutionHandle,
        provider_done: asyncio.Future[ProviderOutcome],
        lease: ResourceLease,
        reason: str,
    ) -> _Watch:
        """Request a stop and wait, bounded by ``max_stop_time_s``, for the provider to confirm.

        The cancel request runs in the background so a provider whose ``cancel()`` blocks cannot
        stretch the bound, and the provider is never torn down: an unconfirmed stop stays tracked.
        """
        inv = self._transition(inv, _State.CANCELING, reason=reason)
        max_stop_s = contract.cancellation.max_stop_time_s
        self._renew(lease, ttl_s=self._ctx.profile.execution.lease_ttl_s + max_stop_s)
        self._track(asyncio.ensure_future(handle.cancel(reason)))
        done, _ = await asyncio.wait({provider_done}, timeout=max_stop_s)
        outcome = _outcome_of(inv, provider_done) if done else None
        return _Watch(inv, outcome, reason, provider_done)

    def _settle(self, watch: _Watch, contract: SkillContract) -> SkillResult | None:
        """Terminal result for everything except a provider SUCCESS, which goes to verification."""
        inv, outcome, reason = watch.invocation, watch.outcome, watch.stop_reason
        if outcome is None:
            assert reason is not None and watch.provider_done is not None
            self._unsettled = {**self._unsettled, inv.invocation_id: watch.provider_done}
            self._track(watch.provider_done)
            detail = f"{reason}: stop not confirmed within {contract.cancellation.max_stop_time_s}s"
            category = _STOP_CATEGORY[reason]
            return self._finish(inv, _State.OUTCOME_UNKNOWN, diagnosis=_diag(category, detail))
        status = outcome.status
        if status == "SUCCESS":
            return None
        if status == "UNKNOWN":
            diagnosis = outcome.diagnosis or _diag("ack_lost", "provider outcome unknown")
            return self._finish(
                inv, _State.OUTCOME_UNKNOWN, provider_status=status, diagnosis=diagnosis
            )
        if reason == CANCEL_REQUESTED:
            diagnosis = _diag("cancelled", "stopped on request; provider confirmed")
            return self._finish(inv, _State.CANCELED, provider_status=status, diagnosis=diagnosis)
        if reason is not None:
            diagnosis = _diag(_STOP_CATEGORY[reason], f"{reason}; provider confirmed stop")
            return self._finish(inv, _State.FAILED, provider_status=status, diagnosis=diagnosis)
        if status == "CANCELED":
            diagnosis = _diag("cancelled", "provider canceled without a request")
            return self._finish(inv, _State.FAILED, provider_status=status, diagnosis=diagnosis)
        diagnosis = outcome.diagnosis or _diag("other", "provider reported failure")
        return self._finish(inv, _State.FAILED, provider_status=status, diagnosis=diagnosis)

    def _track(self, future: asyncio.Future[Any]) -> None:
        """Keep a background future alive and surface (log) its failure."""
        self._background = {*self._background, future}
        future.add_done_callback(self._forget)

    def _forget(self, future: asyncio.Future[Any]) -> None:
        self._background = self._background - {future}
        if not future.cancelled() and future.exception() is not None:
            log.warning("background provider call failed", extra={"error": str(future.exception())})

    # -- steps 8-9: verify and commit ----------------------------------------------------------

    async def _verify_and_commit(
        self, inv: SkillInvocation, contract: SkillContract, outcome: ProviderOutcome
    ) -> SkillResult:
        inv = self._transition(inv, _State.VERIFYING)
        claims = outcome.evidence_references
        if not contract.verification.required:
            return self._finish(
                inv,
                _State.SUCCEEDED,
                provider_status=outcome.status,
                verification=VerificationStatus.NOT_REQUIRED,
                evidence=claims,
            )
        status, facts, refs = await self._verify(inv, contract, phase="verify")
        common: dict[str, Any] = {
            "provider_status": outcome.status,
            "verification": status,
            "effects": facts,
            "evidence": (*claims, *refs),
        }
        if status is VerificationStatus.VERIFIED:
            self._commit(inv, contract, facts)
            return self._finish(inv, _State.SUCCEEDED, **common)
        if status is VerificationStatus.FAILED:
            detail = "expected effects not observed (provider reported SUCCESS)"
            return self._finish(
                inv, _State.FAILED, diagnosis=_diag("verification_failed", detail), **common
            )
        detail = "verification inconclusive: evidence missing, stale or from another epoch"
        return self._finish(
            inv, _State.OUTCOME_UNKNOWN, diagnosis=_diag("verification_failed", detail), **common
        )

    async def _verify(
        self, inv: SkillInvocation, contract: SkillContract, *, phase: str
    ) -> _Verdict:
        """Run the verifier; evidence from another execution epoch is never conclusive."""
        epoch = self._ctx.resources.current_epoch
        verdict: _Verdict
        if inv.epoch is not None and inv.epoch != epoch:
            verdict = (VerificationStatus.UNKNOWN, (), (f"stale_epoch:{inv.epoch}->{epoch}",))
        else:
            verdict = await self._run_verifier(inv, contract)
            if self._ctx.resources.current_epoch != epoch:
                refs = (*verdict[2], "epoch_changed_during_verification")
                verdict = (VerificationStatus.UNKNOWN, (), refs)
        status, facts, _ = verdict
        self._ctx.recorder.record(
            "verification",
            {
                "invocation_id": inv.invocation_id,
                "phase": phase,
                "verifier_id": contract.verification.verifier_id,
                "status": status.value,
                "facts": [fact.model_dump(mode="json") for fact in facts],
            },
        )
        return verdict

    async def _run_verifier(self, inv: SkillInvocation, contract: SkillContract) -> _Verdict:
        verifier_id = contract.verification.verifier_id
        try:
            verifier = self._ctx.verifiers.get(verifier_id)
            return await verifier.verify(contract, inv, self._ctx.world)
        except Exception as exc:
            log.warning("verifier failed", extra={"verifier_id": verifier_id, "error": str(exc)})
            return VerificationStatus.UNKNOWN, (), (f"verifier_error:{exc}",)

    def _commit(
        self, inv: SkillInvocation, contract: SkillContract, facts: tuple[Fact, ...]
    ) -> None:
        """Only verified effects are committed, with the verifier as the source."""
        revision = self._ctx.world.commit(facts, source=contract.verification.verifier_id)
        self._ctx.recorder.record(
            "effects_committed",
            {"invocation_id": inv.invocation_id, "revision": revision, "count": len(facts)},
        )

    # -- lifecycle bookkeeping -----------------------------------------------------------------

    def _remember(self, inv: SkillInvocation) -> None:
        self._invocations = {**self._invocations, inv.invocation_id: inv}

    def _transition(
        self, inv: SkillInvocation, state: LifecycleState, reason: str | None = None, **updates: Any
    ) -> SkillInvocation:
        moved = inv.model_copy(update={"state": state, **updates})
        self._remember(moved)
        self._record_state(moved, inv.state, reason)
        return moved

    def _record_state(
        self, inv: SkillInvocation, previous: LifecycleState | None, reason: str | None = None
    ) -> None:
        payload = {
            "invocation_id": inv.invocation_id,
            "node_id": inv.node_id,
            "skill_id": inv.skill_id,
            "provider_id": inv.provider_id,
            "from": previous.value if previous is not None else None,
            "to": inv.state.value,
            "reason": reason,
        }
        self._ctx.recorder.record("skill_state", payload)
        log.info(
            "skill state",
            extra={
                "invocation_id": inv.invocation_id,
                "skill_id": inv.skill_id,
                "state": inv.state.value,
            },
        )

    def _finish(
        self,
        inv: SkillInvocation,
        state: LifecycleState,
        *,
        provider_status: ProviderStatus | None = None,
        verification: VerificationStatus = VerificationStatus.NOT_RUN,
        effects: tuple[Fact, ...] = (),
        evidence: tuple[str, ...] = (),
        diagnosis: FailureDiagnosis | None = None,
    ) -> SkillResult:
        reason = diagnosis.category if diagnosis is not None else None
        final = self._transition(inv, state, reason=reason)
        return SkillResult(
            invocation_id=final.invocation_id,
            node_id=final.node_id,
            skill_id=final.skill_id,
            provider_id=final.provider_id,
            provider_status=provider_status,
            state=state,
            observed_effects=effects,
            verification_status=verification,
            evidence_references=evidence,
            failure_diagnosis=diagnosis,
        )


def _outcome_of(inv: SkillInvocation, done: asyncio.Future[ProviderOutcome]) -> ProviderOutcome:
    """A provider that crashed mid-execution leaves the physical outcome unknown."""
    try:
        return done.result()
    except Exception as exc:
        return ProviderOutcome(
            invocation_id=inv.invocation_id,
            status="UNKNOWN",
            diagnosis=_diag("other", f"provider raised {type(exc).__name__}: {exc}"),
        )

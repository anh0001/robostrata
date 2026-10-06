import pytest

from robot_framework.core.clock import MockClock
from robot_framework.core.errors import (
    ContractValidationError,
    ResourceConflictError,
    StaleEpochError,
)
from robot_framework.core.resource_manager import (
    RETIRED_LEASE_MEMORY,
    CommandAuthority,
    ResourceManager,
)
from robot_framework.spec import CommandEnvelope, ControlMode, ResourceLease

RESOURCES = frozenset({"base", "arm_0", "gripper_0"})
MODE = ControlMode.TRAJECTORY


@pytest.fixture
def clock():
    return MockClock()


@pytest.fixture
def manager(clock):
    return ResourceManager(clock, RESOURCES)


def envelope(lease: ResourceLease, **overrides) -> CommandEnvelope:
    fields = {
        "envelope_id": "env_1",
        "issuer_id": lease.owner_id,
        "lease_id": lease.lease_id,
        "epoch": lease.epoch,
        "target_resources": lease.resources,
        "control_mode": lease.control_mode,
        "issued_at_monotonic": 0.0,
    }
    return CommandEnvelope(**{**fields, **overrides})


def test_reserve_is_all_or_nothing(manager):
    manager.reserve("owner_a", ["base"], MODE, ttl_s=10)

    with pytest.raises(ResourceConflictError) as exc_info:
        manager.reserve("owner_b", ["base", "arm_0"], MODE, ttl_s=10)

    assert exc_info.value.details["conflicts"] == {"base": "owner_a"}
    assert manager.owner_of("arm_0") is None
    assert manager.owner_of("base") == "owner_a"


def test_reserve_rejects_unknown_resources_and_bad_ttl(manager):
    with pytest.raises(ContractValidationError, match="unknown resource"):
        manager.reserve("owner", ["wing_0"], MODE, ttl_s=1)
    with pytest.raises(ContractValidationError, match="ttl"):
        manager.reserve("owner", ["base"], MODE, ttl_s=0)


def test_lease_expires_on_monotonic_clock(manager, clock):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=1)
    authority = CommandAuthority(manager)

    clock.advance_monotonic_only(2)

    assert manager.owner_of("arm_0") is None
    assert manager.lease_status(lease.lease_id) == "lease_expired"
    ack = authority.check(envelope(lease))
    assert not ack.accepted and ack.reason == "lease_expired"


def test_observation_clock_does_not_expire_leases(manager, clock):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=1)

    clock.advance_observation_only(100)

    assert manager.is_live(lease.lease_id)


def test_bump_epoch_rejects_old_commands(manager):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=10)
    authority = CommandAuthority(manager)

    new_epoch = manager.bump_epoch("sim_reset")

    assert new_epoch == lease.epoch + 1 == manager.current_epoch
    ack = authority.check(envelope(lease))
    assert not ack.accepted and ack.reason == "stale_epoch"
    assert manager.live_leases() == ()
    assert manager.epoch_history == ((1, "sim_reset"),)


def test_command_claiming_the_new_epoch_with_an_old_lease_is_rejected(manager):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=10)
    manager.bump_epoch("sim_reset")

    ack = CommandAuthority(manager).check(envelope(lease, epoch=manager.current_epoch))

    assert not ack.accepted and ack.reason == "stale_epoch"


def test_release_is_idempotent_and_explains_rejections(manager):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=10)

    assert manager.release(lease.lease_id) is True
    assert manager.release(lease.lease_id) is False
    ack = CommandAuthority(manager).check(envelope(lease))
    assert ack.reason == "lease_released"
    assert manager.reserve("other", ["arm_0"], MODE, ttl_s=10).owner_id == "other"


def test_renew_extends_expiry(manager, clock):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=1)
    clock.advance_monotonic_only(0.8)

    renewed = manager.renew(lease.lease_id, ttl_s=1)
    clock.advance_monotonic_only(0.8)

    assert renewed.expires_at_monotonic == pytest.approx(1.8)
    assert manager.is_live(lease.lease_id)
    with pytest.raises(ResourceConflictError, match="not live"):
        manager.renew("lease_unknown", ttl_s=1)


def test_authority_accepts_a_valid_command(manager):
    lease = manager.reserve("owner", ["arm_0", "gripper_0"], MODE, ttl_s=10)

    ack = CommandAuthority(manager).check(envelope(lease, target_resources=("arm_0",)))

    assert ack.accepted and ack.reason is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"target_resources": ("base",)}, "resource_not_leased"),
        ({"control_mode": ControlMode.VELOCITY}, "control_mode_mismatch"),
        ({"lease_id": "lease_forged"}, "unknown_lease"),
        ({"issuer_id": "someone_else"}, "issuer_not_lease_owner"),
    ],
)
def test_authority_rejects_commands_outside_the_lease(manager, overrides, reason):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=10)

    ack = CommandAuthority(manager).check(envelope(lease, **overrides))

    assert not ack.accepted and ack.reason == reason


def test_retired_lease_memory_is_bounded(manager):
    first = manager.reserve("owner", ["arm_0"], MODE, ttl_s=10)
    manager.release(first.lease_id)

    for _ in range(RETIRED_LEASE_MEMORY):
        manager.release(manager.reserve("owner", ["arm_0"], MODE, ttl_s=10).lease_id)

    assert manager.lease_status(first.lease_id) == "unknown_lease"


def test_reserve_refuses_a_stale_epoch_atomically(manager):
    epoch = manager.current_epoch
    manager.bump_epoch("sim_reset")

    with pytest.raises(StaleEpochError, match="refused"):
        manager.reserve("owner", ["arm_0"], MODE, ttl_s=10, epoch=epoch)

    assert manager.live_leases() == ()
    assert manager.reserve("owner", ["arm_0"], MODE, ttl_s=10, epoch=manager.current_epoch)


@pytest.mark.parametrize("ttl_s", [float("inf"), float("nan"), -1.0])
def test_lease_ttl_must_be_bounded(manager, ttl_s):
    lease = manager.reserve("owner", ["arm_0"], MODE, ttl_s=1)

    with pytest.raises(ContractValidationError, match="finite"):
        manager.reserve("other", ["base"], MODE, ttl_s=ttl_s)
    with pytest.raises(ContractValidationError, match="finite"):
        manager.renew(lease.lease_id, ttl_s=ttl_s)

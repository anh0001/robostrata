import pytest

from builders import fact
from robot_framework.core.clock import MockClock, SystemClock
from robot_framework.core.world_interface import InMemoryWorld


@pytest.fixture
def clock():
    return MockClock(now=100.0)


@pytest.fixture
def world(clock):
    return InMemoryWorld(clock)


def test_commit_bumps_revision_once_per_batch_and_stamps_source(world):
    revision = world.commit([fact("at", "robot", "a", time=100.0), fact("door_open", "d1")], "nav")

    assert revision == world.revision == 1
    stored = world.lookup("at", ("robot", "a"))
    assert stored.revision == 1 and stored.source == "nav"
    assert world.commit([], "nav") == 1


def test_commit_replaces_facts_by_key(world):
    world.commit([fact("holding", "robot", "x", value=True)], "a")
    world.commit([fact("holding", "robot", "x", value=False)], "b")

    snapshot = world.snapshot()

    assert len(snapshot.facts) == 1
    assert snapshot.lookup("holding", ("robot", "x")).value is False


def test_snapshot_does_not_change_after_later_commits(world):
    before = world.snapshot()
    world.commit([fact("at", "robot", "a")], "nav")

    assert before.facts == () and before.revision == 0
    assert world.snapshot().snapshot_id != before.snapshot_id


def test_world_marks_fact_stale(world, clock):
    world.commit([fact("pose_known", "bottle", time=100.0, validity_s=5.0)], "cam")
    stored = world.lookup("pose_known", ("bottle",))

    clock.advance_observation_only(4)
    fresh = world.is_stale(stored)
    clock.advance_observation_only(2)

    assert not fresh
    assert world.is_stale(stored)


def test_observe_without_source_returns_none(world):
    assert world.revision == 0
    assert world.lookup("holding", ("robot", "x")) is None


async def test_observe_without_a_registered_source_is_not_observable(world):
    assert await world.observe("holding", ("robot", "x")) is None
    assert world.revision == 0


async def test_observe_commits_a_fresh_observation(world, clock):
    truth = {("robot", "x"): True}
    world.register_observation_source("holding", truth.get, source_id="sim", validity_s=2.0)
    clock.advance_observation_only(7)

    observed = await world.observe("holding", ("robot", "x"))

    assert observed.value is True
    assert observed.observation_time == 107.0
    assert observed.source == "sim" and observed.validity_s == 2.0
    assert observed.revision == world.revision == 1
    assert await world.observe("holding", ("robot", "unknown")) is None


def test_invalidate_all_marks_facts_stale_without_deleting(world):
    world.commit([fact("at", "robot", "a", time=100.0), fact("door_open", "d1", time=100.0)], "x")

    revision = world.invalidate_all("sim_reset")

    facts = world.snapshot().facts
    assert len(facts) == 2
    assert all(world.is_stale(f) for f in facts)
    assert world.invalidations == ((revision, "sim_reset"),)


def test_mock_clock_moves_time_bases_independently():
    clock = MockClock(now=10.0, mono=1.0)

    clock.advance_observation_only(5)
    clock.advance_monotonic_only(2)
    clock.advance(1)

    assert (clock.now(), clock.monotonic()) == (16.0, 4.0)
    with pytest.raises(ValueError, match="forward"):
        clock.advance(-1)


def test_system_clock_reports_both_time_bases():
    clock = SystemClock()

    assert clock.now() > 1e9
    assert clock.monotonic() <= clock.monotonic()

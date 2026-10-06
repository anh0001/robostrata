from builders import make_context, mock_provider, sim
from robot_framework.core.clock import SystemClock
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.spec import LifecycleState, MissionEvent, MissionStatus, VerificationStatus

EXPECTED_NODES = ["go_to_pickup", "observe_object", "pick_object", "go_to_delivery", "place_object"]


async def test_full_mission_via_profile_succeeds_with_verified_effects(ctx, goal):
    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.SUCCEEDED
    assert [r.node_id for r in result.skill_results] == EXPECTED_NODES
    assert all(r.state is LifecycleState.SUCCEEDED for r in result.skill_results)
    assert all(r.verification_status is VerificationStatus.VERIFIED for r in result.skill_results)
    effects = {(f.predicate, f.args, f.value) for f in result.verified_effects}
    assert ("at", ("bottle_17", "desk_2"), True) in effects
    assert ("holding", ("robot", "bottle_17"), False) in effects
    world = ctx.world.snapshot()
    assert world.lookup("at", ("bottle_17", "desk_2")).value is True
    assert ctx.resources.live_leases() == ()


async def test_every_command_is_accepted_and_stays_inside_the_plan_scope(ctx, goal):
    supervisor = MissionSupervisor(ctx)
    scope = (await supervisor.prepare(goal)).resource_scope

    await supervisor.run(goal)

    backend = sim(ctx)
    assert backend.dispatched and backend.accepted == backend.dispatched
    assert all(set(e.target_resources) <= scope for e in backend.dispatched)
    assert [
        len(mock_provider(ctx, p).started)
        for p in ("mock.navigate", "mock.observe", "mock.pick", "mock.place")
    ] == [2, 1, 1, 1]


async def test_mission_record_is_a_replayable_jsonl_file(tmp_path, goal):
    record = tmp_path / "mission.jsonl"
    ctx = make_context(record_path=record)

    result = await MissionSupervisor(ctx).run(goal)

    events = [MissionEvent.model_validate_json(line) for line in record.read_text().splitlines()]
    assert events == list(ctx.recorder.events())
    assert events[0].kind == "goal_received" and events[-1].kind == "mission_finished"
    assert {e.mission_id for e in events} == {result.mission_id}
    assert [e.sequence for e in events] == list(range(len(events)))
    transitions = [e for e in events if e.kind == "skill_state"]
    assert len(transitions) == 6 * len(EXPECTED_NODES)


async def test_mission_runs_on_the_system_clock(goal):
    ctx = make_context(clock=SystemClock())

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.SUCCEEDED

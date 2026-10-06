import asyncio

import pytest

from builders import (
    TEST_SKILL,
    StaticPlanner,
    add_move_skill,
    delivery_goal,
    fact,
    graph_proposal,
    make_context,
    mock_clock,
    mock_provider,
    move_contract,
    seed,
    sim,
    skill_node,
    states_of,
    wait_for_state,
    with_execution,
    with_planner,
)
from robot_framework.core.errors import MissionAlreadyRunningError, PlanRejectedError
from robot_framework.core.mission_supervisor import MissionSupervisor, rejection_reasons
from robot_framework.executives.sequential import SequentialExecutive
from robot_framework.providers.mock import MockFaults
from robot_framework.spec import (
    Constraint,
    HumanInteractionPolicy,
    LifecycleState,
    MissionStatus,
    PlanArtifactKind,
    SuccessCriterion,
)


def codes(result):
    return {reason.code for reason in result.rejection_reasons}


async def test_supervisor_runs_the_default_goal(ctx, goal):
    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.SUCCEEDED
    assert result.failure_reason is None and result.events_ref is None
    kinds = [e.kind for e in ctx.recorder.events()]
    assert kinds[0] == "goal_received" and kinds[-1] == "mission_finished"
    assert "plan_validated" in kinds


async def test_only_one_mission_runs_at_a_time(ctx, goal):
    ctx.providers.get("mock.navigate").configure(MockFaults(duration_s=0.2, steps=4))
    supervisor = MissionSupervisor(ctx)

    first = asyncio.ensure_future(supervisor.run(goal))
    await asyncio.sleep(0)
    with pytest.raises(MissionAlreadyRunningError):
        await supervisor.run(goal)
    result = await first

    assert result.status is MissionStatus.SUCCEEDED
    assert not supervisor.is_running


async def test_deadline_cancels_the_mission(ctx):
    ctx.providers.get("mock.navigate").configure(MockFaults(duration_s=1.0, steps=20))

    result = await MissionSupervisor(ctx).run(delivery_goal(deadline_s=0.05))

    assert result.status is MissionStatus.FAILED
    assert result.failure_reason == "deadline_exceeded"
    assert result.skill_results[-1].state is LifecycleState.CANCELED


async def test_operator_cancel_ends_in_canceled(ctx, goal):
    ctx.providers.get("mock.navigate").configure(MockFaults(duration_s=1.0, steps=20))
    supervisor = MissionSupervisor(ctx)

    run = asyncio.ensure_future(supervisor.run(goal))
    await wait_for_state(ctx, LifecycleState.RUNNING)
    await supervisor.cancel("operator_request")
    result = await run

    assert result.status is MissionStatus.CANCELED
    assert ctx.recorder.events("mission_canceled")[0].payload == {"reason": "operator_request"}
    await supervisor.cancel()  # idle: no-op


async def test_unmet_success_criteria_fail_the_mission(ctx):
    extra = SuccessCriterion(predicate="at", args=("bottle_17", "moon"))
    goal = delivery_goal(success_criteria=(*delivery_goal().success_criteria, extra))

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.FAILED
    assert result.failure_reason.startswith("success_criteria_unmet")
    assert "at(bottle_17, moon)" in result.failure_reason


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"constraints": (Constraint(name="max_speed"),)}, "unsupported_constraint"),
        (
            {"human_policy": HumanInteractionPolicy(require_plan_confirmation=True)},
            "operator_confirmation_unsupported",
        ),
        ({"objective": "make_coffee"}, "unknown_objective"),
        ({"parameters": {"object": "bottle_17"}}, "unresolved_goal_parameter"),
    ],
)
async def test_goals_that_cannot_be_honoured_are_rejected(ctx, updates, code):
    result = await MissionSupervisor(ctx).run(delivery_goal(**updates))

    assert result.status is MissionStatus.REJECTED
    assert codes(result) == {code}
    assert ctx.recorder.events("skill_state") == ()


async def test_soft_constraints_are_accepted(ctx):
    goal = delivery_goal(constraints=(Constraint(name="quiet_hours", hard=False),))

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.SUCCEEDED


async def test_planner_output_must_match_the_profile(ctx, goal):
    planning = ctx.profile.planning.model_copy(
        update={"output_kind": PlanArtifactKind.TEMPORAL_PLAN}
    )
    ctx = ctx.__class__(
        **{**ctx.__dict__, "profile": ctx.profile.model_copy(update={"planning": planning})}
    )

    result = await MissionSupervisor(ctx).run(goal)

    assert codes(result) == {"unexpected_artifact_kind"}


async def test_events_ref_points_at_the_recording(tmp_path, goal):
    record = tmp_path / "mission.jsonl"
    ctx = make_context(record_path=record)

    result = await MissionSupervisor(ctx).run(goal)

    assert result.events_ref == str(record)
    assert record.read_text().count("\n") == len(ctx.recorder.events())


def test_rejection_reasons_fall_back_to_the_error_itself():
    reasons = rejection_reasons(PlanRejectedError("no reasons attached"))

    assert [(r.code, r.detail) for r in reasons] == [("plan_rejected", "no reasons attached")]


def move_planner():
    return StaticPlanner(lambda world: graph_proposal(skill_node(TEST_SKILL, target="box_1")))


async def test_unconfirmed_stop_after_deadline_is_outcome_unknown(ctx):
    provider = add_move_skill(
        ctx,
        move_contract(max_stop_time_s=0.05),
        faults=MockFaults(duration_s=0.3, steps=3, refuse_cancel=True),
    )
    ctx = with_planner(ctx, move_planner())

    result = await MissionSupervisor(ctx).run(delivery_goal(deadline_s=0.05))

    assert result.status is MissionStatus.OUTCOME_UNKNOWN
    assert result.failure_reason == "deadline_exceeded"
    await provider.drain()


async def test_cancelling_run_stops_the_mission_before_returning(ctx, goal):
    navigate = mock_provider(ctx, "mock.navigate")
    navigate.configure(MockFaults(duration_s=1.0, steps=20))
    supervisor = MissionSupervisor(ctx)

    run = asyncio.ensure_future(supervisor.run(goal))
    await wait_for_state(ctx, LifecycleState.RUNNING)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert not supervisor.is_running
    assert ctx.resources.live_leases() == ()
    assert states_of(ctx, navigate.started[0])[-1] == "CANCELED"
    await asyncio.wait_for(navigate.drain(), timeout=0.1)


class SlowPlanner:
    planner_id = "slow_manual"

    def __init__(self, inner):
        self._inner = inner

    async def propose(self, goal, world, skills):
        await asyncio.sleep(0.05)
        return await self._inner.propose(goal, world, skills)


async def test_cancel_during_planning_stops_the_mission_before_execution(ctx, goal):
    ctx = with_planner(ctx, SlowPlanner(ctx.planners.get("manual")))
    supervisor = MissionSupervisor(ctx)

    run = asyncio.ensure_future(supervisor.run(goal))
    await asyncio.sleep(0.01)
    await supervisor.cancel("operator_request")
    result = await run

    assert result.status is MissionStatus.CANCELED
    assert sim(ctx).dispatched == ()
    assert ctx.recorder.events("skill_state") == ()


class CrashingPlanner:
    planner_id = "crashing"

    async def propose(self, goal, world, skills):
        raise ConnectionError("LLM endpoint unreachable")


async def test_planner_crash_is_a_structured_rejection(ctx, goal):
    ctx = with_planner(ctx, CrashingPlanner())

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.REJECTED
    assert codes(result) == {"planner_error"}
    assert "LLM endpoint unreachable" in result.rejection_reasons[0].detail


class BrokenExecutive(SequentialExecutive):
    executive_id = "broken"

    async def start(self, plan, runtime, ctx):
        raise RuntimeError("no threads left")


async def test_executive_start_failure_is_a_failed_mission(ctx, goal):
    ctx.executives.register("broken", BrokenExecutive())
    ctx = with_execution(ctx, plugin="broken")

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.FAILED
    assert result.failure_reason == "internal_error: RuntimeError: no threads left"


async def test_success_criteria_need_evidence_from_this_mission(ctx):
    seed(ctx, fact("door_open", "d1"))
    mock_clock(ctx).advance_observation_only(10.0)
    old_evidence = SuccessCriterion(predicate="door_open", args=("d1",))
    goal = delivery_goal(success_criteria=(*delivery_goal().success_criteria, old_evidence))

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.FAILED
    assert "door_open(d1)" in result.failure_reason

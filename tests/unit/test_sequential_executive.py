import asyncio

import pytest

from builders import (
    TEST_SKILL,
    MoveProvider,
    add_move_skill,
    fact,
    graph_proposal,
    mock_clock,
    move_contract,
    seed,
    sim,
    skill_node,
    wait_for_state,
    with_execution,
)
from robot_framework.core.errors import UnsupportedOperationError
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.executives.sequential import SequentialExecutive
from robot_framework.providers.mock import MockFaults
from robot_framework.spec import (
    ConditionalNode,
    FactPredicate,
    LifecycleState,
    LoopNode,
    ParallelNode,
    PlanArtifactKind,
    PlanProposal,
    PolicyGoal,
    SequenceNode,
    WaitEventNode,
)

S = LifecycleState
RETRY_TWICE = {"again": {"kind": "retry", "max_attempts": 2}}


async def run_graph(ctx, root, recoveries=None):
    handle = await SequentialExecutive().start(
        graph_proposal(root, recoveries=recoveries), SkillRuntime(ctx), ctx
    )
    return await handle.wait(timeout_s=5)


def go_to(location, node_id=None, **kwargs):
    return skill_node(
        "navigation.go_to", node_id=node_id or f"go_{location}", location=location, **kwargs
    )


def at_robot(location):
    return FactPredicate(predicate="at", args=("robot", location))


async def test_conditional_runs_the_otherwise_branch_when_predicate_fails(ctx):
    root = ConditionalNode(
        node_id="where",
        condition=at_robot("kitchen"),
        then=go_to("desk"),
        otherwise=go_to("kitchen"),
    )

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.SUCCEEDED
    assert [r.node_id for r in outcome.skill_results] == ["go_kitchen"]


async def test_conditional_without_otherwise_succeeds_without_running(ctx):
    root = ConditionalNode(node_id="where", condition=at_robot("kitchen"), then=go_to("desk"))

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.SUCCEEDED and outcome.skill_results == ()


async def test_conditional_observes_the_world_before_branching(ctx):
    seed(ctx, fact("at", "robot", "kitchen"))  # stale belief: ground truth says otherwise
    root = ConditionalNode(
        node_id="where",
        condition=at_robot("kitchen"),
        then=go_to("desk"),
        otherwise=go_to("kitchen"),
    )

    believed = await run_graph(ctx, root)
    sim(ctx).ground_truth.set("at", ("robot", "kitchen"), True)
    observed = await run_graph(ctx, root)

    assert [r.node_id for r in believed.skill_results] == ["go_kitchen"]
    assert [r.node_id for r in observed.skill_results] == ["go_desk"]


async def test_loop_stops_as_soon_as_until_holds(ctx):
    root = LoopNode(
        node_id="loop", max_iterations=3, until=at_robot("kitchen"), child=go_to("kitchen")
    )

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.SUCCEEDED and len(outcome.skill_results) == 1


async def test_loop_is_bounded_by_max_iterations(ctx):
    unbounded_goal = LoopNode(
        node_id="loop", max_iterations=2, until=at_robot("moon"), child=go_to("kitchen")
    )
    plain = LoopNode(node_id="loop", max_iterations=2, child=go_to("kitchen"))

    failed = await run_graph(ctx, unbounded_goal)
    repeated = await run_graph(ctx, plain)

    assert failed.state is S.FAILED and len(failed.skill_results) == 2
    assert repeated.state is S.SUCCEEDED and len(repeated.skill_results) == 2


async def test_wait_event_succeeds_when_the_event_arrives(ctx):
    root = WaitEventNode(
        node_id="wait",
        condition=FactPredicate(predicate="door_open", args=("d1",)),
        timeout_s=1.0,
        poll_interval_s=0.005,
    )

    async def open_door():
        await asyncio.sleep(0.02)
        seed(ctx, fact("door_open", "d1"))

    opener = asyncio.ensure_future(open_door())
    outcome = await run_graph(ctx, root)
    await opener

    assert outcome.state is S.SUCCEEDED


async def test_wait_event_fails_after_its_timeout(ctx):
    root = WaitEventNode(
        node_id="wait",
        condition=FactPredicate(predicate="door_open", args=("d1",)),
        timeout_s=0.02,
        poll_interval_s=0.005,
    )

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.FAILED


async def test_parallel_nodes_are_refused_at_runtime(ctx):
    root = ParallelNode(node_id="both", children=(go_to("a"), go_to("b")))

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.FAILED
    assert outcome.error.startswith("unsupported:")
    assert outcome.skill_results == ()


async def test_start_refuses_non_task_graph_artifacts(ctx):
    proposal = PlanProposal(
        proposal_id="p",
        kind=PlanArtifactKind.POLICY_GOAL,
        planner_id="vla",
        policy_goal=PolicyGoal(instruction="tidy up", horizon_s=2.0),
        world_snapshot_id="ws",
    )

    with pytest.raises(UnsupportedOperationError):
        await SequentialExecutive().start(proposal, SkillRuntime(ctx), ctx)


class FailsFirst(MoveProvider):
    async def start(self, request, lease, backend):
        if not self.started:
            self.schedule(MockFaults(fail_after_s=0.0))
        return await super().start(request, lease, backend)


async def test_retry_policy_reruns_a_failed_skill(ctx):
    add_move_skill(ctx, provider_cls=FailsFirst)
    root = skill_node(TEST_SKILL, node_id="move", recovery_ref="again", target="box")

    outcome = await run_graph(ctx, root, RETRY_TWICE)

    assert outcome.state is S.SUCCEEDED
    assert [r.state for r in outcome.skill_results] == [S.FAILED, S.SUCCEEDED]
    assert ctx.recorder.events("recovery_retry")[0].payload == {"node_id": "move", "attempt": 2}


@pytest.mark.parametrize(
    ("contract", "recoveries"),
    [
        (move_contract(retryable=False), RETRY_TWICE),
        (move_contract(), {"again": {"kind": "abort"}}),
    ],
)
async def test_failed_skill_is_not_retried_when_policy_or_contract_forbids(
    ctx, contract, recoveries
):
    add_move_skill(ctx, contract, provider_cls=FailsFirst)
    root = skill_node(TEST_SKILL, node_id="move", recovery_ref="again", target="box")

    outcome = await run_graph(ctx, root, recoveries)

    assert outcome.state is S.FAILED and len(outcome.skill_results) == 1


async def test_sequence_retry_reruns_the_whole_sequence(ctx):
    add_move_skill(ctx, provider_cls=FailsFirst)
    root = SequenceNode(
        node_id="seq",
        recovery_ref="again",
        children=(go_to("kitchen"), skill_node(TEST_SKILL, node_id="move", target="box")),
    )

    outcome = await run_graph(ctx, root, RETRY_TWICE)

    assert outcome.state is S.SUCCEEDED
    assert [r.node_id for r in outcome.skill_results] == [
        "go_kitchen",
        "move",
        "go_kitchen",
        "move",
    ]


async def test_mission_handle_reports_progress_and_cancels(ctx):
    ctx.providers.get("mock.navigate").configure(MockFaults(duration_s=0.4, steps=8))
    root = SequenceNode(node_id="seq", children=(go_to("kitchen"), go_to("desk")))
    handle = await SequentialExecutive().start(graph_proposal(root), SkillRuntime(ctx), ctx)

    initial = handle.progress()
    await asyncio.sleep(0.02)
    await handle.cancel("operator")
    outcome = await handle.wait()

    assert initial.fraction == 0.0 and initial.message == "0/2 skills succeeded"
    assert outcome.state is S.CANCELED
    assert [r.state for r in outcome.skill_results] == [S.CANCELED]


async def test_wait_event_observes_the_world(ctx):
    add_move_skill(ctx)
    sim(ctx).ground_truth.set("moved", ("box_1",), True)
    root = WaitEventNode(
        node_id="wait",
        condition=FactPredicate(predicate="moved", args=("box_1",)),
        timeout_s=0.02,
        poll_interval_s=0.005,
    )

    outcome = await run_graph(ctx, root)

    assert outcome.state is S.SUCCEEDED
    assert ctx.world.snapshot().lookup("moved", ("box_1",)) is not None


async def test_unconfirmed_stop_is_never_reconciled_into_a_retry(ctx):
    ctx = with_execution(ctx, lease_ttl_s=100.0)
    provider = add_move_skill(
        ctx,
        move_contract(timeout_s=5.0, max_stop_time_s=0.05),
        faults=MockFaults(duration_s=0.3, steps=3, refuse_cancel=True),
    )
    root = skill_node(TEST_SKILL, node_id="move", recovery_ref="again", target="box_1")
    recoveries = {"again": {"kind": "retry", "max_attempts": 3, "requires_reconcile": True}}
    handle = await SequentialExecutive().start(
        graph_proposal(root, recoveries=recoveries), SkillRuntime(ctx), ctx
    )

    await wait_for_state(ctx, S.RUNNING)
    mock_clock(ctx).advance_monotonic_only(6.0)
    outcome = await handle.wait(timeout_s=5)

    assert outcome.state is S.OUTCOME_UNKNOWN
    assert len(provider.started) == 1
    assert ctx.recorder.events("reconcile_blocked")
    assert ctx.recorder.events("recovery_retry") == ()
    await provider.drain()


class CrashingRuntime(SkillRuntime):
    async def invoke(self, node, epoch=None, cancel=None):
        raise RuntimeError("runtime bug")


async def test_executive_crash_is_reported_as_outcome_unknown(ctx):
    handle = await SequentialExecutive().start(
        graph_proposal(go_to("kitchen")), CrashingRuntime(ctx), ctx
    )

    outcome = await handle.wait(timeout_s=5)

    assert outcome.state is S.OUTCOME_UNKNOWN
    assert outcome.error == "internal_error: RuntimeError: runtime bug"

"""Architecture note §14: the nine mandatory behaviours, one test each."""

import asyncio

import pytest

from builders import (
    AE_REQUIRED_PROFILE,
    ScriptedGrounding,
    StaticPlanner,
    extension,
    fact,
    graph_proposal,
    make_context,
    mock_clock,
    mock_provider,
    seed,
    sim,
    skill_node,
    wait_for_state,
    with_extensions,
    with_planner,
    with_robot,
    without_capability,
)
from robot_framework.core.errors import ExtensionRequiredError
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.providers.mock import MockFaults
from robot_framework.spec import (
    CommandEnvelope,
    ControlMode,
    LifecycleState,
    MissionStatus,
    NativeArtifact,
    PlanArtifactKind,
    PlanProposal,
    VerificationStatus,
)

S = LifecycleState


def pick(obj, node_id):
    return skill_node("manipulation.pick", node_id=node_id, object=obj)


async def test_two_providers_same_actuator_never_overlap(ctx, runtime):
    mock_provider(ctx, "mock.pick").configure(MockFaults(duration_s=0.05, steps=5))
    seed(ctx, fact("pose_known", "bottle_17"), fact("pose_known", "bottle_18"))
    max_arm_owners = 0
    done = asyncio.Event()

    async def watch_arm():
        nonlocal max_arm_owners
        while not done.is_set():
            owners = [x for x in ctx.resources.live_leases() if "arm_0" in x.resources]
            max_arm_owners = max(max_arm_owners, len(owners))
            await asyncio.sleep(0.001)

    watcher = asyncio.ensure_future(watch_arm())
    first, second = await asyncio.gather(
        runtime.invoke(pick("bottle_17", "pick_a")), runtime.invoke(pick("bottle_18", "pick_b"))
    )
    done.set()
    await watcher

    winner, loser = (first, second) if first.state is S.SUCCEEDED else (second, first)
    assert winner.state is S.SUCCEEDED
    assert loser.state is S.FAILED and loser.failure_diagnosis.category == "resource_conflict"
    assert loser.provider_status is None
    assert max_arm_owners == 1
    assert {e.issuer_id for e in sim(ctx).dispatched} == {winner.invocation_id}


async def test_provider_success_without_held_object_is_not_task_success(ctx, goal):
    mock_provider(ctx, "mock.pick").configure(MockFaults(lie_success=True))

    result = await MissionSupervisor(ctx).run(goal)

    picks = [r for r in result.skill_results if r.skill_id == "manipulation.pick"]
    assert result.status is MissionStatus.FAILED
    assert picks and all(r.provider_status == "SUCCESS" for r in picks)
    assert all(r.verification_status is VerificationStatus.FAILED for r in picks)
    assert all(r.state is S.FAILED for r in picks)
    assert ctx.world.snapshot().lookup("holding", ("robot", "bottle_17")).value is False
    assert mock_provider(ctx, "mock.place").started == ()


async def test_lost_ack_reconciles_before_retry(ctx, goal):
    pick_provider = mock_provider(ctx, "mock.pick")
    pick_provider.configure(MockFaults(drop_ack=True, effect_happened=True))

    result = await MissionSupervisor(ctx).run(goal)

    pick_result = next(r for r in result.skill_results if r.skill_id == "manipulation.pick")
    assert result.status is MissionStatus.SUCCEEDED
    assert len(pick_provider.started) == 1
    assert pick_result.provider_status == "UNKNOWN"
    assert pick_result.reconciled and pick_result.state is S.SUCCEEDED
    assert ctx.recorder.events("reconciled_success")
    assert ctx.recorder.events("recovery_retry") == ()


async def test_stale_observation_holds_action(ctx, runtime):
    seed(ctx, fact("pose_known", "bottle_17"))
    mock_clock(ctx).advance_observation_only(6.0)

    result = await runtime.invoke(pick("bottle_17", "pick"))

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "perception_stale"
    assert sim(ctx).dispatched == ()


async def test_sim_reset_drops_queued_epoch_commands(ctx, runtime):
    backend = sim(ctx)
    lease = ctx.resources.reserve("queued_owner", ["base"], ControlMode.VELOCITY, ttl_s=60)
    queued = [
        CommandEnvelope(
            envelope_id=f"env_{i}",
            issuer_id="queued_owner",
            lease_id=lease.lease_id,
            epoch=lease.epoch,
            target_resources=("base",),
            control_mode=ControlMode.VELOCITY,
            payload={"set_facts": [{"predicate": "at", "args": ["robot", "dock"], "value": True}]},
            issued_at_monotonic=0.0,
        )
        for i in range(3)
    ]
    seed(ctx, fact("door_open", "d1"))

    new_epoch = await backend.reset()
    acks = [await backend.dispatch(envelope) for envelope in queued]

    assert new_epoch == lease.epoch + 1
    assert [ack.reason for ack in acks] == ["stale_epoch"] * 3
    assert backend.ground_truth.get("at", ("robot", "dock")) is False
    assert all(ctx.world.is_stale(f) for f in ctx.world.snapshot().facts)
    assert len(ctx.recorder.events("command_rejected")) == 3


async def test_sim_reset_interrupts_a_running_skill(ctx, runtime):
    mock_provider(ctx, "mock.navigate").configure(MockFaults(duration_s=0.4, steps=8))

    task = asyncio.ensure_future(runtime.invoke(skill_node("navigation.go_to", location="desk_2")))
    await wait_for_state(ctx, S.RUNNING)
    await sim(ctx).reset()
    result = await task

    assert result.state is not S.SUCCEEDED
    assert result.failure_diagnosis.category in {"lease_lost", "command_rejected"}
    assert sim(ctx).ground_truth.get("at", ("robot", "desk_2")) is False
    after_reset = [e for e in sim(ctx).accepted if e.epoch != ctx.resources.current_epoch]
    assert all(e.epoch == 0 for e in after_reset)


async def test_unavailable_skill_rejected_before_execution(ctx, goal):
    planner = StaticPlanner(
        lambda world: graph_proposal(skill_node("manipulation.fly", object="b"))
    )
    ctx = with_planner(ctx, planner)

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.REJECTED
    assert [(r.code, r.node_id) for r in result.rejection_reasons] == [("unknown_skill", "step")]
    assert sim(ctx).dispatched == ()
    assert ctx.recorder.events("skill_state") == ()


async def test_temporal_artifact_rejected_not_downgraded(ctx, goal):
    def temporal(world):
        return PlanProposal(
            proposal_id="pddl_1",
            kind=PlanArtifactKind.TEMPORAL_PLAN,
            planner_id="plansys2",
            native=NativeArtifact(
                format="pddl_plan", content="0.0: (pick bottle_17) [3.0]", validator_id="pddl_check"
            ),
            world_snapshot_id=world.snapshot_id,
        )

    ctx = with_planner(ctx, StaticPlanner(temporal), PlanArtifactKind.TEMPORAL_PLAN)

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.REJECTED
    assert "unsupported_artifact_kind" in {r.code for r in result.rejection_reasons}
    assert ctx.recorder.events("skill_state") == ()
    assert sim(ctx).dispatched == ()


async def test_required_extension_failure_has_no_silent_bypass(ctx, goal):
    with pytest.raises(ExtensionRequiredError):
        make_context(profile=AE_REQUIRED_PROFILE)

    failing = ScriptedGrounding(
        plugin_id="anhar_affordance_effectivity", error=TimeoutError("ae timeout")
    )
    ctx = with_extensions(ctx, extension(failing, required=True))
    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.FAILED
    assert result.failure_reason.startswith("extension_required:")
    assert sim(ctx).dispatched == ()
    assert ctx.resources.live_leases() == ()


async def test_robot_without_capability_yields_unsupported_goal(ctx, goal):
    ctx = with_robot(ctx, without_capability(ctx.robot, "navigation.ground"))

    result = await MissionSupervisor(ctx).run(goal)

    assert result.status is MissionStatus.REJECTED
    missing = [r for r in result.rejection_reasons if r.code == "missing_capability"]
    assert len(missing) == 1 and "navigation.ground" in missing[0].detail
    assert sim(ctx).dispatched == ()

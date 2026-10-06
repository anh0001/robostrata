import asyncio

from builders import (
    TEST_SKILL,
    MoveProvider,
    add_move_skill,
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
)
from robot_framework.core.clock import SystemClock
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.executives.sequential import SequentialExecutive
from robot_framework.providers.mock import MockFaults
from robot_framework.spec import ControlMode, LifecycleState, MissionStatus
from robot_framework.verifiers.world_fact import WorldFactVerifier

S = LifecycleState
SLOW = MockFaults(duration_s=0.4, steps=8)


def move():
    return skill_node(TEST_SKILL, node_id="move_box", target="box_1")


async def test_provider_timeout_takes_the_cancel_path(ctx):
    ctx = with_execution(ctx, lease_ttl_s=100.0)
    add_move_skill(ctx, move_contract(timeout_s=5.0, max_stop_time_s=0.2), faults=SLOW)

    task = asyncio.ensure_future(SkillRuntime(ctx).invoke(move()))
    await wait_for_state(ctx, S.RUNNING)
    mock_clock(ctx).advance_monotonic_only(6.0)
    result = await task

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "provider_timeout"
    assert result.provider_status == "CANCELED"
    assert "CANCELING" in states_of(ctx, result.invocation_id)


async def test_timeout_without_stop_confirmation_is_outcome_unknown(ctx):
    ctx = with_execution(ctx, lease_ttl_s=100.0)
    provider = add_move_skill(
        ctx,
        move_contract(timeout_s=5.0, max_stop_time_s=0.05),
        faults=MockFaults(duration_s=0.3, steps=3, refuse_cancel=True),
    )

    task = asyncio.ensure_future(SkillRuntime(ctx).invoke(move()))
    await wait_for_state(ctx, S.RUNNING)
    mock_clock(ctx).advance_monotonic_only(6.0)
    result = await task

    assert result.state is S.OUTCOME_UNKNOWN
    assert result.failure_diagnosis.category == "provider_timeout"
    await provider.drain()


class WrongModeProvider(MoveProvider):
    def _envelope(self, request, lease, step, effects):
        envelope = super()._envelope(request, lease, step, effects)
        return envelope.model_copy(update={"control_mode": ControlMode.EFFORT})


async def test_command_rejected_by_authority_fails_the_skill(ctx, runtime):
    add_move_skill(ctx, provider_cls=WrongModeProvider)

    result = await runtime.invoke(move())

    assert result.state is S.FAILED and result.provider_status == "FAILURE"
    assert result.failure_diagnosis.category == "command_rejected"
    assert result.failure_diagnosis.detail == "control_mode_mismatch"
    assert ctx.recorder.events("command_rejected")
    assert sim(ctx).accepted == ()


async def test_provider_given_a_released_lease_is_refused(ctx):
    provider = add_move_skill(ctx)
    lease = ctx.resources.reserve("ghost", ["arm_0"], ControlMode.TRAJECTORY, ttl_s=10)
    ctx.resources.release(lease.lease_id)
    request = SkillRuntime(ctx)._validated(move(), ctx.skills.get(TEST_SKILL))

    handle = await provider.start(request, lease, ctx.backend)
    outcome = await handle.wait(timeout_s=1.0)

    assert outcome.status == "FAILURE"
    assert outcome.diagnosis.category == "command_rejected"
    assert outcome.diagnosis.detail == "lease_released"
    assert handle.progress().fraction == 0.0


async def test_lease_renewal_keeps_a_long_skill_alive():
    ctx = with_execution(make_context(clock=SystemClock()), lease_ttl_s=0.05)
    add_move_skill(ctx, faults=MockFaults(duration_s=0.25, steps=5))

    result = await SkillRuntime(ctx).invoke(move())

    assert result.state is S.SUCCEEDED
    assert ctx.recorder.events("lease_renewed")
    assert sim(ctx).accepted == sim(ctx).dispatched


class SlowVerifier(WorldFactVerifier):
    verifier_id = "slow_fact"

    async def verify(self, contract, invocation, world):
        await asyncio.sleep(0.05)
        return await super().verify(contract, invocation, world)


async def test_cancel_during_verifying_is_ignored(ctx, runtime):
    ctx.verifiers.register("slow_fact", SlowVerifier())
    add_move_skill(ctx, move_contract(verifier_id="slow_fact"))
    cancel = asyncio.Event()

    task = asyncio.ensure_future(runtime.invoke(move(), cancel=cancel))
    await wait_for_state(ctx, S.VERIFYING)
    cancel.set()
    result = await task

    assert result.state is S.SUCCEEDED
    assert "CANCELING" not in states_of(ctx, result.invocation_id)


async def test_lost_ack_without_effect_reconciles_then_retries(ctx, goal):
    pick = mock_provider(ctx, "mock.pick")
    pick.schedule(MockFaults(drop_ack=True, effect_happened=False))

    result = await MissionSupervisor(ctx).run(goal)

    picks = [r for r in result.skill_results if r.skill_id == "manipulation.pick"]
    assert result.status is MissionStatus.SUCCEEDED
    assert len(pick.started) == 2
    assert (
        picks[0].reconciled and picks[0].state is S.FAILED and picks[0].provider_status == "UNKNOWN"
    )
    assert picks[1].state is S.SUCCEEDED
    assert ctx.recorder.events("recovery_retry")
    assert ctx.recorder.events("reconciled_success") == ()


async def test_unknown_outcome_that_cannot_be_observed_is_never_retried(ctx):
    provider = add_move_skill(
        ctx, move_contract(effect_predicate="weighed"), faults=MockFaults(drop_ack=True)
    )
    root = skill_node(TEST_SKILL, node_id="move", recovery_ref="again", target="box_1")
    proposal = graph_proposal(root, recoveries={"again": {"kind": "retry", "max_attempts": 3}})

    handle = await SequentialExecutive().start(proposal, SkillRuntime(ctx), ctx)
    outcome = await handle.wait(timeout_s=5)

    assert outcome.state is S.OUTCOME_UNKNOWN
    assert len(provider.started) == 1
    assert outcome.skill_results[0].reconciled is False


async def test_evidence_older_than_the_invocation_cannot_verify_a_lie(ctx, runtime):
    seed(ctx, fact("weighed", "box_1"))  # no observation source for "weighed"
    mock_clock(ctx).advance_observation_only(1.0)
    add_move_skill(
        ctx, move_contract(effect_predicate="weighed"), faults=MockFaults(lie_success=True)
    )

    result = await runtime.invoke(move())

    assert result.provider_status == "SUCCESS"
    assert result.state is S.OUTCOME_UNKNOWN
    assert result.observed_effects == ()

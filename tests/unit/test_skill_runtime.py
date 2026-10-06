import asyncio

import pytest

from builders import (
    TEST_SKILL,
    MoveProvider,
    ScriptedGrounding,
    add_move_skill,
    extension,
    fact,
    make_context,
    mock_clock,
    move_contract,
    seed,
    sim,
    skill_node,
    states_of,
    wait_for_event,
    wait_for_state,
    with_execution,
    with_extensions,
)
from robot_framework.core.clock import SystemClock
from robot_framework.core.errors import ContractValidationError, ExtensionRequiredError
from robot_framework.core.skill_runtime import SkillRuntime
from robot_framework.providers.mock import MockFaults
from robot_framework.spec import (
    AssessmentStatus,
    Condition,
    ControlMode,
    LifecycleState,
    ProviderOutcome,
    RecommendedStep,
    VerificationStatus,
)
from robot_framework.verifiers.world_fact import WorldFactVerifier

S = LifecycleState
SLOW = MockFaults(duration_s=0.4, steps=8)


def move(**params):
    return skill_node(TEST_SKILL, node_id="move_box", **({"target": "box_1"} | params))


async def test_runtime_happy_path_walks_the_lifecycle(ctx, runtime):
    provider = add_move_skill(ctx)

    result = await runtime.invoke(move())

    assert result.state is S.SUCCEEDED
    assert result.provider_status == "SUCCESS"
    assert result.verification_status is VerificationStatus.VERIFIED
    assert [(f.predicate, f.args, f.value) for f in result.observed_effects] == [
        ("moved", ("box_1",), True)
    ]
    assert states_of(ctx, result.invocation_id) == [
        "CREATED",
        "VALIDATED",
        "RESERVED",
        "RUNNING",
        "VERIFYING",
        "SUCCEEDED",
    ]
    assert ctx.world.snapshot().lookup("moved", ("box_1",)).source == "world_fact"
    assert ctx.resources.live_leases() == ()
    assert provider.started == (result.invocation_id,)


async def test_runtime_cancel_waits_for_provider_confirmation(ctx, runtime):
    add_move_skill(ctx, move_contract(max_stop_time_s=0.2), faults=SLOW)
    provider = ctx.providers.get("test.mover")
    provider.configure(MockFaults(duration_s=0.4, steps=8, cancel_latency_s=0.02))
    cancel = asyncio.Event()

    task = asyncio.ensure_future(runtime.invoke(move(), cancel=cancel))
    await wait_for_state(ctx, S.RUNNING)
    cancel.set()
    canceling = await wait_for_state(ctx, S.CANCELING)
    still_leased = len(ctx.resources.live_leases())
    result = await task

    assert canceling.payload["reason"] == "cancel_requested"
    assert still_leased == 1
    assert result.state is S.CANCELED and result.provider_status == "CANCELED"
    assert states_of(ctx, result.invocation_id)[-2:] == ["CANCELING", "CANCELED"]
    assert ctx.resources.live_leases() == ()
    kinds = [e.kind for e in ctx.recorder.events() if e.kind in ("skill_state", "lease_released")]
    assert kinds[-1] == "lease_released"


async def test_runtime_cancel_timeout_yields_outcome_unknown(ctx, runtime):
    provider = add_move_skill(
        ctx,
        move_contract(max_stop_time_s=0.05),
        faults=MockFaults(duration_s=0.3, steps=3, refuse_cancel=True),
    )
    cancel = asyncio.Event()

    task = asyncio.ensure_future(runtime.invoke(move(), cancel=cancel))
    await wait_for_state(ctx, S.RUNNING)
    cancel.set()
    result = await task

    assert result.state is S.OUTCOME_UNKNOWN
    assert result.failure_diagnosis.category == "cancelled"
    assert "stop not confirmed" in result.failure_diagnosis.detail
    assert ctx.resources.live_leases() == ()
    await provider.drain()


async def test_runtime_stale_precondition_fails_without_command(ctx, runtime):
    contract = move_contract(
        preconditions=(Condition(predicate="seen", args=("$target",), max_age_s=5.0),)
    )
    provider = add_move_skill(ctx, contract)
    seed(ctx, fact("seen", "box_1"))
    mock_clock(ctx).advance_observation_only(6)

    result = await runtime.invoke(move())

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "perception_stale"
    assert sim(ctx).dispatched == ()
    assert provider.started == ()


async def test_runtime_missing_and_false_preconditions(ctx, runtime):
    contract = move_contract(preconditions=(Condition(predicate="clear", args=("$target",)),))
    add_move_skill(ctx, contract)

    missing = await runtime.invoke(move())
    seed(ctx, fact("clear", "box_1", value=False))
    false = await runtime.invoke(move())

    assert missing.failure_diagnosis.category == "perception_stale"
    assert false.failure_diagnosis.category == "precondition_unmet"
    assert sim(ctx).dispatched == ()


async def test_runtime_unknown_assessment_is_not_infeasible(ctx):
    provider = add_move_skill(ctx)
    ctx = with_extensions(ctx, extension(ScriptedGrounding(AssessmentStatus.UNKNOWN)))

    result = await SkillRuntime(ctx).invoke(move())

    assert result.state is S.SUCCEEDED
    assert len(provider.started) == 1
    assert ctx.recorder.events("assessment_unknown")


async def test_runtime_unknown_assessment_with_recommendation_skips_provider(ctx):
    provider = add_move_skill(ctx)
    step = RecommendedStep(skill_id="perception.observe_target", reason="refresh pose")
    ctx = with_extensions(
        ctx, extension(ScriptedGrounding(AssessmentStatus.UNKNOWN, recommended=step))
    )

    result = await SkillRuntime(ctx).invoke(move())

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "infeasible"
    assert "recommends 'perception.observe_target'" in result.failure_diagnosis.detail
    assert provider.started == ()


async def test_infeasible_provider_falls_back_to_the_next_candidate(ctx):
    first = add_move_skill(ctx, provider_id="test.mover_a")
    second = add_move_skill(ctx, provider_id="test.mover_b", register_skill=False)
    grounding = ScriptedGrounding(infeasible_for=frozenset({"test.mover_a"}))
    ctx = with_extensions(ctx, extension(grounding))

    result = await SkillRuntime(ctx).invoke(move())

    assert result.state is S.SUCCEEDED and result.provider_id == "test.mover_b"
    assert first.started == () and len(second.started) == 1
    assert grounding.assessed == ("test.mover_a", "test.mover_b")


async def test_provider_preference_orders_candidates(ctx):
    add_move_skill(ctx, provider_id="test.mover_a")
    add_move_skill(ctx, provider_id="test.mover_b", register_skill=False)
    ctx = with_execution(ctx, provider_preference={TEST_SKILL: ("test.mover_b",)})

    result = await SkillRuntime(ctx).invoke(move())

    assert result.provider_id == "test.mover_b"


async def test_required_extension_failure_raises_without_commands(ctx):
    add_move_skill(ctx)
    failing = ScriptedGrounding(error=RuntimeError("model server down"))
    ctx = with_extensions(ctx, extension(failing, required=True))

    with pytest.raises(ExtensionRequiredError, match="model server down"):
        await SkillRuntime(ctx).invoke(move())

    assert sim(ctx).dispatched == ()
    assert ctx.resources.live_leases() == ()


async def test_optional_extension_failure_is_recorded_and_ignored(ctx):
    add_move_skill(ctx)
    ctx = with_extensions(ctx, extension(ScriptedGrounding(error=RuntimeError("flaky"))))

    result = await SkillRuntime(ctx).invoke(move())

    assert result.state is S.SUCCEEDED
    assert ctx.recorder.events("extension_warning")[0].payload["error"] == "flaky"


async def test_hold_condition_violation_stops_the_provider(ctx, runtime):
    contract = move_contract(hold_conditions=(Condition(predicate="clear", args=("$target",)),))
    add_move_skill(ctx, contract, faults=SLOW)
    seed(ctx, fact("clear", "box_1"))

    task = asyncio.ensure_future(runtime.invoke(move()))
    await wait_for_state(ctx, S.RUNNING)
    seed(ctx, fact("clear", "box_1", value=False))
    result = await task

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "hold_violated"
    assert result.provider_status == "CANCELED"


async def test_resource_conflict_fails_without_command(ctx, runtime):
    provider = add_move_skill(ctx)
    ctx.resources.reserve("someone_else", ["arm_0"], ControlMode.TRAJECTORY, ttl_s=60)

    result = await runtime.invoke(move())

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "resource_conflict"
    assert provider.started == () and sim(ctx).dispatched == ()


async def test_stale_mission_epoch_is_refused(ctx, runtime):
    add_move_skill(ctx)
    epoch = ctx.resources.current_epoch
    await sim(ctx).reset()

    result = await runtime.invoke(move(), epoch=epoch)

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "stale_epoch"


async def test_verification_not_required_succeeds_without_effects(ctx, runtime):
    add_move_skill(ctx, move_contract(verification_required=False))

    result = await runtime.invoke(move())

    assert result.state is S.SUCCEEDED
    assert result.verification_status is VerificationStatus.NOT_REQUIRED
    assert result.observed_effects == ()
    assert await runtime.reconcile(result) == result


async def test_unobservable_effect_makes_the_outcome_unknown(ctx, runtime):
    add_move_skill(ctx, move_contract(effect_predicate="weighed"))

    result = await runtime.invoke(move())

    assert result.provider_status == "SUCCESS"
    assert result.state is S.OUTCOME_UNKNOWN
    assert result.verification_status is VerificationStatus.UNKNOWN


async def test_injected_provider_failure_is_failed(ctx, runtime):
    add_move_skill(ctx, faults=MockFaults(fail_after_s=0.0))

    result = await runtime.invoke(move())

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "hardware_fault"


class CrashingProvider(MoveProvider):
    async def _run(self, request, lease, backend, handle, faults):
        raise RuntimeError("driver segfault")


class SelfCancelingProvider(MoveProvider):
    async def _run(self, request, lease, backend, handle, faults):
        return ProviderOutcome(invocation_id=request.invocation_id, status="CANCELED")


@pytest.mark.parametrize(
    ("provider_cls", "state", "category"),
    [
        (CrashingProvider, S.OUTCOME_UNKNOWN, "other"),
        (SelfCancelingProvider, S.FAILED, "cancelled"),
    ],
)
async def test_misbehaving_providers_never_succeed(ctx, runtime, provider_cls, state, category):
    add_move_skill(ctx, provider_cls=provider_cls)

    result = await runtime.invoke(move())

    assert result.state is state
    assert result.failure_diagnosis.category == category


async def test_skill_without_eligible_provider_is_unsupported(ctx, runtime):
    ctx.skills.register(TEST_SKILL, move_contract())

    result = await runtime.invoke(move())

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "unsupported"


async def test_runtime_refuses_programming_errors(ctx, runtime):
    add_move_skill(ctx)

    with pytest.raises(ContractValidationError, match="missing parameter"):
        await runtime.invoke(skill_node(TEST_SKILL))
    with pytest.raises(ContractValidationError, match="not registered"):
        await runtime.invoke(skill_node("test.unknown"))
    with pytest.raises(ContractValidationError, match="unknown invocation"):
        runtime.invocation("inv_missing")


class ResettingGrounding(ScriptedGrounding):
    """Triggers a simulation reset while the runtime is awaiting an assessment."""

    def __init__(self, backend):
        super().__init__()
        self._backend = backend

    async def assess(self, request, provider, world):
        await self._backend.reset()
        return await super().assess(request, provider, world)


async def test_epoch_change_during_assessment_refuses_the_reservation(ctx):
    provider = add_move_skill(ctx)
    epoch = ctx.resources.current_epoch
    ctx = with_extensions(ctx, extension(ResettingGrounding(sim(ctx))))

    result = await SkillRuntime(ctx).invoke(move(), epoch=epoch)

    assert result.state is S.FAILED
    assert result.failure_diagnosis.category == "stale_epoch"
    assert provider.started == () and ctx.resources.live_leases() == ()


class BlockingCancelHandle:
    """Wraps a mock handle whose ``cancel()`` never returns until released."""

    def __init__(self, inner):
        self.invocation_id = inner.invocation_id
        self.released = asyncio.Event()
        self._inner = inner

    async def wait(self, timeout_s=None):
        return await self._inner.wait(timeout_s)

    async def cancel(self, reason):
        await self.released.wait()

    def progress(self):
        return self._inner.progress()


class BlockingCancelProvider(MoveProvider):
    async def start(self, request, lease, backend):
        self.handle = BlockingCancelHandle(await super().start(request, lease, backend))
        return self.handle


async def test_blocking_cancel_request_cannot_stretch_the_stop_bound(ctx, runtime):
    provider = add_move_skill(
        ctx, move_contract(max_stop_time_s=0.05), faults=SLOW, provider_cls=BlockingCancelProvider
    )
    cancel = asyncio.Event()
    loop = asyncio.get_running_loop()

    task = asyncio.ensure_future(runtime.invoke(move(), cancel=cancel))
    await wait_for_state(ctx, S.RUNNING)
    cancel.set()
    started = loop.time()
    result = await task
    elapsed = loop.time() - started

    assert result.state is S.OUTCOME_UNKNOWN
    assert elapsed < 0.3
    assert runtime.provider_may_be_active(result.invocation_id)
    assert ctx.resources.live_leases() == ()
    provider.handle.released.set()
    await provider.drain()
    assert not runtime.provider_may_be_active(result.invocation_id)


async def test_cancelling_the_invoking_task_stops_the_provider(ctx, runtime):
    provider = add_move_skill(ctx, move_contract(max_stop_time_s=0.2), faults=SLOW)

    task = asyncio.ensure_future(runtime.invoke(move()))
    await wait_for_state(ctx, S.RUNNING)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert states_of(ctx, provider.started[0])[-2:] == ["CANCELING", "CANCELED"]
    assert ctx.resources.live_leases() == ()
    await asyncio.wait_for(provider.drain(), timeout=0.1)


class ExplodingStartProvider(MoveProvider):
    async def start(self, request, lease, backend):
        raise RuntimeError("fieldbus error")


async def test_provider_start_crash_is_outcome_unknown(ctx, runtime):
    add_move_skill(ctx, provider_cls=ExplodingStartProvider)

    result = await runtime.invoke(move())

    assert result.state is S.OUTCOME_UNKNOWN
    assert "fieldbus error" in result.failure_diagnosis.detail
    assert ctx.resources.live_leases() == ()


async def test_cancel_before_start_issues_no_command(ctx, runtime):
    provider = add_move_skill(ctx)
    cancel = asyncio.Event()
    cancel.set()

    result = await runtime.invoke(move(), cancel=cancel)

    assert result.state is S.CANCELED
    assert provider.started == () and sim(ctx).dispatched == ()


class ResettingVerifier(WorldFactVerifier):
    verifier_id = "resetting_fact"

    def __init__(self, backend):
        self._backend = backend

    async def verify(self, contract, invocation, world):
        verdict = await super().verify(contract, invocation, world)
        await self._backend.reset()
        return verdict


async def test_epoch_change_during_verification_commits_nothing(ctx, runtime):
    ctx.verifiers.register("resetting_fact", ResettingVerifier(sim(ctx)))
    add_move_skill(ctx, move_contract(verifier_id="resetting_fact"))

    result = await runtime.invoke(move())

    assert result.state is S.OUTCOME_UNKNOWN
    assert result.verification_status is VerificationStatus.UNKNOWN
    assert not any(f.source == "resetting_fact" for f in ctx.world.snapshot().facts)


async def test_lease_is_released_even_if_recording_fails(ctx, runtime, monkeypatch):
    add_move_skill(ctx)
    record = ctx.recorder.record

    def failing_record(kind, payload=None):
        if kind == "lease_acquired":
            raise OSError("disk full")
        return record(kind, payload)

    monkeypatch.setattr(ctx.recorder, "record", failing_record)

    with pytest.raises(OSError, match="disk full"):
        await runtime.invoke(move())
    assert ctx.resources.live_leases() == ()


async def test_lease_stays_live_while_the_provider_stops():
    ctx = with_execution(make_context(clock=SystemClock()), lease_ttl_s=0.05)
    add_move_skill(
        ctx,
        move_contract(max_stop_time_s=0.5),
        faults=MockFaults(duration_s=0.4, steps=8, cancel_latency_s=0.15),
    )
    cancel = asyncio.Event()

    task = asyncio.ensure_future(SkillRuntime(ctx).invoke(move(), cancel=cancel))
    acquired = await wait_for_event(ctx, lambda e: e.kind == "lease_acquired")
    cancel.set()
    result = await task

    lease_id = acquired.payload["lease"]["lease_id"]
    assert result.state is S.CANCELED
    assert ctx.resources.lease_status(lease_id) == "lease_released"


async def test_runtime_type_checks_parameters(ctx, runtime):
    add_move_skill(ctx)

    with pytest.raises(ContractValidationError, match="expects entity"):
        await runtime.invoke(skill_node(TEST_SKILL, target=17))
    with pytest.raises(ContractValidationError, match="unknown parameter 'speed'"):
        await runtime.invoke(skill_node(TEST_SKILL, target="box", speed=1))

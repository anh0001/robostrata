"""Small builders shared by every test suite (importable; fixtures live in conftest.py)."""

import asyncio
import dataclasses
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from robot_framework.core.clock import Clock, MockClock
from robot_framework.core.context import FrameworkContext, build_context
from robot_framework.core.interfaces import LoadedExtension
from robot_framework.core.world_interface import InMemoryWorld
from robot_framework.packages.loader import ROOT_ENV, load_goal
from robot_framework.providers.mock import (
    FactAssignment,
    MockFaults,
    MockProviderBase,
    assignment,
    mock_manifest,
)
from robot_framework.simulation_backends.mock import MockSimulationBackend
from robot_framework.spec import (
    AssessmentContext,
    AssessmentReport,
    AssessmentStatus,
    CancellationSpec,
    Condition,
    ControlMode,
    ExpectedEffect,
    Fact,
    FailureSemantics,
    GoalSpec,
    LifecycleState,
    MissionEvent,
    PlanArtifactKind,
    PlanProposal,
    PortSpec,
    ProviderManifest,
    RecommendedStep,
    RobotManifest,
    SkillContract,
    SkillInvocation,
    SkillNode,
    TaskGraph,
    TaskNode,
    VerificationSpec,
    WorldSnapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILES = REPO_ROOT / "deployment_profiles"
BASELINE_PROFILE = PROFILES / "mock_bottle_delivery.yaml"
AE_REQUIRED_PROFILE = PROFILES / "mock_bottle_delivery_ae_required.yaml"
GOAL_FILE = REPO_ROOT / "task_packs" / "examples" / "goals" / "deliver_bottle.goal.yaml"
START_TIME = 1000.0
TEST_SKILL = "test.move"
TEST_PROVIDER = "test.mover"


def make_context(
    *,
    clock: Clock | None = None,
    profile: Path = BASELINE_PROFILE,
    record_path: Path | None = None,
) -> FrameworkContext:
    return build_context(
        profile,
        clock=clock if clock is not None else MockClock(now=START_TIME),
        record_path=record_path,
        root=REPO_ROOT,
    )


def delivery_goal(**updates: Any) -> GoalSpec:
    return load_goal(GOAL_FILE).model_copy(update=updates)


def skill_node(
    skill_id: str, node_id: str = "step", recovery_ref: str | None = None, **params: Any
) -> SkillNode:
    return SkillNode(node_id=node_id, skill_id=skill_id, params=params, recovery_ref=recovery_ref)


def fact(
    predicate: str,
    *args: str,
    value: Any = True,
    time: float = START_TIME,
    validity_s: float | None = None,
) -> Fact:
    return Fact(
        predicate=predicate,
        args=args,
        value=value,
        source="test",
        observation_time=time,
        validity_s=validity_s,
    )


def seed(ctx: FrameworkContext, *facts: Fact) -> int:
    return ctx.world.commit(facts, source="test")


def graph_proposal(
    root: TaskNode,
    *,
    recoveries: Mapping[str, Any] | None = None,
    planner_id: str = "test_planner",
) -> PlanProposal:
    return PlanProposal(
        proposal_id="plan_test",
        kind=PlanArtifactKind.TASK_GRAPH,
        planner_id=planner_id,
        task_graph=TaskGraph.model_validate({"root": root, "recoveries": dict(recoveries or {})}),
        world_snapshot_id="ws_test",
    )


def write_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Path:
    """A variant of the baseline profile in a temp dir, resolved against the repo packages."""
    data = yaml.safe_load(BASELINE_PROFILE.read_text())
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setenv(ROOT_ENV, str(REPO_ROOT))
    return path


# -- context accessors and variants -------------------------------------------------------------


def mock_provider(ctx: FrameworkContext, provider_id: str) -> MockProviderBase:
    return cast(MockProviderBase, ctx.providers.get(provider_id))


def sim(ctx: FrameworkContext) -> MockSimulationBackend:
    return cast(MockSimulationBackend, ctx.backend)


def mock_clock(ctx: FrameworkContext) -> MockClock:
    return cast(MockClock, ctx.clock)


def with_execution(ctx: FrameworkContext, **updates: Any) -> FrameworkContext:
    execution = ctx.profile.execution.model_copy(update=updates)
    return dataclasses.replace(ctx, profile=ctx.profile.model_copy(update={"execution": execution}))


def with_extensions(ctx: FrameworkContext, *extensions: LoadedExtension) -> FrameworkContext:
    return dataclasses.replace(ctx, extensions=extensions)


def with_robot(ctx: FrameworkContext, robot: RobotManifest) -> FrameworkContext:
    return dataclasses.replace(ctx, robot=robot)


def without_capability(robot: RobotManifest, capability: str) -> RobotManifest:
    bindings = tuple(b for b in robot.capabilities if b.capability != capability)
    return robot.model_copy(update={"capabilities": bindings})


class StaticPlanner:
    """A planner that proposes whatever the test hands it."""

    def __init__(self, make: Callable[[WorldSnapshot], PlanProposal], planner_id: str = "static"):
        self.planner_id = planner_id
        self._make = make

    async def propose(
        self, goal: GoalSpec, world: WorldSnapshot, skills: Mapping[str, SkillContract]
    ) -> PlanProposal:
        return self._make(world)


def with_planner(
    ctx: FrameworkContext,
    planner: StaticPlanner,
    output_kind: PlanArtifactKind = PlanArtifactKind.TASK_GRAPH,
) -> FrameworkContext:
    ctx.planners.register(planner.planner_id, planner)
    planning = ctx.profile.planning.model_copy(
        update={"plugin": planner.planner_id, "output_kind": output_kind}
    )
    return dataclasses.replace(ctx, profile=ctx.profile.model_copy(update={"planning": planning}))


class ScriptedGrounding:
    """Grounding plugin returning a fixed status (or raising) for every assessment."""

    def __init__(
        self,
        status: AssessmentStatus = AssessmentStatus.FEASIBLE,
        *,
        plugin_id: str = "test_grounding",
        recommended: RecommendedStep | None = None,
        error: Exception | None = None,
        infeasible_for: frozenset[str] = frozenset(),
    ) -> None:
        self.plugin_id = plugin_id
        self._status = status
        self._recommended = recommended
        self._error = error
        self._infeasible_for = infeasible_for
        self.assessed: tuple[str, ...] = ()

    async def assess(
        self, request: SkillInvocation, provider: ProviderManifest, world: WorldSnapshot
    ) -> AssessmentReport:
        self.assessed = (*self.assessed, provider.provider_id)
        if self._error is not None:
            raise self._error
        infeasible = provider.provider_id in self._infeasible_for
        return AssessmentReport(
            status=AssessmentStatus.INFEASIBLE if infeasible else self._status,
            reason="scripted",
            context=AssessmentContext(
                world_snapshot_id=world.snapshot_id,
                robot_state_revision=world.revision,
                provider_id=provider.provider_id,
            ),
            recommended_next_step=self._recommended,
        )


def extension(plugin: ScriptedGrounding, *, required: bool = False) -> LoadedExtension:
    return LoadedExtension(extension_id=plugin.plugin_id, required=required, plugin=plugin)


# -- a small test skill: move(target) sets moved(target) --------------------------------------


class MoveProvider(MockProviderBase):
    def effects(self, params: Mapping[str, Any]) -> tuple[FactAssignment, ...]:
        return (assignment("moved", (str(params["target"]),), True),)


def move_contract(
    *,
    skill_id: str = TEST_SKILL,
    max_stop_time_s: float = 0.05,
    timeout_s: float = 5.0,
    resources: tuple[str, ...] = ("arm_0",),
    preconditions: tuple[Condition, ...] = (),
    hold_conditions: tuple[Condition, ...] = (),
    effect_predicate: str = "moved",
    verification_required: bool = True,
    verifier_id: str = "world_fact",
    retryable: bool = True,
) -> SkillContract:
    effects = (
        (ExpectedEffect(predicate=effect_predicate, args=("$target",), expected=True),)
        if verification_required
        else ()
    )
    return SkillContract(
        skill_id=skill_id,
        inputs=(PortSpec(name="target", type="entity"),),
        preconditions=preconditions,
        hold_conditions=hold_conditions,
        expected_effects=effects,
        verification=VerificationSpec(required=verification_required, verifier_id=verifier_id),
        cancellation=CancellationSpec(mode="immediate", max_stop_time_s=max_stop_time_s),
        failure_semantics=FailureSemantics(timeout_s=timeout_s, retryable=retryable),
        required_capabilities=("manipulation.single_arm",),
        required_resources=resources,
    )


def add_move_skill(
    ctx: FrameworkContext,
    contract: SkillContract | None = None,
    *,
    faults: MockFaults | None = None,
    provider_id: str = TEST_PROVIDER,
    provider_cls: type[MoveProvider] = MoveProvider,
    register_skill: bool = True,
) -> MoveProvider:
    """Register the test skill (once), a provider for it, and make ``moved`` observable."""
    contract = contract if contract is not None else move_contract()
    if register_skill:
        ctx.skills.register(contract.skill_id, contract)
    manifest = mock_manifest(
        provider_id,
        contract.skill_id,
        "manipulation.single_arm",
        ControlMode.TRAJECTORY,
        max_stop_time_s=contract.cancellation.max_stop_time_s,
    )
    provider = provider_cls(manifest, ctx.clock, faults)
    ctx.providers.register(provider_id, provider)
    world = cast(InMemoryWorld, ctx.world)
    world.register_observation_source(
        "moved", sim(ctx).ground_truth.reader("moved"), source_id="mock_sim.observation"
    )
    return provider


# -- waiting on the mission record --------------------------------------------------------------


async def wait_for_event(
    ctx: FrameworkContext, matches: Callable[[MissionEvent], bool], timeout_s: float = 2.0
) -> MissionEvent:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while True:
        found = next((e for e in ctx.recorder.events() if matches(e)), None)
        if found is not None:
            return found
        if loop.time() > deadline:
            raise AssertionError("expected mission event was not recorded in time")
        await asyncio.sleep(0.001)


async def wait_for_state(
    ctx: FrameworkContext, state: LifecycleState, skill_id: str | None = None
) -> MissionEvent:
    return await wait_for_event(
        ctx,
        lambda e: (
            e.kind == "skill_state"
            and e.payload["to"] == state.value
            and (skill_id is None or e.payload["skill_id"] == skill_id)
        ),
    )


def states_of(ctx: FrameworkContext, invocation_id: str) -> list[str]:
    return [
        e.payload["to"]
        for e in ctx.recorder.events("skill_state")
        if e.payload["invocation_id"] == invocation_id
    ]

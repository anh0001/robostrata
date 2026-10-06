"""Wiring layer: one ``FrameworkContext`` holds every registry and shared service of a deployment.

``build_context`` turns a deployment profile into a context. Only mock mode exists in this build;
every other mode raises ``UnsupportedOperationError`` rather than pretending to work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from robot_framework.core.clock import Clock, SystemClock
from robot_framework.core.errors import ContractValidationError, UnsupportedOperationError
from robot_framework.core.interfaces import (
    Executive,
    LoadedExtension,
    RobotBackend,
    SkillProvider,
    TaskPlanner,
    Verifier,
    WorldInterface,
)
from robot_framework.core.recorder import MissionRecorder
from robot_framework.core.registry import Registry
from robot_framework.core.resource_manager import CommandAuthority, ResourceManager
from robot_framework.core.world_interface import InMemoryWorld
from robot_framework.executives.sequential import SequentialExecutive
from robot_framework.extensions.loader import ExtensionLoader, default_extension_factories
from robot_framework.packages.loader import (
    TaskPack,
    load_goal,
    load_profile,
    load_robot_manifest,
    load_task_pack,
    pack_file,
    resolve_root,
)
from robot_framework.planning.manual import ManualPlanner
from robot_framework.providers.mock import build_mock_providers
from robot_framework.robot_backends.mock import MockGroundTruth, MockRobotBackend
from robot_framework.simulation_backends.mock import MockSimulationBackend
from robot_framework.spec import (
    DeploymentMode,
    DeploymentProfile,
    GoalSpec,
    RobotManifest,
    SkillContract,
)
from robot_framework.verifiers.world_fact import WorldFactVerifier

log = logging.getLogger(__name__)

MOCK_BACKENDS = frozenset({"mock_sim", "mock_robot"})


@dataclass(frozen=True)
class FrameworkContext:
    root: Path
    profile: DeploymentProfile
    robot: RobotManifest
    clock: Clock
    world: WorldInterface
    resources: ResourceManager
    authority: CommandAuthority
    backend: RobotBackend
    skills: Registry[SkillContract]
    providers: Registry[SkillProvider]
    planners: Registry[TaskPlanner]
    executives: Registry[Executive]
    verifiers: Registry[Verifier]
    extensions: tuple[LoadedExtension, ...]
    recorder: MissionRecorder
    default_goal: GoalSpec | None = None


def build_context(
    profile_path: Path,
    *,
    clock: Clock | None = None,
    record_path: Path | None = None,
    root: Path | None = None,
) -> FrameworkContext:
    profile = load_profile(profile_path)
    base = resolve_root(profile_path, root)
    clock = clock if clock is not None else SystemClock()
    recorder = MissionRecorder(
        clock,
        sink=record_path,
        enabled=profile.recording.mission_events,
        decision_evidence=profile.recording.decision_evidence,
    )
    extensions = ExtensionLoader(default_extension_factories(), recorder).load(profile.extensions)
    robot = load_robot_manifest(base, profile.robot_pack)
    pack = load_task_pack(base, profile.task_pack)
    world = InMemoryWorld(clock)
    resources = ResourceManager(clock, robot.resource_ids())
    authority = CommandAuthority(resources)
    backend = _build_backend(profile, authority, resources, world, recorder)
    skills = _skill_registry(pack)
    _connect_observations(world, backend, skills)
    ctx = FrameworkContext(
        root=base,
        profile=profile,
        robot=robot,
        clock=clock,
        world=world,
        resources=resources,
        authority=authority,
        backend=backend,
        skills=skills,
        providers=_provider_registry(clock),
        planners=_planner_registry(pack),
        executives=_executive_registry(),
        verifiers=_verifier_registry(),
        extensions=extensions,
        recorder=recorder,
        default_goal=_default_goal(pack, profile),
    )
    _check_plugins(ctx)
    return ctx


def _build_backend(
    profile: DeploymentProfile,
    authority: CommandAuthority,
    resources: ResourceManager,
    world: InMemoryWorld,
    recorder: MissionRecorder,
) -> MockRobotBackend:
    mode, backend_id = profile.deployment.mode, profile.deployment.backend
    if mode is not DeploymentMode.MOCK:
        raise UnsupportedOperationError(
            f"deployment mode '{mode.value}' is not available in this build",
            details={"mode": mode.value, "available": [DeploymentMode.MOCK.value]},
        )
    if backend_id not in MOCK_BACKENDS:
        raise UnsupportedOperationError(
            f"backend '{backend_id}' is not available in mock mode",
            details={"backend": backend_id, "available": sorted(MOCK_BACKENDS)},
        )
    truth = MockGroundTruth()
    if backend_id == "mock_sim":
        return MockSimulationBackend(authority, resources, world, truth, recorder=recorder)
    return MockRobotBackend(authority, truth, recorder=recorder)


def _default_goal(pack: TaskPack, profile: DeploymentProfile) -> GoalSpec | None:
    if profile.default_goal is None:
        return None
    return load_goal(pack_file(pack, profile.default_goal))


def _skill_registry(pack: TaskPack) -> Registry[SkillContract]:
    skills: Registry[SkillContract] = Registry("skill", SkillContract)
    for contract in pack.skills:
        skills.register(contract.skill_id, contract)
    return skills


def _provider_registry(clock: Clock) -> Registry[SkillProvider]:
    providers: Registry[SkillProvider] = Registry("provider", SkillProvider)
    for provider in build_mock_providers(clock):
        providers.register(provider.manifest.provider_id, provider)
    return providers


def _planner_registry(pack: TaskPack) -> Registry[TaskPlanner]:
    planners: Registry[TaskPlanner] = Registry("planner", TaskPlanner)
    planners.register(ManualPlanner.planner_id, ManualPlanner(pack.tasks))
    return planners


def _executive_registry() -> Registry[Executive]:
    executives: Registry[Executive] = Registry("executive", Executive)
    executives.register(SequentialExecutive.executive_id, SequentialExecutive())
    return executives


def _verifier_registry() -> Registry[Verifier]:
    verifiers: Registry[Verifier] = Registry("verifier", Verifier)
    verifiers.register(WorldFactVerifier.verifier_id, WorldFactVerifier())
    return verifiers


def _connect_observations(
    world: InMemoryWorld, backend: MockRobotBackend, skills: Registry[SkillContract]
) -> None:
    """The mock simulator can observe every predicate the registered skills talk about."""
    predicates = sorted(
        {
            predicate.predicate
            for contract in skills.items().values()
            for predicate in (
                *contract.preconditions,
                *contract.hold_conditions,
                *contract.expected_effects,
            )
        }
    )
    source_id = f"{backend.backend_id}.observation"
    for predicate in predicates:
        world.register_observation_source(
            predicate, backend.ground_truth.reader(predicate), source_id=source_id
        )


def _check_plugins(ctx: FrameworkContext) -> None:
    selections = (
        ("planner", ctx.profile.planning.plugin, ctx.planners),
        ("executive", ctx.profile.execution.plugin, ctx.executives),
    )
    for kind, plugin_id, registry in selections:
        if plugin_id not in registry:
            raise ContractValidationError(
                f"profile selects unknown {kind} '{plugin_id}'",
                details={"kind": kind, "plugin": plugin_id, "available": sorted(registry.items())},
            )

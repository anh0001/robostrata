"""Core interfaces (architecture note §3.2). Backends implement these Protocols; the core never
imports a concrete backend.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from robot_framework.spec import (
    ActionChunk,
    AssessmentReport,
    CommandAcknowledgement,
    CommandEnvelope,
    Fact,
    GoalSpec,
    LifecycleState,
    PlanArtifactKind,
    PlanProposal,
    PolicyGoal,
    ProgressReport,
    ProviderManifest,
    ProviderOutcome,
    ResourceLease,
    SkillContract,
    SkillInvocation,
    SkillResult,
    VerificationStatus,
    WorldSnapshot,
)

if TYPE_CHECKING:
    from robot_framework.core.context import FrameworkContext
    from robot_framework.core.skill_runtime import SkillRuntime


@runtime_checkable
class ExecutionHandle(Protocol):
    """A long-running provider execution. ``cancel`` is a request; completion is seen via ``wait``."""

    invocation_id: str

    async def wait(self, timeout_s: float | None = None) -> ProviderOutcome: ...

    async def cancel(self, reason: str) -> None: ...

    def progress(self) -> ProgressReport: ...


@dataclass(frozen=True)
class ExecutiveOutcome:
    state: LifecycleState
    skill_results: tuple[SkillResult, ...]
    error: str | None = None


@runtime_checkable
class MissionHandle(Protocol):
    mission_id: str

    async def wait(self, timeout_s: float | None = None) -> ExecutiveOutcome: ...

    async def cancel(self, reason: str) -> None: ...

    def progress(self) -> ProgressReport: ...


@runtime_checkable
class TaskPlanner(Protocol):
    planner_id: str

    async def propose(
        self, goal: GoalSpec, world: WorldSnapshot, skills: Mapping[str, SkillContract]
    ) -> PlanProposal: ...


@runtime_checkable
class Executive(Protocol):
    executive_id: str
    supported_kinds: frozenset[PlanArtifactKind]
    supported_node_kinds: frozenset[str]

    async def start(
        self, plan: PlanProposal, runtime: SkillRuntime, ctx: FrameworkContext
    ) -> MissionHandle: ...


@runtime_checkable
class GroundingPlugin(Protocol):
    """Extension hook (e.g. affordance–effectivity). Returns an assessment, never a command."""

    plugin_id: str

    async def assess(
        self, request: SkillInvocation, provider: ProviderManifest, world: WorldSnapshot
    ) -> AssessmentReport: ...


@runtime_checkable
class RobotBackend(Protocol):
    backend_id: str

    async def dispatch(self, envelope: CommandEnvelope) -> CommandAcknowledgement: ...

    def capabilities(self) -> frozenset[str]: ...


@runtime_checkable
class SimulationBackend(RobotBackend, Protocol):
    async def reset(self) -> int:
        """Return the new epoch; raise ``UnsupportedOperationError`` if not supported."""
        ...


@runtime_checkable
class SkillProvider(Protocol):
    manifest: ProviderManifest

    async def start(
        self, request: SkillInvocation, lease: ResourceLease, backend: RobotBackend
    ) -> ExecutionHandle: ...


@runtime_checkable
class PolicyProvider(Protocol):
    manifest: ProviderManifest

    async def infer(
        self, observations: Mapping[str, Any], goal_context: PolicyGoal
    ) -> ActionChunk: ...


@runtime_checkable
class WorldInterface(Protocol):
    def snapshot(self) -> WorldSnapshot: ...

    def commit(self, facts: Iterable[Fact], source: str) -> int:
        """Commit facts and return the new revision."""
        ...

    async def observe(self, predicate: str, args: tuple[str, ...]) -> Fact | None: ...

    def invalidate_all(self, reason: str) -> int: ...


@runtime_checkable
class Verifier(Protocol):
    verifier_id: str

    async def verify(
        self, contract: SkillContract, invocation: SkillInvocation, world: WorldInterface
    ) -> tuple[VerificationStatus, tuple[Fact, ...], tuple[str, ...]]: ...


@dataclass(frozen=True)
class LoadedExtension:
    extension_id: str
    required: bool
    plugin: GroundingPlugin

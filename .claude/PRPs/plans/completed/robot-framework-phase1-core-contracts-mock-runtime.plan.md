# Plan: robot_framework — Phase 1: Core Contracts + Mock Runtime

## Summary

Build the neutral core of `robot_framework`: versioned, validated contracts (GoalSpec, TaskDefinition,
PlanProposal, SkillContract, ProviderManifest, RobotManifest, WorldSnapshot/Evidence, AssessmentReport,
SkillInvocation/SkillResult, ResourceLease/CommandEnvelope) plus a mock runtime that proves the hard
semantics end to end: a simple task runs **without an LLM and without affordance–effectivity (A-E)**,
and cancellation, resource ownership, execution epochs, and physical-outcome verification all behave
as specified. Everything that is backend-specific (BehaviorTree.CPP, Nav2, MoveIt/MTC, PlanSys2,
BTGenBot-2, VLA, Gazebo, ros2_control) sits behind interfaces that Phase 1 defines but does not
implement; only the mock implementations ship in this phase.

The repository is empty today, so this plan also fixes the project skeleton, tooling, naming, error,
logging, and test conventions that all later phases must follow.

## User Story

As a robotics researcher/engineer (Anhar, and later other teams),
I want a framework whose contracts for goal, skill, state, evidence, command, and result are fixed and
testable while planners, executives, providers, robots, and simulators are swappable packages,
So that I can run the same task on different robots and backends, plug my affordance–effectivity
research in as an extension, and trust that a "success" means a verified physical effect.

## Problem → Solution

**Current state:** An architecture draft exists (in chat) that couples A-E and BehaviorTree.CPP into
the core, treats all planners as identical, uses a flat step-list task IR, and equates "provider said
SUCCESS" with task success. No code exists.

**Desired state (end of Phase 1):** A Python package with validated contracts, a plugin registry, a
resource manager with atomic leases and epochs, a skill runtime
(validate → resolve → assess → reserve → recheck → start → monitor → verify → commit), a mission
supervisor, a sequential reference executive for the portable TaskGraph, a manual planner, mock
providers/robot backend/simulation backend, an extension hook interface with a null implementation,
one example robot package and task pack, one deployment profile, and a conformance test suite
covering the mandatory behaviours in the architecture note (section 14).

## Metadata

- **Complexity**: XL overall (6 phases); this plan covers Phase 1 only, which is **Large**
- **Source PRD**: N/A (free-form architecture note; see `docs/architecture.md` created in Task 2)
- **PRD Phase**: Phase 1 — "Core contracts and mock runtime"
- **Estimated Files**: ~55 (≈40 source, ≈15 test/config/doc)

---

## UX Design

### Before

N/A — repository is empty.

### After

Internal framework; the "user" is a developer or an operator script. Developer-facing flow:

```
┌──────────────────────────────────────────────────────────────────┐
│ $ uv sync --extra dev                                            │
│ $ uv run pytest                      # conformance + unit tests  │
│ $ uv run robot-framework run \                                   │
│       deployment_profiles/mock_bottle_delivery.yaml              │
│   → loads profile → registry → validates plan → runs mission     │
│   → prints mission events + final MissionResult (JSON)           │
│ $ uv run robot-framework schemas export specification/schemas/   │
│   → writes one JSON Schema per contract                          │
└──────────────────────────────────────────────────────────────────┘
```

### Interaction Changes

| Touchpoint | Before | After | Notes |
|---|---|---|---|
| CLI `robot-framework run <profile>` | none | runs a mission from a deployment profile | mock mode only in Phase 1 |
| CLI `robot-framework validate <profile>` | none | loads packages, validates plan + compatibility, no execution | exits non-zero with structured reasons |
| CLI `robot-framework schemas export <dir>` | none | emits JSON Schemas from the pydantic contracts | schemas are generated, never hand-edited |
| Python API | none | `MissionSupervisor.run(goal, profile)` | asyncio-based |

---

## Mandatory Reading

The repository is empty; "mandatory reading" is therefore the conventions in sibling projects and
the host environment facts below.

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 (critical) | `../bodybound_vla/pyproject.toml` | 1-40 | hatchling + src layout + pytest `pythonpath=["src"]` convention to copy |
| P0 (critical) | `../affkernel/pyproject.toml` | 24-50 | ruff config to copy (double quotes, line-length 100, rule set E/W/F/I/UP/B) |
| P1 (important) | `../llm2bt-arm/README.md` | 1-60 | the existing effectivity-evidence executive; Phase 3's `anhar_ae` extension ports concepts from here. Do NOT import code from it in Phase 1 |
| P1 (important) | `../bodybound_vla/tests/test_b2_replay.py` | 1-60 | pytest style: plain functions, `pytest.raises(..., match=...)`, small builders |
| P2 (reference) | `docs/architecture.md` (created in Task 2) | all | the full architecture note, saved into the repo |

### Host environment facts (verified 2026-10-06)

| Fact | Value | Consequence |
|---|---|---|
| Python | 3.10.12 | **No 3.11+ features**: no `StrEnum`, no `tomllib`, no `typing.Self`, no `asyncio.timeout()`, no `ExceptionGroup`/`TaskGroup`. Use `class X(str, Enum)`, PyYAML, `asyncio.wait_for`. |
| Package manager | `uv 0.10.3` | use `uv sync`, `uv run`, commit `uv.lock` |
| pydantic | 2.11.9 | pydantic v2 API only (`model_validate`, `model_json_schema`, `ConfigDict`) |
| jsonschema | 4.25.1 | used only to validate exported schemas / YAML authoring files |
| pytest | 8.4.2 | `pytest-asyncio` must be added as a dev dependency |
| ROS 2 | Humble (`/opt/ros/humble`) | Phase 1 must **not** import `rclpy`; ROS stays in `transports/ros2` for Phase 2 |
| BehaviorTree.CPP | only `behaviortree_cpp_v3` 3.8.7 (apt) | BT.CPP **4.x is not installed**; BTGenBot-2 XML and BehaviorTree.ROS2 need 4.6+. Phase 2 must build BT.CPP 4 from source. Not a Phase 1 concern. |
| MoveIt | `moveit_core` present, **MTC absent** | Phase 2 concern |
| PlanSys2 | absent | Phase 4 concern |
| Gazebo | `ros_gz_sim` (Fortress pairing for Humble) present | Phase 2 concern |
| git | repo **not initialised**; `user.name=anhrisn` | Task 1 runs `git init` |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| pydantic v2 frozen models / JSON schema | https://docs.pydantic.dev/latest/concepts/models/ | `model_config = ConfigDict(frozen=True, extra="forbid")`; `Model.model_json_schema()`; copy with `model_copy(update=...)` |
| pytest-asyncio | https://pytest-asyncio.readthedocs.io/ | set `asyncio_mode = "auto"` in `[tool.pytest.ini_options]` so `async def test_*` just works |
| ROS 2 action cancel semantics (design input only) | https://design.ros2.org/articles/actions.html | cancel request accepted ≠ goal finished ≠ robot stopped; our `CANCELING → CANCELED` must wait for provider confirmation |
| ros2_control resource claiming (design input only) | https://control.ros.org/humble/doc/ros2_control/controller_manager/doc/userdoc.html | hardware-level claiming exists, but mission/skill-level leases are still needed; our ResourceManager is that layer |
| BTGenBot-2 output format (Phase 2/4 input) | https://github.com/AIRLab-POLIMI/BTGenBot-2 | emits BT.CPP 4 XML with a closed node vocabulary; our validator must add parameter/resource/robot checks |
| ROS distro support dates | https://docs.ros.org/en/rolling/Releases.html | Humble EOL May 2027; don't hard-code Humble assumptions into core |

No external research is needed for Phase 1 code itself; it uses only pydantic, PyYAML, asyncio, pytest.

---

## Patterns to Mirror

No code exists in this repo. The patterns below are taken from the author's sibling projects
(verified), and the remaining ones are **defined here** and become the house style for every later
phase. Follow them exactly.

### PROJECT_LAYOUT
```
// SOURCE: ../bodybound_vla/pyproject.toml:1-5, 30-35 (hatchling + src layout + pytest pythonpath)
[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/robot_framework"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"
```

### LINT_CONFIG
```
// SOURCE: ../affkernel/pyproject.toml:24-50 (adapted: target py310)
[tool.ruff]
target-version = "py310"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP", "B"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

### TEST_STRUCTURE
```python
// SOURCE: ../bodybound_vla/tests/test_b2_replay.py:1-25 (style: builders + pytest.raises(match=...))
def row(g, skin, asked, b, q=(.2, .8), decoded=None): ...     # small builder helpers

def test_grid_rejects_duplicates_missing_and_invented_labels():
    rows = grid(); validate_grid(rows)
    with pytest.raises(ValueError, match="duplicate"):
        validate_grid(rows + [rows[0]])
```
House rule for this repo: AAA layout, descriptive `test_<behaviour>` names, builders live in
`tests/conftest.py` or `tests/builders.py`, async tests are plain `async def`.

### NAMING_CONVENTION (defined here)
```python
# Modules/packages: snake_case. Classes: PascalCase. Enums: PascalCase class, UPPER_CASE members.
# Contract models end in the noun from the architecture note: GoalSpec, SkillContract, ...
# Protocols (abstract interfaces) are typing.Protocol classes, no "I" prefix: TaskPlanner, Executive,
#   SkillProvider, PolicyProvider, RobotBackend, SimulationBackend, GroundingPlugin, WorldInterface.
# Mock implementations are prefixed Mock: MockPickProvider, MockRobotBackend.
# Identifiers in data are strings with a dotted namespace: skill ids "manipulation.pick",
#   provider ids "mock.pick", resource ids "arm_0", "gripper_0", "base", entity ids "bottle_17".
# Every contract carries `schema_version: str` (e.g. "v1alpha1") and every artifact a `kind`.
```

### CONTRACT_MODEL (defined here — every contract follows this)
```python
# src/robot_framework/spec/_base.py
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "v1alpha1"


class ContractModel(BaseModel):
    """Base for every framework contract: immutable, strict, versioned."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_assignment=False)
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^v\d+(alpha|beta)?\d*$")


# Immutability rule (global coding-style rule): never mutate; derive with
#   new = old.model_copy(update={"status": LifecycleState.RUNNING})
```

### ERROR_HANDLING (defined here)
```python
# src/robot_framework/core/errors.py
class FrameworkError(Exception):
    """Base. `code` is a stable machine-readable string; `details` is JSON-serialisable."""

    code: str = "framework_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ContractValidationError(FrameworkError):
    code = "contract_validation"


class PlanRejectedError(FrameworkError):
    code = "plan_rejected"  # structured reasons in details["reasons"]


class ResourceConflictError(FrameworkError):
    code = "resource_conflict"


class StaleEpochError(FrameworkError):
    code = "stale_epoch"


class UnsupportedOperationError(FrameworkError):
    code = "unsupported"  # UNSUPPORTED, never fake success


class ExtensionRequiredError(FrameworkError):
    code = "extension_required"  # required plugin missing/failed → no silent bypass


# Rules: raise, never return None on failure. Results that are *expected* outcomes (FAILED,
# OUTCOME_UNKNOWN, INFEASIBLE) are values in result models, not exceptions.
```

### LOGGING_PATTERN (defined here)
```python
# Standard library logging, one logger per module, structured `extra` for ids. No print().
import logging

log = logging.getLogger(__name__)
log.info(
    "skill started",
    extra={
        "invocation_id": inv.invocation_id,
        "skill_id": inv.skill_id,
        "provider_id": inv.provider_id,
        "epoch": lease.epoch,
    },
)
# Decision-relevant events additionally go to the MissionRecorder (Task 11) as MissionEvent models —
# logs are for humans, MissionEvents are the replayable record.
```

### REGISTRY_PATTERN (defined here)
```python
# src/robot_framework/core/registry.py — explicit registration, no import-time magic.
class Registry(Generic[T]):
    def register(self, key: str, item: T) -> None:  # raises ContractValidationError on duplicate key
    def get(self, key: str) -> T:                   # raises KeyError with the key in message
    def items(self) -> Mapping[str, T]:             # read-only view
# A FrameworkContext (Task 12) owns: skills, providers, planners, executives, extensions, verifiers.
```

### ASYNC_LONG_RUNNING_OPERATION (defined here)
```python
# Every long-running operation returns a handle exposing progress, cancel, result, with a timeout.
class ExecutionHandle(Protocol):
    invocation_id: str
    async def wait(self, timeout_s: float | None = None) -> SkillResult: ...
    async def cancel(self, reason: str) -> None:   # request only; completion observed via wait()
    def progress(self) -> ProgressReport: ...
# Use asyncio.wait_for (py3.10), never asyncio.timeout().
```

---

## Files to Change

All paths relative to `/home/anhar/codes/robostrata/`.

| File | Action | Justification |
|---|---|---|
| `pyproject.toml` | CREATE | hatchling, deps (pydantic, pyyaml), dev deps (pytest, pytest-asyncio, ruff, mypy), ruff/pytest/mypy config, CLI script |
| `.gitignore` | CREATE | python/uv/pytest/ruff caches, `.venv`, `recordings/` |
| `.python-version` | CREATE | `3.10` |
| `README.md` | CREATE | English project README (written alongside this plan; keep in sync) |
| `docs/architecture.md` | CREATE | the architecture note (section 1-15) in English, the normative reference |
| `docs/compatibility.md` | CREATE | portability levels (goal/task/skill/provider/policy) + compatibility matrix skeleton |
| `docs/roadmap.md` | CREATE | the 6 phases with exit criteria |
| `specification/semantics/lifecycle.md` | CREATE | lifecycle state machine + cancel semantics |
| `specification/semantics/task_graph.md` | CREATE | node semantics (sequence/parallel/conditional/loop/wait) |
| `specification/schemas/.gitkeep` | CREATE | generated JSON schemas land here (`schemas export`) |
| `src/robot_framework/__init__.py` | CREATE | version string |
| `src/robot_framework/spec/__init__.py` | CREATE | re-export all contracts |
| `src/robot_framework/spec/_base.py` | CREATE | `ContractModel`, `SCHEMA_VERSION`, shared enums |
| `src/robot_framework/spec/goal.py` | CREATE | `GoalSpec`, `SuccessCriterion`, `Constraint`, `HumanInteractionPolicy` |
| `src/robot_framework/spec/task.py` | CREATE | `TaskDefinition`, `TaskGraph`, node models, `RecoveryPolicy` |
| `src/robot_framework/spec/plan.py` | CREATE | `PlanProposal`, `PlanArtifactKind`, `NativeArtifact`, `PolicyGoal`, `ExecutiveRequirements` |
| `src/robot_framework/spec/skill.py` | CREATE | `SkillContract`, `PortSpec`, `Condition`, `ExpectedEffect`, `VerificationSpec`, `CancellationSpec`, `FailureSemantics` |
| `src/robot_framework/spec/provider.py` | CREATE | `ProviderManifest`, `ProviderKind`, `HardwareRequirement`, `ObservationSpace`, `ActionSpace` |
| `src/robot_framework/spec/robot.py` | CREATE | `RobotManifest`, `ComponentNode`, `ComponentEdge`, `CapabilityBinding`, `ResourceDecl` (component graph, not base+arm+gripper) |
| `src/robot_framework/spec/world.py` | CREATE | `Fact`, `Evidence`, `WorldSnapshot`, `Uncertainty`, `Validity` |
| `src/robot_framework/spec/assessment.py` | CREATE | `AssessmentReport`, `AssessmentStatus`, `RecommendedStep` |
| `src/robot_framework/spec/invocation.py` | CREATE | `SkillInvocation`, `SkillResult`, `LifecycleState`, `ProgressReport`, `FailureDiagnosis`, `VerificationStatus` |
| `src/robot_framework/spec/resource.py` | CREATE | `ResourceLease`, `CommandEnvelope`, `CommandAcknowledgement`, `ControlMode` |
| `src/robot_framework/spec/mission.py` | CREATE | `MissionEvent`, `MissionResult`, `MissionStatus` |
| `src/robot_framework/spec/profile.py` | CREATE | `DeploymentProfile`, `DeploymentMode`, `ExtensionRef` (the YAML in section 12) |
| `src/robot_framework/spec/export.py` | CREATE | `export_schemas(dir)` writes JSON schema per contract |
| `src/robot_framework/core/__init__.py` | CREATE | |
| `src/robot_framework/core/errors.py` | CREATE | error hierarchy (pattern above) |
| `src/robot_framework/core/clock.py` | CREATE | `Clock` protocol: `now()` (observation time) + `monotonic()` (deadlines); `MockClock` |
| `src/robot_framework/core/registry.py` | CREATE | generic `Registry` |
| `src/robot_framework/core/interfaces.py` | CREATE | Protocols: `TaskPlanner`, `Executive`, `SkillProvider`, `PolicyProvider`, `RobotBackend`, `SimulationBackend`, `GroundingPlugin`, `Verifier`, `WorldInterface`, `ExecutionHandle`, `MissionHandle` |
| `src/robot_framework/core/resource_manager.py` | CREATE | atomic reserve/release, bounded leases, epochs, `CommandAuthority.check(envelope)` |
| `src/robot_framework/core/world_interface.py` | CREATE | `InMemoryWorld` implementing `WorldInterface` with revisioned facts and validity |
| `src/robot_framework/core/validation.py` | CREATE | `PlanValidator`: skill catalog, parameter types, robot capability, executive compat, native-artifact gate |
| `src/robot_framework/core/skill_runtime.py` | CREATE | the 9-step pipeline, lifecycle, cancellation, OUTCOME_UNKNOWN, verification |
| `src/robot_framework/core/mission_supervisor.py` | CREATE | `MissionSupervisor.run()`; single-executive ownership rule; recorder |
| `src/robot_framework/core/recorder.py` | CREATE | `MissionRecorder` (in-memory + JSONL file sink) |
| `src/robot_framework/core/context.py` | CREATE | `FrameworkContext` (all registries + world + clock + resource manager) and `build_context(profile)` |
| `src/robot_framework/planning/__init__.py` | CREATE | |
| `src/robot_framework/planning/manual.py` | CREATE | `ManualPlanner`: loads a `TaskDefinition` from a task pack and emits a `PlanProposal` (kind=task_graph) |
| `src/robot_framework/executives/__init__.py` | CREATE | |
| `src/robot_framework/executives/sequential.py` | CREATE | `SequentialExecutive`: interprets portable TaskGraph (sequence, conditional, bounded loop, wait; rejects parallel in Phase 1 with UNSUPPORTED) |
| `src/robot_framework/providers/__init__.py` | CREATE | |
| `src/robot_framework/providers/mock.py` | CREATE | `MockObserveProvider`, `MockNavigateProvider`, `MockPickProvider`, `MockPlaceProvider`; fault-injection knobs (`fail_after`, `lie_success`, `drop_ack`, `cancel_latency_s`) |
| `src/robot_framework/verifiers/__init__.py` | CREATE | |
| `src/robot_framework/verifiers/world_fact.py` | CREATE | `WorldFactVerifier`: checks expected effects against fresh world facts (evidence-based) |
| `src/robot_framework/robot_backends/__init__.py` | CREATE | |
| `src/robot_framework/robot_backends/mock.py` | CREATE | `MockRobotBackend.dispatch(envelope)` → ack; enforces `CommandAuthority`; returns UNSUPPORTED for reset/step |
| `src/robot_framework/simulation_backends/__init__.py` | CREATE | |
| `src/robot_framework/simulation_backends/mock.py` | CREATE | `MockSimulationBackend`: declares capabilities `{reset, step, pause}`; `reset()` bumps epoch, invalidates facts |
| `src/robot_framework/extensions/__init__.py` | CREATE | |
| `src/robot_framework/extensions/null.py` | CREATE | `NullGroundingPlugin` (returns NOT_APPLICABLE); `ExtensionLoader` honouring `required: true` |
| `src/robot_framework/packages/__init__.py` | CREATE | |
| `src/robot_framework/packages/loader.py` | CREATE | load `robot_packages/<name>/manifest.yaml`, `task_packs/<name>/*.yaml`, `deployment_profiles/*.yaml` → contracts |
| `src/robot_framework/cli.py` | CREATE | `run`, `validate`, `schemas export` (argparse) |
| `robot_packages/mock_mobile_manipulator/manifest.yaml` | CREATE | component graph: base, arm_0, gripper_0, camera_0; capability bindings; resources |
| `robot_packages/mock_mobile_manipulator/conformance_tests/README.md` | CREATE | what a robot package must pass (Phase 2 fills in) |
| `task_packs/examples/bottle_delivery.task.yaml` | CREATE | observe → navigate → pick → navigate → place as a TaskGraph |
| `task_packs/examples/skills/*.skill.yaml` | CREATE | `perception.observe_target`, `navigation.go_to`, `manipulation.pick`, `manipulation.place` SkillContracts |
| `deployment_profiles/mock_bottle_delivery.yaml` | CREATE | mode=mock, planner=manual, executive=sequential, extensions=[], verification=evidence_based |
| `tests/conftest.py` | CREATE | fixtures: `clock`, `world`, `context`, `profile`, builders |
| `tests/contract/test_schema_roundtrip.py` | CREATE | every contract: build → json → validate → equal; `extra="forbid"` rejects unknown fields; schema export idempotent |
| `tests/contract/test_robot_manifest.py` | CREATE | component graph validation (cycles, dangling refs, duplicate resources) |
| `tests/unit/test_resource_manager.py` | CREATE | atomic reserve, lease expiry, epoch rejection |
| `tests/unit/test_world_interface.py` | CREATE | revisions, validity, stale detection |
| `tests/unit/test_validation.py` | CREATE | unknown skill, bad params, missing capability, unsupported artifact |
| `tests/unit/test_skill_runtime.py` | CREATE | lifecycle transitions, cancel semantics, OUTCOME_UNKNOWN |
| `tests/integration/test_bottle_delivery_mock.py` | CREATE | full mission via profile succeeds; MissionResult has verified effects |
| `tests/conformance/test_section14.py` | CREATE | the 9 mandatory behaviours (one test each, named after the row) |
| `tests/fault_injection/test_provider_faults.py` | CREATE | lie_success, drop_ack, timeout, cancel latency |

## NOT Building

- BehaviorTree.CPP executive, BehaviorTree.ROS2 transport, any `rclpy` code (Phase 2)
- Nav2, MoveIt/MTC, Servo, force-control, VLA/LeRobot providers (Phase 2/4)
- LLM, BTGenBot-2, PlanSys2 planner adapters and their validators (Phase 4)
- Gazebo/Isaac/MuJoCo simulation backends (Phase 2/5)
- `anhar_ae` affordance–effectivity extension (Phase 3) — only the hook interface + null plugin now
- Parallel TaskGraph nodes with resource-aware scheduling (interface reserved; executive returns UNSUPPORTED)
- Temporal plans (artifact kind exists so the validator can reject it; no executor)
- Studio/GUI, diagnostics dashboards, replay viewer
- Security (SROS2, credentials, audit) beyond "generated plans can only call registered skills"
- Learning/outcome-update pipelines
- A second robot package or non-manipulation use case (Phase 5)

---

## Step-by-Step Tasks

Order matters: each task's VALIDATE must pass before starting the next.

### Task 1: Project skeleton and tooling
- **ACTION**: Initialise git and the Python project.
- **IMPLEMENT**: `git init -b main`; create `pyproject.toml` with `[project] name="robot-framework"`, `version="0.1.0a1"`, `requires-python=">=3.10"`, `dependencies=["pydantic>=2.11,<3","pyyaml>=6"]`, `[project.optional-dependencies] dev=["pytest>=8","pytest-asyncio>=0.24","ruff>=0.6","mypy>=1.11","jsonschema>=4.25","types-PyYAML"]`, `[project.scripts] robot-framework="robot_framework.cli:main"`, `authors=[{name="Anhar Risnumawan"}]`, plus PROJECT_LAYOUT and LINT_CONFIG blocks verbatim, and `[tool.mypy] python_version="3.10"`, `strict=true`, `plugins=["pydantic.mypy"]`. Create `.gitignore`, `.python-version`, empty package `__init__.py` files, `src/robot_framework/__init__.py` with `__version__ = "0.1.0a1"`.
- **MIRROR**: PROJECT_LAYOUT, LINT_CONFIG
- **IMPORTS**: none
- **GOTCHA**: `uv sync` must run without ROS sourced; the package must never import `rclpy`. Pin `pydantic<3`.
- **VALIDATE**: `uv sync --extra dev && uv run python -c "import robot_framework; print(robot_framework.__version__)"` prints `0.1.0a1`.

### Task 2: Normative docs
- **ACTION**: Save the architecture note and semantics documents into the repo.
- **IMPLEMENT**: `docs/architecture.md` = English rendering of sections 1–15 of the note (tables kept; mark the config example "illustrative"); `docs/roadmap.md` = the 6-phase table with exit criteria; `docs/compatibility.md` = the four portability levels + an empty compatibility matrix (planner × executive × artifact kind); `specification/semantics/lifecycle.md` = state machine below; `specification/semantics/task_graph.md` = node semantics below.
  Lifecycle: `CREATED → VALIDATED → RESERVED → RUNNING → VERIFYING → SUCCEEDED`; from RUNNING/VERIFYING: `FAILED`; from any pre-terminal: `CANCELING → CANCELED`; from RUNNING when acknowledgement is lost: `OUTCOME_UNKNOWN`. Terminal: SUCCEEDED, FAILED, CANCELED, OUTCOME_UNKNOWN. **CANCELED is only entered after the provider confirms stop**; a cancel request alone keeps CANCELING. Resources are released on every terminal state.
  TaskGraph nodes: `skill` (id, skill_id, params, bindings), `sequence` (children, stops at first non-SUCCEEDED), `conditional` (fact predicate on world, then/else), `loop` (child, `max_iterations` required, `until` predicate), `wait_event` (fact predicate, `timeout_s` required), `parallel` (children, `completion: all|any`, `on_branch_failure: cancel_others|continue`; Phase 1 executive rejects with UNSUPPORTED), `recovery_ref` (named RecoveryPolicy).
- **MIRROR**: n/a (prose)
- **GOTCHA**: Do not claim anything is implemented that is not; the docs mark Phase ≥2 items explicitly.
- **VALIDATE**: files exist; `grep -c "Phase 2" docs/roadmap.md` ≥ 1.

### Task 3: Contract base + enums
- **ACTION**: Create `spec/_base.py`.
- **IMPLEMENT**: `ContractModel` (pattern CONTRACT_MODEL), `SCHEMA_VERSION`, `Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")]` for dotted ids, `EntityId = Annotated[str, Field(min_length=1)]`, `Timestamp = float` (seconds, documented as observation-clock), `DeploymentMode(str, Enum)` = MOCK, SIMULATION, HIL, REAL, REPLAY. `Unit` is a `str` field on every physical quantity model (`Quantity(value: float, unit: str)`), never a bare float with an implied unit.
- **MIRROR**: CONTRACT_MODEL, NAMING_CONVENTION
- **IMPORTS**: `from enum import Enum`; `from typing import Annotated`; `from pydantic import BaseModel, ConfigDict, Field`
- **GOTCHA**: `StrEnum` does not exist on 3.10; use `(str, Enum)`. Frozen models hash by value, so avoid `list` fields in models used as dict keys (use `tuple`).
- **VALIDATE**: `uv run python -c "from robot_framework.spec._base import ContractModel"`; mypy clean.

### Task 4: Core contracts (goal, task, plan, skill, provider, robot)
- **ACTION**: Implement the six authoring-side contracts.
- **IMPLEMENT**:
  - `goal.py`: `GoalSpec(goal_id, objective: Identifier, parameters: dict[str, Any], success_criteria: tuple[SuccessCriterion,...], constraints: tuple[Constraint,...], deadline_s: float|None, human_policy: HumanInteractionPolicy)`. `SuccessCriterion(predicate: str, args: tuple[str,...], expected: bool)`.
  - `task.py`: node models as a discriminated union on `kind` (`Literal["skill"]`, …) using `Annotated[Union[...], Field(discriminator="kind")]`; `TaskGraph(root: TaskNode, recoveries: dict[str, RecoveryPolicy])`; `TaskDefinition(task_id, objective, graph, required_capabilities: tuple[Identifier,...])`. Validator: `loop.max_iterations >= 1`, `wait_event.timeout_s > 0`, recovery_ref names exist.
  - `plan.py`: `PlanArtifactKind(str, Enum)` = TASK_GRAPH, NATIVE_BT_XML, TEMPORAL_PLAN, POLICY_GOAL. `PlanProposal(proposal_id, kind, task_graph: TaskGraph|None, native: NativeArtifact|None, policy_goal: PolicyGoal|None, assumptions: tuple[str,...], world_snapshot_id: str, executive_requirements: ExecutiveRequirements)`; model validator enforces exactly one payload matches `kind`. `NativeArtifact(format: str, content: str, validator_id: Identifier, resource_scope: tuple[Identifier,...], entry_contract: dict, exit_contract: dict)`.
  - `skill.py`: `SkillContract(skill_id, inputs: tuple[PortSpec,...], outputs: tuple[PortSpec,...], preconditions, hold_conditions, expected_effects: tuple[ExpectedEffect,...], verification: VerificationSpec, cancellation: CancellationSpec, failure_semantics: FailureSemantics, required_capabilities, required_resources: tuple[Identifier,...])`. `PortSpec(name, type: Literal["string","number","boolean","entity","pose","object"], required: bool, unit: str|None)`. `Condition(predicate, args, expected: bool, max_age_s: float|None)`. `CancellationSpec(mode: Literal["immediate","safe_state_first","custom"], max_stop_time_s: float)`.
  - `provider.py`: `ProviderManifest(provider_id, kind: ProviderKind, implements: tuple[Identifier,...], hardware: tuple[HardwareRequirement,...], domains: tuple[str,...], version: str, model_ref: str|None, cancellation: CancellationSpec)`. `ProviderKind` = SKILL, POLICY, DEVICE.
  - `robot.py`: `ComponentNode(component_id, type: str, resources: tuple[ResourceDecl,...], interfaces: tuple[str,...])`, `ComponentEdge(parent, child, joint: str|None)`, `CapabilityBinding(capability: Identifier, components: tuple[str,...], structural: bool)`, `RobotManifest(robot_id, components, edges, capabilities, calibration_ref, safety_ref, description_ref)`. Validator: edge endpoints exist, graph is acyclic (DFS), resource ids unique across components.
- **MIRROR**: CONTRACT_MODEL, NAMING_CONVENTION, ERROR_HANDLING (validators raise `ValueError`, pydantic wraps them; `packages/loader.py` converts to `ContractValidationError`)
- **IMPORTS**: `from typing import Any, Literal, Union, Annotated`; `from pydantic import Field, model_validator, field_validator`
- **GOTCHA**: Discriminated unions with recursive `TaskNode` need `model_rebuild()` at module end. Keep `dict[str, Any]` for `parameters` but validate against `PortSpec` in `PlanValidator`, not in the model.
- **VALIDATE**: `uv run pytest tests/contract -q` (write `test_schema_roundtrip.py` for these six in the same task; see Testing Strategy).

### Task 5: Runtime contracts (world, assessment, invocation, resource, mission, profile) + schema export
- **ACTION**: Implement the runtime-side contracts and the exporter.
- **IMPLEMENT**:
  - `world.py`: `Fact(predicate, args: tuple[EntityId,...], value: Any, source: str, observation_time: float, validity_s: float|None, confidence: float|None, revision: int)`; `WorldSnapshot(snapshot_id, revision, time, facts: tuple[Fact,...])` with `.lookup(predicate, args) -> Fact|None` and `.is_stale(fact, now) -> bool`. `Evidence(evidence_id, kind, ref, time)`.
  - `assessment.py`: `AssessmentStatus` = FEASIBLE, INFEASIBLE, UNKNOWN, NOT_APPLICABLE; `AssessmentReport(status, reason, context: AssessmentContext(world_snapshot_id, robot_state_revision, provider_id), evidence: dict[str, str], applicable_constraints: tuple[str,...], recommended_next_step: RecommendedStep|None)` — exactly the YAML in section 6.2.
  - `invocation.py`: `LifecycleState` (10 states), `VerificationStatus` = VERIFIED, FAILED, UNKNOWN, NOT_REQUIRED; `SkillInvocation(invocation_id, skill_id, provider_id, bound_params, lease_id, epoch, state, created_at)`; `ProgressReport(fraction: float|None, message, time)`; `FailureDiagnosis(category: Literal["perception_stale","unreachable","provider_timeout","hardware_fault","safety_stop","cancelled","ack_lost","verification_failed","unsupported","other"], detail, evidence_refs)`; `SkillResult(invocation_id, provider_status: Literal["SUCCESS","FAILURE","CANCELED","UNKNOWN"], state: LifecycleState, observed_effects: tuple[Fact,...], verification_status, evidence_references, failure_diagnosis: FailureDiagnosis|None)`.
  - `resource.py`: `ControlMode(str, Enum)` = POSITION, VELOCITY, EFFORT, TRAJECTORY, POLICY, NONE; `ResourceLease(lease_id, owner_id, resources: tuple[Identifier,...], control_mode, epoch: int, expires_at_monotonic: float)`; `CommandEnvelope(envelope_id, lease_id, epoch, target_resources, control_mode, payload: dict, issued_at_monotonic)`; `CommandAcknowledgement(envelope_id, accepted: bool, reason: str|None)`.
  - `mission.py`: `MissionStatus` = PENDING, VALIDATED, RUNNING, SUCCEEDED, FAILED, CANCELED, OUTCOME_UNKNOWN, REJECTED; `MissionEvent(mission_id, time, kind: str, payload: dict)`; `MissionResult(mission_id, status, goal_id, proposal_id, skill_results: tuple[SkillResult,...], verified_effects: tuple[Fact,...], rejection_reasons: tuple[str,...], events_ref: str|None)`.
  - `profile.py`: `DeploymentProfile(api_version: Literal["robot_framework/v1alpha1"], task_pack: str, robot_pack: str, deployment: Deployment(mode, backend, profile), planning: PlanningCfg(plugin, output_kind: PlanArtifactKind), execution: ExecutionCfg(plugin), extensions: tuple[ExtensionRef(id, required: bool, config: str|None),...], verification: VerificationCfg(profile), safety: SafetyCfg(profile), recording: RecordingCfg(mission_events: bool, decision_evidence: bool))`. Validator: `mode == REAL` requires `safety.profile` not to be `"mock"` or `"none"`.
  - `export.py`: `CONTRACTS: tuple[type[ContractModel],...]`; `export_schemas(out_dir: Path) -> list[Path]` writes `<ClassName>.schema.json` with `json.dumps(model.model_json_schema(), indent=2, sort_keys=True)`.
- **MIRROR**: CONTRACT_MODEL
- **IMPORTS**: `import json`; `from pathlib import Path`
- **GOTCHA**: `observation_time` uses the observation clock; `expires_at_monotonic`/`issued_at_monotonic` use the monotonic clock. Never compare the two. `value: Any` on `Fact` must be JSON-serialisable; add a `field_validator` that round-trips through `json.dumps`.
- **VALIDATE**: `uv run robot-framework schemas export /tmp/schemas && ls /tmp/schemas | wc -l` ≥ 15; `uv run pytest tests/contract -q`.

### Task 6: Errors, clock, registry, interfaces
- **ACTION**: Core infrastructure modules.
- **IMPLEMENT**: `errors.py` per ERROR_HANDLING. `clock.py`: `class Clock(Protocol): def now(self) -> float; def monotonic(self) -> float`; `SystemClock` (time.time / time.monotonic); `MockClock(now=0.0, mono=0.0)` with `advance(seconds)` advancing both and `advance_observation_only(seconds)` / `advance_monotonic_only(seconds)` so tests can split them. `registry.py` per REGISTRY_PATTERN. `interfaces.py`: all Protocols from section 3.2 with these exact signatures:
  ```python
  class TaskPlanner(Protocol):
      planner_id: str

      async def propose(
          self, goal: GoalSpec, world: WorldSnapshot, skills: Mapping[str, SkillContract]
      ) -> PlanProposal: ...


  class Executive(Protocol):
      executive_id: str
      supported_kinds: frozenset[PlanArtifactKind]

      async def start(
          self, plan: PlanProposal, runtime: "SkillRuntime", ctx: "FrameworkContext"
      ) -> MissionHandle: ...


  class GroundingPlugin(Protocol):
      plugin_id: str

      async def assess(
          self, request: SkillInvocation, provider: ProviderManifest, world: WorldSnapshot
      ) -> AssessmentReport: ...


  class SkillProvider(Protocol):
      manifest: ProviderManifest

      async def start(
          self, request: SkillInvocation, lease: ResourceLease, backend: "RobotBackend"
      ) -> ExecutionHandle: ...


  class PolicyProvider(Protocol):
      manifest: ProviderManifest

      async def infer(
          self, observations: Mapping[str, Any], goal_context: PolicyGoal
      ) -> ActionChunk: ...


  class RobotBackend(Protocol):
      backend_id: str

      async def dispatch(self, envelope: CommandEnvelope) -> CommandAcknowledgement: ...
      def capabilities(self) -> frozenset[str]: ...


  class SimulationBackend(RobotBackend, Protocol):
      async def reset(
          self,
      ) -> int: ...  # returns new epoch; raises UnsupportedOperationError if not supported


  class Verifier(Protocol):
      verifier_id: str

      async def verify(
          self, contract: SkillContract, invocation: SkillInvocation, world: "WorldInterface"
      ) -> tuple[VerificationStatus, tuple[Fact, ...], tuple[str, ...]]: ...


  class WorldInterface(Protocol):
      def snapshot(self) -> WorldSnapshot: ...
      def commit(self, facts: Iterable[Fact], source: str) -> int: ...  # returns new revision
      async def observe(self, predicate: str, args: tuple[str, ...]) -> Fact | None: ...
      def invalidate_all(self, reason: str) -> int: ...
  ```
  `ActionChunk(actions: tuple[dict,...], horizon: int, frame: str, epoch: int)` lives in `spec/invocation.py`.
- **MIRROR**: ERROR_HANDLING, REGISTRY_PATTERN, ASYNC_LONG_RUNNING_OPERATION
- **IMPORTS**: `from typing import Protocol, Generic, TypeVar, Mapping, Iterable, Any, runtime_checkable`
- **GOTCHA**: Decorate Protocols with `@runtime_checkable` so the registry can `isinstance` on registration. Use string forward refs for `SkillRuntime`/`FrameworkContext` to avoid cycles.
- **VALIDATE**: `uv run mypy src` clean.

### Task 7: ResourceManager and CommandAuthority
- **ACTION**: Implement atomic leases, expiry, epochs, and command gating.
- **IMPLEMENT**: `ResourceManager(clock, known_resources: frozenset[str])` with `reserve(owner_id, resources, control_mode, ttl_s) -> ResourceLease` (all-or-nothing; raises `ResourceConflictError(details={"conflicts": {...}})` listing current owners), `release(lease_id)`, `renew(lease_id, ttl_s)`, `owner_of(resource) -> str|None`, `current_epoch: int`, `bump_epoch(reason) -> int` (releases **all** leases, records reason). Expired leases are treated as released on the next call (lazy sweep using `clock.monotonic()`). `CommandAuthority(resource_manager)` with `check(envelope) -> CommandAcknowledgement`: rejects if lease unknown/expired, if `envelope.epoch != current_epoch` (reason `"stale_epoch"`), if any `target_resources` not in the lease, or if `control_mode` differs from the lease.
- **MIRROR**: ERROR_HANDLING, LOGGING_PATTERN
- **IMPORTS**: `import uuid`; `from robot_framework.spec import ResourceLease, CommandEnvelope, CommandAcknowledgement, ControlMode`
- **GOTCHA**: Single-threaded asyncio: atomicity is guaranteed by not awaiting inside `reserve`. Document that assumption; a lock (`asyncio.Lock`) is still added so a future threaded transport does not break it.
- **VALIDATE**: `uv run pytest tests/unit/test_resource_manager.py -q`.

### Task 8: InMemoryWorld
- **ACTION**: Implement `WorldInterface` for mock/testing.
- **IMPLEMENT**: `InMemoryWorld(clock)` storing `dict[tuple[str, tuple[str,...]], Fact]`; `commit()` bumps a global revision and stamps each fact with it; `snapshot()` returns a frozen `WorldSnapshot` with a fresh `snapshot_id`; `observe()` returns the stored fact re-stamped with `observation_time=clock.now()` only if an `ObservationSource` callback is registered for the predicate (mock providers register these), else `None`; `invalidate_all(reason)` sets `validity_s=0.0` on every fact (they become stale, not deleted) and records the reason. Provide `is_stale(fact)` using `clock.now() - fact.observation_time > validity_s`.
- **MIRROR**: CONTRACT_MODEL (facts are immutable; replace, never mutate)
- **GOTCHA**: The world is not the BT blackboard; do not store execution-local variables here. `value` must round-trip JSON.
- **VALIDATE**: `uv run pytest tests/unit/test_world_interface.py -q`.

### Task 9: PlanValidator
- **ACTION**: Validation, grounding and compatibility check stage.
- **IMPLEMENT**: `PlanValidator(ctx).validate(proposal, robot: RobotManifest, executive: Executive) -> ValidatedPlan` where `ValidatedPlan(proposal, skill_refs: tuple[str,...], resource_scope: frozenset[str])`. Checks, each appending a structured reason `{"code": ..., "node_id": ..., "detail": ...}` and finally raising `PlanRejectedError(details={"reasons": [...]})` if any: (1) `proposal.kind in executive.supported_kinds` else `unsupported_artifact_kind`; (2) every `skill` node's `skill_id` exists in `ctx.skills` else `unknown_skill`; (3) node params satisfy `PortSpec` (required present, type check for string/number/boolean/entity) else `invalid_parameter`; (4) union of `SkillContract.required_capabilities` ⊆ robot capabilities (structural) else `missing_capability`; (5) union of `required_resources` ⊆ robot resources else `unknown_resource`; (6) at least one registered provider implements each skill else `no_provider`; (7) for NATIVE_BT_XML/TEMPORAL_PLAN: reject in Phase 1 with `native_validator_missing` unless `native.validator_id` is registered (none are); (8) `loop` nodes have `max_iterations`, `wait_event` have `timeout_s` (already enforced by models; re-check defensively). Preflight **does not** evaluate future-step preconditions against the current world (section 5).
- **MIRROR**: ERROR_HANDLING
- **GOTCHA**: Capability check uses *structural* availability only; *current* availability (controller active, tool mounted) is a runtime check in the skill runtime.
- **VALIDATE**: `uv run pytest tests/unit/test_validation.py -q`.

### Task 10: SkillRuntime
- **ACTION**: The 9-step per-skill pipeline with lifecycle, cancellation and verification.
- **IMPLEMENT**: `SkillRuntime(ctx)` with `async def invoke(node: SkillNode, epoch: int, cancel: asyncio.Event) -> SkillResult`:
  1. **Validate request**: resolve `SkillContract`; bind params (→ `SkillInvocation` state CREATED→VALIDATED).
  2. **Resolve candidate providers**: `ctx.providers` whose manifest `implements` the skill; order: profile-declared preference, else registration order.
  3. **Assess**: for each `GroundingPlugin` in `ctx.extensions` call `assess()`; if any returns INFEASIBLE skip provider; UNKNOWN is **not** INFEASIBLE — if the report has `recommended_next_step`, record it and continue to the next provider, otherwise treat as allowed with a `MissionEvent(kind="assessment_unknown")`. If a plugin marked `required` raises or is missing → `ExtensionRequiredError` (no bypass). Precondition check: each `Condition` must match a non-stale fact; stale → result FAILED with diagnosis `perception_stale` (no retry inside the runtime; the executive's recovery policy decides).
  4. **Reserve**: `ResourceManager.reserve(owner=invocation_id, resources=contract.required_resources, ttl=contract.cancellation.max_stop_time_s + budget)` → RESERVED; conflict → FAILED (`category="other"`, detail `resource_conflict`), no command issued.
  5. **Recheck time-sensitive conditions**: re-evaluate conditions with `max_age_s`.
  6. **Start provider** → RUNNING; obtain `ExecutionHandle`.
  7. **Monitor**: `asyncio.wait` on `{handle.wait(), cancel.wait(), lease-expiry timer, hold-condition poll}`. On cancel: state CANCELING, call `handle.cancel()`, then `wait_for(handle.wait(), max_stop_time_s)`; on confirmation → CANCELED; on timeout → OUTCOME_UNKNOWN (never assume stop). On provider `UNKNOWN` status (ack lost) → OUTCOME_UNKNOWN. On hold-condition violation → cancel path with diagnosis.
  8. **Verify** → VERIFYING: if `contract.verification.required`, call the `Verifier` named by `verification.verifier_id`; VERIFIED → SUCCEEDED; FAILED → state FAILED with `verification_failed` even if provider said SUCCESS; UNKNOWN → OUTCOME_UNKNOWN.
  9. **Commit & release**: commit `observed_effects` (from verifier, not from provider claims) to the world with source=verifier id; `release(lease)`. Emit `MissionEvent` for every state transition.
  OUTCOME_UNKNOWN reconciliation helper: `async def reconcile(invocation) -> WorldSnapshot` re-observes every predicate in `expected_effects` and returns the snapshot; the executive must call this before any retry.
- **MIRROR**: ASYNC_LONG_RUNNING_OPERATION, LOGGING_PATTERN, ERROR_HANDLING
- **IMPORTS**: `import asyncio`, `from robot_framework.core.errors import ...`
- **GOTCHA**: `asyncio.wait_for` cancels the inner awaitable on timeout — wrap `handle.wait()` in `asyncio.shield` during cancel-confirmation so the provider's own stop routine is not torn down. Keep this function under 50 lines by splitting into `_assess`, `_reserve`, `_monitor`, `_verify_and_commit`.
- **VALIDATE**: `uv run pytest tests/unit/test_skill_runtime.py -q`.

### Task 11: MissionRecorder
- **ACTION**: Replayable decision record.
- **IMPLEMENT**: `MissionRecorder(mission_id, sink: Path|None)`: `record(kind, payload)` → appends `MissionEvent` to an in-memory tuple (rebuilt immutably) and, if sink, one JSON line. Kinds (fixed strings): `goal_received`, `plan_proposed`, `plan_validated`, `plan_rejected`, `skill_state`, `assessment`, `provider_selected`, `lease_acquired`, `lease_released`, `command_rejected`, `verification`, `effects_committed`, `epoch_bumped`, `mission_finished`. `events()` returns the tuple.
- **MIRROR**: LOGGING_PATTERN
- **GOTCHA**: Payloads must be JSON-serialisable; pass `model_dump(mode="json")` of contracts.
- **VALIDATE**: covered by integration test (JSONL file has ≥ 1 line per skill state transition).

### Task 12: FrameworkContext, ExtensionLoader, package loader
- **ACTION**: Wiring layer.
- **IMPLEMENT**: `FrameworkContext` dataclass(frozen=True) holding `clock, world, resources, skills: Registry[SkillContract], providers: Registry[SkillProvider], planners: Registry[TaskPlanner], executives: Registry[Executive], verifiers: Registry[Verifier], extensions: tuple[LoadedExtension,...], backend: RobotBackend, robot: RobotManifest, profile: DeploymentProfile, recorder: MissionRecorder`. `build_context(profile_path) -> FrameworkContext`: loads profile YAML → `DeploymentProfile`; loads `robot_packages/<robot_pack>/manifest.yaml` → `RobotManifest`; loads `task_packs/<task_pack>/skills/*.skill.yaml` → skills; selects `MockRobotBackend`/`MockSimulationBackend` for mode MOCK (any other mode → `UnsupportedOperationError("deployment mode X not available in this build")`); registers mock providers, `ManualPlanner`, `SequentialExecutive`, `WorldFactVerifier`; `ExtensionLoader.load(profile.extensions)` resolves ids from a `Registry[type[GroundingPlugin]]` (Phase 1 contains only `"null_grounding"`); unknown id with `required: true` → `ExtensionRequiredError`; unknown with `required: false` → warning event. `packages/loader.py`: YAML → contract via `Model.model_validate`, converting `pydantic.ValidationError` to `ContractValidationError(details={"file": ..., "errors": e.errors()})`.
- **MIRROR**: REGISTRY_PATTERN, ERROR_HANDLING
- **IMPORTS**: `import yaml` (`yaml.safe_load` only)
- **GOTCHA**: Never `yaml.load` without `SafeLoader`. Package roots are resolved relative to the profile file's directory parent (repo root), overridable by env `ROBOT_FRAMEWORK_ROOT`.
- **VALIDATE**: `uv run robot-framework validate deployment_profiles/mock_bottle_delivery.yaml` exits 0 and prints the validated skill list.

### Task 13: ManualPlanner and SequentialExecutive
- **ACTION**: Reference planner and executive.
- **IMPLEMENT**: `ManualPlanner(task_definitions: Mapping[str, TaskDefinition])`: `propose()` picks the `TaskDefinition` whose `objective == goal.objective` (else `PlanRejectedError(unknown_objective)`), substitutes `goal.parameters` into node params where a param value is the string `"$goal.<key>"`, returns `PlanProposal(kind=TASK_GRAPH, world_snapshot_id=world.snapshot_id, assumptions=("manual_task_pack",))`. `SequentialExecutive(supported_kinds={TASK_GRAPH})`: `start()` returns a `MissionHandle` wrapping an `asyncio.Task` that walks the graph: `sequence` runs children in order, stops on first non-SUCCEEDED and applies the node's `recovery_ref` (Phase 1 policies: `retry(max_attempts, requires_reconcile: bool)` and `abort`); `conditional` evaluates predicate against `world.snapshot()`; `loop` repeats until `until` holds or `max_iterations`; `wait_event` polls every `poll_interval_s` until predicate or timeout; `parallel` → raises `UnsupportedOperationError`. On OUTCOME_UNKNOWN the executive **must** call `runtime.reconcile()` and re-check expected effects before counting a retry; if effects already hold, mark the node SUCCEEDED-by-reconciliation (event `reconciled_success`) and do **not** re-execute. `MissionHandle.cancel()` sets the shared cancel event and awaits the task.
- **MIRROR**: ASYNC_LONG_RUNNING_OPERATION, ERROR_HANDLING
- **GOTCHA**: One mission = one executive. `MissionSupervisor` enforces that only one `MissionHandle` is live per context (second `run()` while running → `FrameworkError("mission_already_running")`).
- **VALIDATE**: `uv run pytest tests/integration -q`.

### Task 14: MissionSupervisor and CLI
- **ACTION**: Top-level orchestration and entry points.
- **IMPLEMENT**: `MissionSupervisor(ctx)`: `async def run(goal: GoalSpec) -> MissionResult`: record `goal_received` → planner from `profile.planning.plugin` → `propose` → `PlanValidator.validate` (rejection → `MissionResult(status=REJECTED, rejection_reasons=...)`, no execution) → executive from `profile.execution.plugin` → `start` → await handle → aggregate `SkillResult`s → `verified_effects` = union of results' `observed_effects` with `verification_status == VERIFIED` → status mapping (all SUCCEEDED → SUCCEEDED; any OUTCOME_UNKNOWN unresolved → OUTCOME_UNKNOWN; canceled → CANCELED; else FAILED). `cli.py` with argparse subcommands `run <profile> [--goal goal.yaml] [--record out.jsonl]`, `validate <profile>`, `schemas export <dir>`; `run` prints `MissionResult.model_dump_json(indent=2)` and exits 0 only on SUCCEEDED.
- **MIRROR**: LOGGING_PATTERN, ERROR_HANDLING
- **GOTCHA**: `asyncio.run()` once in `main()`; configure `logging.basicConfig(level=INFO)` only in the CLI, never in library code.
- **VALIDATE**: `uv run robot-framework run deployment_profiles/mock_bottle_delivery.yaml` exits 0 with `"status": "SUCCEEDED"`.

### Task 15: Mock providers, verifier, backends
- **ACTION**: Mock implementations that make the semantics testable.
- **IMPLEMENT**: `providers/mock.py`: a `MockProviderBase(manifest, world, clock, faults: MockFaults)` where `MockFaults(duration_s=0.01, fail_after_s=None, lie_success=False, drop_ack=False, cancel_latency_s=0.0, refuse_cancel=False)`. `start()` reserves nothing itself (the runtime did), builds a `CommandEnvelope` from the lease and dispatches it through `backend.dispatch()`; a rejected ack → provider status FAILURE with diagnosis `command_rejected`. Each provider simulates its effect by committing facts to the world **only when not lying**: observe → `pose_known(<target>)=true`; navigate → `at(robot, <location>)=true`; pick → `holding(robot, <object>)=true` and registers an observation source for `holding`; place → `holding=false`, `at(<object>, <location>)=true`. `lie_success` returns SUCCESS without committing. `drop_ack` returns provider_status UNKNOWN after the effect may or may not have happened (parameter `effect_happened: bool`). `verifiers/world_fact.py`: `WorldFactVerifier` re-observes each `ExpectedEffect` via `world.observe()` (falls back to snapshot lookup if no observation source) and returns VERIFIED only when every expected fact matches and is non-stale; mismatch → FAILED; missing → UNKNOWN. `robot_backends/mock.py`: `MockRobotBackend(authority)`: `dispatch()` = `authority.check()` + record; `capabilities()` = `{"dispatch"}`; `reset()` raises `UnsupportedOperationError`. `simulation_backends/mock.py`: `MockSimulationBackend(authority, resources, world)`: `capabilities()` = `{"dispatch","reset","step","pause"}`; `reset()` → `resources.bump_epoch("sim_reset")`, `world.invalidate_all("sim_reset")`, returns new epoch; `step()`/`pause()` no-ops with events.
- **MIRROR**: ASYNC_LONG_RUNNING_OPERATION, ERROR_HANDLING
- **GOTCHA**: Mock "duration" uses `await asyncio.sleep(duration_s)` real time by default for simplicity (keep ≤ 0.05 s); tests that need deterministic time use `MockClock` for staleness only.
- **VALIDATE**: `uv run pytest tests/fault_injection -q`.

### Task 16: Example robot package, task pack, deployment profile
- **ACTION**: Authoring-side YAML that exercises the loaders.
- **IMPLEMENT**: `robot_packages/mock_mobile_manipulator/manifest.yaml` (components: `base` [resource `base`], `arm_0` [resource `arm_0`], `gripper_0` [resource `gripper_0`], `camera_0`; edges base→arm_0→gripper_0, arm_0→camera_0; capabilities `navigation.ground`, `manipulation.single_arm`, `perception.rgbd` with `structural: true`). Four `*.skill.yaml` files with preconditions/effects: e.g. `manipulation.pick`: inputs `object: entity`; preconditions `pose_known(object)=true (max_age_s=5)`, `holding(robot, *)=false`; expected_effects `holding(robot, object)=true`; verification `{required: true, verifier_id: world_fact}`; cancellation `safe_state_first, max_stop_time_s: 2.0`; required_resources `[arm_0, gripper_0]`; required_capabilities `[manipulation.single_arm]`. `task_packs/examples/bottle_delivery.task.yaml`: objective `deliver_object`; sequence: observe(`$goal.object`) → go_to(`$goal.pickup_location`) → pick(`$goal.object`) → go_to(`$goal.delivery_location`) → place(`$goal.object`, `$goal.delivery_location`); recovery `retry_after_reconcile: {max_attempts: 2, requires_reconcile: true}` referenced by pick. `deployment_profiles/mock_bottle_delivery.yaml` exactly as section 12 but `mode: mock`, `backend: mock_sim`, `planning.plugin: manual`, `execution.plugin: sequential`, `extensions: []`, `safety.profile: mock`. Add `deployment_profiles/mock_bottle_delivery_ae_required.yaml` identical but `extensions: [{id: anhar_affordance_effectivity, required: true}]` (used by the conformance test to prove no silent bypass).
- **MIRROR**: NAMING_CONVENTION
- **GOTCHA**: YAML lists become tuples in models; the loader must not reject that (pydantic coerces list→tuple by default).
- **VALIDATE**: `uv run robot-framework validate deployment_profiles/mock_bottle_delivery.yaml` exit 0; the `_ae_required` profile exits non-zero with code `extension_required`.

### Task 17: Conformance suite (section 14) and remaining tests
- **ACTION**: Write `tests/conformance/test_section14.py` with one test per mandatory behaviour, plus `tests/integration/test_bottle_delivery_mock.py`.
- **IMPLEMENT**: see Testing Strategy table; each test uses `build_context` on the mock profile and manipulates `MockFaults`/world directly.
- **MIRROR**: TEST_STRUCTURE
- **GOTCHA**: Tests must not depend on wall-clock ordering beyond the ≤ 0.05 s mock durations; use `asyncio.Event`s for synchronisation where two providers must overlap.
- **VALIDATE**: `uv run pytest -q` all green; `uv run pytest --cov=robot_framework --cov-report=term-missing` ≥ 80 %.

### Task 18: README finalisation and roadmap hand-off
- **ACTION**: Make README match what actually runs; mark Phase 1 exit criteria.
- **IMPLEMENT**: update README quick-start commands to the real CLI output; in `docs/roadmap.md` set Phase 1 status `complete` only when Task 17 is green; add "What is implemented vs. designed" table to README.
- **VALIDATE**: every command in README runs as written.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_contract_roundtrip[<Model>]` (parametrised over all contracts) | built instance | `Model.model_validate_json(m.model_dump_json()) == m` | no |
| `test_contract_rejects_unknown_field` | dict with extra key | `ValidationError` | yes |
| `test_schema_export_is_idempotent` | export twice | identical bytes | no |
| `test_robot_manifest_rejects_cycle` | edges a→b, b→a | `ValueError` match `cycle` | yes |
| `test_robot_manifest_rejects_duplicate_resource` | two components declare `arm_0` | `ValueError` match `duplicate` | yes |
| `test_plan_proposal_requires_matching_payload` | kind=TASK_GRAPH, native set | `ValueError` | yes |
| `test_reserve_is_all_or_nothing` | A holds `base`; B asks `{base, arm_0}` | `ResourceConflictError`, `arm_0` still free | yes |
| `test_lease_expires_on_monotonic_clock` | ttl 1 s; advance monotonic 2 s | `owner_of` is None; command rejected `lease_expired` | yes |
| `test_bump_epoch_rejects_old_commands` | envelope epoch n; bump → n+1 | ack `accepted=False`, reason `stale_epoch` | yes |
| `test_world_marks_fact_stale` | validity 5 s; advance 6 s | `is_stale` True | yes |
| `test_validator_rejects_unknown_skill` | graph with `manipulation.fly` | `PlanRejectedError` reasons contain `unknown_skill` | yes |
| `test_validator_rejects_missing_capability` | robot without `manipulation.single_arm` | reason `missing_capability` | yes |
| `test_validator_rejects_temporal_artifact_for_sequential_executive` | kind=TEMPORAL_PLAN | reason `unsupported_artifact_kind` | yes |
| `test_runtime_cancel_waits_for_provider_confirmation` | cancel_latency 0.02 s | state CANCELING observed, then CANCELED; lease released after | yes |
| `test_runtime_cancel_timeout_yields_outcome_unknown` | refuse_cancel | OUTCOME_UNKNOWN, lease released, event recorded | yes |
| `test_runtime_stale_precondition_fails_without_command` | advance clock past max_age | FAILED `perception_stale`; backend saw 0 envelopes | yes |
| `test_runtime_unknown_assessment_is_not_infeasible` | plugin returns UNKNOWN | provider still runs; `assessment_unknown` event | yes |

### Conformance tests (section 14; file `tests/conformance/test_section14.py`)

| Test | Scenario | Expected |
|---|---|---|
| `test_two_providers_same_actuator_never_overlap` | two pick invocations on `arm_0` concurrently | second gets `resource_conflict`; backend never holds two live leases on `arm_0`; envelope count from the loser is 0 |
| `test_provider_success_without_held_object_is_not_task_success` | `lie_success=True` on pick | SkillResult `provider_status=SUCCESS`, `verification_status=FAILED`, state FAILED; mission FAILED |
| `test_lost_ack_reconciles_before_retry` | `drop_ack=True, effect_happened=True` | OUTCOME_UNKNOWN → `reconcile` → `reconciled_success` event; pick provider started exactly once |
| `test_stale_observation_holds_action` | advance observation clock past `max_age_s` | pick FAILED `perception_stale`, 0 commands |
| `test_sim_reset_drops_queued_epoch_commands` | start navigate, call `sim.reset()` mid-run | provider's next envelope rejected `stale_epoch`; world facts stale |
| `test_unavailable_skill_rejected_before_execution` | planner emits unknown skill | mission REJECTED, 0 commands, reason `unknown_skill` |
| `test_temporal_artifact_rejected_not_downgraded` | PlanProposal kind=TEMPORAL_PLAN | REJECTED `unsupported_artifact_kind`; no sequence executed |
| `test_required_extension_failure_has_no_silent_bypass` | `_ae_required` profile | `build_context` raises `ExtensionRequiredError`; no mission runs |
| `test_robot_without_capability_yields_unsupported_goal` | robot manifest without `navigation.ground` | REJECTED `missing_capability` listing the capability |

### Fault-injection tests (`tests/fault_injection/test_provider_faults.py`)

provider timeout → cancel path → CANCELED/OUTCOME_UNKNOWN; command rejected by authority → FAILURE with `command_rejected`; lease renewal keeps long skill alive; cancel during VERIFYING is ignored (verification completes).

### Edge Cases Checklist
- [x] Empty input (empty TaskGraph → model validation error)
- [x] Maximum size input (loop with `max_iterations` cap; no unbounded loops)
- [x] Invalid types (PortSpec checks)
- [x] Concurrent access (resource conflicts, single live mission)
- [x] Network failure (ack lost → OUTCOME_UNKNOWN)
- [x] Permission denied (command authority rejection)

---

## Validation Commands

### Static Analysis
```bash
cd /home/anhar/codes/robostrata
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```
EXPECT: zero findings, zero type errors.

### Unit Tests
```bash
uv run pytest tests/contract tests/unit -q
```
EXPECT: all pass.

### Full Test Suite
```bash
uv run pytest -q --cov=robot_framework --cov-report=term-missing
```
EXPECT: all pass; coverage ≥ 80 %.

### Schema Validation
```bash
uv run robot-framework schemas export specification/schemas
git diff --exit-code specification/schemas   # committed schemas match generated ones
```
EXPECT: no diff.

### Manual Validation
- [ ] `uv run robot-framework validate deployment_profiles/mock_bottle_delivery.yaml` → exit 0
- [ ] `uv run robot-framework run deployment_profiles/mock_bottle_delivery.yaml --record /tmp/m.jsonl` → `"status": "SUCCEEDED"`, JSONL contains `goal_received … mission_finished`
- [ ] `uv run robot-framework validate deployment_profiles/mock_bottle_delivery_ae_required.yaml` → non-zero, prints `extension_required`
- [ ] Without ROS sourced (`env -i HOME=$HOME PATH=$PATH uv run pytest -q`) everything still passes

---

## Acceptance Criteria
- [ ] All 18 tasks completed
- [ ] All validation commands pass
- [ ] Phase 1 exit criterion from the roadmap met: a simple task runs without LLM and without A-E; cancellation, resource ownership, and verification work and are covered by the conformance suite
- [ ] No `rclpy` / ROS import anywhere under `src/`
- [ ] No type errors, no lint errors
- [ ] README commands run as written

## Completion Checklist
- [ ] Code follows the patterns defined above (frozen contracts, dotted ids, Protocol interfaces)
- [ ] Errors raise `FrameworkError` subclasses with stable `code`; expected outcomes are values, not exceptions
- [ ] Logging via module loggers + MissionRecorder; no `print` outside `cli.py`
- [ ] Tests follow AAA with builders in `conftest.py`
- [ ] No hardcoded values (durations, ttl, max attempts come from contracts/profile)
- [ ] `docs/` and README updated to reflect what runs
- [ ] No scope creep into Phase 2+ items
- [ ] Self-contained — implementer needs no further searching

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Contracts over-designed before real backends exist, forcing churn in Phase 2 | Medium | Medium | `v1alpha1` versioning; keep fields minimal; every field must be exercised by a Phase 1 test or be removed |
| asyncio cancel/shield subtleties produce flaky cancel tests | Medium | High | explicit `asyncio.Event` synchronisation in mocks; `cancel_latency_s` deterministic; no reliance on scheduler order |
| Discriminated recursive unions in pydantic v2 for TaskGraph are fiddly | Medium | Low | `model_rebuild()`; test deep nesting in contract tests |
| Py3.10 host vs. newer syntax habits | High | Low | ruff `target-version=py310` + mypy `python_version=3.10` catch it |
| BT.CPP 4 absent on host blocks Phase 2 | High | Medium (Phase 2) | recorded in roadmap; Phase 2 starts with a source build of BT.CPP 4.6+ in a colcon workspace |
| "Mock" semantics drift from later real backends (e.g. reset) | Medium | Medium | backends declare capabilities; real backend returns UNSUPPORTED; conformance tests are backend-parametrised from Phase 2 |

## Notes
- Naming: the Python distribution is `robot-framework`, the import package `robot_framework`, the folder `robostrata`. The research extension will be `extensions/anhar_ae` (Phase 3); `ae_` is never a core prefix.
- The existing `../llm2bt-arm` project already implements look-then-grasp effectivity evidence for the PiPER arm in MuJoCo. It is the natural source for Phase 3's `anhar_ae` plugin and for a Phase 5 MuJoCo backend, but Phase 1 must not depend on it.
- The git identity on this host is `anhrisn`; the pyproject author is `Anhar Risnumawan` (matches sibling projects).
- The plan language is English to match the repository; the originating architecture note was in Indonesian and is preserved in English in `docs/architecture.md`.

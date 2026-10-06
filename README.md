# robostrata — `robot_framework`

A standardized, extensible robot task framework: **one set of contracts for goals, skills, state,
evidence, commands and results**, with planners, executives, skill providers, robots, simulators and
research extensions as swappable packages.

> **Status: Phase 1 complete (core contracts + mock runtime).** The contracts, the mock runtime and
> the conformance suite run today without ROS, without an LLM and without the
> affordance–effectivity extension. Real robots, simulators, behavior-tree executives and
> LLM/BTGenBot-2/PlanSys2/VLA backends are later phases; the
> [Implemented vs. designed](#implemented-vs-designed) table is the source of truth. The Phase 1
> plan and its implementation report live under `.claude/PRPs/`.

## Why

Most robot stacks hard-wire one planner, one executive, one robot and one AI method together. This
framework instead **standardizes the meaning** of a goal, a skill, a world fact, a command and a
result, and leaves the algorithms open:

- The same task definition can run on different robots when they expose the required capabilities.
- Planners (manual, LLM, BTGenBot-2, PlanSys2) and executives (BehaviorTree.CPP, delegated) are
  configuration choices that must pass a compatibility check, not code changes.
- A provider reporting `SUCCESS` is **not** task success. Success means a **verified physical effect**.
- Affordance–effectivity reasoning (the author's research line) is an **optional extension package**,
  required in the research profile and absent in the baseline profile, without any change to the core.

## Design principles

1. **Core defines contracts, not algorithms.** The core never computes reachability, grasps or
   locomotion; it validates, schedules, reserves, monitors, verifies and records.
2. **Separate task planning, executive, and motor policy.** One technology may fill several roles
   through different adapters; no technology is forced into a role it does not fit.
3. **Portable TaskGraph plus validated native artifacts.** Behavior-tree XML, temporal plans and
   policy goals are first-class artifacts with declared executives, validators and resource scopes.
   Unsupported artifacts are rejected, never silently downgraded.
4. **Evidence, not facts.** Every world fact carries source, observation time, validity, uncertainty
   and revision. Assessments are `FEASIBLE | INFEASIBLE | UNKNOWN | NOT_APPLICABLE`; unknown is not
   infeasible and confidence is not permission to move.
5. **Resource ownership and execution epochs.** Atomic, bounded leases on arms, bases, grippers,
   control modes and workspaces; commands from a stale epoch or without a valid lease are rejected.
6. **Cancel is a request, stop is an observation.** A cancel request is acknowledged; `CANCELED` is
   only reached after the provider confirms, otherwise the outcome is `OUTCOME_UNKNOWN` and the
   world is re-observed before any retry.
7. **Simulation and real share contracts, not assumptions.** Backends declare what they support
   (`reset`, `step`, `pause`, ground truth); real backends return `UNSUPPORTED` rather than faking it.
8. **Safety, security and recovery are not add-ons.** All commands pass a single command authority;
   generated plans can only call registered skills; recovery is diagnosis-driven and budgeted.

## Architecture

```text
                    USER / APPLICATION / OPERATOR
                  Natural language | GUI | API | Teleop
                                  |
                         GOAL & TASK CONTRACT
                                  |
                         PLANNING / DECISION ROUTER
                    manual | LLM | BTGenBot-2 | PlanSys2
                                  |
                           PLAN PROPOSAL
              TaskGraph | Native BT | TemporalPlan | PolicyGoal
                                  |
                VALIDATION, GROUNDING & COMPATIBILITY CHECK
                                  |
                         MISSION SUPERVISOR
                                  |
                          EXECUTIVE BACKEND
                 sequential (ref) | BehaviorTree.CPP | delegated
                                  |
                            SKILL RUNTIME
   validate -> resolve -> assess -> reserve -> recheck -> start -> monitor -> verify -> commit
                                  |
                         EXECUTION PROVIDERS
             Nav2 | MoveIt/MTC | Servo | Force | VLA/RL | Device | mock
                                  |
                   COMMAND AUTHORITY & MODE ARBITRATION
                                  |
                           ROBOT BACKEND
                  ros2_control | Vendor SDK | Autopilot | mock
                           REAL / SIMULATION

   SHARED SERVICES                         EXTENSIONS
   World state & evidence                  Affordance–effectivity (anhar_ae)
   Capability / skill / provider registry  Custom grounding & recovery
   Resource manager & epochs               Domain reasoning, task families
   Safety supervision, lifecycle, health   Custom Studio panels
   Logging, replay & evaluation
```

The full architecture note (what was wrong with the earlier design, the contract catalogue, how
LLM/BTGenBot-2/PlanSys2/VLA integrate, world model, robot packages, sim/real, safety, packaging,
conformance) lives in [`docs/architecture.md`](docs/architecture.md). The normative lifecycle and
TaskGraph semantics are in [`specification/semantics/`](specification/semantics/).

## Standardized contracts

Every contract is a versioned, strictly validated model (`schema_version`, unknown fields rejected,
units explicit). JSON Schemas are generated from the models, never hand-written.

| Contract | Minimum content |
|---|---|
| `GoalSpec` | objective, parameters, success criteria, constraints, deadline, human-interaction policy |
| `TaskDefinition` / `TaskGraph` | skill composition, dependencies, conditionals, bounded loops, event waits, concurrency, recovery refs |
| `PlanProposal` | artifact kind + payload, assumptions, world snapshot id, executive requirements |
| `SkillContract` | typed ports, pre/hold conditions, expected effects, verification, cancellation, failure semantics, required capabilities and resources |
| `ProviderManifest` | implemented skills, observation/action space, hardware needs, domains, versions |
| `RobotManifest` | component **graph** (not fixed base+arm+gripper), resources, capability bindings, calibration/safety refs |
| `WorldSnapshot` / `Fact` / `Evidence` | entity ids, relations, timestamps, validity, uncertainty, source, revision |
| `AssessmentReport` | status, reason, context, evidence, applicable constraints, recommended next step |
| `SkillInvocation` / `SkillResult` | identity, bound params, lifecycle state, provider status, **observed** effects, verification status, diagnosis |
| `ResourceLease` / `CommandEnvelope` | owner, resources, control mode, epoch, expiry; every command carries lease + epoch |
| `DeploymentProfile` | task pack, robot pack, mode, backend, planner, executive, extensions (`required` flag), verification, safety, recording |

Skill lifecycle: `CREATED → VALIDATED → RESERVED → RUNNING → VERIFYING → SUCCEEDED`, with
`FAILED`, `CANCELING → CANCELED`, and `OUTCOME_UNKNOWN`
(full transition table: [`specification/semantics/lifecycle.md`](specification/semantics/lifecycle.md)).

## Repository layout

```text
robostrata/
  README.md
  pyproject.toml                  # uv + hatchling, src layout
  docs/                           # architecture.md, roadmap.md, compatibility.md
  specification/
    schemas/                      # generated JSON Schemas (one per contract)
    semantics/                    # lifecycle.md, task_graph.md
  src/robot_framework/
    spec/                         # the contracts (pydantic v2, frozen, schema_version v1alpha1)
    core/                         # registry, resource_manager, world_interface, validation,
                                  # skill_runtime, mission_supervisor, recorder, context, clock
    planning/                     # manual (P1) | llm | btgenbot2 | plansys2 (P4)
    executives/                   # sequential (P1) | btcpp | delegated (P2+)
    providers/                    # mock (P1) | navigation | manipulation | perception | policies
    verifiers/                    # world_fact (P1)
    robot_backends/               # mock (P1) | ros2_control | vendor_sdk | autopilot
    simulation_backends/          # mock (P1) | gazebo | isaac | mujoco
    extensions/                   # loader + null (P1) | anhar_ae (P3)
    packages/                     # YAML loaders for robot/task packs, goals and profiles
    cli.py
    # transports/ (ros2, model_rpc) arrives in Phase 2
  robot_packages/<robot>/         # manifest.yaml, conformance_tests/ (+ description, calibration P2)
  task_packs/<pack>/              # *.task.yaml, skills/*.skill.yaml, goals/*.goal.yaml
  deployment_profiles/*.yaml
  tests/{contract,unit,integration,conformance,fault_injection}/
```

## Quick start

Requires Python 3.10+ and [`uv`](https://docs.astral.sh/uv/). ROS 2 is **not** required (if a ROS
environment is sourced, its pytest plugins are blocked in `pyproject.toml`).

```bash
uv sync --extra dev
uv run pytest -q                                   # contract, unit, integration, conformance, faults
uv run robot-framework validate deployment_profiles/mock_bottle_delivery.yaml
uv run robot-framework run deployment_profiles/mock_bottle_delivery.yaml --record /tmp/mission.jsonl
uv run robot-framework schemas export specification/schemas
```

- `validate` plans the profile's default goal and prints the validated plan (skills, resource
  scope, planner, executive) as JSON without executing anything.
- `run` executes the mission and prints the `MissionResult` as JSON (`"status": "SUCCEEDED"`); with
  `--record` every decision is appended to a JSONL file, from `goal_received` to
  `mission_finished`. Pass `--goal path/to/goal.yaml` to run a different goal.
- `schemas export` writes one JSON Schema per contract.
- Exit codes: `0` success, `1` mission finished but did not succeed (`FAILED`, `REJECTED`,
  `CANCELED`, `OUTCOME_UNKNOWN`), `2` framework error, printed as JSON on stderr with a stable
  `error` code (e.g. `extension_required`, `unsupported`, `contract_validation`), `3` internal error
  (a bug; the traceback is logged).
- Logs go to stderr (`--log-level`, default `INFO`); results go to stdout.

The example mission moves `bottle_17` from `kitchen_table` to `desk_2` on a mock mobile
manipulator: `go_to → observe → pick → go_to → place`. The object is observed right before the pick
because the pick precondition only accepts a pose observed in the last 5 s. Every skill holds
resource leases, every command passes the command authority, and every step only succeeds once
its expected effect has been re-observed. No LLM and no affordance–effectivity extension is
involved.

The research profile `deployment_profiles/mock_bottle_delivery_ae_required.yaml` requires the
`anhar_affordance_effectivity` extension, which ships in Phase 3. Until then it fails with
`extension_required` (exit code 2) rather than running without it.

Baseline deployment profile (`deployment_profiles/mock_bottle_delivery.yaml`):

```yaml
api_version: robot_framework/v1alpha1
task_pack: examples
robot_pack: mock_mobile_manipulator
default_goal: goals/deliver_bottle.goal.yaml
deployment: {mode: mock, backend: mock_sim, profile: mock}
planning: {plugin: manual, output_kind: task_graph}
execution: {plugin: sequential, lease_ttl_s: 5.0, monitor_poll_s: 0.005}
extensions: []            # research profile: [{id: anhar_affordance_effectivity, required: true}]
verification: {profile: evidence_based}
safety: {profile: mock}
recording: {mission_events: true, decision_evidence: true}
```

Only `mode: mock` with `backend: mock_sim` or `mock_robot` is available in this build; any other
mode or backend fails with `unsupported` instead of pretending to work.

Switching planner, executive, robot or mode is a profile change **plus** a compatibility validation.
A `required: true` extension that is missing or failing aborts the mission; there is no silent
fallback to a reduced mode.

## Conformance behaviours (mandatory tests)

| Situation | Required behaviour |
|---|---|
| Two providers request the same actuator | one is refused or waits; never concurrent commands |
| Provider reports success but the object is not held | task is **not** successful |
| Acknowledgement lost after an action may have happened | `OUTCOME_UNKNOWN`, reconcile state before any retry |
| Observation / TF too old | action held or information refreshed per policy |
| Simulation reset while commands are queued | old-epoch commands dropped |
| Planner emits an unavailable skill | rejected before execution with structured reasons |
| Temporal artifact given to a non-temporal executive | rejected, not silently sequenced |
| Required extension fails | no silent bypass |
| Robot lacks a required capability | unsupported goal or explicit alternative |

Each row is one test in [`tests/conformance/test_section14.py`](tests/conformance/test_section14.py)
(the sim-reset row has two: queued commands and a running skill).

Portability is measured separately at four levels: **goal**, **task**, **provider**, **policy**
([`docs/compatibility.md`](docs/compatibility.md)).

## Implemented vs. designed

| Component | Phase 1 (implemented) | Later |
|---|---|---|
| Contracts + JSON Schema export | ✔ | evolve under `schema_version` |
| Registry, resource manager, epochs, command authority | ✔ | ros2_control claiming bridge (P2) |
| In-memory world with evidence/validity | ✔ | TF / Nav2 / MoveIt / perception projections (P2) |
| Plan validator (skills, params, capabilities, artifact kind) | ✔ | BT XML + PDDL validators (P4) |
| Skill runtime (9-step pipeline, cancel, verify) | ✔ | — |
| Sequential TaskGraph executive | ✔ | BehaviorTree.CPP 4 executive, delegated PlanSys2 (P2/P4) |
| Manual planner | ✔ | LLM, BTGenBot-2, PlanSys2 adapters (P4) |
| Mock providers / backends / sim with fault injection | ✔ | Nav2, MoveIt/MTC, Servo, VLA via policy server (P2/P4) |
| Extension hook + null plugin | ✔ | `anhar_ae` affordance–effectivity package (P3) |
| Example robot package, task pack, profile | ✔ | real PiPER mobile manipulator + a non-manipulation embodiment (P2/P5) |
| Conformance + fault-injection suites | ✔ | backend-parametrised across sim/real (P5) |
| Studio, diagnostics, replay, evaluation tools | — | P6 |
| Security (SROS2, credentials, audit) | — | P5/P6 |

## Roadmap

| Phase | Proves |
|---|---|
| 1. Core contracts + mock runtime | simple task runs without LLM and without A-E; cancellation, ownership, verification work |
| 2. Pilot mobile manipulator | observe/navigate/pick/place on simulator and pilot robot through the same contracts (ROS 2, BT.CPP 4, Nav2, MoveIt) |
| 3. A-E extension | assessment, evidence, preparation and recovery plug in without changing the core |
| 4. Planning / policy backends | LLM, BTGenBot-2, PlanSys2, VLA integrated in their proper roles |
| 5. Portability | a second, different embodiment and a second simulator; a non-manipulation use case |
| 6. Framework release | conformance suite, deployment profiles, docs, diagnostics, Studio |

Reference runtime target: ROS 2 (Humble today; do not hard-code it) + BehaviorTree.CPP 4.6+.
The host currently ships only BehaviorTree.CPP v3 from apt, so Phase 2 begins with a source build.

## Contributing

- Checks that must stay green:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q`.
  Coverage: `uv run pytest --cov=robot_framework --cov-report=term-missing` (Phase 1: 98 %).
- House style: `ruff` (double quotes, line length 100), `mypy --strict`, pytest with AAA tests;
  shared test builders live in `tests/builders.py`.
- Contracts are immutable; derive new values with `model_copy(update=...)`.
- JSON Schemas are generated, never edited: re-run `schemas export` after changing a contract.
- Unsupported operations raise `UnsupportedOperationError` (`unsupported`); they never pretend to
  succeed. Expected outcomes (`FAILED`, `OUTCOME_UNKNOWN`, `INFEASIBLE`) are values, not exceptions.
- `src/` must never import `rclpy` or other ROS packages; ROS lives in `transports/` from Phase 2.

## License

[MIT](LICENSE) © 2026 Anhar Risnumawan.

# robot_framework — Architecture Note

> **Normative reference.** This is the English rendering of the architecture note behind
> `robot_framework`. It was consolidated from the Phase 1 implementation plan and the README; the
> original discussion (in Indonesian) is not stored in the repository. Where a section describes
> something that is not implemented in Phase 1, it is marked **(Phase N)**. Configuration examples
> are **illustrative** unless they are files under `deployment_profiles/`.

## 1. Purpose and scope

`robot_framework` standardizes the *meaning* of a goal, a skill, a world fact, a command and a
result, and keeps the algorithms open. Planners, executives, skill providers, policies, robots,
simulators and research extensions are swappable packages that must pass a compatibility check
before they run together.

Non-goals of the core: computing reachability, grasps, trajectories or locomotion; owning a
particular behavior-tree engine; owning a particular AI method.

## 2. What was wrong with the earlier draft

| Earlier draft | Problem | Resolution |
|---|---|---|
| Affordance–effectivity (A-E) inside the core | Every deployment paid for a research method; baseline comparisons were impossible | A-E becomes an optional extension (`extensions/anhar_ae`, Phase 3) behind the `GroundingPlugin` hook |
| BehaviorTree.CPP inside the core | The core could only express what one engine expresses | The core owns a portable `TaskGraph`; BT.CPP is one executive (Phase 2) |
| All planners treated as identical | LLMs, BTGenBot-2, PlanSys2 and VLAs produce different artifacts with different guarantees | `PlanProposal` carries an artifact *kind*; each kind needs a compatible executive and validator |
| Flat step-list task IR | No conditionals, bounded loops, event waits, concurrency or recovery | `TaskGraph` with typed nodes (see `specification/semantics/task_graph.md`) |
| "Provider said SUCCESS" = task success | A gripper can close on nothing | Success requires a **verified physical effect** |
| Fixed base+arm+gripper robot model | Excludes dual-arm, legged, aerial, tool changers | `RobotManifest` is a component **graph** with capability bindings |

## 3. Layered architecture

### 3.1 Layers

```text
USER / APPLICATION / OPERATOR
  -> GOAL & TASK CONTRACT                     GoalSpec, TaskDefinition
  -> PLANNING / DECISION ROUTER               manual | LLM | BTGenBot-2 | PlanSys2
  -> PLAN PROPOSAL                            TaskGraph | Native BT | TemporalPlan | PolicyGoal
  -> VALIDATION, GROUNDING & COMPATIBILITY    PlanValidator
  -> MISSION SUPERVISOR                       one live mission, one executive
  -> EXECUTIVE BACKEND                        sequential (ref) | BehaviorTree.CPP | delegated
  -> SKILL RUNTIME                            validate -> resolve -> assess -> reserve -> recheck
                                              -> start -> monitor -> verify -> commit
  -> EXECUTION PROVIDERS                      Nav2 | MoveIt/MTC | Servo | Force | VLA/RL | mock
  -> COMMAND AUTHORITY & MODE ARBITRATION     leases + epochs
  -> ROBOT BACKEND                            ros2_control | vendor SDK | autopilot | mock
```

Shared services: world state and evidence, registries, resource manager and epochs, safety
supervision, lifecycle and health, logging/replay/evaluation. Extensions: A-E, custom grounding and
recovery, domain reasoning, Studio panels.

### 3.2 Core interfaces

All interfaces are `typing.Protocol` classes in `robot_framework.core.interfaces`:

| Protocol | Responsibility |
|---|---|
| `TaskPlanner` | `propose(goal, world, skills) -> PlanProposal` |
| `Executive` | declares `supported_kinds`; `start(plan, runtime, ctx) -> MissionHandle` |
| `SkillProvider` | implements one or more skills; `start(invocation, lease, backend) -> ExecutionHandle` |
| `PolicyProvider` | `infer(observations, policy_goal) -> ActionChunk` (Phase 4 consumers) |
| `RobotBackend` | `dispatch(CommandEnvelope) -> CommandAcknowledgement`; declares capabilities |
| `SimulationBackend` | a `RobotBackend` that may also `reset()` (bumps the execution epoch) |
| `GroundingPlugin` | `assess(invocation, provider, world) -> AssessmentReport` (extension hook) |
| `Verifier` | checks expected effects against fresh evidence |
| `WorldInterface` | revisioned facts: `snapshot`, `commit`, `observe`, `invalidate_all` |
| `ExecutionHandle` / `MissionHandle` | progress, cancel (a request), result with timeout |

## 4. Contract catalogue

Every contract is an immutable, strictly validated pydantic model with `schema_version`
(`v1alpha1`). Unknown fields are rejected. Physical quantities carry explicit units. JSON Schemas
are generated (`robot-framework schemas export`), never hand-written.

| Contract | Minimum content |
|---|---|
| `GoalSpec` | objective, parameters, success criteria, constraints, deadline, human-interaction policy |
| `TaskDefinition` / `TaskGraph` | typed nodes, bounded loops, event waits, recovery references, required capabilities |
| `PlanProposal` | artifact kind + exactly one matching payload, assumptions, world snapshot id, executive requirements |
| `SkillContract` | typed ports, pre/hold conditions, expected effects, verification, cancellation, failure semantics, capabilities, resources |
| `ProviderManifest` | implemented skills, kind, hardware needs, domains, version, model reference, cancellation |
| `RobotManifest` | component graph, resources, capability bindings, calibration/safety/description references |
| `Fact` / `WorldSnapshot` / `Evidence` | predicate, args, value, source, observation time, validity, confidence, revision |
| `AssessmentReport` | status, reason, context, evidence, applicable constraints, recommended next step |
| `SkillInvocation` / `SkillResult` | identity, bound params, lease, epoch, lifecycle state, provider status, observed effects, verification, diagnosis |
| `ResourceLease` / `CommandEnvelope` / `CommandAcknowledgement` | owner, resources, control mode, epoch, expiry; every command carries lease + epoch |
| `MissionEvent` / `MissionResult` | replayable decision record; final status and verified effects |
| `DeploymentProfile` | task pack, robot pack, mode, backend, planner, executive, extensions, verification, safety, recording |

## 5. Planning, validation and compatibility

A plan proposal is untrusted input regardless of its origin. Before execution the `PlanValidator`
checks, and reports every failure as a structured reason `{code, node_id, detail}`:

1. the artifact kind is supported by the selected executive (`unsupported_artifact_kind`);
2. every skill exists in the registry (`unknown_skill`);
3. parameters satisfy the skill's typed ports (`invalid_parameter`);
4. required capabilities are *structurally* present on the robot (`missing_capability`);
5. required resources exist on the robot (`unknown_resource`);
6. at least one provider implements each skill (`no_provider`);
7. native artifacts (BT XML, temporal plans) have a registered validator (`native_validator_missing`);
8. loops are bounded and event waits have timeouts.

Preflight does **not** evaluate the preconditions of future steps against the current world: the
world will have changed by the time those steps run. Preconditions are checked by the skill runtime
immediately before each skill starts. Likewise, *current* availability (a controller is active, a
tool is mounted) is a runtime check, not a preflight check.

Unsupported artifacts are rejected; they are never silently downgraded (for example, a temporal plan
is never executed as a plain sequence).

## 6. World model, evidence and assessment

### 6.1 Facts and evidence

The world model stores **evidence**, not truth. A `Fact` carries its predicate and arguments, a
JSON-serializable value, its source, its observation time (observation clock), an optional validity
window, an optional confidence and the world revision at which it was committed. Facts are immutable;
a new observation replaces the old fact and bumps the revision. A fact older than its validity
window is *stale*. Invalidating the world (for example after a simulation reset) marks facts stale;
it does not delete them.

The world is not a behavior-tree blackboard: execution-local variables never live in it.

Two clocks are distinguished: the observation clock (`now()`, comparable to sensor timestamps) and
the monotonic clock (`monotonic()`, for deadlines and lease expiry). They are never compared with
each other.

### 6.2 Assessment

Grounding plugins return an `AssessmentReport`:

```yaml
status: FEASIBLE | INFEASIBLE | UNKNOWN | NOT_APPLICABLE
reason: "object partially occluded"
context: { world_snapshot_id: ws_42, robot_state_revision: 17, provider_id: mock.pick }
evidence: { pose_known: fact@rev17 }
applicable_constraints: [max_payload]
recommended_next_step: { skill_id: perception.observe_target, reason: refresh pose }
```

`UNKNOWN` is not `INFEASIBLE`, and confidence is not permission to move. An unknown assessment with
a recommended next step is recorded and the runtime tries the next candidate provider; an unknown
assessment without one is allowed to proceed and recorded as `assessment_unknown`.

## 7. Skill runtime and lifecycle

Each skill invocation passes nine steps:

1. **validate** the request and bind parameters;
2. **resolve** candidate providers;
3. **assess** with grounding plugins and check preconditions against non-stale facts;
4. **reserve** the contract's resources atomically;
5. **recheck** time-sensitive conditions;
6. **start** the provider;
7. **monitor** for completion, cancellation, lease expiry and hold-condition violations;
8. **verify** the expected effects against fresh evidence;
9. **commit** verified effects to the world and release the lease.

The lifecycle state machine is specified in `specification/semantics/lifecycle.md`. Two rules are
central: **cancel is a request, stop is an observation** (`CANCELED` is entered only after the
provider confirms; otherwise `OUTCOME_UNKNOWN`), and **a provider's SUCCESS is not task success**
(only a `VERIFIED` result reaches `SUCCEEDED`). After `OUTCOME_UNKNOWN`, the executive must
reconcile (re-observe the expected effects) before any retry.

## 8. Resource ownership, command authority and epochs

- Resources (arms, bases, grippers, workspaces) are reserved **atomically** (all or nothing) under a
  bounded lease with a control mode and an expiry on the monotonic clock.
- Every command is a `CommandEnvelope` carrying a lease id and an execution epoch. The single
  `CommandAuthority` rejects commands with an unknown or expired lease, a stale epoch, resources
  outside the lease, or a control mode that differs from the lease.
- An epoch bump (simulation reset, emergency stop recovery, operator takeover) releases every lease
  and invalidates every command issued before it.
- Hardware-level claiming (for example ros2_control) still exists below this layer **(Phase 2)**;
  mission/skill-level leases are needed in addition.

## 9. Planner and policy integration

| Technology | Role | Artifact | Phase |
|---|---|---|---|
| Manual task packs | planner | `TaskGraph` | 1 |
| LLM | planner (proposal generator only) | `TaskGraph` | 4 |
| BTGenBot-2 | planner | native BT.CPP 4 XML (closed node vocabulary) + validator | 4 |
| PlanSys2 | planner + delegated executive | temporal plan | 4 |
| VLA / RL policies | `PolicyProvider` behind a skill | `PolicyGoal` / `ActionChunk` | 4 |
| BehaviorTree.CPP 4.6+ | executive | native BT XML / compiled TaskGraph | 2 |

Generated plans can only call registered skills. LLM output is a proposal and passes the same
validator as any other plan. A policy never bypasses the command authority: action chunks are
dispatched under a lease and epoch like any other command.

## 10. Robot packages

A robot package contains a manifest (component graph, resources, capability bindings), and references
to description, calibration, controllers and safety configuration, plus conformance tests. The
component graph is a DAG of components (bases, arms, grippers, sensors, tools) with joints as edges.
Capabilities are bound to components and may be *structural* (the hardware exists) or dynamic (the
controller is currently active — checked at runtime).

## 11. Simulation and real

Simulation and real backends share contracts, not assumptions. Backends declare their capabilities
(`dispatch`, `reset`, `step`, `pause`, ground truth). A real backend returns `UNSUPPORTED` for
`reset`; it never fakes it. A simulation reset bumps the execution epoch and invalidates the world.
Deployment modes: `mock`, `simulation`, `hil`, `real`, `replay`.

## 12. Deployment profiles and packaging

A deployment profile selects every swappable part. Switching planner, executive, robot or mode is a
profile change **plus** a compatibility validation. Illustrative example:

```yaml
api_version: robot_framework/v1alpha1
task_pack: examples
robot_pack: mock_mobile_manipulator
deployment: { mode: mock, backend: mock_sim, profile: mock }
planning:  { plugin: manual, output_kind: task_graph }
execution: { plugin: sequential }
extensions: []            # research profile: [{ id: anhar_affordance_effectivity, required: true }]
verification: { profile: evidence_based }
safety: { profile: mock }
recording: { mission_events: true, decision_evidence: true }
```

A `required: true` extension that is missing or failing aborts the mission; there is no silent
fallback. `mode: real` requires a real safety profile.

Package layout: `robot_packages/<robot>/`, `task_packs/<pack>/` (`*.task.yaml`,
`skills/*.skill.yaml`), `deployment_profiles/*.yaml`.

## 13. Safety, security and recovery

- All commands pass a single command authority; there is no side channel to the backend.
- Generated plans can only reference registered skills; unknown skills are rejected before
  execution.
- Recovery is diagnosis-driven and budgeted: every retry policy has `max_attempts`, and retries after
  `OUTCOME_UNKNOWN` require reconciliation.
- Safety supervision (speed/force limits, e-stop) and security (SROS2, credentials, audit) are
  **(Phase 5/6)**; Phase 1 only enforces the command authority and the registered-skill rule.

## 14. Conformance

Every implementation must pass these behaviours (`tests/conformance/test_section14.py`):

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

Portability is measured separately at the goal, task, provider and policy levels
(`docs/compatibility.md`).

## 15. Roadmap

See `docs/roadmap.md`. Reference runtime target for later phases: ROS 2 (Humble today; not
hard-coded) and BehaviorTree.CPP 4.6+, which must be built from source on the current host.

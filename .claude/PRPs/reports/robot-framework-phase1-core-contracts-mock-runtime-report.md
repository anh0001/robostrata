# Implementation Report: robot_framework — Phase 1: Core Contracts + Mock Runtime

## Summary

Implemented the neutral core of `robot_framework` as a Python 3.10 package (`src/robot_framework`):
21 versioned, frozen, strictly validated pydantic contracts with generated JSON Schemas; a typed
plugin registry; a resource manager with atomic bounded leases, execution epochs and a single
command authority; an evidence-based in-memory world with validity windows; a plan validator that
collects structured rejection reasons; the 9-step skill runtime (validate → resolve → assess →
reserve → recheck → start → monitor → verify → commit) with honest cancellation, `OUTCOME_UNKNOWN`
and reconciliation; a mission supervisor; a sequential reference executive for the portable
TaskGraph; a manual planner; mock providers / robot backend / simulation backend with fault
injection; the extension hook with a null plugin and a `required`-honouring loader; YAML package
loaders; a CLI (`run`, `validate`, `schemas export`); one robot package, task pack, goal and two
deployment profiles; normative docs; and contract, unit, integration, conformance (§14) and
fault-injection suites.

The Phase 1 exit criterion holds: the example mission runs without an LLM and without A-E, and
cancellation, resource ownership, epochs and physical-outcome verification are covered by the
conformance suite.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large (as predicted; runtime cancel/verify semantics were the bulk) |
| Confidence | not stated | High — 257 tests, 98 % coverage, three consecutive green runs, green with and without ROS sourced; 12 review findings fixed |
| Files Changed | ~55 (≈40 source, ≈15 test/config/doc) | ~85 authored (46 source incl. `__init__`/`py.typed`, 16 test, 13 YAML/doc packs, 5 docs, config) + 21 generated schemas + `uv.lock` |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | Project skeleton and tooling | [done] Complete | `git init -b main`; added `pytest-cov`; pytest blocks ROS `launch_testing` plugins |
| 2 | Normative docs | [done] Complete | `docs/architecture.md` reconstructed (see Deviations) |
| 3 | Contract base + enums | [done] Complete | `ValueModel` base for nested parts |
| 4 | Core contracts (goal, task, plan, skill, provider, robot) | [done] Complete | `$port` reference syntax; `recovery_ref` as node field |
| 5 | Runtime contracts + schema export | [done] Complete | 21 contracts exported (plan: ≥ 15) |
| 6 | Errors, clock, registry, interfaces | [done] Complete | `MissionAlreadyRunningError` added; `ExecutionHandle.wait()` returns `ProviderOutcome` |
| 7 | ResourceManager and CommandAuthority | [done] Complete | `threading.RLock`; retired-lease memory explains rejections |
| 8 | InMemoryWorld | [done] Complete | observation sources produce fresh values |
| 9 | PlanValidator | [done] Complete | extra checks: node kind, executive pin, bindings, verifier |
| 10 | SkillRuntime | [done] Complete | lease TTL + renewal from profile; internal stop → FAILED |
| 11 | MissionRecorder | [done] Complete | `sequence` field; JSONL sink |
| 12 | FrameworkContext, ExtensionLoader, package loader | [done] Complete | loader in `extensions/loader.py`; pack-path escape check |
| 13 | ManualPlanner and SequentialExecutive | [done] Complete | always reconciles `OUTCOME_UNKNOWN`; retries only after definitive FAILED |
| 14 | MissionSupervisor and CLI | [done] Complete | goal deadline, success criteria on fresh evidence, constraint/confirmation honesty |
| 15 | Mock providers, verifier, backends | [done] Complete | effects travel as commands into closed-world ground truth |
| 16 | Example robot package, task pack, profile | [done] Complete | order `go_to → observe → pick → go_to → place`; default goal file |
| 17 | Conformance suite and remaining tests | [done] Complete | 10 conformance tests (sim reset split in two) |
| 18 | README finalisation and roadmap hand-off | [done] Complete | Phase 1 marked complete in `docs/roadmap.md` |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | [done] Pass | `ruff check .` clean, `ruff format --check .` clean, `mypy --strict src` clean (46 files) |
| Unit Tests | [done] Pass | 257 passed (178 test functions, parametrised) |
| Build | [done] Pass | `uv sync --extra dev` builds the hatchling wheel; console script `robot-framework` works |
| Integration | [done] Pass | full mission via profile; JSONL record; system clock; `mock_robot` backend |
| Edge Cases | [done] Pass | empty graph, bounded loops/waits, invalid types, concurrency, lost acks, authority rejection |
| Coverage | [done] Pass | 98 % line+branch (plan: ≥ 80 %) |
| Schemas | [done] Pass | `schemas export specification/schemas` writes 21 files, export is byte-identical across runs |
| No-ROS run | [done] Pass | `env -i HOME=$HOME PATH=$PATH uv run pytest -q` → 257 passed; no ROS imports under `src/` |
| README commands | [done] Pass | every quick-start command run as written |

## Files Changed

All files are new (the repository was empty apart from `README.md` and the plan).

| Area | Action | Files / Lines |
|---|---|---|
| `pyproject.toml`, `.gitignore`, `.python-version`, `uv.lock` | CREATED | 4 files |
| `src/robot_framework/spec/` | CREATED | 15 files, 1226 lines |
| `src/robot_framework/core/` | CREATED | 12 files, 1993 lines |
| `src/robot_framework/{planning,executives,providers,verifiers,robot_backends,simulation_backends,extensions,packages}/`, `cli.py` | CREATED | 18 files, 1125 lines |
| `tests/` | CREATED | 16 files, 2948 lines |
| `docs/` | CREATED | 3 files, 314 lines |
| `specification/semantics/` | CREATED | 2 files, 86 lines |
| `specification/schemas/` | GENERATED | 21 `*.schema.json` |
| `robot_packages/`, `task_packs/`, `deployment_profiles/` | CREATED | 10 files, 176 lines |
| `README.md` | UPDATED | status, layout, quick start, exit codes, contributing |

## Deviations from Plan

1. **`docs/architecture.md` is a reconstruction.** WHAT: written from the plan and README. WHY: the
   original architecture note existed only in an earlier chat and is not in the repository; the
   document says so at the top.
2. **Nested value objects use `ValueModel`** (frozen, `extra="forbid"`, no `schema_version`); only
   top-level contracts extend `ContractModel`. WHY: keeps authored YAML free of repeated versions.
3. **`ExecutionHandle.wait()` returns a new `ProviderOutcome` contract**, not a `SkillResult`.
   WHY: a provider *claim* and the runtime's verified *result* must be different types.
4. **Structured `RejectionReason(code, node_id, detail)`** in `MissionResult.rejection_reasons`
   instead of strings, plus `MissionResult.failure_reason`. WHY: tests and callers need stable codes.
5. **Added contract fields** the plan left implicit: `PlanProposal.planner_id`,
   `CommandEnvelope.issuer_id`, `ProviderManifest.control_mode`, `SkillInvocation.node_id`,
   `SkillResult.{node_id, skill_id, provider_id, reconciled}`, `MissionEvent.sequence`,
   `DeploymentProfile.default_goal`, `ExecutionCfg.{lease_ttl_s, monitor_poll_s,
   provider_preference}`, `FailureSemantics.{timeout_s, retryable}`, `VerificationStatus.NOT_RUN`,
   extra `FailureCategory` values (`precondition_unmet`, `infeasible`, `hold_violated`,
   `command_rejected`, `resource_conflict`, `stale_epoch`, `lease_lost`). WHY: each is exercised by a
   test and needed to keep durations/TTLs out of code and diagnoses machine-readable.
6. **Recovery is a node field** (`recovery_ref` on every node) with a `retry | abort` discriminated
   `RecoveryPolicy`, not a separate `recovery_ref` node kind; conditionals use `then`/`otherwise`.
7. **Skill conditions reference ports as `$port`**; the wildcard precondition `holding(robot, *)` was
   dropped (no wildcard semantics in Phase 1) and `place` instead requires
   `holding(robot, $object)` and `at(robot, $location)`.
8. **Example task order is `go_to → observe → pick → go_to → place`** (plan: observe first). WHY: the
   pick precondition only accepts a pose younger than 5 s, so observation belongs right before the
   pick.
9. **Mock effects flow through the command authority.** Providers put `set_facts` in their final
   `CommandEnvelope`; the mock backend applies them to a closed-world `MockGroundTruth` only if the
   authority accepts the command, and the world's observation sources read that ground truth.
   Providers never write the world model. WHY: the plan's "re-stamp the stored fact" observation
   would make verification circular, and `lie_success` could not produce `FAILED`.
10. **Lease TTL comes from `execution.lease_ttl_s` with renewal at half-life**, instead of
    `max_stop_time_s + budget`; the skill timeout is `failure_semantics.timeout_s`.
11. **Internal stops are `FAILED`, not `CANCELED`.** A confirmed stop caused by timeout, hold
    violation or lost lease ends `FAILED` with that diagnosis; `CANCELED` is reserved for requested
    cancellation. A provider that completes with `SUCCESS` while a stop is pending goes to
    `VERIFYING`. `specification/semantics/lifecycle.md` documents both transitions.
12. **`reconcile(previous: SkillResult) -> SkillResult`** (plan: returns a `WorldSnapshot`). WHY:
    the executive needs the reconciled verdict and the verified effects, not just a snapshot.
    Retries after `OUTCOME_UNKNOWN` happen only when reconciliation proves the effect absent.
13. **`threading.RLock` instead of `asyncio.Lock`** in `ResourceManager`. WHY: `reserve` is
    synchronous by design, and the stated goal (future threaded transports) needs a thread lock.
14. **`ExtensionLoader` lives in `extensions/loader.py`**, not `extensions/null.py`.
15. **Supervisor honesty checks:** goals with hard constraints or `require_plan_confirmation` are
    `REJECTED` (nothing in Phase 1 can enforce them); success criteria are re-observed after the
    executive finishes; `deadline_s` cancels the mission and fails it with `deadline_exceeded`; the
    planner's artifact kind must match `planning.output_kind`.
16. **Validator extras:** `unsupported_node_kind` (executives declare `supported_node_kinds`, so
    `parallel` is rejected before execution, with the runtime `UNSUPPORTED` kept as a backstop),
    `executive_mismatch`, `invalid_binding`, `unknown_verifier`; providers are eligible only if their
    hardware is structurally present and they stop at least as fast as the skill contract demands.
17. **Test tooling:** `pytest-cov` added to dev deps; `tests/` on the pytest path for
    `tests/builders.py`; `addopts = "-p no:launch_testing -p no:launch_ros"` because a sourced ROS
    Humble environment otherwise auto-loads a pytest plugin that crashes; `MockProviderBase.schedule()`
    injects per-start faults. Extra test modules: `test_sequential_executive.py`,
    `test_mission_supervisor.py`, `test_cli.py`, `test_packages_loader.py`, `test_manual_planner.py`.
18. **`Uncertainty`/`Validity` are not separate models**; `Fact` carries `validity_s` and
    `confidence` directly.
19. **Git:** the repository was initialised on `main`; no feature branch was created because there
    is no commit to branch from, and nothing has been committed.

## Issues Encountered

- **ROS pytest plugins.** With `/opt/ros/humble` on `PYTHONPATH`, pytest auto-loaded
  `launch_testing`, which failed on a missing `lark` module. Fixed by blocking the two ROS plugins in
  `addopts`; the suite passes both with and without ROS sourced.
- **Edit gate.** The local GateGuard hook requires a fact statement before the first write to every
  new file; this added round-trips but no code changes.
- Code review findings and their resolution: see "Code Review" below.

## Code Review

An independent review (python-reviewer agent, read-only) reported 12 findings, each reproduced with
a script. All were fixed, each with a regression test:

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | HIGH | Mission epoch checked before awaiting assessment, so a reset during `assess` still got a lease in the new epoch | `ResourceManager.reserve(epoch=...)` refuses a stale epoch under the reservation lock |
| 2 | HIGH | After an unconfirmed stop, reconciliation could find the effect absent and allow a retry while the first provider was still acting | runtime tracks unconfirmed providers; `reconcile` is blocked (`reconcile_blocked`) until they settle |
| 3 | HIGH | A deadline or error forced mission `FAILED`, masking `OUTCOME_UNKNOWN` | `mission_status()`: any unresolved `OUTCOME_UNKNOWN` dominates; the failure reason is kept |
| 4 | HIGH | A blocking `handle.cancel()` escaped the `max_stop_time_s` bound | cancel request runs in the background; only the confirmation wait is awaited (bounded) |
| 5 | HIGH | Cancelling `run()` / the invoking task orphaned the executive and never stopped the provider | supervisor shields `handle.cancel()` on `CancelledError`; runtime winds down with a bounded stop |
| 6 | HIGH | Non-framework exceptions escaped (no `MissionResult`, lost results, CLI exit 1) | provider-start crash → `OUTCOME_UNKNOWN`; executive crash → `OUTCOME_UNKNOWN` + `internal_error`; planner crash → `REJECTED planner_error`; CLI exit code 3 |
| 7 | MEDIUM | Verifier (and success criteria) accepted facts older than the invocation/mission | evidence must be observed at/after invocation creation (criteria: mission start) |
| 8 | MEDIUM | A reset during `VERIFYING` still committed effects | verification in another epoch, or across an epoch change, is `UNKNOWN`; nothing committed |
| 9 | MEDIUM | Cancel during planning was dropped; cancel during assessment still started the provider | supervisor remembers a pending cancel; runtime checks the cancel before `provider.start` |
| 10 | MEDIUM | `wait_event` / `conditional` / loop `until` never observed the world | the executive observes each predicate (where observable) before evaluating it |
| 11 | LOW | Lease leak if recording failed after reserve; leases not renewed while stopping | lease bookkeeping moved inside `try/finally`; lease renewed for `ttl + max_stop` on stop |
| 12 | LOW | Authority ignored issuer; infinite TTL accepted; runtime didn't type-check params | `issuer_not_lease_owner`; finite-duration checks (`allow_inf_nan=False`, `math.isfinite`); runtime uses `param_problem` |

Kept as designed: envelopes with empty `target_resources` are accepted (sensor-only skills such as
`perception.observe_target` lease no actuator).

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `tests/contract/test_schema_roundtrip.py` | 25 (86 with parametrisation) | every contract: round-trip, unknown-field rejection, schema validation; graph/plan/skill/profile validators |
| `tests/contract/test_robot_manifest.py` | 9 | component graph: cycles, self-loops, duplicates, dangling edges, bindings |
| `tests/unit/test_resource_manager.py` | 13 | atomic reserve, expiry, epochs, release, renew, authority reasons, bounded memory |
| `tests/unit/test_world_interface.py` | 10 | revisions, staleness, observation sources, invalidation, clocks |
| `tests/unit/test_validation.py` | 13 | every rejection code, port types, provider eligibility |
| `tests/unit/test_skill_runtime.py` | 29 | lifecycle, cancel confirm/timeout/blocking cancel/task cancellation, preconditions, assessments, extensions, hold, conflicts, epochs during assess and verify, lease safety |
| `tests/unit/test_sequential_executive.py` | 16 | conditional/wait observing the world, loop, parallel refusal, retry/abort, unconfirmed-stop no-retry, crash → OUTCOME_UNKNOWN, mission handle |
| `tests/unit/test_mission_supervisor.py` | 16 | single live mission, deadline (incl. OUTCOME_UNKNOWN dominance), cancel during planning/run/task cancellation, criteria freshness, planner/executive crashes, honest rejections |
| `tests/unit/test_manual_planner.py` | 3 | `$goal` binding in every node kind, unresolved parameters |
| `tests/unit/test_cli.py` | 7 | `validate`, `run`, `schemas export`, exit codes, misconfigured profiles |
| `tests/unit/test_packages_loader.py` | 14 | loaders, path escape, registry, extension loader, backends, errors |
| `tests/integration/test_bottle_delivery_mock.py` | 4 | full mission, command scope, JSONL replay record, system clock |
| `tests/conformance/test_section14.py` | 10 | the nine §14 behaviours |
| `tests/fault_injection/test_provider_faults.py` | 9 | timeout, rejected commands, lease renewal, cancel during verify, lost acks, stale evidence vs. lying provider |

## Next Steps

- [ ] Code review via `/code-review`
- [ ] Commit (`/prp-commit`) and create a PR via `/prp-pr`
- [ ] Phase 2 plan (`/prp-plan`): BT.CPP 4.6+ source build, ROS 2 transport, Nav2/MoveIt providers,
      Gazebo backend, conformance suite parametrised over mock + sim

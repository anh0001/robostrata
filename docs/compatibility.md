# Compatibility and portability

## Portability levels

Portability is measured separately at each level; a claim at one level says nothing about another.

| Level | Portable when | Measured by |
|---|---|---|
| Goal | the same `GoalSpec` is accepted (or explicitly rejected with `missing_capability`) on a different robot | plan validation outcome per robot package |
| Task | the same `TaskDefinition` runs on a different robot or executive without edits | conformance + integration suites per deployment profile |
| Provider | the same `SkillContract` is served by a different provider with the same verified effects | verification status per provider |
| Policy | the same policy checkpoint runs on a different embodiment through a `PolicyProvider` | policy-level success with verified effects (Phase 4+) |

## Compatibility matrix: planner × executive × artifact kind

A cell is `✔` when the combination is implemented and covered by tests, `✗` when the validator must
reject it, and `—` when it is not yet built. Rejection is a feature: an unsupported combination is
refused before execution, never silently downgraded.

| Planner \ Executive | `sequential` (P1) | BehaviorTree.CPP (P2) | delegated PlanSys2 (P4) |
|---|---|---|---|
| `manual` → `task_graph` | ✔ | — | ✗ |
| LLM → `task_graph` (P4) | — | — | ✗ |
| BTGenBot-2 → `native_bt_xml` (P4) | ✗ (`unsupported_artifact_kind`) | — | ✗ |
| PlanSys2 → `temporal_plan` (P4) | ✗ (`unsupported_artifact_kind`) | ✗ | — |
| any → `policy_goal` (P4) | ✗ (`unsupported_artifact_kind`) | — | ✗ |

## Robot × task pack matrix

| Robot package | `examples` task pack |
|---|---|
| `mock_mobile_manipulator` | ✔ (mock mode) |

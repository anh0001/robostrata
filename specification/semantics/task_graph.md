# TaskGraph node semantics

A `TaskGraph` has one `root` node and a table of named `recoveries`. Every node has a unique
`node_id` and a `kind` discriminator. Nodes evaluate to a lifecycle outcome (`SUCCEEDED`, `FAILED`,
`CANCELED`, `OUTCOME_UNKNOWN`).

| Kind | Fields | Semantics |
|---|---|---|
| `skill` | `skill_id`, `params`, `bindings`, `recovery_ref?` | Invoke one skill through the skill runtime. String params of the form `$goal.<key>` are substituted from the goal by the planner. |
| `sequence` | `children` (≥ 1), `recovery_ref?` | Run children in order; stop at the first child that does not succeed and return its outcome. |
| `conditional` | `condition` (fact predicate), `then`, `else?` | Evaluate the predicate against the current world snapshot; run `then` if it holds, else `else` (or succeed if absent). |
| `loop` | `child`, `max_iterations` (≥ 1, **required**), `until?` | Repeat `child` until `until` holds or `max_iterations` is reached; stop on child failure. Reaching the cap without `until` holding is `FAILED` when `until` is set. |
| `wait_event` | `condition`, `timeout_s` (> 0, **required**), `poll_interval_s` | Poll the world until the predicate holds (`SUCCEEDED`) or the timeout elapses (`FAILED`). |
| `parallel` | `children` (≥ 2), `completion: all\|any`, `on_branch_failure: cancel_others\|continue` | Reserved. The Phase 1 sequential executive rejects it with `UNSUPPORTED`; resource-aware parallel scheduling arrives with a later executive. |

## Predicates

A predicate is `{predicate, args, expected}`. It holds when the world contains a non-stale fact with
that predicate and arguments whose value equals `expected`. A missing or stale fact does not hold.

## Recovery policies

`recovery_ref` names an entry in `TaskGraph.recoveries`; the name must exist.

| Policy | Fields | Semantics |
|---|---|---|
| `retry` | `max_attempts` (≥ 1), `requires_reconcile` | Re-run the failed node up to `max_attempts` total attempts. When the outcome was `OUTCOME_UNKNOWN`, the executive must reconcile first; `requires_reconcile: true` additionally forces reconciliation before every retry. |
| `abort` | — | Stop and propagate the failure. |

No loop or retry is unbounded.

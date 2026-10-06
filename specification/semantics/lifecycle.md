# Skill lifecycle semantics

## States

| State | Meaning | Terminal |
|---|---|---|
| `CREATED` | invocation object exists | no |
| `VALIDATED` | contract resolved, parameters bound and type-checked | no |
| `RESERVED` | resources held under a lease for the current epoch | no |
| `RUNNING` | provider started; commands may be dispatched | no |
| `VERIFYING` | provider finished; expected effects are being checked against fresh evidence | no |
| `CANCELING` | cancel requested; waiting for the provider to confirm it stopped | no |
| `SUCCEEDED` | expected effects verified | yes |
| `FAILED` | provider failed, a precondition was stale/false, a resource was unavailable, or verification failed | yes |
| `CANCELED` | the provider **confirmed** it stopped | yes |
| `OUTCOME_UNKNOWN` | the physical outcome cannot be known (acknowledgement lost, stop not confirmed, verification inconclusive) | yes |

## Transitions

```text
CREATED -> VALIDATED -> RESERVED -> RUNNING -> VERIFYING -> SUCCEEDED
VALIDATED                       -> FAILED            (stale epoch, no eligible/feasible provider,
                                                      stale/false precondition, resource conflict)
RESERVED                        -> FAILED            (time-sensitive precondition went stale)
RESERVED                        -> CANCELED          (cancel pending before start; nothing commanded)
RESERVED                        -> OUTCOME_UNKNOWN   (provider start crashed; commands may have gone out)
RUNNING | VERIFYING             -> FAILED            (provider failure, verification failed)
RUNNING                         -> OUTCOME_UNKNOWN   (acknowledgement lost / provider status UNKNOWN)
VERIFYING                       -> OUTCOME_UNKNOWN   (verification inconclusive, or the execution
                                                      epoch changed before/during verification)
RUNNING                         -> CANCELING         (cancel request, timeout, hold violation, lease lost)
CANCELING                       -> CANCELED          (external cancel; provider confirmed stop)
CANCELING                       -> FAILED            (internal stop reason; provider confirmed stop)
CANCELING                       -> VERIFYING         (provider completed before the stop took effect)
CANCELING                       -> OUTCOME_UNKNOWN   (no confirmation within max_stop_time_s)
```

A cancel requested before `RUNNING` ends the invocation `CANCELED` without starting the provider.
The stop wait is bounded by `max_stop_time_s` even if the provider's `cancel()` call itself blocks;
the cancel request runs in the background. Cancelling the task that invokes a skill is treated as
an external cancel: the runtime still requests the stop and waits (bounded) before giving up.

## Rules

1. **Cancel is a request, stop is an observation.** A cancel request moves the invocation to
   `CANCELING` only. `CANCELED` is entered only after the provider confirms it stopped. If no
   confirmation arrives within the contract's `cancellation.max_stop_time_s`, the state is
   `OUTCOME_UNKNOWN`; the runtime never assumes the robot stopped. `CANCELED` is reserved for
   *requested* cancellation: a confirmed stop caused by the runtime itself (timeout, hold-condition
   violation, lost lease) is `FAILED` with that diagnosis.
2. **Provider success is not task success.** A provider status of `SUCCESS` moves the invocation to
   `VERIFYING`. Only a `VERIFIED` result reaches `SUCCEEDED`; a failed verification is `FAILED`
   (diagnosis `verification_failed`) even when the provider said `SUCCESS`.
3. **Only verified effects are committed** to the world, with the verifier as the source.
   Verification evidence must be fresh, observed no earlier than the invocation was created, and
   from the invocation's execution epoch; otherwise the outcome is `OUTCOME_UNKNOWN`.
4. **Resources are released on every terminal state.**
5. **Cancel during `VERIFYING` is ignored**: no commands are in flight, so verification completes and
   determines the outcome.
6. **After `OUTCOME_UNKNOWN`, reconcile before any retry.** The executive re-observes the expected
   effects; if they already hold the step counts as succeeded (`reconciled_success`) and is **not**
   re-executed; if they are definitively absent (`reconciled_absent`) a retry is allowed. While a
   provider that never confirmed its stop may still be acting, reconciliation concludes nothing
   (`reconcile_blocked`) and the step stays `OUTCOME_UNKNOWN`. Reconciliation is recorded as its own
   events; the invocation's terminal state is never rewritten.
7. **A mission with any unresolved `OUTCOME_UNKNOWN` step is `OUTCOME_UNKNOWN`**, even when it also
   missed its deadline or hit an error; the failure reason is kept alongside.
8. Every transition is recorded as a `skill_state` mission event.

"""Sequential reference executive for the portable TaskGraph.

Runs sequence, conditional, bounded loop and wait_event nodes. Parallel nodes are reserved for a
resource-aware executive and are refused with ``UNSUPPORTED``. After ``OUTCOME_UNKNOWN`` the
executive always reconciles before counting a retry, and never re-executes an effect that holds.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import TYPE_CHECKING

from robot_framework.core.errors import FrameworkError, UnsupportedOperationError
from robot_framework.core.interfaces import ExecutiveOutcome
from robot_framework.spec import (
    ConditionalNode,
    FactPredicate,
    LifecycleState,
    LoopNode,
    PlanArtifactKind,
    PlanProposal,
    ProgressReport,
    RecoveryPolicy,
    RetryPolicy,
    SequenceNode,
    SkillNode,
    SkillResult,
    TaskGraph,
    TaskNode,
    WaitEventNode,
    iter_nodes,
)

if TYPE_CHECKING:
    from robot_framework.core.context import FrameworkContext
    from robot_framework.core.skill_runtime import SkillRuntime

log = logging.getLogger(__name__)

_State = LifecycleState


class _GraphRun:
    def __init__(
        self,
        graph: TaskGraph,
        runtime: SkillRuntime,
        ctx: FrameworkContext,
        cancel: asyncio.Event,
    ) -> None:
        self._graph = graph
        self._runtime = runtime
        self._ctx = ctx
        self._cancel = cancel
        self._epoch = ctx.resources.current_epoch
        self._results: tuple[SkillResult, ...] = ()
        self._skill_total = sum(1 for n in iter_nodes(graph.root) if isinstance(n, SkillNode))

    @property
    def results(self) -> tuple[SkillResult, ...]:
        return self._results

    @property
    def skill_total(self) -> int:
        return self._skill_total

    async def execute(self) -> ExecutiveOutcome:
        try:
            state = await self._run_node(self._graph.root)
        except FrameworkError as exc:
            return ExecutiveOutcome(_State.FAILED, self._results, f"{exc.code}: {exc.message}")
        except Exception as exc:
            # A crash mid-graph may have interrupted a skill whose effect is unknown.
            log.exception("sequential executive crashed")
            error = f"internal_error: {type(exc).__name__}: {exc}"
            return ExecutiveOutcome(_State.OUTCOME_UNKNOWN, self._results, error)
        return ExecutiveOutcome(state, self._results)

    async def _run_node(self, node: TaskNode) -> LifecycleState:
        policy = self._recovery(node)
        attempts = policy.max_attempts if isinstance(policy, RetryPolicy) else 1
        state = _State.FAILED
        for attempt in range(1, attempts + 1):
            if self._cancel.is_set():
                return _State.CANCELED
            if attempt > 1:
                self._ctx.recorder.record(
                    "recovery_retry", {"node_id": node.node_id, "attempt": attempt}
                )
            state = await self._settle(node, await self._dispatch(node), policy)
            if not self._may_retry(node, state):
                return state
        return state

    def _recovery(self, node: TaskNode) -> RecoveryPolicy | None:
        return self._graph.recoveries.get(node.recovery_ref) if node.recovery_ref else None

    async def _settle(
        self, node: TaskNode, state: LifecycleState, policy: RecoveryPolicy | None
    ) -> LifecycleState:
        """Reconcile skill outcomes that are unknown (always) or failed (when policy demands)."""
        must_reconcile = state is _State.OUTCOME_UNKNOWN or (
            state is _State.FAILED and isinstance(policy, RetryPolicy) and policy.requires_reconcile
        )
        if not isinstance(node, SkillNode) or not must_reconcile or not self._results:
            return state
        previous = self._results[-1]
        if previous.node_id != node.node_id:
            return state
        reconciled = await self._runtime.reconcile(previous)
        self._results = (*self._results[:-1], reconciled)
        return reconciled.state

    def _may_retry(self, node: TaskNode, state: LifecycleState) -> bool:
        if state is not _State.FAILED or self._cancel.is_set():
            return False
        if isinstance(node, SkillNode):
            return self._ctx.skills.get(node.skill_id).failure_semantics.retryable
        return True

    async def _dispatch(self, node: TaskNode) -> LifecycleState:
        if isinstance(node, SkillNode):
            result = await self._runtime.invoke(node, self._epoch, self._cancel)
            self._results = (*self._results, result)
            return result.state
        if isinstance(node, SequenceNode):
            return await self._run_sequence(node)
        if isinstance(node, ConditionalNode):
            branch = node.then if await self._holds(node.condition) else node.otherwise
            return _State.SUCCEEDED if branch is None else await self._run_node(branch)
        if isinstance(node, LoopNode):
            return await self._run_loop(node)
        if isinstance(node, WaitEventNode):
            return await self._run_wait(node)
        raise UnsupportedOperationError(
            f"the sequential executive does not run '{node.kind}' nodes",
            details={"node_id": node.node_id, "kind": node.kind},
        )

    async def _run_sequence(self, node: SequenceNode) -> LifecycleState:
        for child in node.children:
            state = await self._run_node(child)
            if state is not _State.SUCCEEDED:
                return state
        return _State.SUCCEEDED

    async def _run_loop(self, node: LoopNode) -> LifecycleState:
        for _ in range(node.max_iterations):
            state = await self._run_node(node.child)
            if state is not _State.SUCCEEDED:
                return state
            if node.until is not None and await self._holds(node.until):
                return _State.SUCCEEDED
        return _State.SUCCEEDED if node.until is None else _State.FAILED

    async def _run_wait(self, node: WaitEventNode) -> LifecycleState:
        polls = max(1, math.ceil(node.timeout_s / node.poll_interval_s))
        for _ in range(polls):
            if await self._holds(node.condition):
                return _State.SUCCEEDED
            if self._cancel.is_set():
                return _State.CANCELED
            await asyncio.sleep(node.poll_interval_s)
        return _State.SUCCEEDED if await self._holds(node.condition) else _State.FAILED

    async def _holds(self, test: FactPredicate) -> bool:
        """Observe the predicate where possible, then require a fresh matching fact."""
        await self._ctx.world.observe(test.predicate, test.args)
        snapshot = self._ctx.world.snapshot()
        return snapshot.holds(test, snapshot.time)


class GraphMissionHandle:
    def __init__(
        self,
        mission_id: str,
        task: asyncio.Task[ExecutiveOutcome],
        cancel: asyncio.Event,
        run: _GraphRun,
        clock_now: float,
    ) -> None:
        self.mission_id = mission_id
        self._task = task
        self._cancel = cancel
        self._run = run
        self._started_at = clock_now

    async def wait(self, timeout_s: float | None = None) -> ExecutiveOutcome:
        return await asyncio.wait_for(asyncio.shield(self._task), timeout_s)

    async def cancel(self, reason: str) -> None:
        """Request cancellation and wait until the running skill has settled."""
        self._cancel.set()
        await asyncio.wait({self._task})

    def progress(self) -> ProgressReport:
        done = sum(1 for r in self._run.results if r.state is _State.SUCCEEDED)
        total = self._run.skill_total
        fraction = min(1.0, done / total) if total else None
        return ProgressReport(
            fraction=fraction, message=f"{done}/{total} skills succeeded", time=self._started_at
        )


class SequentialExecutive:
    executive_id = "sequential"
    supported_kinds = frozenset({PlanArtifactKind.TASK_GRAPH})
    supported_node_kinds = frozenset({"skill", "sequence", "conditional", "loop", "wait_event"})

    async def start(
        self, plan: PlanProposal, runtime: SkillRuntime, ctx: FrameworkContext
    ) -> GraphMissionHandle:
        if plan.kind not in self.supported_kinds or plan.task_graph is None:
            raise UnsupportedOperationError(
                f"the sequential executive does not accept '{plan.kind.value}' artifacts"
            )
        cancel = asyncio.Event()
        run = _GraphRun(plan.task_graph, runtime, ctx, cancel)
        task = asyncio.ensure_future(run.execute())
        return GraphMissionHandle(ctx.recorder.mission_id, task, cancel, run, ctx.clock.now())

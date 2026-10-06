"""Manual planner: picks a TaskDefinition from the task pack and binds goal parameters.

String values of the form ``$goal.<key>`` in node params and predicate args are replaced by
``goal.parameters[<key>]``. A missing key rejects the plan; nothing is silently left unbound.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from robot_framework.core.errors import PlanRejectedError
from robot_framework.spec import (
    ConditionalNode,
    FactPredicate,
    GoalSpec,
    LoopNode,
    ParallelNode,
    PlanArtifactKind,
    PlanProposal,
    RejectionReason,
    SequenceNode,
    SkillContract,
    SkillNode,
    TaskDefinition,
    TaskNode,
    WaitEventNode,
    WorldSnapshot,
)

GOAL_REF_PREFIX = "$goal."


class _UnresolvedGoalParameter(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _resolve(value: Any, params: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith(GOAL_REF_PREFIX):
        key = value[len(GOAL_REF_PREFIX) :]
        if key not in params:
            raise _UnresolvedGoalParameter(key)
        return params[key]
    if isinstance(value, dict):
        return {k: _resolve(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, params) for v in value]
    return value


def _resolve_predicate(test: FactPredicate, params: Mapping[str, Any]) -> FactPredicate:
    return test.model_copy(update={"args": tuple(str(_resolve(a, params)) for a in test.args)})


def _bind(node: TaskNode, params: Mapping[str, Any]) -> TaskNode:
    if isinstance(node, SkillNode):
        return node.model_copy(update={"params": _resolve(node.params, params)})
    if isinstance(node, (SequenceNode, ParallelNode)):
        return node.model_copy(update={"children": tuple(_bind(c, params) for c in node.children)})
    if isinstance(node, ConditionalNode):
        otherwise = _bind(node.otherwise, params) if node.otherwise is not None else None
        return node.model_copy(
            update={
                "condition": _resolve_predicate(node.condition, params),
                "then": _bind(node.then, params),
                "otherwise": otherwise,
            }
        )
    if isinstance(node, LoopNode):
        until = _resolve_predicate(node.until, params) if node.until is not None else None
        return node.model_copy(update={"child": _bind(node.child, params), "until": until})
    if isinstance(node, WaitEventNode):
        return node.model_copy(update={"condition": _resolve_predicate(node.condition, params)})
    raise TypeError(f"unhandled node type {type(node).__name__}")


def _rejected(code: str, detail: str) -> PlanRejectedError:
    reason = RejectionReason(code=code, detail=detail)
    return PlanRejectedError(detail, details={"reasons": [reason.model_dump()]})


class ManualPlanner:
    planner_id = "manual"

    def __init__(self, task_definitions: Mapping[str, TaskDefinition]) -> None:
        self._tasks = dict(task_definitions)

    async def propose(
        self, goal: GoalSpec, world: WorldSnapshot, skills: Mapping[str, SkillContract]
    ) -> PlanProposal:
        task = next((t for t in self._tasks.values() if t.objective == goal.objective), None)
        if task is None:
            raise _rejected(
                "unknown_objective",
                f"no task in the pack achieves objective '{goal.objective}'",
            )
        try:
            root = _bind(task.graph.root, goal.parameters)
        except _UnresolvedGoalParameter as exc:
            raise _rejected(
                "unresolved_goal_parameter",
                f"task '{task.task_id}' needs goal parameter '{exc.key}'",
            ) from exc
        return PlanProposal(
            proposal_id=f"plan_{uuid.uuid4().hex[:12]}",
            kind=PlanArtifactKind.TASK_GRAPH,
            planner_id=self.planner_id,
            task_graph=task.graph.model_copy(update={"root": root}),
            assumptions=("manual_task_pack", f"task:{task.task_id}"),
            world_snapshot_id=world.snapshot_id,
        )

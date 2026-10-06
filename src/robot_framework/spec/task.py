"""Portable TaskGraph: typed nodes, bounded loops, event waits and named recovery policies.

Node semantics are specified in ``specification/semantics/task_graph.md``.
"""

from collections.abc import Iterator
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from robot_framework.spec._base import ContractModel, Identifier, ValueModel
from robot_framework.spec.world import FactPredicate


class _NodeBase(ValueModel):
    node_id: Identifier
    recovery_ref: str | None = None


class SkillNode(_NodeBase):
    kind: Literal["skill"] = "skill"
    skill_id: Identifier
    params: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)


class SequenceNode(_NodeBase):
    kind: Literal["sequence"] = "sequence"
    children: tuple["TaskNode", ...] = Field(min_length=1)


class ConditionalNode(_NodeBase):
    kind: Literal["conditional"] = "conditional"
    condition: FactPredicate
    then: "TaskNode"
    otherwise: "TaskNode | None" = None


class LoopNode(_NodeBase):
    kind: Literal["loop"] = "loop"
    child: "TaskNode"
    max_iterations: int = Field(ge=1)
    until: FactPredicate | None = None


class WaitEventNode(_NodeBase):
    kind: Literal["wait_event"] = "wait_event"
    condition: FactPredicate
    timeout_s: float = Field(gt=0.0, allow_inf_nan=False)
    poll_interval_s: float = Field(default=0.05, gt=0.0, allow_inf_nan=False)


class ParallelNode(_NodeBase):
    kind: Literal["parallel"] = "parallel"
    children: tuple["TaskNode", ...] = Field(min_length=2)
    completion: Literal["all", "any"] = "all"
    on_branch_failure: Literal["cancel_others", "continue"] = "cancel_others"


TaskNode = Annotated[
    SkillNode | SequenceNode | ConditionalNode | LoopNode | WaitEventNode | ParallelNode,
    Field(discriminator="kind"),
]

for _model in (SequenceNode, ConditionalNode, LoopNode, ParallelNode):
    _model.model_rebuild()


class RetryPolicy(ValueModel):
    kind: Literal["retry"] = "retry"
    max_attempts: int = Field(ge=1)
    requires_reconcile: bool = False


class AbortPolicy(ValueModel):
    kind: Literal["abort"] = "abort"


RecoveryPolicy = Annotated[RetryPolicy | AbortPolicy, Field(discriminator="kind")]


def child_nodes(node: TaskNode) -> tuple[TaskNode, ...]:
    if isinstance(node, (SequenceNode, ParallelNode)):
        return node.children
    if isinstance(node, ConditionalNode):
        return (node.then,) if node.otherwise is None else (node.then, node.otherwise)
    if isinstance(node, LoopNode):
        return (node.child,)
    return ()


def iter_nodes(root: TaskNode) -> Iterator[TaskNode]:
    """Depth-first, pre-order walk over every node in the graph."""
    yield root
    for child in child_nodes(root):
        yield from iter_nodes(child)


class TaskGraph(ContractModel):
    root: TaskNode
    recoveries: dict[str, RecoveryPolicy] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_graph(self) -> "TaskGraph":
        ids = [node.node_id for node in iter_nodes(self.root)]
        duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate node_id(s): {duplicates}")
        missing = sorted(
            {
                node.recovery_ref
                for node in iter_nodes(self.root)
                if node.recovery_ref is not None and node.recovery_ref not in self.recoveries
            }
        )
        if missing:
            raise ValueError(f"unknown recovery_ref(s): {missing}")
        return self


class TaskDefinition(ContractModel):
    task_id: Identifier
    objective: Identifier
    description: str = ""
    graph: TaskGraph
    required_capabilities: tuple[Identifier, ...] = ()

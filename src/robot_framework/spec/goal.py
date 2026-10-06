"""Goal contract: what the user wants, independent of how it is achieved."""

from typing import Any

from pydantic import Field

from robot_framework.spec._base import ContractModel, Identifier, Quantity, ValueModel
from robot_framework.spec.world import FactPredicate


class SuccessCriterion(FactPredicate):
    """A world predicate that must hold, on fresh evidence, for the goal to count as achieved."""


class Constraint(ValueModel):
    """A limit the mission must respect. Hard constraints that no component enforces are rejected."""

    name: Identifier
    limit: Quantity | None = None
    hard: bool = True


class HumanInteractionPolicy(ValueModel):
    require_plan_confirmation: bool = False


class GoalSpec(ContractModel):
    goal_id: str = Field(min_length=1)
    objective: Identifier
    parameters: dict[str, Any] = Field(default_factory=dict)
    success_criteria: tuple[SuccessCriterion, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    deadline_s: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    human_policy: HumanInteractionPolicy = Field(default_factory=HumanInteractionPolicy)

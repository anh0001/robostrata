"""Assessment reports from grounding plugins. UNKNOWN is not INFEASIBLE."""

from enum import Enum
from typing import Any

from pydantic import Field

from robot_framework.spec._base import ContractModel, Identifier, ValueModel


class AssessmentStatus(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssessmentContext(ValueModel):
    world_snapshot_id: str = Field(min_length=1)
    robot_state_revision: int = Field(ge=0)
    provider_id: Identifier


class RecommendedStep(ValueModel):
    skill_id: Identifier
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class AssessmentReport(ContractModel):
    status: AssessmentStatus
    reason: str = ""
    context: AssessmentContext
    evidence: dict[str, str] = Field(default_factory=dict)
    applicable_constraints: tuple[str, ...] = ()
    recommended_next_step: RecommendedStep | None = None

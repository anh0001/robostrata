"""Plan proposals: an artifact kind plus exactly one matching payload.

A proposal is untrusted input regardless of which planner produced it.
"""

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from robot_framework.spec._base import ContractModel, EntityId, Identifier, ValueModel
from robot_framework.spec.task import TaskGraph
from robot_framework.spec.world import FactPredicate


class PlanArtifactKind(str, Enum):
    TASK_GRAPH = "task_graph"
    NATIVE_BT_XML = "native_bt_xml"
    TEMPORAL_PLAN = "temporal_plan"
    POLICY_GOAL = "policy_goal"


NATIVE_KINDS = frozenset({PlanArtifactKind.NATIVE_BT_XML, PlanArtifactKind.TEMPORAL_PLAN})

_PAYLOAD_FOR_KIND = {
    PlanArtifactKind.TASK_GRAPH: "task_graph",
    PlanArtifactKind.NATIVE_BT_XML: "native",
    PlanArtifactKind.TEMPORAL_PLAN: "native",
    PlanArtifactKind.POLICY_GOAL: "policy_goal",
}


class NativeArtifact(ValueModel):
    """A backend-native artifact (BT.CPP XML, temporal plan) that needs a registered validator."""

    format: str = Field(min_length=1)
    content: str
    validator_id: Identifier
    resource_scope: tuple[Identifier, ...] = ()
    entry_contract: dict[str, Any] = Field(default_factory=dict)
    exit_contract: dict[str, Any] = Field(default_factory=dict)


class PolicyGoal(ValueModel):
    instruction: str = Field(min_length=1)
    target_entities: tuple[EntityId, ...] = ()
    success_predicates: tuple[FactPredicate, ...] = ()
    horizon_s: float = Field(gt=0.0)


class ExecutiveRequirements(ValueModel):
    """Optional pin to a specific executive; the validator rejects any other."""

    executive_id: Identifier | None = None


class PlanProposal(ContractModel):
    proposal_id: str = Field(min_length=1)
    kind: PlanArtifactKind
    planner_id: Identifier
    task_graph: TaskGraph | None = None
    native: NativeArtifact | None = None
    policy_goal: PolicyGoal | None = None
    assumptions: tuple[str, ...] = ()
    world_snapshot_id: str = Field(min_length=1)
    executive_requirements: ExecutiveRequirements = Field(default_factory=ExecutiveRequirements)

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> "PlanProposal":
        present = {
            name
            for name in ("task_graph", "native", "policy_goal")
            if getattr(self, name) is not None
        }
        expected = {_PAYLOAD_FOR_KIND[self.kind]}
        if present != expected:
            raise ValueError(
                f"kind {self.kind.value} requires exactly the payload {sorted(expected)}, "
                f"got {sorted(present)}"
            )
        return self

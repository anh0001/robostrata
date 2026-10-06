"""Mission events (the replayable decision record) and mission results."""

import json
from enum import Enum
from typing import Any, Literal

from pydantic import Field, field_validator

from robot_framework.spec._base import ContractModel, Timestamp, ValueModel
from robot_framework.spec.invocation import SkillResult
from robot_framework.spec.world import Fact


class MissionStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    REJECTED = "REJECTED"


MissionEventKind = Literal[
    "goal_received",
    "plan_proposed",
    "plan_validated",
    "plan_rejected",
    "skill_state",
    "assessment",
    "assessment_unknown",
    "extension_warning",
    "provider_selected",
    "lease_acquired",
    "lease_renewed",
    "lease_released",
    "command_rejected",
    "verification",
    "effects_committed",
    "reconciled_success",
    "reconciled_absent",
    "reconcile_blocked",
    "recovery_retry",
    "epoch_bumped",
    "sim_step",
    "sim_pause",
    "mission_canceled",
    "mission_finished",
]


class MissionEvent(ContractModel):
    mission_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    time: Timestamp
    kind: MissionEventKind
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_is_json(cls, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"event payload must be JSON-serialisable: {exc}") from exc
        return payload


class RejectionReason(ValueModel):
    code: str = Field(min_length=1)
    node_id: str | None = None
    detail: str = ""


class MissionResult(ContractModel):
    mission_id: str = Field(min_length=1)
    status: MissionStatus
    goal_id: str = Field(min_length=1)
    proposal_id: str | None = None
    skill_results: tuple[SkillResult, ...] = ()
    verified_effects: tuple[Fact, ...] = ()
    rejection_reasons: tuple[RejectionReason, ...] = ()
    failure_reason: str | None = None
    events_ref: str | None = None

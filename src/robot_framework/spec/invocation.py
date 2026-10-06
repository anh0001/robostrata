"""Skill invocations, provider outcomes and skill results.

A provider outcome is a *claim*; a skill result is what the runtime concluded after verification.
"""

from enum import Enum
from typing import Any, Literal

from pydantic import Field

from robot_framework.spec._base import ContractModel, Identifier, Timestamp, ValueModel
from robot_framework.spec.world import Fact


class LifecycleState(str, Enum):
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    CANCELING = "CANCELING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


TERMINAL_STATES = frozenset(
    {
        LifecycleState.SUCCEEDED,
        LifecycleState.FAILED,
        LifecycleState.CANCELED,
        LifecycleState.OUTCOME_UNKNOWN,
    }
)


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_RUN = "NOT_RUN"


ProviderStatus = Literal["SUCCESS", "FAILURE", "CANCELED", "UNKNOWN"]

FailureCategory = Literal[
    "perception_stale",
    "precondition_unmet",
    "unreachable",
    "infeasible",
    "provider_timeout",
    "hardware_fault",
    "safety_stop",
    "hold_violated",
    "cancelled",
    "ack_lost",
    "command_rejected",
    "resource_conflict",
    "stale_epoch",
    "lease_lost",
    "verification_failed",
    "unsupported",
    "other",
]


class FailureDiagnosis(ValueModel):
    category: FailureCategory
    detail: str = ""
    evidence_refs: tuple[str, ...] = ()


class ProgressReport(ValueModel):
    fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    message: str = ""
    time: Timestamp


class SkillInvocation(ContractModel):
    invocation_id: str = Field(min_length=1)
    node_id: str | None = None
    skill_id: Identifier
    provider_id: Identifier | None = None
    bound_params: dict[str, Any] = Field(default_factory=dict)
    lease_id: str | None = None
    epoch: int | None = Field(default=None, ge=0)
    state: LifecycleState = LifecycleState.CREATED
    created_at: Timestamp


class ProviderOutcome(ContractModel):
    """What a provider *claims* happened. Never task success by itself."""

    invocation_id: str = Field(min_length=1)
    status: ProviderStatus
    diagnosis: FailureDiagnosis | None = None
    evidence_references: tuple[str, ...] = ()


class SkillResult(ContractModel):
    invocation_id: str = Field(min_length=1)
    node_id: str | None = None
    skill_id: Identifier
    provider_id: Identifier | None = None
    provider_status: ProviderStatus | None = None
    state: LifecycleState
    observed_effects: tuple[Fact, ...] = ()
    verification_status: VerificationStatus
    evidence_references: tuple[str, ...] = ()
    failure_diagnosis: FailureDiagnosis | None = None
    reconciled: bool = False


class ActionChunk(ContractModel):
    """A short horizon of policy actions; dispatched under a lease and epoch like any command."""

    actions: tuple[dict[str, Any], ...] = ()
    horizon: int = Field(ge=1)
    frame: str = Field(min_length=1)
    epoch: int = Field(ge=0)

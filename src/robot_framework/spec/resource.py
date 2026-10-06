"""Resource leases and command envelopes: every command carries a lease and an execution epoch."""

from enum import Enum
from typing import Any

from pydantic import Field

from robot_framework.spec._base import ContractModel, Identifier


class ControlMode(str, Enum):
    POSITION = "position"
    VELOCITY = "velocity"
    EFFORT = "effort"
    TRAJECTORY = "trajectory"
    POLICY = "policy"
    NONE = "none"


class ResourceLease(ContractModel):
    """Bounded, exclusive ownership of resources. Expiry is on the monotonic clock."""

    lease_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    resources: tuple[Identifier, ...] = ()
    control_mode: ControlMode
    epoch: int = Field(ge=0)
    expires_at_monotonic: float


class CommandEnvelope(ContractModel):
    envelope_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    target_resources: tuple[Identifier, ...] = ()
    control_mode: ControlMode
    payload: dict[str, Any] = Field(default_factory=dict)
    issued_at_monotonic: float


class CommandAcknowledgement(ContractModel):
    envelope_id: str = Field(min_length=1)
    accepted: bool
    reason: str | None = None

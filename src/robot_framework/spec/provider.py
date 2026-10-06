"""Provider manifest: what an execution provider implements and what hardware it needs."""

from enum import Enum

from pydantic import Field

from robot_framework.spec._base import ContractModel, Identifier, ValueModel
from robot_framework.spec.resource import ControlMode
from robot_framework.spec.skill import CancellationSpec


class ProviderKind(str, Enum):
    SKILL = "skill"
    POLICY = "policy"
    DEVICE = "device"


class HardwareRequirement(ValueModel):
    """A robot capability that must be structurally present for the provider to be eligible."""

    capability: Identifier


class ObservationSpace(ValueModel):
    keys: tuple[str, ...] = ()
    frame: str | None = None


class ActionSpace(ValueModel):
    control_mode: ControlMode
    dimension: int = Field(ge=1)
    frame: str | None = None
    rate_hz: float | None = Field(default=None, gt=0.0)


class ProviderManifest(ContractModel):
    provider_id: Identifier
    kind: ProviderKind
    implements: tuple[Identifier, ...] = Field(min_length=1)
    hardware: tuple[HardwareRequirement, ...] = ()
    domains: tuple[str, ...] = ()
    version: str = Field(min_length=1)
    model_ref: str | None = None
    cancellation: CancellationSpec
    control_mode: ControlMode = ControlMode.NONE
    observation_space: ObservationSpace | None = None
    action_space: ActionSpace | None = None

"""Deployment profile: selects every swappable part of a deployment."""

from typing import Literal

from pydantic import Field, model_validator

from robot_framework.spec._base import ContractModel, DeploymentMode, Identifier, ValueModel
from robot_framework.spec.plan import PlanArtifactKind

UNSAFE_SAFETY_PROFILES = frozenset({"mock", "none"})


class Deployment(ValueModel):
    mode: DeploymentMode
    backend: Identifier
    profile: str = Field(default="default", min_length=1)


class PlanningCfg(ValueModel):
    plugin: Identifier
    output_kind: PlanArtifactKind = PlanArtifactKind.TASK_GRAPH


class ExecutionCfg(ValueModel):
    plugin: Identifier
    lease_ttl_s: float = Field(default=5.0, gt=0.0, allow_inf_nan=False)
    monitor_poll_s: float = Field(default=0.005, gt=0.0, allow_inf_nan=False)
    provider_preference: dict[str, tuple[Identifier, ...]] = Field(default_factory=dict)


class ExtensionRef(ValueModel):
    id: Identifier
    required: bool = False
    config: str | None = None


class VerificationCfg(ValueModel):
    profile: Literal["evidence_based"] = "evidence_based"


class SafetyCfg(ValueModel):
    profile: str = Field(min_length=1)


class RecordingCfg(ValueModel):
    mission_events: bool = True
    decision_evidence: bool = True


class DeploymentProfile(ContractModel):
    api_version: Literal["robot_framework/v1alpha1"]
    task_pack: Identifier
    robot_pack: Identifier
    default_goal: str | None = None
    deployment: Deployment
    planning: PlanningCfg
    execution: ExecutionCfg
    extensions: tuple[ExtensionRef, ...] = ()
    verification: VerificationCfg = Field(default_factory=VerificationCfg)
    safety: SafetyCfg
    recording: RecordingCfg = Field(default_factory=RecordingCfg)

    @model_validator(mode="after")
    def _check_profile(self) -> "DeploymentProfile":
        if (
            self.deployment.mode is DeploymentMode.REAL
            and self.safety.profile in UNSAFE_SAFETY_PROFILES
        ):
            raise ValueError(
                f"mode 'real' requires a real safety profile, got '{self.safety.profile}'"
            )
        ids = [ref.id for ref in self.extensions]
        if len(ids) != len(set(ids)):
            raise ValueError("extension ids must be unique")
        return self

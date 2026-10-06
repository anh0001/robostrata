"""Skill contract: typed ports, conditions, expected effects, verification and cancellation."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, model_validator

from robot_framework.spec._base import ContractModel, Identifier, ValueModel
from robot_framework.spec.world import FactPredicate

PORT_REF_PREFIX = "$"
"""Condition and effect arguments starting with ``$`` name an input port (``$object``)."""

PortType = Literal["string", "number", "boolean", "entity", "pose", "object"]


class PortSpec(ValueModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: PortType
    required: bool = True
    unit: str | None = None
    description: str = ""


class Condition(FactPredicate):
    """A pre- or hold-condition. ``max_age_s`` makes it time-sensitive (rechecked after reserve)."""

    max_age_s: float | None = Field(default=None, gt=0.0)


class ExpectedEffect(FactPredicate):
    """A physical effect the skill must produce; checked by a verifier on fresh evidence."""


class VerificationSpec(ValueModel):
    required: bool = True
    verifier_id: Identifier = "world_fact"


class CancellationSpec(ValueModel):
    mode: Literal["immediate", "safe_state_first", "custom"] = "immediate"
    max_stop_time_s: float = Field(gt=0.0, allow_inf_nan=False)


class FailureSemantics(ValueModel):
    timeout_s: float = Field(default=30.0, gt=0.0, allow_inf_nan=False)
    retryable: bool = True


def bind_args(args: tuple[str, ...], params: Mapping[str, Any]) -> tuple[str, ...]:
    """Replace ``$port`` references with bound parameter values; literals pass through."""
    return tuple(
        str(params[arg[len(PORT_REF_PREFIX) :]]) if arg.startswith(PORT_REF_PREFIX) else arg
        for arg in args
    )


class SkillContract(ContractModel):
    skill_id: Identifier
    description: str = ""
    inputs: tuple[PortSpec, ...] = ()
    outputs: tuple[PortSpec, ...] = ()
    preconditions: tuple[Condition, ...] = ()
    hold_conditions: tuple[Condition, ...] = ()
    expected_effects: tuple[ExpectedEffect, ...] = ()
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    cancellation: CancellationSpec
    failure_semantics: FailureSemantics = Field(default_factory=FailureSemantics)
    required_capabilities: tuple[Identifier, ...] = ()
    required_resources: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _check_contract(self) -> "SkillContract":
        for label, ports in (("input", self.inputs), ("output", self.outputs)):
            names = [port.name for port in ports]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate {label} port names in {self.skill_id}")
        unknown = sorted(self.referenced_ports() - {port.name for port in self.inputs})
        if unknown:
            raise ValueError(f"{self.skill_id} references unknown input port(s): {unknown}")
        if self.verification.required and not self.expected_effects:
            raise ValueError(
                f"{self.skill_id} requires verification but declares no expected effects"
            )
        return self

    def referenced_ports(self) -> frozenset[str]:
        predicates = (*self.preconditions, *self.hold_conditions, *self.expected_effects)
        return frozenset(
            arg[len(PORT_REF_PREFIX) :]
            for predicate in predicates
            for arg in predicate.args
            if arg.startswith(PORT_REF_PREFIX)
        )

    def input(self, name: str) -> PortSpec | None:
        return next((port for port in self.inputs if port.name == name), None)

    def output(self, name: str) -> PortSpec | None:
        return next((port for port in self.outputs if port.name == name), None)

"""World facts, evidence and snapshots: the world model stores evidence, not truth."""

import json
from typing import Any

from pydantic import Field, field_validator

from robot_framework.spec._base import ContractModel, EntityId, Timestamp, ValueModel

FactKey = tuple[str, tuple[str, ...]]


class FactPredicate(ValueModel):
    """A test against the world: ``predicate(*args) == expected`` on a fresh fact."""

    predicate: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    expected: bool = True


class Fact(ContractModel):
    """One piece of evidence about the world, with provenance and freshness."""

    predicate: str = Field(min_length=1)
    args: tuple[EntityId, ...] = ()
    value: Any
    source: str = Field(min_length=1)
    observation_time: Timestamp
    validity_s: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    revision: int = Field(default=0, ge=0)

    @field_validator("value")
    @classmethod
    def _value_is_json(cls, value: Any) -> Any:
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fact value must be JSON-serialisable: {exc}") from exc
        return value

    @property
    def key(self) -> FactKey:
        return (self.predicate, self.args)

    def is_stale(self, now: Timestamp) -> bool:
        """A fact is stale once its validity window has elapsed on the observation clock."""
        return self.validity_s is not None and now - self.observation_time >= self.validity_s


class Evidence(ContractModel):
    """A reference to recorded evidence (sensor frame, log entry, fact revision)."""

    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    time: Timestamp


class WorldSnapshot(ContractModel):
    """An immutable view of the world at one revision."""

    snapshot_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    time: Timestamp
    facts: tuple[Fact, ...] = ()

    def lookup(self, predicate: str, args: tuple[str, ...]) -> Fact | None:
        return next((f for f in self.facts if f.predicate == predicate and f.args == args), None)

    def is_stale(self, fact: Fact, now: Timestamp) -> bool:
        return fact.is_stale(now)

    def holds(self, test: FactPredicate, now: Timestamp) -> bool:
        """True only when a non-stale fact exists and its value equals ``test.expected``."""
        fact = self.lookup(test.predicate, test.args)
        return fact is not None and not fact.is_stale(now) and fact.value == test.expected

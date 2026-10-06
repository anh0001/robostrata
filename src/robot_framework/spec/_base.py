"""Contract base models, the schema version and shared identifier types."""

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "v1alpha1"
IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"

Identifier = Annotated[str, Field(pattern=IDENTIFIER_PATTERN)]
"""Dotted lowercase identifier: skill, provider, capability, resource and plugin ids."""

EntityId = Annotated[str, Field(min_length=1)]
"""Identifier of a thing in the world, e.g. ``bottle_17`` or ``robot``."""

Timestamp = float
"""Seconds on the observation clock (comparable to sensor timestamps, never to monotonic time)."""


class ValueModel(BaseModel):
    """Immutable, strict building block nested inside contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ContractModel(ValueModel):
    """Base for every top-level framework contract: immutable, strict, versioned.

    Never mutate a contract; derive a new one with ``model_copy(update={...})``.
    """

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^v\d+(alpha|beta)?\d*$")


class DeploymentMode(str, Enum):
    MOCK = "mock"
    SIMULATION = "simulation"
    HIL = "hil"
    REAL = "real"
    REPLAY = "replay"


class Quantity(ValueModel):
    """A physical quantity with an explicit unit; never a bare float with an implied unit."""

    value: float
    unit: str = Field(min_length=1)

"""Framework error hierarchy.

Raise, never return ``None`` on failure. Expected outcomes (FAILED, OUTCOME_UNKNOWN, INFEASIBLE)
are values in result models, not exceptions. Every error has a stable machine-readable ``code``.
"""

from typing import Any


class FrameworkError(Exception):
    """Base. ``code`` is a stable machine-readable string; ``details`` is JSON-serialisable."""

    code: str = "framework_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "details": self.details}


class ContractValidationError(FrameworkError):
    code = "contract_validation"


class PlanRejectedError(FrameworkError):
    """Structured reasons live in ``details["reasons"]`` as ``{code, node_id, detail}`` dicts."""

    code = "plan_rejected"


class ResourceConflictError(FrameworkError):
    code = "resource_conflict"


class StaleEpochError(FrameworkError):
    code = "stale_epoch"


class UnsupportedOperationError(FrameworkError):
    """The operation is not available here. Never fake success instead of raising this."""

    code = "unsupported"


class ExtensionRequiredError(FrameworkError):
    """A required extension is missing or failed; there is no silent bypass."""

    code = "extension_required"


class MissionAlreadyRunningError(FrameworkError):
    code = "mission_already_running"

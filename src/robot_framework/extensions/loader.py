"""Extension loader honouring ``required: true``: a missing or failing required extension aborts;
there is no silent fallback to a reduced mode.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from robot_framework.core.errors import ExtensionRequiredError
from robot_framework.core.interfaces import GroundingPlugin, LoadedExtension
from robot_framework.core.registry import Registry
from robot_framework.extensions.null import NullGroundingPlugin
from robot_framework.spec import ExtensionRef

if TYPE_CHECKING:
    from robot_framework.core.recorder import MissionRecorder

log = logging.getLogger(__name__)

ExtensionFactory = Callable[[str | None], GroundingPlugin]
"""Builds a plugin from the optional ``config`` string of its ``ExtensionRef``."""


def default_extension_factories() -> Registry[ExtensionFactory]:
    factories: Registry[ExtensionFactory] = Registry("extension")
    factories.register("null_grounding", lambda config: NullGroundingPlugin())
    return factories


class ExtensionLoader:
    def __init__(
        self, factories: Registry[ExtensionFactory], recorder: MissionRecorder | None = None
    ) -> None:
        self._factories = factories
        self._recorder = recorder

    def load(self, refs: Iterable[ExtensionRef]) -> tuple[LoadedExtension, ...]:
        loaded = (self._load_one(ref) for ref in refs)
        return tuple(extension for extension in loaded if extension is not None)

    def _load_one(self, ref: ExtensionRef) -> LoadedExtension | None:
        if ref.id not in self._factories:
            self._unavailable(ref, "is not installed", None)
            return None
        try:
            plugin = self._factories.get(ref.id)(ref.config)
        except Exception as exc:
            self._unavailable(ref, f"failed to load: {exc}", exc)
            return None
        return LoadedExtension(extension_id=ref.id, required=ref.required, plugin=plugin)

    def _unavailable(self, ref: ExtensionRef, problem: str, cause: Exception | None) -> None:
        details = {"extension_id": ref.id, "available": sorted(self._factories.items())}
        if ref.required:
            raise ExtensionRequiredError(
                f"required extension '{ref.id}' {problem}", details=details
            ) from cause
        log.warning("optional extension unavailable", extra={"extension_id": ref.id})
        if self._recorder is not None:
            self._recorder.record("extension_warning", {**details, "problem": problem})

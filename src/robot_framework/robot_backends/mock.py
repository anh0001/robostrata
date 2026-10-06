"""Mock robot backend: every command passes the command authority, and only accepted commands
change the mock world's ground truth.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from robot_framework.core.errors import UnsupportedOperationError
from robot_framework.core.resource_manager import CommandAuthority
from robot_framework.core.world_interface import ObservationSource
from robot_framework.spec import CommandAcknowledgement, CommandEnvelope, FactKey

if TYPE_CHECKING:
    from robot_framework.core.recorder import MissionRecorder

log = logging.getLogger(__name__)

SET_FACTS_KEY = "set_facts"
"""Envelope payload key: ``[{predicate, args, value}]`` physical effects of the command."""


class MockGroundTruth:
    """Complete physical state of the mock world: a predicate that was never set is false."""

    def __init__(self, initial: Mapping[FactKey, Any] | None = None) -> None:
        self._initial = dict(initial or {})
        self._values = dict(self._initial)

    def get(self, predicate: str, args: tuple[str, ...]) -> Any:
        return self._values.get((predicate, tuple(args)), False)

    def set(self, predicate: str, args: tuple[str, ...], value: Any) -> None:
        self._values = {**self._values, (predicate, tuple(args)): value}

    def apply(self, assignments: Iterable[Mapping[str, Any]]) -> None:
        for assignment in assignments:
            self.set(assignment["predicate"], tuple(assignment["args"]), assignment["value"])

    def reset(self) -> None:
        self._values = dict(self._initial)

    def reader(self, predicate: str) -> ObservationSource:
        return lambda args: self.get(predicate, args)


class MockRobotBackend:
    def __init__(
        self,
        authority: CommandAuthority,
        ground_truth: MockGroundTruth | None = None,
        *,
        recorder: MissionRecorder | None = None,
        backend_id: str = "mock_robot",
    ) -> None:
        self.backend_id = backend_id
        self.ground_truth = ground_truth if ground_truth is not None else MockGroundTruth()
        self._authority = authority
        self._recorder = recorder
        self._dispatched: tuple[tuple[CommandEnvelope, CommandAcknowledgement], ...] = ()

    @property
    def dispatched(self) -> tuple[CommandEnvelope, ...]:
        return tuple(envelope for envelope, _ in self._dispatched)

    @property
    def accepted(self) -> tuple[CommandEnvelope, ...]:
        return tuple(envelope for envelope, ack in self._dispatched if ack.accepted)

    @property
    def acknowledgements(self) -> tuple[CommandAcknowledgement, ...]:
        return tuple(ack for _, ack in self._dispatched)

    def capabilities(self) -> frozenset[str]:
        return frozenset({"dispatch"})

    async def dispatch(self, envelope: CommandEnvelope) -> CommandAcknowledgement:
        ack = self._authority.check(envelope)
        self._dispatched = (*self._dispatched, (envelope, ack))
        if ack.accepted:
            self.ground_truth.apply(envelope.payload.get(SET_FACTS_KEY, ()))
        elif self._recorder is not None:
            self._recorder.record(
                "command_rejected",
                {"envelope": envelope.model_dump(mode="json"), "reason": ack.reason},
            )
        return ack

    async def reset(self) -> int:
        raise UnsupportedOperationError(f"backend '{self.backend_id}' does not support reset")

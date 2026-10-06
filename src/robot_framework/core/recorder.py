"""Mission recorder: the replayable decision record.

Logs are for humans; mission events are the record. Payloads must be JSON-serialisable, so pass
``model_dump(mode="json")`` of contracts.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from robot_framework.core.clock import Clock
from robot_framework.spec import MissionEvent, MissionEventKind

SESSION_MISSION_ID = "session"
DECISION_EVIDENCE_KINDS = frozenset({"assessment", "assessment_unknown", "verification"})


class MissionRecorder:
    def __init__(
        self,
        clock: Clock,
        *,
        sink: Path | None = None,
        mission_id: str = SESSION_MISSION_ID,
        enabled: bool = True,
        decision_evidence: bool = True,
    ) -> None:
        self._clock = clock
        self._sink = sink
        self._mission_id = mission_id
        self._enabled = enabled
        self._decision_evidence = decision_evidence
        self._events: tuple[MissionEvent, ...] = ()
        if sink is not None:
            sink.parent.mkdir(parents=True, exist_ok=True)

    @property
    def mission_id(self) -> str:
        return self._mission_id

    @property
    def sink(self) -> Path | None:
        return self._sink

    def start_mission(self, mission_id: str) -> None:
        self._mission_id = mission_id

    def record(
        self, kind: MissionEventKind, payload: Mapping[str, Any] | None = None
    ) -> MissionEvent:
        event = MissionEvent(
            mission_id=self._mission_id,
            sequence=len(self._events),
            time=self._clock.now(),
            kind=kind,
            payload=dict(payload or {}),
        )
        if not self._enabled or (kind in DECISION_EVIDENCE_KINDS and not self._decision_evidence):
            return event
        self._events = (*self._events, event)
        if self._sink is not None:
            with self._sink.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
        return event

    def events(self, kind: str | None = None) -> tuple[MissionEvent, ...]:
        if kind is None:
            return self._events
        return tuple(event for event in self._events if event.kind == kind)

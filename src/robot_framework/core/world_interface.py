"""In-memory world model: revisioned evidence with validity windows.

The world is not a behavior-tree blackboard; execution-local variables never live here.
"""

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from robot_framework.core.clock import Clock
from robot_framework.spec import Fact, FactKey, WorldSnapshot

log = logging.getLogger(__name__)

ObservationSource = Callable[[tuple[str, ...]], Any]
"""Returns the currently observed value for the given args, or ``None`` when not observable."""


@dataclass(frozen=True)
class _Source:
    read: ObservationSource
    source_id: str
    validity_s: float | None


class InMemoryWorld:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._facts: dict[FactKey, Fact] = {}
        self._revision = 0
        self._sources: dict[str, _Source] = {}
        self._invalidations: tuple[tuple[int, str], ...] = ()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def invalidations(self) -> tuple[tuple[int, str], ...]:
        return self._invalidations

    def snapshot(self) -> WorldSnapshot:
        return WorldSnapshot(
            snapshot_id=f"ws_{uuid.uuid4().hex[:12]}",
            revision=self._revision,
            time=self._clock.now(),
            facts=tuple(self._facts.values()),
        )

    def lookup(self, predicate: str, args: tuple[str, ...]) -> Fact | None:
        return self._facts.get((predicate, args))

    def is_stale(self, fact: Fact) -> bool:
        return fact.is_stale(self._clock.now())

    def commit(self, facts: Iterable[Fact], source: str) -> int:
        """Replace facts by key; the whole batch shares one new revision."""
        batch = tuple(facts)
        if not batch:
            return self._revision
        revision = self._revision + 1
        stamped = {
            fact.key: fact.model_copy(update={"source": source, "revision": revision})
            for fact in batch
        }
        self._facts = {**self._facts, **stamped}
        self._revision = revision
        return revision

    def register_observation_source(
        self,
        predicate: str,
        read: ObservationSource,
        *,
        source_id: str,
        validity_s: float | None = None,
    ) -> None:
        self._sources = {**self._sources, predicate: _Source(read, source_id, validity_s)}

    async def observe(self, predicate: str, args: tuple[str, ...]) -> Fact | None:
        """Take a fresh observation and commit it; ``None`` when the predicate is not observable."""
        source = self._sources.get(predicate)
        if source is None:
            return None
        value = source.read(args)
        if value is None:
            return None
        fact = Fact(
            predicate=predicate,
            args=args,
            value=value,
            source=source.source_id,
            observation_time=self._clock.now(),
            validity_s=source.validity_s,
        )
        self.commit((fact,), source.source_id)
        return self._facts[fact.key]

    def invalidate_all(self, reason: str) -> int:
        """Mark every fact stale (validity 0); facts are kept as history, not deleted."""
        revision = self._revision + 1
        self._facts = {
            key: fact.model_copy(update={"validity_s": 0.0, "revision": revision})
            for key, fact in self._facts.items()
        }
        self._revision = revision
        self._invalidations = (*self._invalidations, (revision, reason))
        log.warning("world invalidated", extra={"revision": revision, "reason": reason})
        return revision

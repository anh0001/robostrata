"""Clocks. ``now()`` is the observation clock; ``monotonic()`` is for deadlines and lease expiry.

The two are never compared with each other.
"""

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> float:
        """Observation time in seconds, comparable to sensor timestamps."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds for deadlines, timeouts and lease expiry."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class MockClock:
    """Deterministic clock for tests; both time bases can be advanced together or separately."""

    def __init__(self, now: float = 0.0, mono: float = 0.0) -> None:
        self._now = now
        self._mono = mono

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self.advance_observation_only(seconds)
        self.advance_monotonic_only(seconds)

    def advance_observation_only(self, seconds: float) -> None:
        self._now = self._now + _non_negative(seconds)

    def advance_monotonic_only(self, seconds: float) -> None:
        self._mono = self._mono + _non_negative(seconds)


def _non_negative(seconds: float) -> float:
    if seconds < 0:
        raise ValueError(f"clocks only move forward, got {seconds}")
    return seconds

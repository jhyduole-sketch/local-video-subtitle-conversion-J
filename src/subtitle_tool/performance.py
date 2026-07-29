from __future__ import annotations

from contextlib import contextmanager
import time
from typing import Callable, Iterator


class StageTimer:
    """Accumulates monotonic timings without coupling stages to logging."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._started_at = clock()
        self._active: dict[str, float] = {}
        self._durations: dict[str, float] = {}

    def start(self, name: str) -> None:
        self._active[name] = self._clock()

    def finish(self, name: str) -> float:
        started_at = self._active.pop(name, None)
        if started_at is None:
            return 0.0
        elapsed = max(0.0, self._clock() - started_at)
        self._durations[name] = self._durations.get(name, 0.0) + elapsed
        return elapsed

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        self.start(name)
        try:
            yield
        finally:
            self.finish(name)

    def durations(self) -> dict[str, float]:
        return {name: round(value, 3) for name, value in self._durations.items()}

    def total_duration_seconds(self) -> float:
        return round(max(0.0, self._clock() - self._started_at), 3)

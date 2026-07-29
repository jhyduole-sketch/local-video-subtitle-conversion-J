from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Callable, Iterator

from .errors import CancellationError
from .process_control import CancelCheck


class HeavyResourceScheduler:
    def __init__(self, poll_interval_seconds: float = 0.25):
        self._semaphore = threading.Semaphore(1)
        self._state_lock = threading.Lock()
        self._active_label: str | None = None
        self._poll_interval_seconds = poll_interval_seconds

    @contextmanager
    def reserve(
        self,
        label: str,
        *,
        cancel_check: CancelCheck | None = None,
        wait_callback: Callable[[str], None] | None = None,
    ) -> Iterator[None]:
        reported_wait = False
        while not self._semaphore.acquire(timeout=self._poll_interval_seconds):
            if cancel_check and cancel_check():
                raise CancellationError("Task was cancelled while waiting for resources.")
            if wait_callback and not reported_wait:
                with self._state_lock:
                    active_label = self._active_label or "其他重任务"
                wait_callback(active_label)
                reported_wait = True
        with self._state_lock:
            self._active_label = label
        try:
            if cancel_check and cancel_check():
                raise CancellationError("Task was cancelled by user.")
            yield
        finally:
            with self._state_lock:
                self._active_label = None
            self._semaphore.release()


HEAVY_RESOURCE_SCHEDULER = HeavyResourceScheduler()

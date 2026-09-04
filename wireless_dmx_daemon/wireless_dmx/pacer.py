"""Latest-state DMX pacing."""

from __future__ import annotations

import time
from threading import Condition, Event, Lock, Thread
from typing import Callable

from .models import DmxStatistics


class DmxPacer:
    def __init__(self, rate_hz: float, send: Callable[[bytes], None], stats: DmxStatistics | None = None) -> None:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self.rate_hz = rate_hz
        self._send = send
        self.stats = stats or DmxStatistics()
        self._pending: bytes | None = None
        self._condition = Condition(Lock())
        self._stop = Event()
        self._thread: Thread | None = None

    def submit(self, universe: bytes) -> None:
        if len(universe) != 512:
            raise ValueError("pacer requires a normalized 512-byte universe")
        with self._condition:
            if self._pending is not None:
                self.stats.frames_dropped_by_pacer += 1
            self._pending = bytes(universe)
            self._condition.notify()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="dmx-pacer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        period = 1.0 / self.rate_hz
        next_send = time.monotonic()
        while not self._stop.is_set():
            wait = max(0.0, next_send - time.monotonic())
            with self._condition:
                if self._pending is None and wait > 0:
                    self._condition.wait(timeout=min(wait, 0.1))
                universe = self._pending if time.monotonic() >= next_send else None
                self._pending = None if universe is not None else self._pending
            if universe is not None:
                self._send(universe)
                self.stats.frames_submitted += 1
                self.stats.output_rate_hz = self.rate_hz
                next_send += period
                if next_send < time.monotonic() - period:
                    next_send = time.monotonic() + period
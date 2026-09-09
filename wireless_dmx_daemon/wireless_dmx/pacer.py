"""Latest-state DMX pacing."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
from typing import Callable

from .models import DmxStatistics, PriorityStatus


@dataclass
class PriorityItem:
    universe: bytes
    priority_id: int
    reason: str
    repeat_count: int
    ttl_seconds: float
    created: float
    repeat_index: int = 0
    attempt: int = 1
    target_receiver_id: int = 0


class DmxPacer:
    def __init__(self, rate_hz: float, send: Callable[[bytes], None], stats: DmxStatistics | None = None,
                 send_priority: Callable[[bytes], None] | None = None,
                 on_priority_started: Callable[[], None] | None = None,
                 on_priority_completed: Callable[[], None] | None = None,
                 priority_enabled: bool = True, priority_max_queue_depth: int = 4,
                 priority_max_repeat_count: int = 10, priority_max_ttl_seconds: float = 5.0,
                 priority_lead_in_ms: int = 50, priority_lead_out_ms: int = 50,
                 priority_max_consecutive_events: int = 3) -> None:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        self.rate_hz = rate_hz
        self._send = send
        self._send_priority = send_priority or send
        self._on_priority_started = on_priority_started
        self._on_priority_completed = on_priority_completed
        self.stats = stats or DmxStatistics()
        self._pending: bytes | None = None
        self.priority_enabled = priority_enabled
        self.priority_max_queue_depth = priority_max_queue_depth
        self.priority_max_repeat_count = priority_max_repeat_count
        self.priority_max_ttl_seconds = priority_max_ttl_seconds
        self.priority_lead_in_ms = priority_lead_in_ms
        self.priority_lead_out_ms = priority_lead_out_ms
        self.priority_max_consecutive_events = priority_max_consecutive_events
        self._priority_queue: deque[PriorityItem] = deque(maxlen=priority_max_queue_depth)
        self._priority_current: PriorityItem | None = None
        self._priority_state = "idle"
        self._priority_id = 0
        self._priority_last_result = ""
        self._priority_state_until = 0.0
        self._priority_consecutive_events = 0
        self._condition = Condition(Lock())
        self._stop = Event()
        self._thread: Thread | None = None

    def submit(self, universe: bytes) -> None:
        if len(universe) != 512:
            raise ValueError("pacer requires a normalized 512-byte universe")
        with self._condition:
            if self._pending is not None:
                self.stats.frames_dropped_by_pacer += 1
            if self._priority_current is not None or self._priority_queue:
                self.stats.normal_frames_during_priority += 1
            self._pending = bytes(universe)
            self._condition.notify()

    def submit_priority(self, universe: bytes, repeat_count: int = 1,
                        ttl_seconds: float = 2.0, reason: str = "manual",
                        priority_id: int | None = None, attempt: int = 1,
                        target_receiver_id: int = 0) -> int:
        if not self.priority_enabled:
            raise RuntimeError("priority transmission is disabled")
        if len(universe) != 512:
            raise ValueError("priority requires a normalized 512-byte universe")
        if not 1 <= repeat_count <= self.priority_max_repeat_count:
            raise ValueError("invalid priority repeat count")
        if not 0 < ttl_seconds <= self.priority_max_ttl_seconds:
            raise ValueError("invalid priority TTL")
        with self._condition:
            if len(self._priority_queue) >= self.priority_max_queue_depth:
                self.stats.priority_rejected_queue_full += 1
                raise OverflowError("priority queue is full")
            if not 1 <= attempt <= 255:
                raise ValueError("invalid priority attempt")
            if priority_id is None:
                priority_id = self._priority_id
                self._priority_id = (self._priority_id + 1) & 0xFFFFFFFF
            self._priority_queue.append(PriorityItem(bytes(universe), priority_id,
                                                     reason[:48], repeat_count, ttl_seconds,
                                                       time.monotonic(), attempt=attempt,
                                                       target_receiver_id=target_receiver_id))
            self.stats.priority_received += 1
            self.stats.priority_queued += 1
            self.stats.priority_queue_depth = len(self._priority_queue)
            self._condition.notify()
            return priority_id

    def clear_priority(self) -> None:
        with self._condition:
            self._priority_queue.clear()
            if self._priority_current is not None:
                self._priority_last_result = "cancelled"
                self.stats.priority_cancelled += 1
            self._priority_current = None
            self._priority_state = "idle"
            self.stats.priority_queue_depth = 0
            self._condition.notify_all()

    def priority_status(self) -> PriorityStatus:
        with self._condition:
            item = self._priority_current
            return PriorityStatus(
                enabled=self.priority_enabled,
                state=self._priority_state,
                queue_depth=len(self._priority_queue),
                queue_capacity=self.priority_max_queue_depth,
                priority_id=item.priority_id if item else None,
                reason=item.reason if item else "",
                attempt=item.attempt if item else 0,
                repeat_index=item.repeat_index if item else 0,
                repeat_count=item.repeat_count if item else 0,
                last_result=self._priority_last_result,
            )

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
            now = time.monotonic()
            with self._condition:
                if (self._priority_current is None and self._priority_queue and
                        not (self._priority_consecutive_events >= self.priority_max_consecutive_events and
                             self._pending is not None)):
                    self._priority_current = self._priority_queue.popleft()
                    self.stats.priority_queue_depth = len(self._priority_queue)
                    self._priority_state = "lead_in"
                    self._priority_state_until = now + self.priority_lead_in_ms / 1000.0
                elif self._priority_current is not None and now >= self._priority_current.created + self._priority_current.ttl_seconds:
                    self._priority_last_result = "expired"
                    self.stats.priority_expired += 1
                    self._priority_current = None
                    self._priority_state = "idle"
                    self._priority_consecutive_events = 0
            wait = max(0.0, next_send - time.monotonic())
            with self._condition:
                if self._pending is None and self._priority_current is None and wait > 0:
                    self._condition.wait(timeout=min(wait, 0.1))
                now = time.monotonic()
                universe = None
                priority_universe = False
                if self._priority_current is not None:
                    item = self._priority_current
                    if self._priority_state == "lead_in" and now >= self._priority_state_until:
                        self._priority_state = "transmitting"
                        if self._on_priority_started:
                            self._on_priority_started()
                    if self._priority_state == "transmitting" and now >= next_send:
                        universe = item.universe
                        priority_universe = True
                        item.repeat_index += 1
                        self.stats.priority_frames_submitted += 1
                        next_send = now + period
                        if item.repeat_index >= item.repeat_count:
                            self._priority_state = "lead_out"
                            self._priority_state_until = now + self.priority_lead_out_ms / 1000.0
                    elif self._priority_state == "lead_out" and now >= self._priority_state_until:
                        self._priority_last_result = "submitted"
                        self.stats.priority_completed += 1
                        self._priority_current = None
                        self._priority_state = "idle"
                        if self._on_priority_completed:
                            self._on_priority_completed()
                        self._priority_consecutive_events += 1
                        if self._pending is not None:
                            universe = self._pending
                            self._pending = None
                            next_send = now + period
                    self.stats.priority_queue_depth = len(self._priority_queue)
                elif self._pending is not None and now >= next_send:
                    universe = self._pending
                    self._pending = None
                    self._priority_consecutive_events = 0
                    if self._priority_queue:
                        self.stats.priority_burst_limit_hits += 1
            if universe is not None:
                (self._send_priority if priority_universe else self._send)(universe)
                if self._priority_current is None or self._priority_state == "idle":
                    self.stats.frames_submitted += 1
                    self.stats.output_rate_hz = self.rate_hz
                if self._priority_current is None and self._priority_state == "idle":
                    next_send = max(next_send, time.monotonic() + period)
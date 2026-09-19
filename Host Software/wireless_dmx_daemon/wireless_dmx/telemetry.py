"""Receiver telemetry storage and background request scheduling."""

from __future__ import annotations

import time
from dataclasses import replace
from threading import Lock

from .models import ReceiverLinkState, ReceiverTelemetry
from .transmitter.management import TelemetryReportPart


class TelemetryStore:
    def __init__(self, stale_seconds: float = 15, offline_seconds: float = 30) -> None:
        self.stale_seconds = stale_seconds
        self.offline_seconds = offline_seconds
        self._items: dict[int, tuple[ReceiverTelemetry, float]] = {}
        self._lock = Lock()

    def update(self, telemetry: ReceiverTelemetry) -> None:
        with self._lock:
            previous = self._items.get(telemetry.receiver_id)
            if previous is not None:
                previous_sequence = previous[0].telemetry_sequence
                if telemetry.telemetry_sequence == previous_sequence:
                    # The transmitter may be republishing a cached record;
                    # update displayed data but do not refresh liveness.
                    self._items[telemetry.receiver_id] = (telemetry, previous[1])
                    return
                if ((telemetry.telemetry_sequence - previous_sequence) & 0xFFFFFFFF) >= 0x80000000:
                    # Receiver firmware starts telemetrySequence at zero after
                    # reboot. A simultaneous uptime regression distinguishes
                    # that fresh boot from an old/out-of-order cached record.
                    if telemetry.uptime_seconds >= previous[0].uptime_seconds:
                        return
            self._items[telemetry.receiver_id] = (telemetry, time.monotonic())

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def update_report(self, parts: tuple[TelemetryReportPart, ...]) -> bool:
        """Publish one complete, internally consistent multipart report."""
        if not parts:
            return False
        first = parts[0]
        if (len(parts) != first.part_count or
                sorted(part.part_index for part in parts) != list(range(first.part_count)) or
                any(part.report_sequence != first.report_sequence for part in parts)):
            return False
        for part in parts:
            for telemetry in part.records:
                self.update(telemetry)
        return True

    def snapshot(self) -> tuple[ReceiverTelemetry, ...]:
        now = time.monotonic()
        result = []
        with self._lock:
            for telemetry, seen in self._items.values():
                age_ms = int((now - seen) * 1000)
                if age_ms / 1000 <= self.stale_seconds:
                    state = ReceiverLinkState.ONLINE
                elif age_ms / 1000 <= self.offline_seconds:
                    state = ReceiverLinkState.STALE
                else:
                    state = ReceiverLinkState.OFFLINE
                result.append(replace(telemetry, link_state=state, transmitter_last_seen_ms=age_ms))
        return tuple(sorted(result, key=lambda item: item.receiver_id))
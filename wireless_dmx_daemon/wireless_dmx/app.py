"""Application service coordinating adapters and frontend snapshots."""

from __future__ import annotations

import time
import logging
import random
from threading import Event, Thread, Lock

from .enttec.parser import EnttecParser
from .artnet import ArtNetListener, ArtNetParser
from .models import (DaemonConfig, DaemonHealth, DaemonSnapshot, DmxStatistics,
                      PriorityAck, PriorityAckSummary, PriorityStatus, TelemetryStatus)
from .pacer import DmxPacer
from .telemetry import TelemetryStore
from .transmitter.connection import TransmitterConnection
from .transmitter.management import (CacheClearedResponse, ManagementParser, PriorityAckReport,
                                     clear_receiver_cache_request, get_priority_acks_request, get_telemetry_request,
                                     mark_next_priority)
from .virtual_serial.linux_pty import LinuxPtyBackend


class NullVirtualBackend:
    """No-op backend used when virtual serial input is disabled."""

    path = ""
    client_connected = False
    master_fd = None

    def start(self) -> None:
        pass

    def read(self, size: int = 4096) -> bytes:
        return b""

    def stop(self) -> None:
        pass


class WirelessDmxService:
    def __init__(self, config: DaemonConfig, serial_factory=None, virtual_backend=None) -> None:
        config.validate()
        self.config = config
        self.stats = DmxStatistics()
        self.enttec = EnttecParser(stats=self.stats)
        self.telemetry = TelemetryStore(config.telemetry_stale_seconds, config.telemetry_offline_seconds)
        self.management = ManagementParser()
        self.virtual = virtual_backend or (LinuxPtyBackend(config.virtual_port_path)
                                           if config.virtual_serial_enabled else NullVirtualBackend())
        self.artnet_parser = ArtNetParser(config.artnet_universe, self.stats)
        self.artnet = ArtNetListener(config.artnet_bind_host, config.artnet_port, self.artnet_parser) \
            if config.artnet_enabled else None
        self.transmitter = TransmitterConnection(config, self._on_transmitter_data, serial_factory)
        self.pacer = DmxPacer(
            config.pacer_rate_hz, self._send_universe, self.stats,
            send_priority=self._send_priority_universe,
            on_priority_started=self._on_priority_started,
            on_priority_completed=self._on_priority_completed,
            priority_enabled=config.priority_enabled,
            priority_max_queue_depth=config.priority_max_queue_depth,
            priority_max_repeat_count=config.priority_max_repeat_count,
            priority_max_ttl_seconds=config.priority_max_ttl_seconds,
            priority_lead_in_ms=config.priority_lead_in_ms,
            priority_lead_out_ms=config.priority_lead_out_ms,
            priority_max_consecutive_events=config.priority_max_consecutive_events,
        )
        self.manual_universe = bytearray(512)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._health = DaemonHealth.STARTING
        self._last_error: str | None = None
        self._last_telemetry_request = 0.0
        self._last_ack_request = 0.0
        self._telemetry_request_started = 0.0
        self._telemetry_requests_sent = 0
        self._telemetry_reports_received = 0
        self._telemetry_consecutive_failures = 0
        self._telemetry_last_report = 0.0
        self._cache_clear_sent_at = 0.0
        self._cache_clear_acknowledged = False
        self._cache_clear_sent = 0
        self._cache_clear_retries = 0
        self._cache_clear_retry_interval = 0.5
        self._report_parts = {}
        self._report_part_times = {}
        self._priority_submissions: dict[int, float] = {}
        # One accepted ACK is valid per submitted event, receiver, and attempt.
        # Frame sequence is diagnostic only: repeated priority fragments/events
        # can legitimately carry different wireless frame sequences.
        self._priority_events: dict[int, dict] = {}
        # One ACK is retained per submitted event, receiver, and attempt.
        # Retry attempts are distinct evidence and must not be discarded as
        # duplicates of the initial attempt.
        self._priority_acks: dict[tuple[int, int, int], PriorityAck] = {}
        self._priority_ack_summary = PriorityAckSummary()
        self._priority_retry_attempts = 0
        self._priority_retry_recovered = 0
        self._priority_retry_failures = 0
        self._normal_quiet_until = 0.0
        self._priority_output_active = False
        self._priority_output_active = False
        self._logger = logging.getLogger("wireless_dmx.service")

    def set_manual_channel(self, channel: int, value: int) -> None:
        if not 1 <= channel <= 512:
            raise ValueError("channel must be 1..512")
        if not 0 <= value <= 255:
            raise ValueError("value must be 0..255")
        self.manual_universe[channel - 1] = value

    def set_manual_universe(self, universe: bytes) -> None:
        if len(universe) != 512:
            raise ValueError("manual universe must contain 512 channels")
        self.manual_universe[:] = universe

    def clear_manual_universe(self) -> None:
        self.manual_universe[:] = bytes(512)

    def manual_universe_snapshot(self) -> bytes:
        return bytes(self.manual_universe)

    def send_manual(self, priority: bool = False, repeat_count: int | None = None,
                    ttl_seconds: float | None = None, reason: str = "manual dashboard") -> int | None:
        universe = bytes(self.manual_universe)
        if priority:
            physical_repeat_count = repeat_count or self.config.priority_default_repeat_count
            self._normal_quiet_until = max(self._normal_quiet_until,
                time.monotonic() + self.config.priority_normal_quiet_before_ms / 1000.0)
            # The transmitter owns the three physical 1 Hz repeats. The daemon
            # submits one logical universe per attempt only.
            priority_id = self.pacer.submit_priority(
                universe,
                repeat_count=1,
                ttl_seconds=ttl_seconds or self.config.priority_default_ttl_seconds,
                reason=reason,
            )
            # The marker is deliberately queued ahead of the following
            # complete-universe DMX submission. Existing receivers ignore it.
            self._priority_submissions[priority_id] = time.monotonic()
            self._priority_events[priority_id] = {
                "universe": universe, "repeat_count": physical_repeat_count,
                "ttl_seconds": ttl_seconds or self.config.priority_default_ttl_seconds,
                "reason": reason, "attempt": 1, "last_attempt_at": time.monotonic(),
                "retry_count": 0, "terminal": False, "terminal_reason": None,
                "transmission_complete": False, "ack_complete": False,
                "first_attempt_ack_receivers": set(), "ack_receivers": set(),
                "submitted_at": time.monotonic(), "ack_completed_at": None,
                "expected_receivers": set(receiver.receiver_id for receiver in self.telemetry.snapshot()
                                           if receiver.link_state.value == "online"),
                "retry_due_at": None,
            }
            self.transmitter.send_immediate(mark_next_priority(
                priority_id, physical_repeat_count))
            return priority_id
        self.pacer.submit(universe)
        return None

    def clear_priority(self) -> None:
        self.pacer.clear_priority()

    def seed_priority_ids(self, seed: int) -> None:
        """Set the next priority ID before submitting any priority events."""
        with self.pacer._condition:
            if self.pacer._priority_queue or self.pacer._priority_current is not None:
                raise RuntimeError("cannot seed priority IDs while priority traffic is active")
            self.pacer._priority_id = seed & 0xFFFFFFFF

    def start(self) -> None:
        self.telemetry.clear()
        self.virtual.start()
        if self.artnet:
            self.artnet.start()
        self.transmitter.start()
        self._send_cache_clear()
        self.pacer.start()
        self._stop.clear()
        self._thread = Thread(target=self._run, name="wireless-dmx-service", daemon=True)
        self._thread.start()
        self._health = DaemonHealth.RUNNING
        self._logger.info("service_started")

    def stop(self) -> None:
        self._health = DaemonHealth.STOPPING
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.pacer.stop()
        self.transmitter.stop()
        if self.artnet:
            self.artnet.stop()
        self.virtual.stop()
        self._logger.info("service_stopped")

    def snapshot(self) -> DaemonSnapshot:
        stats = DmxStatistics(**self.stats.__dict__)
        virtual_path = self.virtual.path if getattr(self.virtual, "master_fd", None) is not None else None
        priority = self.pacer.priority_status()
        ack_summary = self._priority_ack_summary
        priority = PriorityStatus(**{**priority.__dict__,
            "ack_accepted": ack_summary.accepted_count,
            "ack_duplicates": ack_summary.duplicate_count,
            "ack_invalid": ack_summary.invalid_count,
            "ack_unknown": ack_summary.unknown_priority_count,
            "ack_duplicate_records": ack_summary.duplicate_record_count,
            "ack_dropped": ack_summary.dropped_count,
            "ack_window_failures": ack_summary.window_failure_count})
        priority = PriorityStatus(**{**priority.__dict__,
            "ack_records_received": ack_summary.records_received})
        priority = PriorityStatus(**{**priority.__dict__,
            "retry_attempts": self._priority_retry_attempts,
            "retry_recovered": self._priority_retry_recovered,
            "retry_failures": self._priority_retry_failures})
        return DaemonSnapshot(health=self._health, virtual_port=virtual_path,
                              transmitter_connected=self.transmitter.connected,
                              virtual_client_connected=self.virtual.client_connected,
                              dmx=stats, receivers=self.telemetry.snapshot(),
                               priority=priority,
                              telemetry=TelemetryStatus(
                                  enabled=self.config.telemetry_enabled,
                                  request_in_flight=self._telemetry_request_started > 0,
                                  requests_sent=self._telemetry_requests_sent,
                                  reports_received=self._telemetry_reports_received,
                                  consecutive_failures=self._telemetry_consecutive_failures,
                                  last_request_age_ms=(int((time.monotonic() - self._telemetry_request_started) * 1000)
                                                       if self._telemetry_request_started else None),
                                  last_report_age_ms=(int((time.monotonic() - self._telemetry_last_report) * 1000)
                                                       if self._telemetry_last_report else None),
                                  cache_clear_sent=self._cache_clear_sent,
                                  cache_clear_acknowledged=self._cache_clear_acknowledged,
                                  cache_clear_age_ms=(int((time.monotonic() - self._cache_clear_sent_at) * 1000)
                                                     if self._cache_clear_sent_at else None),
                                  cache_clear_retries=self._cache_clear_retries),
                              last_error=self._last_error)

    def _send_cache_clear(self) -> None:
        self.transmitter.send_immediate(clear_receiver_cache_request())
        self._cache_clear_sent += 1
        self._cache_clear_retries = max(0, self._cache_clear_sent - 1)
        self._cache_clear_sent_at = time.monotonic()
        self._logger.info("receiver_cache_clear_sent attempt=%s", self._cache_clear_sent)

    def _send_universe(self, universe: bytes) -> None:
        if self._priority_output_active or time.monotonic() < self._normal_quiet_until:
            self.stats.frames_dropped_by_pacer += 1
            return
        from .enttec.protocol import encode_dmx
        self.transmitter.send_latest(encode_dmx(universe))

    def _send_priority_universe(self, universe: bytes) -> None:
        from .enttec.protocol import encode_dmx
        self.transmitter.send_latest(encode_dmx(universe))

    def _on_priority_started(self) -> None:
        self._priority_output_active = True

    def _on_priority_completed(self) -> None:
        self._priority_output_active = False
        self._normal_quiet_until = max(self._normal_quiet_until,
            time.monotonic() + self.config.priority_normal_quiet_after_ms / 1000.0)

    def _accept_source_frame(self, universe: bytes, source: str) -> None:
        policy = self.config.input_source_policy
        if policy != "latest" and policy != source:
            self.stats.source_frames_rejected += 1
            return
        if source == "artnet":
            self.stats.artnet_source_frames += 1
        else:
            self.stats.serial_source_frames += 1
        if self.config.pacer_enabled:
            self.pacer.submit(universe)
        else:
            self._send_universe(universe)
            self.stats.frames_submitted += 1

    def _on_transmitter_data(self, data: bytes) -> None:
        for part in self.management.feed(data):
            if isinstance(part, CacheClearedResponse):
                self._cache_clear_acknowledged = True
                self.telemetry.clear()
                self._report_parts.clear()
                self._report_part_times.clear()
                self._logger.info("receiver_cache_cleared")
                continue
            if isinstance(part, PriorityAckReport):
                self._consume_priority_ack_report(part)
                continue
            report = self._report_parts.setdefault(part.report_sequence, {})
            report[part.part_index] = part
            self._report_part_times.setdefault(part.report_sequence, time.monotonic())
            if len(report) == part.part_count:
                if self.telemetry.update_report(tuple(report[index] for index in range(part.part_count))):
                    self._logger.info("telemetry_report_received sequence=%s parts=%s", part.report_sequence, part.part_count)
                    self._telemetry_reports_received += 1
                    self._telemetry_consecutive_failures = 0
                    self._telemetry_last_report = time.monotonic()
                    self._telemetry_request_started = 0.0
                del self._report_parts[part.report_sequence]
                del self._report_part_times[part.report_sequence]

    def _consume_priority_ack_report(self, report: PriorityAckReport) -> None:
        previous = self._priority_ack_summary
        duplicate_records = previous.duplicate_record_count
        unknown = previous.unknown_priority_count
        window_failures = previous.window_failure_count
        for raw in report.records:
            received = PriorityAck(**{**raw.__dict__, "received_monotonic": time.monotonic()})
            key = (received.priority_id, received.receiver_id, received.attempt)
            if key in self._priority_acks:
                duplicate_records += 1
                continue
            self._priority_acks[key] = received
            event = self._priority_events.get(received.priority_id)
            if event is not None and received.attempt > 1:
                event["recovered"] = True
                self._priority_retry_recovered += 1
            if event is not None:
                event.setdefault("ack_receivers", set()).add(received.receiver_id)
                if received.attempt == 1:
                    event.setdefault("first_attempt_ack_receivers", set()).add(received.receiver_id)
                expected = event["expected_receivers"]
                if expected and expected.issubset(event["ack_receivers"]):
                    event["ack_complete"] = True
                    event["ack_completed_at"] = event.get("ack_completed_at") or time.monotonic()
            submitted = self._priority_submissions.get(received.priority_id)
            if submitted is None:
                unknown += 1
            elif (received.ack_delay_ms != 0xFFFF and
                  received.ack_delay_ms > self.config.priority_confirmation_window_ms):
                window_failures += 1
        self._priority_ack_summary = PriorityAckSummary(
            accepted_count=report.accepted_count,
            duplicate_count=report.duplicate_count,
            invalid_count=report.invalid_count,
            dropped_count=report.dropped_count,
            records_received=sum(1 for _ in self._priority_acks),
            unknown_priority_count=unknown,
            duplicate_record_count=duplicate_records,
            window_failure_count=window_failures,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                incoming = self.virtual.read()
                if incoming:
                    for frame in self.enttec.feed(incoming):
                        self._accept_source_frame(frame.universe(), "serial")
                if self.artnet:
                    for frame in self.artnet.receive():
                        data = frame.data + bytes(512 - len(frame.data))
                        self._accept_source_frame(data, "artnet")
                now = time.monotonic()
                self._service_priority_retries(now)
                if not self._cache_clear_acknowledged:
                    if (now - self._cache_clear_sent_at >= self._cache_clear_retry_interval):
                        self._send_cache_clear()
                    # Do not poll telemetry or priority ACKs until the
                    # transmitter has confirmed that its receiver cache is
                    # empty. Otherwise the first report can be old cache data.
                    time.sleep(0.001)
                    continue
                for sequence, started in list(self._report_part_times.items()):
                    if now - started > self.config.telemetry_max_report_age_seconds:
                        self._report_parts.pop(sequence, None)
                        self._report_part_times.pop(sequence, None)
                if self.config.telemetry_enabled and now - self._last_telemetry_request >= self.config.telemetry_interval_seconds:
                    if (self._telemetry_request_started and
                            now - self._telemetry_request_started >= self.config.telemetry_response_timeout_seconds):
                        self._telemetry_consecutive_failures += 1
                        self._telemetry_request_started = 0.0
                    self.transmitter.send_immediate(get_telemetry_request())
                    self._last_telemetry_request = now
                    self._telemetry_request_started = now
                    self._telemetry_requests_sent += 1
                if now - self._last_ack_request >= 0.1:
                    self.transmitter.send_immediate(get_priority_acks_request())
                    self._last_ack_request = now
            except Exception as exc:
                self._last_error = str(exc)
                self._health = DaemonHealth.TELEMETRY_DEGRADED
            else:
                if not self.transmitter.connected:
                    self._health = DaemonHealth.TRANSMITTER_DISCONNECTED
                elif self._health in (DaemonHealth.TRANSMITTER_DISCONNECTED, DaemonHealth.TELEMETRY_DEGRADED):
                    self._health = DaemonHealth.RUNNING
            time.sleep(0.001)

    def _service_priority_retries(self, now: float) -> None:
        # The ACK delay is measured at the transmitter, but the daemon receives
        # the exported record on a later management poll and the pacer may have
        # queued a retry behind the current priority event. Give every attempt
        # one full confirmation window plus a bounded export/drain grace period.
        window = max(self.config.priority_confirmation_window_ms / 1000.0, 1.0)
        for priority_id, event in list(self._priority_events.items()):
            if event["terminal"] or now - event["last_attempt_at"] < window:
                continue
            expected = event["expected_receivers"]
            if not expected:
                expected.update(receiver.receiver_id for receiver in self.telemetry.snapshot()
                                if receiver.link_state.value == "online")
            received_ids = {key[1] for key in self._priority_acks if key[0] == priority_id}
            if expected and expected.issubset(received_ids):
                event["ack_complete"] = True
                event["transmission_complete"] = True
                event["terminal_reason"] = "ack_complete"
                event["terminal"] = True
                continue
            if event["retry_due_at"] is None:
                event["retry_due_at"] = now + random.uniform(
                    self.config.priority_retry_cooldown_min_seconds,
                    self.config.priority_retry_cooldown_max_seconds)
                continue
            if now < event["retry_due_at"]:
                continue
            if event["attempt"] < self.config.priority_max_attempts:
                with self.pacer._condition:
                    if self.pacer._priority_current is not None or self.pacer._priority_queue:
                        continue
                next_attempt = event["attempt"] + 1
                try:
                    self.pacer.submit_priority(event["universe"], 1,
                                               event["ttl_seconds"], event["reason"],
                                               priority_id=priority_id, attempt=next_attempt)
                    self.transmitter.send_immediate(mark_next_priority(
                        priority_id, event["repeat_count"], next_attempt))
                    event["attempt"] = next_attempt
                    event["retry_count"] += 1
                    event["last_attempt_at"] = now
                    event["retry_due_at"] = None
                    self._priority_retry_attempts += 1
                except (OverflowError, RuntimeError):
                    event["last_attempt_at"] = now
            else:
                if now - event["last_attempt_at"] >= window * 2.0:
                    event["transmission_complete"] = True
                    event["terminal_reason"] = "ack_timeout"
                    event["terminal"] = True
                    self._priority_retry_failures += 1
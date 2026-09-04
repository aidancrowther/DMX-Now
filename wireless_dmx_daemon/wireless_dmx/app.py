"""Application service coordinating adapters and frontend snapshots."""

from __future__ import annotations

import time
import logging
from threading import Event, Thread, Lock

from .enttec.parser import EnttecParser
from .models import DaemonConfig, DaemonHealth, DaemonSnapshot, DmxStatistics
from .pacer import DmxPacer
from .telemetry import TelemetryStore
from .transmitter.connection import TransmitterConnection
from .transmitter.management import ManagementParser, get_telemetry_request
from .virtual_serial.linux_pty import LinuxPtyBackend


class WirelessDmxService:
    def __init__(self, config: DaemonConfig, serial_factory=None, virtual_backend=None) -> None:
        config.validate()
        self.config = config
        self.stats = DmxStatistics()
        self.enttec = EnttecParser(stats=self.stats)
        self.telemetry = TelemetryStore(config.telemetry_stale_seconds, config.telemetry_offline_seconds)
        self.management = ManagementParser()
        self.virtual = virtual_backend or LinuxPtyBackend(config.virtual_port_path)
        self.transmitter = TransmitterConnection(config, self._on_transmitter_data, serial_factory)
        self.pacer = DmxPacer(config.pacer_rate_hz, self._send_universe, self.stats)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._health = DaemonHealth.STARTING
        self._last_error: str | None = None
        self._last_telemetry_request = 0.0
        self._report_parts = {}
        self._report_part_times = {}
        self._logger = logging.getLogger("wireless_dmx.service")

    def start(self) -> None:
        self.virtual.start()
        self.transmitter.start()
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
        self.virtual.stop()
        self._logger.info("service_stopped")

    def snapshot(self) -> DaemonSnapshot:
        stats = DmxStatistics(**self.stats.__dict__)
        return DaemonSnapshot(health=self._health, virtual_port=self.virtual.path if self.virtual.master_fd is not None else None,
                              transmitter_connected=self.transmitter.connected,
                              virtual_client_connected=self.virtual.client_connected,
                              dmx=stats, receivers=self.telemetry.snapshot(), last_error=self._last_error)

    def _send_universe(self, universe: bytes) -> None:
        from .enttec.protocol import encode_dmx
        self.transmitter.send_latest(encode_dmx(universe))

    def _on_transmitter_data(self, data: bytes) -> None:
        for part in self.management.feed(data):
            report = self._report_parts.setdefault(part.report_sequence, {})
            report[part.part_index] = part
            self._report_part_times.setdefault(part.report_sequence, time.monotonic())
            if len(report) == part.part_count:
                if self.telemetry.update_report(tuple(report[index] for index in range(part.part_count))):
                    self._logger.info("telemetry_report_received sequence=%s parts=%s", part.report_sequence, part.part_count)
                del self._report_parts[part.report_sequence]
                del self._report_part_times[part.report_sequence]

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                incoming = self.virtual.read()
                if incoming:
                    for frame in self.enttec.feed(incoming):
                        universe = frame.universe()
                        if self.config.pacer_enabled:
                            self.pacer.submit(universe)
                        else:
                            self._send_universe(universe)
                            self.stats.frames_submitted += 1
                now = time.monotonic()
                for sequence, started in list(self._report_part_times.items()):
                    if now - started > self.config.telemetry_max_report_age_seconds:
                        self._report_parts.pop(sequence, None)
                        self._report_part_times.pop(sequence, None)
                if self.config.telemetry_enabled and now - self._last_telemetry_request >= self.config.telemetry_interval_seconds:
                    self.transmitter.send_immediate(get_telemetry_request())
                    self._last_telemetry_request = now
            except Exception as exc:
                self._last_error = str(exc)
                self._health = DaemonHealth.TELEMETRY_DEGRADED
            else:
                if not self.transmitter.connected:
                    self._health = DaemonHealth.TRANSMITTER_DISCONNECTED
                elif self._health in (DaemonHealth.TRANSMITTER_DISCONNECTED, DaemonHealth.TELEMETRY_DEGRADED):
                    self._health = DaemonHealth.RUNNING
            time.sleep(0.001)
"""Core data models shared by the CLI, future GUI, and service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class ReceiverLinkState(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


class DaemonHealth(str, Enum):
    STARTING = "starting"
    READY = "ready"
    NO_VIRTUAL_CLIENT = "no_virtual_client"
    TRANSMITTER_DISCONNECTED = "transmitter_disconnected"
    TELEMETRY_DEGRADED = "telemetry_degraded"
    RUNNING = "running"
    STOPPING = "stopping"


@dataclass
class DmxStatistics:
    """Counters and rates for normalized ENTTEC DMX input and pacing."""

    bytes_received: int = 0
    frames_received: int = 0
    valid_dmx_frames: int = 0
    invalid_frames: int = 0
    unsupported_commands: int = 0
    frames_submitted: int = 0
    frames_dropped_by_pacer: int = 0
    input_rate_hz: float = 0.0
    output_rate_hz: float = 0.0
    last_frame_monotonic: Optional[float] = None
    artnet_packets: int = 0
    artnet_valid_frames: int = 0
    artnet_invalid_packets: int = 0
    artnet_source_frames: int = 0
    serial_source_frames: int = 0
    source_frames_rejected: int = 0


@dataclass(frozen=True)
class TelemetryStatus:
    enabled: bool = True
    request_in_flight: bool = False
    requests_sent: int = 0
    reports_received: int = 0
    consecutive_failures: int = 0
    last_request_age_ms: Optional[int] = None
    last_report_age_ms: Optional[int] = None


@dataclass(frozen=True)
class ReceiverTelemetry:
    """Normalized Feature 11 receiver state presented to frontends."""

    receiver_id: int
    mac_address: str
    link_state: ReceiverLinkState
    battery_low: bool
    transmitter_rssi: int
    receiver_last_rssi: int
    uptime_seconds: int
    last_active_sequence: int
    complete_universes: int
    incomplete_universes: int
    malformed_packets: int
    time_since_last_universe_ms: int
    transmitter_last_seen_ms: int
    firmware_version: int
    protocol_version: int
    telemetry_sequence: int


@dataclass(frozen=True)
class DaemonConfig:
    """Validated Phase 0 configuration contract.

    I/O adapters are added in later phases; keeping their settings here lets
    CLI and GUI layers share one configuration object from the beginning.
    """

    transmitter_device: str = "/dev/ttyUSB0"
    transmitter_baud: int = 115200
    transmitter_data_bits: int = 8
    transmitter_parity: str = "none"
    transmitter_stop_bits: int = 2
    pacer_enabled: bool = True
    pacer_rate_hz: float = 20.0
    pacer_maximum_rate_hz: float = 20.0
    allow_experimental_rates: bool = False
    telemetry_enabled: bool = True
    telemetry_interval_seconds: float = 10.0
    telemetry_response_timeout_seconds: float = 2.0
    telemetry_stale_seconds: float = 15.0
    telemetry_offline_seconds: float = 30.0
    virtual_port_path: str = "/tmp/wireless-dmx"
    telemetry_max_report_age_seconds: float = 5.0
    virtual_serial_enabled: bool = True
    artnet_enabled: bool = True
    artnet_bind_host: str = "0.0.0.0"
    artnet_port: int = 6454
    artnet_universe: int = 0
    input_source_policy: str = "latest"

    def validate(self) -> None:
        if not self.transmitter_device:
            raise ValueError("transmitter_device must not be empty")
        if self.transmitter_baud <= 0:
            raise ValueError("transmitter_baud must be positive")
        if self.transmitter_baud not in (300, 600, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
            raise ValueError("unsupported transmitter baud rate")
        if self.transmitter_data_bits not in (5, 6, 7, 8):
            raise ValueError("transmitter_data_bits must be 5, 6, 7, or 8")
        if self.transmitter_parity not in {"none", "even", "odd", "mark", "space"}:
            raise ValueError("unsupported transmitter parity")
        if self.transmitter_stop_bits not in (1, 2):
            raise ValueError("transmitter_stop_bits must be 1 or 2")
        if self.pacer_rate_hz <= 0 or self.pacer_maximum_rate_hz <= 0:
            raise ValueError("pacer rates must be positive")
        if self.pacer_rate_hz > self.pacer_maximum_rate_hz:
            raise ValueError("pacer_rate_hz cannot exceed pacer_maximum_rate_hz")
        if not self.allow_experimental_rates and self.pacer_maximum_rate_hz > 20.0:
            raise ValueError("rates above 20 Hz require allow_experimental_rates")
        if self.telemetry_interval_seconds <= 0 or self.telemetry_response_timeout_seconds <= 0:
            raise ValueError("telemetry intervals must be positive")
        if self.telemetry_stale_seconds <= 0 or self.telemetry_offline_seconds <= 0:
            raise ValueError("telemetry freshness thresholds must be positive")
        if self.telemetry_stale_seconds >= self.telemetry_offline_seconds:
            raise ValueError("stale threshold must be below offline threshold")
        if not self.virtual_port_path:
            if self.virtual_serial_enabled:
                raise ValueError("virtual_port_path must not be empty when virtual serial is enabled")
        if not self.virtual_serial_enabled and not self.artnet_enabled:
            raise ValueError("at least one DMX input must be enabled")
        if not self.artnet_bind_host:
            raise ValueError("artnet_bind_host must not be empty")
        if not 1 <= self.artnet_port <= 65535:
            raise ValueError("artnet_port must be between 1 and 65535")
        if not 0 <= self.artnet_universe <= 32767:
            raise ValueError("artnet_universe must be between 0 and 32767")
        if self.input_source_policy not in ("latest", "serial", "artnet"):
            raise ValueError("input_source_policy must be latest, serial, or artnet")
        if self.telemetry_max_report_age_seconds <= 0:
            raise ValueError("telemetry_max_report_age_seconds must be positive")


@dataclass(frozen=True)
class DaemonSnapshot:
    """Immutable state snapshot intended for CLI and future GUI consumers."""

    health: DaemonHealth = DaemonHealth.STARTING
    virtual_port: Optional[str] = None
    transmitter_connected: bool = False
    virtual_client_connected: bool = False
    dmx: DmxStatistics = field(default_factory=DmxStatistics)
    receivers: Tuple[ReceiverTelemetry, ...] = ()
    telemetry: TelemetryStatus = field(default_factory=TelemetryStatus)
    last_error: Optional[str] = None
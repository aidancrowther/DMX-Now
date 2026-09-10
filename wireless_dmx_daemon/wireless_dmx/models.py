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


class ChannelGate(str, Enum):
    OPEN = "open"
    MANAGEMENT_ONLY = "management_only"
    LOCKED = "locked"


class ReceiverFailsafeMode(str, Enum):
    HOLD = "hold"
    BLACKOUT = "blackout"
    DISABLE_LINE = "disable_line"


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
    serial_channels_blocked: int = 0
    artnet_channels_blocked: int = 0
    management_channels_rejected: int = 0
    channel_gate_changes: int = 0
    priority_received: int = 0
    priority_queued: int = 0
    priority_frames_submitted: int = 0
    priority_completed: int = 0
    priority_expired: int = 0
    priority_cancelled: int = 0
    priority_rejected_queue_full: int = 0
    priority_burst_limit_hits: int = 0
    normal_frames_during_priority: int = 0
    priority_queue_depth: int = 0


@dataclass(frozen=True)
class PriorityStatus:
    enabled: bool = True
    state: str = "idle"
    queue_depth: int = 0
    queue_capacity: int = 4
    priority_id: int | None = None
    reason: str = ""
    attempt: int = 0
    repeat_index: int = 0
    repeat_count: int = 0
    confirmed_receivers: int = 0
    known_receivers: int = 0
    last_result: str = ""
    ack_accepted: int = 0
    ack_duplicates: int = 0
    ack_invalid: int = 0
    ack_unknown: int = 0
    ack_duplicate_records: int = 0
    ack_dropped: int = 0
    ack_window_failures: int = 0
    ack_records_received: int = 0
    retry_attempts: int = 0
    retry_recovered: int = 0
    retry_failures: int = 0


@dataclass(frozen=True)
class PriorityAck:
    priority_id: int
    receiver_id: int
    frame_sequence: int
    attempt: int
    completion_status: int
    attempts_observed: int
    last_rssi: int
    received_at_ms: int
    ack_delay_ms: int
    received_monotonic: float


PRIORITY_COMPLETE_GATE_APPLIED = 5


@dataclass(frozen=True)
class PriorityAckSummary:
    accepted_count: int = 0
    duplicate_count: int = 0
    invalid_count: int = 0
    dropped_count: int = 0
    records_received: int = 0
    unknown_priority_count: int = 0
    duplicate_record_count: int = 0
    window_failure_count: int = 0


@dataclass(frozen=True)
class TelemetryStatus:
    enabled: bool = True
    request_in_flight: bool = False
    requests_sent: int = 0
    reports_received: int = 0
    consecutive_failures: int = 0
    last_request_age_ms: Optional[int] = None
    last_report_age_ms: Optional[int] = None
    cache_clear_sent: int = 0
    cache_clear_acknowledged: bool = False
    cache_clear_age_ms: Optional[int] = None
    cache_clear_retries: int = 0


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
    failsafe_mode: str = "hold"
    failsafe_active: bool = False
    failsafe_timeout_seconds: int = 60
    failsafe_generation: int = 0
    failsafe_activations: int = 0


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
    priority_enabled: bool = True
    priority_max_queue_depth: int = 4
    priority_default_repeat_count: int = 3
    priority_max_repeat_count: int = 10
    priority_default_ttl_seconds: float = 2.0
    priority_max_ttl_seconds: float = 5.0
    # The transmitter parses management markers from the same UART as ENTTEC
    # data. Allow its byte-wise parser time to consume MARK_NEXT_PRIORITY before
    # the priority universe is emitted.
    priority_lead_in_ms: int = 500
    priority_lead_out_ms: int = 500
    priority_confirmation_window_ms: int = 1500
    priority_max_attempts: int = 5
    priority_receiver_budget_seconds: float = 4.0
    priority_retry_cooldown_min_seconds: float = 1.0
    priority_retry_cooldown_max_seconds: float = 2.5
    priority_normal_quiet_before_ms: int = 500
    priority_normal_quiet_after_ms: int = 1000
    priority_max_consecutive_events: int = 3
    management_only_channels: tuple[int, ...] = ()
    locked_channels: tuple[int, ...] = ()
    receiver_failsafe_mode: ReceiverFailsafeMode = ReceiverFailsafeMode.HOLD
    receiver_failsafe_timeout_seconds: int = 60

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
        for name, channels in (("management_only_channels", self.management_only_channels),
                               ("locked_channels", self.locked_channels)):
            if len(set(channels)) != len(channels) or any(not 1 <= channel <= 512 for channel in channels):
                raise ValueError(f"{name} must contain unique channels from 1 through 512")
        if set(self.management_only_channels) & set(self.locked_channels):
            raise ValueError("channel gate lists must not overlap")
        try:
            ReceiverFailsafeMode(self.receiver_failsafe_mode)
        except ValueError as exc:
            raise ValueError("receiver_failsafe_mode must be hold, blackout, or disable_line") from exc
        if not 30 <= self.receiver_failsafe_timeout_seconds <= 3600:
            raise ValueError("receiver_failsafe_timeout_seconds must be between 30 and 3600")
        if self.priority_max_queue_depth < 1:
            raise ValueError("priority_max_queue_depth must be positive")
        if not 1 <= self.priority_default_repeat_count <= self.priority_max_repeat_count:
            raise ValueError("invalid priority repeat count defaults")
        if self.priority_max_repeat_count > 255:
            raise ValueError("priority_max_repeat_count must be <= 255")
        if self.priority_default_ttl_seconds <= 0 or self.priority_max_ttl_seconds <= 0:
            raise ValueError("priority TTL values must be positive")
        if self.priority_default_ttl_seconds > self.priority_max_ttl_seconds:
            raise ValueError("priority default TTL cannot exceed maximum TTL")
        if self.priority_lead_in_ms < 500:
            raise ValueError("priority lead-in must be at least 500 ms")
        if self.priority_lead_out_ms < 500:
            raise ValueError("priority lead-out must be at least 500 ms")
        if self.priority_confirmation_window_ms < 1500:
            raise ValueError("priority confirmation window must be at least 1500 ms")
        if self.priority_normal_quiet_before_ms < 500:
            raise ValueError("normal quiet-before must be at least 500 ms")
        if self.priority_normal_quiet_after_ms < 1000:
            raise ValueError("normal quiet-after must be at least 1000 ms")
        if self.priority_max_consecutive_events < 1:
            raise ValueError("priority_max_consecutive_events must be positive")
        if not 1 <= self.priority_max_attempts <= 255:
            raise ValueError("priority_max_attempts must be between 1 and 255")
        if self.priority_receiver_budget_seconds < 4.0:
            raise ValueError("priority receiver budget must be at least 4 seconds")
        if self.priority_retry_cooldown_min_seconds < 0:
            raise ValueError("priority_retry_cooldown_min_seconds must not be negative")
        if self.priority_retry_cooldown_max_seconds < self.priority_retry_cooldown_min_seconds:
            raise ValueError("priority retry cooldown maximum must not be below minimum")
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
    priority: PriorityStatus = field(default_factory=PriorityStatus)
    last_error: Optional[str] = None
"""Editable configuration field model shared by terminal and future GUIs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import save_config
from .models import DaemonConfig

EDITABLE_FIELDS = (
    ("Transmitter device", "transmitter_device", str),
    ("Transmitter baud", "transmitter_baud", int),
    ("Virtual serial enabled", "virtual_serial_enabled", bool),
    ("Virtual port path", "virtual_port_path", str),
    ("Raw DMX serial enabled", "raw_virtual_serial_enabled", bool),
    ("Raw DMX port path", "raw_virtual_port_path", str),
    ("Raw DMX timeout seconds", "raw_virtual_timeout_seconds", float),
    ("Art-Net enabled", "artnet_enabled", bool),
    ("Art-Net UDP port", "artnet_port", int),
    ("Art-Net universe", "artnet_universe", int),
    ("Art-Net bind host", "artnet_bind_host", str),
    ("Input source policy", "input_source_policy", str),
    ("Pacer enabled", "pacer_enabled", bool),
    ("Pacer rate Hz", "pacer_rate_hz", float),
    ("Telemetry enabled", "telemetry_enabled", bool),
    ("Telemetry interval seconds", "telemetry_interval_seconds", float),
    ("Priority enabled", "priority_enabled", bool),
    ("Priority queue depth", "priority_max_queue_depth", int),
    ("Priority repeat count", "priority_default_repeat_count", int),
    ("Priority default TTL seconds", "priority_default_ttl_seconds", float),
    ("Priority lead-in ms", "priority_lead_in_ms", int),
    ("Priority lead-out ms", "priority_lead_out_ms", int),
    ("Priority confirmation window ms", "priority_confirmation_window_ms", int),
    ("Priority max consecutive events", "priority_max_consecutive_events", int),
    ("Receiver fail-safe mode", "receiver_failsafe_mode", str),
    ("Receiver fail-safe timeout seconds", "receiver_failsafe_timeout_seconds", int),
)


def field_value(config: DaemonConfig, index: int) -> str:
    _, name, _ = EDITABLE_FIELDS[index]
    return str(getattr(config, name))


def update_field(config: DaemonConfig, index: int, text: str) -> DaemonConfig:
    _, name, converter = EDITABLE_FIELDS[index]
    if converter is bool:
        normalized = text.strip().lower()
        if normalized not in ("true", "false", "yes", "no", "1", "0"):
            raise ValueError("boolean value must be true or false")
        value = normalized in ("true", "yes", "1")
    else:
        value = converter(text.strip())
    result = replace(config, **{name: value})
    result.validate()
    return result


def save_edited_config(config: DaemonConfig, path: str) -> None:
    save_config(config, path)


def receiver_name(config: DaemonConfig, receiver_id: int) -> str:
    return dict(config.receiver_names).get(receiver_id, "")


def set_receiver_name(config: DaemonConfig, receiver_id: int, name: str) -> DaemonConfig:
    names = dict(config.receiver_names)
    cleaned = name.strip()
    if cleaned:
        names[receiver_id] = cleaned
    else:
        names.pop(receiver_id, None)
    result = replace(config, receiver_names=tuple(sorted(names.items())))
    result.validate()
    return result
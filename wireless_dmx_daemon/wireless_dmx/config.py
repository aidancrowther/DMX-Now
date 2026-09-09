"""TOML configuration loading and CLI override helpers."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import fields, replace
import os
import tempfile
from pathlib import Path

from .models import DaemonConfig


DEFAULT_CONFIG_PATH = "default.conf"


def load_config(path: str | None = None) -> DaemonConfig:
    if path is None:
        candidates = (DEFAULT_CONFIG_PATH, str(Path(__file__).resolve().parents[1] / DEFAULT_CONFIG_PATH))
        path = next((candidate for candidate in candidates if os.path.exists(candidate)), None)
    values = {}
    if path:
        with Path(path).open("rb") as stream:
            data = tomllib.load(stream)
        transmitter = data.get("transmitter", {})
        values.update({"transmitter_" + key: value for key, value in transmitter.items()})
        values.update({"pacer_" + key: value for key, value in data.get("pacer", {}).items()})
        values.update({"telemetry_" + key: value for key, value in data.get("telemetry", {}).items()})
        values.update({"virtual_port_path": data.get("virtual_port", {}).get("requested_path", "/tmp/wireless-dmx")})
        values.update({"virtual_serial_enabled": data.get("virtual_port", {}).get("enabled", True)})
        values.update({"artnet_" + key: value for key, value in data.get("artnet", {}).items()})
        values.update({"input_source_policy": data.get("input", {}).get("source_policy", "latest")})
        values.update({"priority_" + key: value for key, value in data.get("priority", {}).items()})
        gates = data.get("channel_gates", {})
        values["management_only_channels"] = tuple(gates.get("management_only", ()))
        values["locked_channels"] = tuple(gates.get("locked", ()))
    aliases = {"device": "transmitter_device", "baud": "transmitter_baud",
               "data_bits": "transmitter_data_bits", "parity": "transmitter_parity",
               "stop_bits": "transmitter_stop_bits", "rate": "pacer_rate_hz",
               "telemetry_interval": "telemetry_interval_seconds"}
    values = {aliases.get(k, k): v for k, v in values.items()}
    allowed = {f.name for f in fields(DaemonConfig)}
    return DaemonConfig(**{k: v for k, v in values.items() if k in allowed})


def save_config(config: DaemonConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    """Atomically write validated configuration as TOML."""
    config.validate()
    sections = {
        "virtual_port": {"enabled": config.virtual_serial_enabled, "requested_path": config.virtual_port_path},
        "transmitter": {"device": config.transmitter_device, "baud": config.transmitter_baud,
                         "data_bits": config.transmitter_data_bits, "parity": config.transmitter_parity,
                         "stop_bits": config.transmitter_stop_bits},
        "pacer": {"enabled": config.pacer_enabled, "rate_hz": config.pacer_rate_hz,
                   "maximum_rate_hz": config.pacer_maximum_rate_hz,
                   "allow_experimental_rates": config.allow_experimental_rates},
        "artnet": {"enabled": config.artnet_enabled, "bind_host": config.artnet_bind_host,
                    "port": config.artnet_port, "universe": config.artnet_universe},
        "input": {"source_policy": config.input_source_policy},
        "priority": {"enabled": config.priority_enabled, "max_queue_depth": config.priority_max_queue_depth,
                      "default_repeat_count": config.priority_default_repeat_count,
                      "max_repeat_count": config.priority_max_repeat_count,
                      "default_ttl_seconds": config.priority_default_ttl_seconds,
                      "max_ttl_seconds": config.priority_max_ttl_seconds,
                      "lead_in_ms": config.priority_lead_in_ms,
                      "lead_out_ms": config.priority_lead_out_ms,
                      "confirmation_window_ms": config.priority_confirmation_window_ms,
                      "max_attempts": config.priority_max_attempts,
                      "receiver_budget_seconds": config.priority_receiver_budget_seconds,
                      "retry_cooldown_min_seconds": config.priority_retry_cooldown_min_seconds,
                      "retry_cooldown_max_seconds": config.priority_retry_cooldown_max_seconds,
                      "normal_quiet_before_ms": config.priority_normal_quiet_before_ms,
                      "normal_quiet_after_ms": config.priority_normal_quiet_after_ms,
                      "max_consecutive_events": config.priority_max_consecutive_events},
        "telemetry": {"enabled": config.telemetry_enabled, "interval_seconds": config.telemetry_interval_seconds,
                       "response_timeout_seconds": config.telemetry_response_timeout_seconds,
                       "stale_seconds": config.telemetry_stale_seconds,
                       "offline_seconds": config.telemetry_offline_seconds,
                       "max_report_age_seconds": config.telemetry_max_report_age_seconds},
        "channel_gates": {"management_only": list(config.management_only_channels),
                          "locked": list(config.locked_channels)},
    }
    lines = ["# Wireless DMX daemon configuration\n"]
    for section, values in sections.items():
        lines.append(f"[{section}]\n")
        for key, value in values.items():
            if isinstance(value, bool): rendered = "true" if value else "false"
            elif isinstance(value, str): rendered = '"' + value.replace('"', '\\"') + '"'
            else: rendered = str(value)
            lines.append(f"{key} = {rendered}\n")
        lines.append("\n")
    target = os.path.abspath(path)
    directory = os.path.dirname(target) or "."
    fd, temporary = tempfile.mkstemp(prefix=".wireless-dmx-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.writelines(lines)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def apply_args(config: DaemonConfig, args: argparse.Namespace) -> DaemonConfig:
    updates = {}
    for arg, field_name in (("transmitter", "transmitter_device"), ("baud", "transmitter_baud"),
                            ("rate", "pacer_rate_hz"), ("virtual_port", "virtual_port_path"),
                            ("telemetry_interval", "telemetry_interval_seconds")):
        value = getattr(args, arg, None)
        if value is not None:
            updates[field_name] = value
    if getattr(args, "allow_experimental_rates", False):
        updates["allow_experimental_rates"] = True
        updates["pacer_maximum_rate_hz"] = max(config.pacer_maximum_rate_hz, config.pacer_rate_hz)
    result = replace(config, **updates)
    result.validate()
    return result
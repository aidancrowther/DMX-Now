"""TOML configuration loading and CLI override helpers."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import fields, replace
import os
import tempfile
from pathlib import Path

from .models import DaemonConfig, ReceiverFailsafeMode


DEFAULT_CONFIG_PATH = "default.conf"
CONFIG_DIRECTORY = Path(__file__).resolve().parents[1] / "configs"


def available_config_paths(directory: str = ".") -> tuple[str, ...]:
    """Return selectable TOML/config files in a directory, with default first."""
    paths = {str(path) for path in Path(directory).glob("*.conf")}
    paths.update(str(path) for path in Path(directory).glob("*.toml"))
    default = str(Path(directory) / DEFAULT_CONFIG_PATH)
    return tuple(sorted(paths, key=lambda path: (path != default, path)))


def last_config_path(directory: str | Path = CONFIG_DIRECTORY) -> str | None:
    marker = Path(directory) / ".last_config"
    try:
        candidate = Path(marker.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeError):
        candidate = None
    if candidate is not None:
        if not candidate.is_absolute():
            candidate = Path(directory) / candidate
        if candidate.exists() and candidate.is_file() and candidate.name not in ("default.conf", "config.example.toml"):
            return str(candidate)
    if Path(directory).is_dir():
        writable = [path for path in Path(directory).iterdir()
                    if path.is_file() and path.suffix in (".conf", ".toml")
                    and path.name not in ("default.conf", "config.example.toml")]
        if writable:
            return str(max(writable, key=lambda path: path.stat().st_mtime))
    return None


def remember_config_path(path: str, directory: str | Path = CONFIG_DIRECTORY) -> None:
    target = Path(path).expanduser().resolve()
    config_dir = Path(directory).resolve()
    if target.name in ("default.conf", "config.example.toml"):
        return
    try:
        target.relative_to(config_dir)
    except ValueError:
        return
    config_dir.mkdir(parents=True, exist_ok=True)
    temporary = config_dir / ".last_config.tmp"
    temporary.write_text(str(target), encoding="utf-8")
    temporary.replace(config_dir / ".last_config")


def load_config(path: str | None = None) -> DaemonConfig:
    if path is None:
        candidates = (DEFAULT_CONFIG_PATH, str(CONFIG_DIRECTORY / DEFAULT_CONFIG_PATH),
                      str(Path(__file__).resolve().parents[1] / DEFAULT_CONFIG_PATH))
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
        raw_port = data.get("raw_virtual_port", {})
        values["raw_virtual_serial_enabled"] = raw_port.get("enabled", False)
        values["raw_virtual_port_path"] = raw_port.get("requested_path", "/tmp/wireless-dmx-raw")
        values["raw_virtual_timeout_seconds"] = raw_port.get("timeout_seconds", 1.0)
        values.update({"artnet_" + key: value for key, value in data.get("artnet", {}).items()})
        values.update({"input_source_policy": data.get("input", {}).get("source_policy", "latest")})
        values.update({"priority_" + key: value for key, value in data.get("priority", {}).items()})
        gates = data.get("channel_gates", {})
        values["management_only_channels"] = tuple(gates.get("management_only", ()))
        values["locked_channels"] = tuple(gates.get("locked", ()))
        failsafe = data.get("receiver_failsafe", {})
        values["receiver_failsafe_mode"] = ReceiverFailsafeMode(failsafe.get("mode", "hold"))
        values["receiver_failsafe_timeout_seconds"] = failsafe.get("timeout_seconds", 60)
        names = data.get("receiver_names", {})
        values["receiver_names"] = tuple(
            (int(str(receiver_id), 16), str(name))
            for receiver_id, name in names.items()
        )
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
        "raw_virtual_port": {"enabled": config.raw_virtual_serial_enabled,
                              "requested_path": config.raw_virtual_port_path,
                              "timeout_seconds": config.raw_virtual_timeout_seconds},
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
        "receiver_failsafe": {"mode": getattr(config.receiver_failsafe_mode, "value", config.receiver_failsafe_mode),
                               "timeout_seconds": config.receiver_failsafe_timeout_seconds},
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
    if config.receiver_names:
        lines.append("[receiver_names]\n")
        for receiver_id, name in sorted(config.receiver_names):
            escaped = name.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'"{receiver_id:08X}" = "{escaped}"\n')
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
    for arg, field_name in (("raw_dmx_enabled", "raw_virtual_serial_enabled"),
                            ("raw_dmx_port", "raw_virtual_port_path"),
                            ("raw_dmx_timeout", "raw_virtual_timeout_seconds")):
        value = getattr(args, arg, None)
        if value is not None:
            updates[field_name] = value
    if getattr(args, "allow_experimental_rates", False):
        updates["allow_experimental_rates"] = True
        updates["pacer_maximum_rate_hz"] = max(config.pacer_maximum_rate_hz, config.pacer_rate_hz)
    result = replace(config, **updates)
    result.validate()
    return result
"""TOML configuration loading and CLI override helpers."""

from __future__ import annotations

import argparse
import tomllib
from dataclasses import fields, replace
from pathlib import Path

from .models import DaemonConfig


def load_config(path: str | None = None) -> DaemonConfig:
    values = {}
    if path:
        with Path(path).open("rb") as stream:
            data = tomllib.load(stream)
        transmitter = data.get("transmitter", {})
        values.update({"transmitter_" + key: value for key, value in transmitter.items()})
        values.update({"pacer_" + key: value for key, value in data.get("pacer", {}).items()})
        values.update({"telemetry_" + key: value for key, value in data.get("telemetry", {}).items()})
        values.update({"virtual_port_path": data.get("virtual_port", {}).get("requested_path", "/tmp/wireless-dmx")})
    aliases = {"device": "transmitter_device", "baud": "transmitter_baud",
               "data_bits": "transmitter_data_bits", "parity": "transmitter_parity",
               "stop_bits": "transmitter_stop_bits", "rate": "pacer_rate_hz",
               "telemetry_interval": "telemetry_interval_seconds"}
    values = {aliases.get(k, k): v for k, v in values.items()}
    allowed = {f.name for f in fields(DaemonConfig)}
    return DaemonConfig(**{k: v for k, v in values.items() if k in allowed})


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
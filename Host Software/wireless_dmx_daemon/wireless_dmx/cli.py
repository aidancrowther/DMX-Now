"""Command-line frontend."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict

from .app import WirelessDmxService
from .config import apply_args, load_config
from .logging_setup import configure_logging


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="dmx-now",
        description="DMX Now host daemon and receiver-management interface.",
    )
    root.add_argument("--config", help="TOML/config file; defaults to the selected/default configuration")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "receivers", "stats"):
        command = sub.add_parser(name, help={
            "run": "run the daemon until interrupted",
            "status": "start briefly and print a full status snapshot",
            "receivers": "start briefly and print receiver telemetry",
            "stats": "start briefly and print DMX statistics",
        }[name])
        command.add_argument("--transmitter", help="management transmitter serial device")
        command.add_argument("--baud", type=int, help="management transmitter UART baud rate")
        command.add_argument("--rate", type=float, help="normal DMX wireless pacing rate in Hz")
        command.add_argument("--virtual-port", help="requested ENTTEC-compatible PTY path")
        command.add_argument("--raw-dmx-enabled", action=argparse.BooleanOptionalAction, default=None,
                             help="enable or disable the raw 512-byte DMX PTY")
        command.add_argument("--raw-dmx-port", help="requested raw-DMX PTY path")
        command.add_argument("--raw-dmx-timeout", type=float, help="incomplete raw-DMX burst timeout in seconds")
        command.add_argument("--telemetry-interval", type=float, help="receiver telemetry polling interval in seconds")
        command.add_argument("--allow-experimental-rates", action="store_true",
                             help="allow configured pacer ceilings above the validated 20 Hz rate")
        mode = command.add_mutually_exclusive_group()
        mode.add_argument("--management-only", action="store_true",
                          help="disable normal DMX inputs/output; retain management and priority traffic")
        mode.add_argument("--bridge-mode", action="store_true",
                          help="enable normal DMX bridge behavior for this invocation")
    sub.add_parser("version", help="print the daemon version")
    check = sub.add_parser("config-check", help="validate and print a configuration without starting hardware")
    check.add_argument("--config", help="TOML/config file to validate")
    return root


def _service(args) -> WirelessDmxService:
    config = apply_args(load_config(args.config), args)
    return WirelessDmxService(config)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.command == "version":
        print("DMX Now 0.1.0")
        return 0
    if args.command == "config-check":
        config = load_config(args.config)
        config.validate()
        print(json.dumps(asdict(config), indent=2))
        return 0
    configure_logging("INFO")
    service = _service(args)
    if args.command == "run":
        service.start()
        if service.config.virtual_serial_enabled:
            print(f"Virtual ENTTEC port: {service.virtual.path}", flush=True)
        if service.config.raw_virtual_serial_enabled:
            print(f"Virtual raw DMX port: {service.raw_virtual.path}", flush=True)
        try:
            while True:
                time.sleep(1)
                if service.snapshot().health.value != "running":
                    print(json.dumps(service.snapshot(), default=str), flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            service.stop()
        return 0
    # One-shot status commands briefly start the same service used by `run`,
    # allowing them to query the physical transmitter and recent telemetry.
    service.start()
    try:
        time.sleep(max(0.1, min(30.0, service.config.telemetry_response_timeout_seconds)))
        snapshot = service.snapshot()
        if args.command == "receivers":
            print(json.dumps([asdict(r) for r in snapshot.receivers], default=str, indent=2))
        elif args.command == "stats":
            print(json.dumps(asdict(snapshot.dmx), indent=2))
        else:
            print(json.dumps(asdict(snapshot), default=str, indent=2))
    finally:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
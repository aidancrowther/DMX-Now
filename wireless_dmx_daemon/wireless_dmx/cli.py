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
    root = argparse.ArgumentParser(prog="dmx-now")
    root.add_argument("--config")
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "receivers", "stats"):
        command = sub.add_parser(name)
        command.add_argument("--transmitter")
        command.add_argument("--baud", type=int)
        command.add_argument("--rate", type=float)
        command.add_argument("--virtual-port")
        command.add_argument("--telemetry-interval", type=float)
        command.add_argument("--allow-experimental-rates", action="store_true")
    sub.add_parser("version")
    check = sub.add_parser("config-check")
    check.add_argument("--config")
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
        print(f"Virtual ENTTEC port: {service.virtual.path}", flush=True)
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
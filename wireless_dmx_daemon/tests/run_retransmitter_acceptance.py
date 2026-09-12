#!/usr/bin/env python3
"""Finite live acceptance runner for the retransmitter Mega harness.

This script is intentionally not run by the repository validation workflow.
It opens real serial devices only when explicitly invoked after the operator
has completed wiring and flashing. It drives the Mega command port and runs
the daemon in management-only mode, leaving normal DMX authority with the
physical re-transmitter.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wireless_dmx.app import WirelessDmxService
from wireless_dmx.models import DaemonConfig, DaemonMode
from wireless_dmx.receiver_diagnostic import ReceiverDiagnosticParser


def wait_line(port: serial.Serial, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            print("MEGA " + line, flush=True)
            if line.startswith(prefix):
                return line
    raise TimeoutError(f"waiting for {prefix!r}")


def command(port: serial.Serial, text: str, prefix: str = "ACK", timeout: float = 8.0) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return wait_line(port, prefix, timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", required=True, help="management transmitter USB serial port")
    parser.add_argument("--mega-port", required=True, help="Mega USB command/result port")
    parser.add_argument("--receiver-port", required=True, help="diagnostic receiver USB serial port")
    parser.add_argument("--receiver-baud", type=int, default=115200)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--pattern", choices=("const", "ramp"), default="const")
    parser.add_argument("--value", type=int, default=77)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 <= args.value <= 255 or args.seconds <= 0:
        parser.error("value must be 0..255 and seconds must be positive")

    frame_command = f"GENERATE {'CONST' if args.pattern == 'const' else 'RAMP'} {args.value}"
    summary: dict[str, object] = {"passed": False, "seconds": args.seconds,
                                  "pattern": args.pattern, "value": args.value}
    mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
    receiver = serial.Serial(args.receiver_port, args.receiver_baud, timeout=0.05)
    diagnostic = ReceiverDiagnosticParser()
    records = []
    service = WirelessDmxService(DaemonConfig(
        transmitter_device=args.tx_port,
        mode=DaemonMode.MANAGEMENT_ONLY,
        virtual_serial_enabled=False,
        raw_virtual_serial_enabled=False,
        artnet_enabled=False,
        virtual_port_path="",
        telemetry_interval_seconds=1.0,
    ))
    try:
        wait_line(mega, "READY RETRANSMITTER_E2E_MEGA", 10)
        command(mega, frame_command, "ACK GENERATE")
        service.start()
        command(mega, f"START 3 {args.seconds}", "ACK START")
        deadline = time.monotonic() + args.seconds + 15
        result = None
        while time.monotonic() < deadline:
            data = receiver.read(4096)
            if data:
                records.extend(diagnostic.feed(data))
            line = mega.readline().decode(errors="replace").strip()
            if line:
                print("MEGA " + line, flush=True)
                if line.startswith("RESULT "):
                    result = line
                    break
        if result is None:
            raise TimeoutError("waiting for Mega RESULT")
        values: dict[str, int] = {}
        for token in result.split()[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                values[key] = int(value.rstrip("ms"))
        summary["result"] = values
        summary["diagnostic_records"] = len(records)
        summary["diagnostic_bad_crc"] = diagnostic.records_bad_crc
        summary["diagnostic_unknown_type"] = diagnostic.records_unknown_type
        expected = (bytes([args.value]) * 512 if args.pattern == "const" else
                    bytes((args.value + index) & 0xFF for index in range(512)))
        summary["diagnostic_matching_records"] = sum(
            record.record_type == 1 and record.universe == expected for record in records)
        summary["transmitter_connected"] = service.snapshot().transmitter_connected
        summary["passed"] = (summary["diagnostic_matching_records"] > 0 and
                              diagnostic.records_bad_crc == 0 and
                              service.snapshot().transmitter_connected)
        print(json.dumps(summary, indent=2, default=str), flush=True)
        if args.output:
            args.output.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        return 0 if summary["passed"] else 1
    finally:
        service.stop()
        mega.close()
        receiver.close()


if __name__ == "__main__":
    raise SystemExit(main())
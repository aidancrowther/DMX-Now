#!/usr/bin/env python3
"""Bounded Feature 8 production soak runner.

The test sends a distinctive full universe to the production transmitter and
measures the wired DMX output on the Mega for the requested duration. STATUS
polls provide a liveness check while the Mega is recording. Only the TX and
Mega ports are opened; no receiver programming port is used.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import serial

from enttec_protocol import dmx_frame


def wait_for(port: serial.Serial, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            seen.append(line)
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-10:]!r}")


def command(mega: serial.Serial, text: str, prefix: str, timeout: float = 5.0) -> str:
    mega.write((text + "\n").encode())
    mega.flush()
    return wait_for(mega, prefix, timeout)


def result_fields(line: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = int(value.rstrip("ms"))
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--status-period", type=float, default=30.0)
    args = parser.parse_args()
    if args.seconds < 60 or args.seconds > 7200:
        parser.error("--seconds must be between 60 and 7200")
    if args.status_period < 5 or args.status_period > 300:
        parser.error("--status-period must be between 5 and 300 seconds")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "tx_port": args.tx_port,
        "mega_port": args.mega_port,
        "seconds_requested": args.seconds,
        "status_period": args.status_period,
        "passed": False,
        "status_polls": [],
    }
    ramp_base = 0x17
    ramp = bytes((ramp_base + i) & 255 for i in range(512))

    try:
        with serial.Serial(args.tx_port, 57600, bytesize=8,
                           parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                           timeout=0.2) as tx, serial.Serial(args.mega_port, 115200,
                                                             timeout=0.2) as mega:
            tx.reset_input_buffer()
            tx.reset_output_buffer()
            mega.reset_input_buffer()
            time.sleep(1.0)

            command(mega, f"EXPECT RAMP {ramp_base}", "ACK EXPECT")
            tx.write(dmx_frame(ramp))
            tx.flush()
            command(mega, f"START 5 {args.seconds}", "ACK START")

            measurement_start = time.monotonic()
            deadline = measurement_start + args.seconds + 12.0
            next_status = measurement_start + args.status_period
            result_line: str | None = None
            while time.monotonic() < deadline:
                now = time.monotonic()
                # Do not issue a STATUS command during the final five seconds
                # of the measurement. The monitor may emit RESULT at the same
                # boundary; waiting for STATUS there could consume RESULT and
                # make the harness report a false timeout.
                if (now >= next_status and
                        now < measurement_start + args.seconds - 5.0):
                    status = command(mega, "STATUS", "STATUS ", timeout=5.0)
                    summary["status_polls"].append({
                        "elapsed_seconds": round(now - measurement_start, 1),
                        "line": status,
                    })
                    if "state=2" not in status:
                        raise RuntimeError(f"monitor left measurement state: {status}")
                    next_status += args.status_period
                # Always perform a short blocking read. Relying on
                # `in_waiting` can miss a line at the USB/driver boundary.
                line = mega.readline().decode(errors="replace").strip()
                if line.startswith("RESULT "):
                    result_line = line
                    break

            if result_line is None:
                # The Mega may need a few loop iterations to finish its final
                # DMX snapshot and emit RESULT at the measurement boundary.
                # Keep this bounded, but do not turn a delayed USB line into a
                # false soak failure.
                result_line = wait_for(mega, "RESULT ", 15.0)
            summary["result"] = result_line
            fields = result_fields(result_line)
            # The Mega reports integer seconds using elapsed milliseconds / 1000;
            # a run ending a few milliseconds after the boundary can therefore
            # legitimately print requested_seconds - 1. The host-side hard
            # timeout and the STATUS poll sequence still enforce the full run.
            summary["passed"] = (
                fields.get("seconds", 0) >= args.seconds - 1
                and fields.get("checks", 0) > 0
                and fields.get("fail", -1) == 0
            )
    except Exception as exc:
        summary["error"] = repr(exc)

    (args.run_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
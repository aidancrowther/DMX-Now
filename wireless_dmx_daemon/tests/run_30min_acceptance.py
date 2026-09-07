#!/usr/bin/env python3
"""End-to-end 30-minute daemon acceptance test using the real Mega monitor.

This runner is intentionally outside the package test suite because it uses
real serial devices. It opens the daemon's Linux PTY as a lighting client,
streams a stable full-universe ENTTEC ramp at 20 Hz, and verifies the receiver
output using the Arduino Mega on its USB serial port.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wireless_dmx.app import WirelessDmxService
from wireless_dmx.enttec.protocol import encode_dmx
from wireless_dmx.models import DaemonConfig
from wireless_dmx.virtual_serial.linux_pty import LinuxPtyBackend


def wait_line(port: serial.Serial, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            seen.append(line)
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-10:]!r}")


def send_mega_command(port: serial.Serial, text: str, prefix: str, timeout: float = 5.0) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return wait_line(port, prefix, timeout)


def parse_mega_result(line: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            values[key] = int(value.rstrip("ms"))
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--telemetry-interval", type=float, default=15.0)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 1800:
        parser.error("--seconds must be at least 1800")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.run_dir / "manifest.json"
    telemetry_path = args.run_dir / "daemon_telemetry.jsonl"
    progress_path = args.run_dir / "progress.jsonl"
    requested_path = f"/tmp/wireless-dmx-acceptance-{os.getpid()}"
    try:
        os.unlink(requested_path)
    except FileNotFoundError:
        pass

    summary: dict[str, object] = {
        "tx_port": args.tx_port,
        "mega_port": args.mega_port,
        "seconds_requested": args.seconds,
        "dmx_hz_requested": 20.0,
        "telemetry_interval_seconds": args.telemetry_interval,
        "passed": False,
    }
    service: WirelessDmxService | None = None
    client: serial.Serial | None = None
    mega: serial.Serial | None = None
    tx_times: list[float] = []
    telemetry_reports = 0
    telemetry_records = 0
    telemetry_log = telemetry_path.open("w", encoding="utf-8")
    progress_log = progress_path.open("w", encoding="utf-8")
    started = time.monotonic()

    try:
        config = DaemonConfig(
            transmitter_device=args.tx_port,
            virtual_port_path=requested_path,
            pacer_enabled=True,
            pacer_rate_hz=20.0,
            telemetry_enabled=True,
            telemetry_interval_seconds=args.telemetry_interval,
        )
        service = WirelessDmxService(config)
        service.start()

        mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
        mega.reset_input_buffer()
        send_mega_command(mega, "EXPECT RAMP 23", "ACK EXPECT")
        send_mega_command(mega, f"START 5 {args.seconds}", "ACK START")

        # Opening the PTY with pyserial exercises the same VCP-like client path
        # a lighting application will use. The baud is client-side configuration;
        # the PTY itself remains transparent.
        client = serial.Serial(service.virtual.path, 115200, bytesize=8,
                               parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                               timeout=0.1)
        frame = encode_dmx(bytes((0x17 + i) & 255 for i in range(512)))
        next_frame = time.monotonic()
        next_progress = next_frame + 30.0
        deadline = next_frame + args.seconds

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_frame:
                client.write(frame)
                tx_times.append(time.monotonic())
                next_frame += 0.05
                if next_frame < now - 1.0:
                    next_frame = now + 0.05

            snapshot = service.snapshot()
            # Record every newly visible receiver report in a compact JSONL
            # stream. The receiver telemetry itself is already normalized by
            # the daemon; this is not text emitted by the transmitter UART.
            current_records = len(snapshot.receivers)
            if current_records:
                telemetry_records = max(telemetry_records, current_records)
            if now >= next_progress:
                progress = {
                    "elapsed_seconds": round(now - started, 1),
                    "daemon_health": snapshot.health.value,
                    "transmitter_connected": snapshot.transmitter_connected,
                    "virtual_client_connected": snapshot.virtual_client_connected,
                    "dmx_valid_frames": snapshot.dmx.valid_dmx_frames,
                    "dmx_submitted": snapshot.dmx.frames_submitted,
                    "dmx_dropped": snapshot.dmx.frames_dropped_by_pacer,
                    "receivers": current_records,
                    "receiver_states": [r.link_state.value for r in snapshot.receivers],
                }
                progress_log.write(json.dumps(progress) + "\n")
                progress_log.flush()
                telemetry_log.write(json.dumps({
                    "elapsed_seconds": progress["elapsed_seconds"],
                    "receivers": [r.__dict__ for r in snapshot.receivers],
                }, default=str) + "\n")
                telemetry_log.flush()
                print("PROGRESS " + json.dumps(progress), flush=True)
                next_progress += 30.0

            time.sleep(0.001)

        result_line = wait_line(mega, "RESULT ", 20.0)
        mega_result = parse_mega_result(result_line)
        intervals = [b - a for a, b in zip(tx_times, tx_times[1:])]
        report_count = len(service.snapshot().receivers)
        summary.update({
            "dmx_frames_submitted_to_pty": len(tx_times),
            "dmx_input_rate_hz": len(tx_times) / args.seconds,
            "dmx_interval_mean_ms": (sum(intervals) / len(intervals) * 1000
                                      if intervals else None),
            "dmx_interval_max_ms": (max(intervals) * 1000 if intervals else None),
            "daemon_snapshot": {
                "valid_dmx_frames": service.snapshot().dmx.valid_dmx_frames,
                "frames_submitted": service.snapshot().dmx.frames_submitted,
                "frames_dropped": service.snapshot().dmx.frames_dropped_by_pacer,
                "receiver_count": report_count,
            },
            "telemetry_records_seen": telemetry_records,
            "mega_result": mega_result,
        })
        summary["passed"] = bool(
            len(tx_times) >= int(args.seconds * 20 * 0.95) and
            service.snapshot().dmx.valid_dmx_frames >= int(args.seconds * 20 * 0.95) and
            report_count > 0 and
            mega_result.get("seconds", 0) >= args.seconds - 1 and
            mega_result.get("checks", 0) > 0 and
            mega_result.get("fail", -1) == 0
        )
    except Exception as exc:
        summary["error"] = repr(exc)
    finally:
        if client is not None:
            client.close()
        if service is not None:
            service.stop()
        if mega is not None:
            mega.close()
        telemetry_log.close()
        progress_log.close()
        if os.path.islink(requested_path):
            os.unlink(requested_path)
        manifest_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
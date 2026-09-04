#!/usr/bin/env python3
"""Feature 11 extended 20 Hz DMX + telemetry hardware soak.

The transmitter receives continuous 512-slot ENTTEC frames at 115200 8N2 on
the TX port. The Mega monitor receives the receiver's wired DMX output on its
DMX input and reports the measured result on its USB serial port. Telemetry is
decoded on the host and written to telemetry.jsonl; transmitter text logging is
intentionally not enabled because it would corrupt the ENTTEC UART stream.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Testing/feature8/tools"))
sys.path.insert(0, str(ROOT / "Testing/feature11/tools"))
from enttec_protocol import dmx_frame
from test_telemetry import extract_frames, parse_frame, request


def wait_line(port: serial.Serial, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"timed out waiting for {prefix!r}")


def send_command(port: serial.Serial, text: str, prefix: str) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return wait_line(port, prefix, 5.0)


def parse_result(line: str) -> dict[str, int]:
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
    parser.add_argument("--seconds", type=int, default=660)
    parser.add_argument("--dmx-hz", type=float, default=20.0)
    parser.add_argument("--telemetry-interval", type=float, default=15.0)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 601:
        parser.error("--seconds must be greater than 10 minutes")
    if args.dmx_hz != 20.0:
        parser.error("this acceptance test is fixed at 20 Hz")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    telemetry_log = args.run_dir / "telemetry.jsonl"
    ramp_base = 0x17
    started = time.monotonic()
    tx_times: list[float] = []
    request_times: list[float] = []
    response_latencies: list[float] = []
    parsed_parts = []
    bad_responses: list[str] = []
    completed_sequences: set[int] = set()
    request_count = 0
    buffer = bytearray()

    with telemetry_log.open("w", encoding="utf-8") as log:
        try:
            with serial.Serial(args.tx_port, 115200, bytesize=8,
                               parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                               timeout=0.01) as tx, serial.Serial(args.mega_port, 115200,
                                                                  timeout=0.1) as mega:
                tx.reset_input_buffer()
                tx.reset_output_buffer()
                mega.reset_input_buffer()
                time.sleep(1.0)

                send_command(mega, f"EXPECT RAMP {ramp_base}", "ACK EXPECT")
                tx.write(dmx_frame(bytes((ramp_base + i) & 255 for i in range(512))))
                tx.flush()
                send_command(mega, f"START 5 {args.seconds}", "ACK START")

                next_dmx = time.monotonic()
                next_request = next_dmx + args.telemetry_interval
                deadline = next_dmx + args.seconds
                while time.monotonic() < deadline:
                    now = time.monotonic()
                    if now >= next_dmx:
                        # Keep the expected universe stable so the Mega can
                        # validate every physical DMX frame. The host-side
                        # write count independently verifies 20 Hz input.
                        tx.write(dmx_frame(bytes((ramp_base + i) & 255 for i in range(512))))
                        tx_times.append(time.monotonic())
                        next_dmx += 1.0 / args.dmx_hz
                        if next_dmx < now - 1.0:
                            next_dmx = now + 1.0 / args.dmx_hz

                    if now >= next_request:
                        request_count += 1
                        request_times.append(time.monotonic())
                        tx.write(request())
                        tx.flush()
                        next_request += args.telemetry_interval
                        if next_request < now:
                            next_request = now + args.telemetry_interval

                    chunk = tx.read(tx.in_waiting or 1)
                    if chunk:
                        buffer.extend(chunk)
                        for raw in extract_frames(buffer):
                            received_at = time.monotonic()
                            try:
                                part = parse_frame(raw)
                                parsed_parts.append(part)
                                sequence = part[2]
                                parts = [p for p in parsed_parts if p[2] == sequence]
                                if (sequence not in completed_sequences and
                                        len(parts) == part[1] and
                                        sorted(p[0] for p in parts) == list(range(part[1]))):
                                    completed_sequences.add(sequence)
                                    latency = None
                                    if request_times:
                                        latency = (received_at - request_times.pop(0)) * 1000.0
                                        response_latencies.append(latency / 1000.0)
                                    records = [record for p in parts for record in p[3]]
                                    event = {
                                        "elapsed_seconds": round(received_at - started, 3),
                                        "report_sequence": sequence,
                                        "parts": part[1],
                                        "records": records,
                                        "latency_ms": round(latency, 3) if latency is not None else None,
                                    }
                                    log.write(json.dumps(event) + "\n")
                                    log.flush()
                                    print("TELEMETRY " + json.dumps(event), flush=True)
                            except ValueError as exc:
                                bad_responses.append(str(exc))
                    time.sleep(0.001)

                # Allow the Mega to emit RESULT after its measurement boundary.
                result_line = wait_line(mega, "RESULT ", 15.0)
                monitor = parse_result(result_line)
        except Exception as exc:
            summary = {"passed": False, "error": repr(exc)}
        else:
            report_sequences = {p[2] for p in parsed_parts}
            complete_reports = 0
            receiver_counts: list[int] = []
            for sequence in report_sequences:
                parts = [p for p in parsed_parts if p[2] == sequence]
                if (len(parts) == parts[0][1] and
                        sorted(p[0] for p in parts) == list(range(parts[0][1]))):
                    complete_reports += 1
                    receiver_counts.append(sum(len(p[3]) for p in parts))
            intervals = [b - a for a, b in zip(tx_times, tx_times[1:])]
            summary = {
                "tx_port": args.tx_port,
                "mega_port": args.mega_port,
                "seconds_requested": args.seconds,
                "dmx_hz_requested": args.dmx_hz,
                "telemetry_interval_seconds": args.telemetry_interval,
                "dmx_frames_written": len(tx_times),
                "dmx_write_rate_hz": len(tx_times) / args.seconds,
                "dmx_interval_mean_ms": statistics.mean(intervals) * 1000 if intervals else None,
                "dmx_interval_max_ms": max(intervals) * 1000 if intervals else None,
                "telemetry_requests": request_count,
                "telemetry_complete_reports": complete_reports,
                "telemetry_success_percent": 100.0 * complete_reports / request_count if request_count else 0.0,
                "telemetry_latency_mean_ms": statistics.mean(response_latencies) * 1000 if response_latencies else None,
                "telemetry_latency_max_ms": max(response_latencies) * 1000 if response_latencies else None,
                "telemetry_records_seen": max(receiver_counts) if receiver_counts else 0,
                "telemetry_bad_responses": bad_responses,
                "mega_result": monitor,
            }
            expected_frames = int(args.seconds * args.dmx_hz * 0.95)
            summary["passed"] = bool(
                len(tx_times) >= expected_frames and
                complete_reports == request_count and
                summary["telemetry_records_seen"] > 0 and
                not bad_responses and
                monitor.get("seconds", 0) >= args.seconds - 1 and
                monitor.get("checks", 0) > 0 and
                monitor.get("fail", -1) == 0
            )

    (args.run_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
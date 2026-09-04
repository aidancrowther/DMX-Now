#!/usr/bin/env python3
"""Feature 11 DMX/telemetry coexistence soak test.

Streams full 512-slot ENTTEC frames while occasionally requesting receiver
telemetry from the same transmitter UART. The test measures management response
success/latency and the actual cadence of serial DMX writes. It does not require
a DMX monitor, although the receiver should be powered and listening.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--seconds", type=float, default=180.0)
    parser.add_argument("--dmx-hz", type=float, default=10.0)
    parser.add_argument("--request-interval", type=float, default=10.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.seconds <= 0 or args.dmx_hz <= 0 or args.request_interval <= 0:
        parser.error("seconds, dmx-hz, and request-interval must be positive")

    dmx = dmx_frame(bytes(512))
    tx_times: list[float] = []
    request_times: list[float] = []
    response_latencies: list[float] = []
    responses = []
    completed_sequences: set[int] = set()
    bad_responses = []
    buffer = bytearray()
    next_dmx = time.monotonic()
    next_request = next_dmx
    deadline = next_dmx + args.seconds
    request_number = 0

    try:
        with serial.Serial(args.tx_port, 115200, bytesize=8,
                           parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                           timeout=0.02) as tx:
            tx.reset_input_buffer()
            tx.reset_output_buffer()
            while time.monotonic() < deadline:
                now = time.monotonic()
                if now >= next_dmx:
                    tx.write(dmx)
                    tx_times.append(time.monotonic())
                    next_dmx += 1.0 / args.dmx_hz
                    if next_dmx < now - 1.0:
                        next_dmx = now + 1.0 / args.dmx_hz

                if now >= next_request:
                    request_number += 1
                    request_times.append(time.monotonic())
                    tx.write(request())
                    tx.flush()
                    next_request += args.request_interval
                    if next_request < now:
                        next_request = now + args.request_interval

                chunk = tx.read(tx.in_waiting or 1)
                if chunk:
                    buffer.extend(chunk)
                    for raw_frame in extract_frames(buffer):
                        received_at = time.monotonic()
                        try:
                            parsed = parse_frame(raw_frame)
                            responses.append(parsed)
                            sequence = parsed[2]
                            report_parts = [p for p in responses if p[2] == sequence]
                            if (sequence not in completed_sequences and
                                    len(report_parts) == parsed[1] and
                                    sorted(p[0] for p in report_parts) == list(range(parsed[1]))):
                                completed_sequences.add(sequence)
                                if request_times:
                                    response_latencies.append(received_at - request_times.pop(0))
                        except ValueError as exc:
                            bad_responses.append(str(exc))

                sleep_for = min(0.002, max(0.0, min(next_dmx, next_request) - time.monotonic()))
                if sleep_for:
                    time.sleep(sleep_for)
    except Exception as exc:
        print(f"FAIL: serial communication: {exc}", file=sys.stderr)
        return 1

    intervals = [b - a for a, b in zip(tx_times, tx_times[1:])]
    expected_requests = request_number
    # A response is successful only when every part of that report arrived.
    report_sequences = {p[2] for p in responses}
    complete_reports = 0
    receiver_counts = []
    for sequence in report_sequences:
        parts = [p for p in responses if p[2] == sequence]
        if len(parts) == parts[0][1] and sorted(p[0] for p in parts) == list(range(parts[0][1])):
            complete_reports += 1
            receiver_counts.append(sum(len(p[3]) for p in parts))
    result = {
        "tx_port": args.tx_port,
        "seconds": args.seconds,
        "dmx_hz_requested": args.dmx_hz,
        "request_interval": args.request_interval,
        "dmx_frames_written": len(tx_times),
        "dmx_write_rate_hz": len(tx_times) / args.seconds,
        "dmx_interval_mean_ms": statistics.mean(intervals) * 1000 if intervals else None,
        "dmx_interval_max_ms": max(intervals) * 1000 if intervals else None,
        "telemetry_requests": expected_requests,
        "telemetry_complete_reports": complete_reports,
        "telemetry_success_percent": (100.0 * complete_reports / expected_requests
                                        if expected_requests else 0.0),
        "telemetry_latency_mean_ms": statistics.mean(response_latencies) * 1000
        if response_latencies else None,
        "telemetry_latency_max_ms": max(response_latencies) * 1000
        if response_latencies else None,
        "telemetry_records_seen": max(receiver_counts) if receiver_counts else 0,
        "bad_responses": bad_responses,
    }
    # The transmitter's serial output is not a DMX acknowledgement channel, so
    # this test treats write cadence and complete telemetry reports separately.
    result["passed"] = bool(
        complete_reports == expected_requests and
        result["telemetry_records_seen"] > 0 and
        not bad_responses and
        len(tx_times) >= int(args.seconds * args.dmx_hz * 0.95)
    )

    print(json.dumps(result, indent=2))
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
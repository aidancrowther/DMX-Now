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
        if port.in_waiting:
            line = port.readline().decode(errors="replace").strip()
            if line:
                print("MEGA " + line, flush=True)
                if line.startswith(prefix):
                    return line
        time.sleep(0.005)
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
    parser.add_argument("--receiver-baud", type=int, default=460800)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--pattern", choices=("const", "ramp", "dynamic", "short"), default="dynamic")
    parser.add_argument("--value", type=int, default=77)
    parser.add_argument("--slots", type=int, default=512,
                        help="physical DMX slot count for short pattern")
    parser.add_argument("--accept-partial", action="store_true",
                        help="expect the retransmitter partial-universe build")
    parser.add_argument("--change-ms", type=int, default=1000,
                        help="dynamic generator epoch interval in milliseconds")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (not 0 <= args.value <= 255 or args.seconds <= 0 or
            args.change_ms < 100 or args.change_ms > 60000 or
            not 1 <= args.slots <= 512):
        parser.error("value 0..255, positive seconds, change-ms 100..60000, slots 1..512")

    frame_command = (f"GENERATE DYNAMIC {args.value} {args.change_ms}"
                     if args.pattern == "dynamic" else
                     f"GENERATE SHORT {args.slots} {args.value}"
                     if args.pattern == "short" else
                     f"GENERATE {'CONST' if args.pattern == 'const' else 'RAMP'} {args.value}")
    summary: dict[str, object] = {"passed": False, "seconds": args.seconds,
                                  "pattern": args.pattern, "value": args.value,
                                  "change_ms": args.change_ms}
    baseline_expected = bytes([args.value]) * 512
    mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
    receiver = serial.Serial(args.receiver_port, args.receiver_baud, timeout=0.05)
    diagnostic = ReceiverDiagnosticParser()
    records = []
    baseline_records = []
    service = WirelessDmxService(DaemonConfig(
        transmitter_device=args.tx_port,
        mode=DaemonMode.MANAGEMENT_ONLY,
        virtual_serial_enabled=False,
        raw_virtual_serial_enabled=False,
        artnet_enabled=False,
        virtual_port_path="",
        # Snapshot sampling below never sends a request; the service retains the
        # normal 10-second management telemetry cadence.
        telemetry_interval_seconds=10.0,
    ))
    try:
        wait_line(mega, "READY RETRANSMITTER_E2E_MEGA", 10)
        if args.pattern == "short":
            # Establish a known full-universe baseline before changing the
            # physical source length. This is required to distinguish strict
            # retention from an absent diagnostic record.
            command(mega, f"GENERATE CONST {args.value}", "ACK GENERATE")
        else:
            command(mega, frame_command, "ACK GENERATE")
        service.start()
        if args.pattern == "short":
            command(mega, "START 3 5", "ACK START")
            baseline_deadline = time.monotonic() + 20
            baseline_result_seen = False
            while time.monotonic() < baseline_deadline:
                data = receiver.read(4096)
                if data:
                    baseline_records.extend(diagnostic.feed(data))
                if mega.in_waiting:
                    line = mega.readline().decode(errors="replace").strip()
                    if line.startswith("RESULT "):
                        baseline_result_seen = True
                if (baseline_result_seen and
                        any(record.record_type == 1 and record.universe == baseline_expected
                            for record in baseline_records)):
                    break
            if not any(record.record_type == 1 and record.universe == baseline_expected
                       for record in baseline_records):
                raise TimeoutError("waiting for baseline diagnostic universe")
            # Discard baseline observations and parser alignment state. The
            # following short phase owns the verdict for this invocation.
            records = []
            diagnostic = ReceiverDiagnosticParser()
            command(mega, frame_command, "ACK GENERATE")
        command(mega, f"START 3 {args.seconds}", "ACK START")
        deadline = time.monotonic() + args.seconds + 15
        settle_until = time.monotonic() + 3.0
        result = None
        telemetry_samples = []
        measurement_started_at = time.monotonic()
        next_sample_at = measurement_started_at
        content_ready = False
        diagnostic_bad_crc_at_content_ready = 0
        diagnostic_unknown_at_content_ready = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            data = receiver.read(4096)
            if data:
                received_records = diagnostic.feed(data)
                # Ignore receiver output from the explicit START settle period.
                # It may still contain the prior universe or the receiver's
                # boot-time zero universe; only promotions during measurement
                # belong to this run's content verdict.
                if now >= settle_until:
                    for received in received_records:
                        if received.record_type != 1:
                            continue
                        epoch = received.universe[0]
                        valid = all(value == (epoch if index == 0 else
                                              (args.value + index - 1) & 0xFF)
                                    for index, value in enumerate(received.universe))
                        # Establish the content window on the first valid
                        # dynamic promotion. This avoids treating a final
                        # pre-source/boot universe as a failure at the settle
                        # boundary, while every later promotion is strict.
                        if not content_ready and args.pattern == "dynamic" and valid:
                            content_ready = True
                            diagnostic_bad_crc_at_content_ready = diagnostic.records_bad_crc
                            diagnostic_unknown_at_content_ready = diagnostic.records_unknown_type
                        if content_ready or args.pattern != "dynamic":
                            records.append(received)
            if mega.in_waiting:
                line = mega.readline().decode(errors="replace").strip()
                if line:
                    print("MEGA " + line, flush=True)
                    if line.startswith("RESULT "):
                        result = line
                        break
            if now >= next_sample_at:
                snapshot = service.snapshot()
                telemetry_samples.append({
                    "elapsed_seconds": round(now - measurement_started_at, 3),
                    "health": snapshot.health.value,
                    "transmitter_connected": snapshot.transmitter_connected,
                    "transmitter_mode": snapshot.transmitter_mode,
                    "transmitter_mode_sync": snapshot.transmitter_mode_sync,
                    "last_error": snapshot.last_error,
                    "requests_sent": snapshot.telemetry.requests_sent,
                    "reports_received": snapshot.telemetry.reports_received,
                    "consecutive_failures": snapshot.telemetry.consecutive_failures,
                    "receivers": [{
                        "id": item.receiver_id,
                        "link_state": item.link_state.value,
                        "telemetry_sequence": item.telemetry_sequence,
                        "complete_universes": item.complete_universes,
                        "incomplete_universes": item.incomplete_universes,
                        "last_seen_ms": item.transmitter_last_seen_ms,
                    } for item in snapshot.receivers],
                })
                next_sample_at += 1.0
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
        summary["diagnostic_bad_crc_after_content_ready"] = max(
            0, diagnostic.records_bad_crc - diagnostic_bad_crc_at_content_ready)
        summary["diagnostic_unknown_after_content_ready"] = max(
            0, diagnostic.records_unknown_type - diagnostic_unknown_at_content_ready)
        summary["telemetry_samples"] = telemetry_samples
        expected = (bytes([args.value]) * 512 if args.pattern == "const" else
                    bytes((args.value + index) & 0xFF for index in range(512)))
        if args.pattern == "short":
            expected = bytes((args.value + index) & 0xFF for index in range(args.slots)) + bytes(512 - args.slots)
        if args.pattern == "dynamic":
            summary["diagnostic_matching_records"] = sum(
                record.record_type == 1 and
                all(value == (record.universe[0] if index == 0 else
                              (args.value + index - 1) & 0xFF)
                    for index, value in enumerate(record.universe))
                for record in records)
        else:
            summary["diagnostic_matching_records"] = sum(
                record.record_type == 1 and record.universe == expected for record in records)
        if args.pattern == "dynamic":
            invalid_dynamic = []
            invalid_examples = []
            for record in records:
                if record.record_type != 1:
                    continue
                epoch = record.universe[0]
                mismatches = [(index + 1, value, epoch if index == 0 else
                               (args.value + index - 1) & 0xFF)
                              for index, value in enumerate(record.universe)
                              if value != (epoch if index == 0 else
                                           (args.value + index - 1) & 0xFF)]
                if mismatches:
                    invalid_dynamic.append(record.sequence)
                    if len(invalid_examples) < 10:
                        invalid_examples.append({"sequence": record.sequence,
                                                 "epoch": epoch,
                                                 "mismatches": mismatches[:10]})
            summary["diagnostic_invalid_records"] = invalid_dynamic
            summary["diagnostic_invalid_examples"] = invalid_examples
        elif args.pattern == "short":
            short_matches = sum(record.record_type == 1 and record.universe == expected
                                for record in records)
            short_promotions = sum(record.record_type == 1 and
                                    record.universe[:args.slots] == expected[:args.slots] and
                                    record.universe[args.slots:] == bytes(512 - args.slots)
                                    for record in records)
            summary["diagnostic_matching_records"] = short_matches
            summary["diagnostic_normal_records"] = sum(record.record_type == 1 for record in records)
            summary["diagnostic_short_promotions"] = short_promotions
            summary["diagnostic_invalid_records"] = []
            # A strict image must retain the prior complete universe rather
            # than promote the short source frame. A partial image must produce
            # the exact requested prefix and a zero-filled tail.
            summary["short_expectation_met"] = (
                short_promotions > 0 if args.accept_partial else short_promotions == 0)
            summary["baseline_normal_records"] = sum(record.record_type == 1
                                                      for record in baseline_records)
            summary["baseline_complete_matches"] = sum(
                record.record_type == 1 and record.universe == baseline_expected
                for record in baseline_records)
        else:
            summary["diagnostic_invalid_records"] = []
            summary["short_expectation_met"] = True
        summary["telemetry_requests_sent"] = telemetry_samples[-1]["requests_sent"] if telemetry_samples else 0
        summary["telemetry_reports_received"] = telemetry_samples[-1]["reports_received"] if telemetry_samples else 0
        summary["telemetry_bad_samples"] = [sample for sample in telemetry_samples
                                             if not sample["transmitter_connected"] or
                                             sample["transmitter_mode"] != "management_only" or
                                             sample["transmitter_mode_sync"] != "synchronized" or
                                             sample["last_error"]]
        summary["telemetry_progressed"] = summary["telemetry_reports_received"] > 0
        summary["transmitter_connected"] = service.snapshot().transmitter_connected
        content_records_present = ((summary["baseline_complete_matches"] > 0 and
                                    summary["diagnostic_normal_records"] >= 0)
                                   if args.pattern == "short" else
                                    summary["diagnostic_matching_records"] > 0)
        summary["passed"] = (content_records_present and
                              summary["diagnostic_bad_crc_after_content_ready"] == 0 and
                              summary["diagnostic_unknown_after_content_ready"] == 0 and
                              not summary["diagnostic_invalid_records"] and
                              service.snapshot().transmitter_connected and
                              summary["telemetry_progressed"] and
                              not summary["telemetry_bad_samples"] and
                              summary.get("short_expectation_met", True))
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
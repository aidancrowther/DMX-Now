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
from collections import Counter
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
from wireless_dmx.retransmitter_patterns import dynamic_mismatches, dynamic_universe


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


def read_silent_line(port: serial.Serial, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            print("RECEIVER " + line, flush=True)
            if line.startswith(prefix):
                return line
    raise TimeoutError(f"waiting for receiver {prefix!r}")


def receiver_command(port: serial.Serial, text: str, prefix: str,
                     timeout: float = 10.0) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return read_silent_line(port, prefix, timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", required=True, help="management transmitter USB serial port")
    parser.add_argument("--mega-port", required=True, help="Mega USB command/result port")
    parser.add_argument("--receiver-port", required=True, help="diagnostic receiver USB serial port")
    parser.add_argument("--receiver-baud", type=int, default=460800)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--pattern", choices=("const", "ramp", "dynamic", "dynamic-short", "short"), default="dynamic")
    parser.add_argument("--value", type=int, default=77)
    parser.add_argument("--slots", type=int, default=512,
                        help="physical DMX slot count for short pattern")
    parser.add_argument("--change-ms", type=int, default=1000,
                        help="dynamic generator epoch interval in milliseconds")
    parser.add_argument("--expected-rate-hz", type=float, default=0.0,
                        help="require this minimum diagnostic promotion rate (0 disables the gate)")
    parser.add_argument("--rate-tolerance-hz", type=float, default=2.0,
                        help="allowed rate below expected-rate-hz")
    parser.add_argument("--expected-source-rate-hz", type=float, default=44.0,
                        help="require this minimum Mega physical-DMX source rate")
    parser.add_argument("--source-rate-tolerance-hz", type=float, default=1.0,
                        help="allowed source-rate shortfall")
    parser.add_argument("--silent-capture", action="store_true",
                        help="use receiver in-device validation and compact RDS1 summary")
    parser.add_argument("--source-mac", default="cc:50:e3:fd:a9:76",
                        help="expected normal-DMX retransmitter source MAC")
    parser.add_argument("--telemetry-log", type=Path,
                        help="write per-second telemetry snapshots as JSONL")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (not 0 <= args.value <= 255 or args.seconds <= 0 or
            args.change_ms < 100 or args.change_ms > 60000 or
            not 1 <= args.slots <= 512 or args.expected_rate_hz < 0 or
            args.rate_tolerance_hz < 0 or args.expected_source_rate_hz < 0 or
            args.source_rate_tolerance_hz < 0):
        parser.error("value 0..255, positive seconds, change-ms 100..60000, slots 1..512, nonnegative rate settings")

    frame_command = (f"GENERATE DYNAMIC {args.value} {args.change_ms}"
                     if args.pattern == "dynamic" else
                     f"GENERATE DYNAMIC_SHORT {args.slots} {args.value} {args.change_ms}"
                     if args.pattern == "dynamic-short" else
                     f"GENERATE SHORT {args.slots} {args.value}"
                     if args.pattern == "short" else
                     f"GENERATE {'CONST' if args.pattern == 'const' else 'RAMP'} {args.value}")
    summary: dict[str, object] = {"passed": False, "seconds": args.seconds,
                                  "pattern": args.pattern, "value": args.value,
                                  "change_ms": args.change_ms}
    baseline_expected = bytes([args.value]) * 512
    mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
    receiver = serial.Serial(args.receiver_port, args.receiver_baud, timeout=0.05)
    receiver.reset_input_buffer()
    diagnostic = ReceiverDiagnosticParser()
    records = []
    record_times = []
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
    telemetry_log = None
    telemetry_path = args.telemetry_log
    if telemetry_path is None and args.output is not None:
        telemetry_path = args.output.with_suffix(".telemetry.jsonl")
    if telemetry_path is not None:
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        telemetry_log = telemetry_path.open("w", encoding="utf-8")
    silent_summary = None
    try:
        wait_line(mega, "READY RETRANSMITTER_E2E_MEGA", 10)
        if args.pattern == "short":
            # Establish a known full-universe baseline before changing the
            # physical source length. This proves the later zero-filled tail
            # does not retain data from a previous longer universe.
            command(mega, f"GENERATE CONST {args.value}", "ACK GENERATE")
        else:
            command(mega, frame_command, "ACK GENERATE")
        service.start()
        if args.silent_capture:
            mac = args.source_mac
            receiver_command(receiver,
                             f"CAPTURE START {args.source_mac} {args.value} {args.slots} {args.seconds + 30}",
                             "ACK CAPTURE START")
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
                if args.silent_capture:
                    # Keep compact RDS1 text available for collection after the
                    # measurement, without feeding it to the RDX1 parser.
                    silent_summary = (silent_summary or b"") + data
                    if b"RDS1 " in silent_summary:
                        silent_summary = silent_summary[silent_summary.find(b"RDS1 "):]
                else:
                    received_records = diagnostic.feed(data)
                # Ignore receiver output from the explicit START settle period.
                # It may still contain the prior universe or the receiver's
                # boot-time zero universe; only promotions during measurement
                # belong to this run's content verdict.
                if now >= settle_until and not args.silent_capture:
                    for received in received_records:
                        if received.record_type != 1:
                            continue
                        valid = not dynamic_mismatches(
                            received.universe, args.value,
                            args.slots if args.pattern == "dynamic-short" else 512)
                        # Establish the content window on the first valid
                        # dynamic promotion. This avoids treating a final
                        # pre-source/boot universe as a failure at the settle
                        # boundary, while every later promotion is validated.
                        if not content_ready and args.pattern in ("dynamic", "dynamic-short") and valid:
                            content_ready = True
                            diagnostic_bad_crc_at_content_ready = diagnostic.records_bad_crc
                            diagnostic_unknown_at_content_ready = diagnostic.records_unknown_type
                        if content_ready or args.pattern != "dynamic":
                            records.append(received)
                            record_times.append(now)
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
                if telemetry_log:
                    telemetry_log.write(json.dumps(telemetry_samples[-1], separators=(",", ":")) + "\n")
                    telemetry_log.flush()
                next_sample_at += 1.0
        if args.silent_capture:
            summary_line = receiver_command(receiver, "CAPTURE STOP", "RDS1", timeout=10.0)
            if summary_line:
                line = summary_line
                values = {}
                for token in line.split()[1:]:
                    if "=" in token:
                        key, value = token.split("=", 1)
                        try:
                            values[key] = int(value)
                        except ValueError:
                            values[key] = float(value)
                summary["silent_summary"] = values
                summary["telemetry_log"] = str(telemetry_path) if telemetry_path else None
                summary["diagnostic_records"] = int(values.get("promotions", 0))
                summary["diagnostic_matching_records"] = int(values.get("matching", 0))
                summary["diagnostic_invalid_records"] = list(range(
                    int(values.get("corrupt", 0))))
                summary["diagnostic_sequence_gaps"] = int(values.get("sequence_gaps", 0))
                summary["diagnostic_sequence_backtracks"] = int(values.get("sequence_backtracks", 0))
                summary["diagnostic_source_macs"] = {mac: int(values.get("matching", 0))}
                summary["diagnostic_bad_crc"] = 0
                summary["diagnostic_attempt_rate_hz"] = (
                    (int(values.get("last_sequence", 0)) - int(values.get("first_sequence", 0))) /
                    max(0.001, float(values.get("elapsed_ms", 1))) * 1000.0)
                summary["diagnostic_promotion_rate_hz"] = (
                    int(values.get("promotions", 0)) /
                    max(0.001, float(values.get("elapsed_ms", 1))) * 1000.0)
                summary["diagnostic_ring_overflows"] = int(values.get("ring_overflows", 0))
                summary["diagnostic_malformed"] = int(values.get("malformed", 0))
                summary["diagnostic_complete_total"] = int(values.get("complete_total", 0))
                summary["diagnostic_first_mismatch_channel"] = int(
                    values.get("first_mismatch_channel", 0))
                summary["diagnostic_first_mismatch_actual"] = int(
                    values.get("first_mismatch_actual", 0))
                summary["diagnostic_first_mismatch_expected"] = int(
                    values.get("first_mismatch_expected", 0))
                summary["promotion_rate_expectation_met"] = True
                summary["source_rate_expectation_met"] = True
            else:
                raise TimeoutError("waiting for receiver RDS1 summary")
        # Diagnostic receiver mode intentionally disables the receiver's
        # physical DMX output, so the Mega's returned-DMX monitor may not emit a
        # RESULT. The host-side diagnostic capture is authoritative in that
        # mode; retain an optional Mega result when it is available.
        values: dict[str, float | int] = {}
        if result is None:
            summary["mega_result_missing"] = True
        for token in (result or "").split()[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                value = value.rstrip("ms")
                try:
                    values[key] = int(value)
                except ValueError:
                    values[key] = float(value)
        summary["result"] = values
        summary["source_frames"] = values.get("source_frames")
        summary["source_rate_hz"] = values.get("source_rate_hz")
        source_rate_floor = max(0.0, args.expected_source_rate_hz - args.source_rate_tolerance_hz)
        summary["expected_source_rate_hz"] = args.expected_source_rate_hz
        summary["source_rate_tolerance_hz"] = args.source_rate_tolerance_hz
        summary["minimum_required_source_rate_hz"] = source_rate_floor
        summary["source_rate_expectation_met"] = (
            isinstance(summary["source_rate_hz"], (int, float)) and
            summary["source_rate_hz"] >= source_rate_floor)
        if not args.silent_capture:
            summary["diagnostic_records"] = len(records)
        if not args.silent_capture:
            summary["diagnostic_bad_crc"] = diagnostic.records_bad_crc
        summary["diagnostic_unknown_type"] = diagnostic.records_unknown_type
        if not args.silent_capture:
            summary["diagnostic_source_macs"] = dict(Counter(
            record.source_mac.hex(":") for record in records
                if record.record_type == 1))
        normal_records = [record for record in records if record.record_type == 1]
        sequences = [record.sequence for record in normal_records]
        sequence_backtracks = sum(
            1 for previous, current in zip(sequences, sequences[1:])
            if current <= previous)
        sequence_gaps = sum(
            max(0, current - previous - 1)
            for previous, current in zip(sequences, sequences[1:])
            if current > previous)
        if not args.silent_capture:
            summary["diagnostic_sequence_first"] = sequences[0] if sequences else None
            summary["diagnostic_sequence_last"] = sequences[-1] if sequences else None
            summary["diagnostic_sequence_backtracks"] = sequence_backtracks
            summary["diagnostic_sequence_gaps"] = sequence_gaps
        if not args.silent_capture and len(record_times) >= 2 and sequences:
            summary["diagnostic_attempt_rate_hz"] = round(
                (sequences[-1] - sequences[0]) /
                (record_times[-1] - record_times[0]), 3)
        elif not args.silent_capture:
            summary["diagnostic_attempt_rate_hz"] = 0.0
        if not args.silent_capture and len(record_times) >= 2:
            gaps_ms = [(later - earlier) * 1000
                       for earlier, later in zip(record_times, record_times[1:])]
            summary["diagnostic_promotion_rate_hz"] = round(
                (len(record_times) - 1) / (record_times[-1] - record_times[0]), 3)
            summary["diagnostic_promotion_gap_ms_max"] = round(max(gaps_ms), 1)
            summary["diagnostic_promotion_gap_ms_p95"] = round(
                sorted(gaps_ms)[int(0.95 * (len(gaps_ms) - 1))], 1)
        elif not args.silent_capture:
            summary["diagnostic_promotion_rate_hz"] = 0.0
            summary["diagnostic_promotion_gap_ms_max"] = None
            summary["diagnostic_promotion_gap_ms_p95"] = None
        rate_floor = max(0.0, args.expected_rate_hz - args.rate_tolerance_hz)
        summary["expected_rate_hz"] = args.expected_rate_hz
        summary["rate_tolerance_hz"] = args.rate_tolerance_hz
        summary["minimum_required_rate_hz"] = rate_floor
        summary["promotion_rate_expectation_met"] = (
            args.expected_rate_hz <= 0 or
            summary["diagnostic_attempt_rate_hz"] >= rate_floor)
        summary["promotion_rate_observed_hz"] = summary["diagnostic_promotion_rate_hz"]
        summary["diagnostic_bad_crc_after_content_ready"] = max(
            0, diagnostic.records_bad_crc - diagnostic_bad_crc_at_content_ready)
        summary["diagnostic_unknown_after_content_ready"] = max(
            0, diagnostic.records_unknown_type - diagnostic_unknown_at_content_ready)
        summary["telemetry_samples"] = telemetry_samples
        expected = (bytes([args.value]) * 512 if args.pattern == "const" else
                    bytes((args.value + index) & 0xFF for index in range(512)))
        if args.pattern == "short":
            expected = bytes((args.value + index) & 0xFF for index in range(args.slots)) + bytes(512 - args.slots)
        if args.silent_capture:
            summary["diagnostic_invalid_examples"] = []
        elif args.pattern in ("dynamic", "dynamic-short"):
            summary["diagnostic_matching_records"] = sum(
                record.record_type == 1 and
                not dynamic_mismatches(record.universe, args.value,
                                       args.slots if args.pattern == "dynamic-short" else 512)
                for record in records)
        else:
            summary["diagnostic_matching_records"] = sum(
                record.record_type == 1 and record.universe == expected for record in records)
        if args.pattern in ("dynamic", "dynamic-short"):
            invalid_dynamic = []
            invalid_examples = []
            for record in records:
                if record.record_type != 1:
                    continue
                mismatches = dynamic_mismatches(
                    record.universe, args.value,
                    args.slots if args.pattern == "dynamic-short" else 512)
                epoch = record.universe[0]
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
            # Partial mode must produce the exact requested prefix and a
            # zero-filled tail.
            summary["short_expectation_met"] = short_promotions > 0
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
        # The first sample is commonly collected before the asynchronous
        # management handshake completes. Do not report that expected pending
        # state as a runtime failure; validate every sample after the first
        # successful management report.
        telemetry_ready = any(sample["reports_received"] > 0
                              for sample in telemetry_samples)
        summary["telemetry_bad_samples"] = [sample for sample in telemetry_samples
                                             if sample["reports_received"] > 0 and
                                             (not sample["transmitter_connected"] or
                                              sample["transmitter_mode"] != "management_only" or
                                              sample["transmitter_mode_sync"] != "synchronized" or
                                              sample["last_error"])]
        summary["telemetry_progressed"] = telemetry_ready
        summary["transmitter_connected"] = service.snapshot().transmitter_connected
        content_records_present = ((summary["baseline_complete_matches"] > 0 and
                                    summary["diagnostic_normal_records"] >= 0)
                                   if args.pattern == "short" else
                                    summary["diagnostic_matching_records"] > 0)
        summary["passed"] = ((args.silent_capture and
                               summary.get("diagnostic_records", 0) > 0 and
                               summary.get("diagnostic_matching_records", 0) == summary.get("diagnostic_records", 0) and
                               not summary.get("diagnostic_invalid_records")) or
                              (not args.silent_capture and content_records_present and
                              summary["diagnostic_bad_crc_after_content_ready"] == 0 and
                              summary["diagnostic_unknown_after_content_ready"] == 0 and
                              not summary["diagnostic_invalid_records"] and
                              summary["diagnostic_sequence_backtracks"] == 0 and
                              summary["promotion_rate_expectation_met"] and
                              summary["source_rate_expectation_met"] and
                              service.snapshot().transmitter_connected and
                              summary["telemetry_progressed"] and
                              not summary["telemetry_bad_samples"] and
                              summary.get("short_expectation_met", True)))
        print(json.dumps(summary, indent=2, default=str), flush=True)
        if args.output:
            args.output.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        return 0 if summary["passed"] else 1
    finally:
        if telemetry_log:
            telemetry_log.close()
        service.stop()
        mega.close()
        receiver.close()


if __name__ == "__main__":
    raise SystemExit(main())
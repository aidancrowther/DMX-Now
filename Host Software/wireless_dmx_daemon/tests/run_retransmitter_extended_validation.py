#!/usr/bin/env python3
"""Low-rate extended validation; device firmware does real-time work locally."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wireless_dmx.receiver_diagnostic import parse_summary_line

DEFAULT_SLOTS = (24, 25, 100, 235, 236, 237, 255, 256, 257, 471, 472, 473, 511, 512)
TRANSITIONS = ((512, 24), (24, 512), (512, 236), (236, 512),
               (473, 471), (471, 473), (257, 255), (255, 257))
RETRANSMITTER_TARGET_RATE_HZ = 10.0
RETRANSMITTER_MIN_PROMOTION_RATE_HZ = 9.0


def reset_receiver(port: serial.Serial) -> None:
    port.dtr = False
    port.rts = True
    time.sleep(0.2)
    port.rts = False
    time.sleep(2.0)
    port.reset_input_buffer()


def read_until(port: serial.Serial, marker: bytes, timeout: float) -> bytes:
    end = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < end:
        chunk = port.read(256)
        if chunk:
            data.extend(chunk)
            if marker in data:
                return bytes(data)
        else:
            time.sleep(0.005)
    raise TimeoutError(f"waiting for {marker!r}; tail={bytes(data[-300:])!r}")


def read_summary(port: serial.Serial, marker: bytes, timeout: float) -> bytes:
    data = bytearray()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        chunk = port.read(256)
        if chunk:
            data.extend(chunk)
            pos = data.find(marker)
            if pos >= 0:
                newline = data.find(b"\n", pos)
                if newline >= 0:
                    return bytes(data[pos:newline + 1])
        else:
            time.sleep(0.005)
    raise TimeoutError(f"waiting for complete {marker!r}; tail={bytes(data[-300:])!r}")


def command(port: serial.Serial, text: str, marker: bytes, timeout: float = 8) -> bytes:
    port.write((text + "\n").encode())
    port.flush()
    return read_until(port, marker, timeout)


def last_line(data: bytes, prefix: bytes) -> str | None:
    lines = [line.decode(errors="replace").strip() for line in data.splitlines()
             if line.startswith(prefix)]
    return lines[-1] if lines else None


def parse_values(line: str | None) -> dict[str, int | float | str]:
    if not line:
        return {}
    return parse_summary_line(line, prefix=line.split(None, 1)[0])


def run_case(mega: serial.Serial, receiver: serial.Serial, slots: int,
             seconds: int, base: int, change_ms: int, source_mac: str,
             settle: int = 3) -> dict[str, object]:
    mega.reset_input_buffer()
    command(mega, "STOP", b"ACK STOP")
    time.sleep(0.25)
    command(mega, f"GENERATE DYNAMIC_SHORT {slots} {base} {change_ms}", b"ACK GENERATE")

    receiver.reset_input_buffer()
    ack = receiver.write(f"CAPTURE START {source_mac} {base} {slots} {seconds + settle}\r".encode())
    del ack
    receiver.flush()
    receiver_ack = read_until(receiver, b"ACK CAPTURE START", 8)
    if receiver_ack.count(b"ACK CAPTURE START") != 1:
        raise RuntimeError("receiver CAPTURE START acknowledgement replayed")

    mega.write(f"START {settle} {seconds}\n".encode())
    mega.flush()
    read_until(mega, b"ACK START", 8)

    # Do not read either UART during the real-time measurement.
    time.sleep(settle + seconds + 1.0)
    mega_data = bytearray()
    while mega.in_waiting:
        mega_data.extend(mega.read(256))
    receiver_data = bytearray()
    while receiver.in_waiting:
        receiver_data.extend(receiver.read(256))
    if b"RESULT " not in mega_data:
        try:
            mega_data.extend(read_until(mega, b"RESULT ", 5))
        except TimeoutError:
            pass
    if b"RDS1 " not in receiver_data:
        try:
            receiver_data.extend(read_summary(receiver, b"RDS1 ", 5))
        except TimeoutError:
            pass

    result_line = last_line(bytes(mega_data), b"RESULT ")
    rds_line = last_line(bytes(receiver_data), b"RDS1 ")
    result = parse_values(result_line)
    rds = parse_values(rds_line)
    elapsed = int(rds.get("elapsed_ms", 0))
    promotions = int(rds.get("promotions", 0))
    matching = int(rds.get("matching", 0))
    fragments = [int(rds.get(f"rx{i}", 0)) for i in range(3)]
    rate = promotions / max(0.001, elapsed / 1000.0)
    checks = {
        "has_result": result_line is not None,
        "has_rds1": rds_line is not None,
        "has_data": promotions > 0,
        "source_rate_ok": float(result.get("source_rate_hz", 0)) >= (39.5 if slots == 512 else 43.0),
        # The standalone retransmitter is intentionally a 10 Hz source. The
        # 20 Hz bridge target does not apply to this runner.
        "promotion_rate_ok": rate >= RETRANSMITTER_MIN_PROMOTION_RATE_HZ,
        "matching_ok": matching >= int(promotions * 0.98),
        "corrupt_zero": int(rds.get("corrupt", 0)) == 0,
        "source_mismatches_zero": int(rds.get("source_mismatches", 0)) == 0,
        "backtracks_zero": int(rds.get("sequence_backtracks", 0)) == 0,
        "queues_healthy": all(int(rds.get(k, 0)) == 0 for k in
                               ("qrx_evictions", "qrx_push_failures", "ring_overflows")),
        "fragment_counts_present": min(fragments) > 0,
        "fragment_balance_ok": max(fragments) - min(fragments) <= max(10, int(max(fragments) * 0.10)),
    }
    return {"slots": slots, "seconds": seconds, "result_line": result_line,
            "rds1_line": rds_line, "result": result, "rds1": rds,
            "promotion_rate_hz": rate, "fragment_counts": fragments,
            "checks": checks, "passed": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--receiver-port", default="/dev/ttyUSB2")
    parser.add_argument("--receiver-baud", type=int, default=115200)
    parser.add_argument("--source-mac", default="cc:50:e3:fd:a9:76")
    parser.add_argument("--base", type=int, default=53)
    parser.add_argument("--change-ms", type=int, default=100)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--matrix-only", action="store_true")
    parser.add_argument("--transitions-only", action="store_true")
    parser.add_argument("--soaks", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    selected = [args.preflight_only, args.matrix_only, args.transitions_only, args.soaks, args.all]
    if sum(selected) > 1:
        parser.error("phase selectors are mutually exclusive")
    if not any(selected):
        args.preflight_only = True
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir or Path("runs/retransmitter-extended") / stamp
    output.mkdir(parents=True, exist_ok=True)
    if args.preflight_only:
        cases = [(236, 30), (512, 30)]
    elif args.matrix_only:
        cases = [(s, 30) for s in DEFAULT_SLOTS]
    elif args.transitions_only:
        cases = [(new, 30) for _, new in TRANSITIONS]
    elif args.soaks:
        cases = [(512, 900), (24, 600), (237, 600)]
    else:
        cases = ([(236, 30), (512, 30)] + [(s, 30) for s in DEFAULT_SLOTS] +
                 [(new, 30) for _, new in TRANSITIONS] + [(512, 900), (24, 600), (237, 600)])
    phase = "preflight" if args.preflight_only else "matrix" if args.matrix_only else "transitions" if args.transitions_only else "soaks" if args.soaks else "all"
    report: dict[str, object] = {"timestamp": stamp, "phase": phase, "receiver_baud": args.receiver_baud, "cases": []}
    mega = receiver = None
    try:
        mega = serial.Serial(args.mega_port, 115200, timeout=.1, write_timeout=1)
        receiver = serial.Serial(args.receiver_port, args.receiver_baud, timeout=.1, write_timeout=1)
        reset_receiver(receiver)
        command(receiver, "CAPTURE STATUS", b"STATUS capture=", 5)
        receiver.reset_input_buffer()
        for index, (slots, seconds) in enumerate(cases, 1):
            print(f"CASE {index}/{len(cases)} slots={slots} seconds={seconds}", flush=True)
            try:
                case = run_case(mega, receiver, slots, seconds, args.base, args.change_ms, args.source_mac)
            except Exception as exc:
                case = {"slots": slots, "seconds": seconds, "passed": False, "harness_failure": str(exc)}
            report["cases"].append(case)
            (output / f"case-{index:02d}-slots-{slots}.json").write_text(json.dumps(case, indent=2, default=str) + "\n")
            print(json.dumps({k: case.get(k) for k in ("slots", "passed", "promotion_rate_hz", "fragment_counts", "checks", "harness_failure")}, indent=2), flush=True)
            if case.get("harness_failure"):
                break
    finally:
        if mega is not None:
            try:
                mega.write(b"STOP\n"); mega.flush()
            except serial.SerialException:
                pass
            mega.close()
        if receiver is not None:
            receiver.close()
    report["passed"] = bool(report["cases"]) and all(c.get("passed", False) for c in report["cases"])
    (output / "summary.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (output / "summary.md").write_text("# Retransmitter extended validation\n\nPassed: **%s**\n" % report["passed"])
    print(f"REPORT {output / 'summary.json'}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
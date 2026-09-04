#!/usr/bin/env python3
"""Bounded Feature 8 serial delivery/load checks.

This runner deliberately opens only the transmitter and Mega monitor ports.
Each case has a deadline and writes its result before the next case starts.
"""
from __future__ import annotations

import argparse
import json
import random
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


def command(mega: serial.Serial, text: str) -> str:
    mega.write((text + "\n").encode())
    mega.flush()
    return wait_for(mega, "ACK ", 5.0)


def measure(mega: serial.Serial, expectation: str, settle: int = 2,
            seconds: int = 3) -> str:
    command(mega, expectation)
    command(mega, f"START {settle} {seconds}")
    return wait_for(mega, "RESULT ", seconds + 5.0)


def fields(line: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = int(value.rstrip("ms"))
    return result


def send_bytewise(tx: serial.Serial, data: bytes, gap: float) -> None:
    for value in data:
        tx.write(bytes((value,)))
        tx.flush()
        time.sleep(gap)


def send_chunks(tx: serial.Serial, data: bytes, sizes: list[int]) -> None:
    offset = 0
    for size in sizes:
        tx.write(data[offset:offset + size])
        tx.flush()
        offset += size
    if offset < len(data):
        tx.write(data[offset:])
        tx.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)
    summary = {"tx_port": args.tx_port, "mega_port": args.mega_port,
               "passed": True, "results": []}

    def record(name: str, passed: bool, detail: str) -> None:
        item = {"name": name, "passed": passed, "detail": detail}
        summary["results"].append(item)
        summary["passed"] = summary["passed"] and passed
        (args.run_dir / f"{len(summary['results']):02d}_{name}.json").write_text(
            json.dumps(item, indent=2) + "\n"
        )

    try:
        with serial.Serial(args.tx_port, 115200, bytesize=8,
                           parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                           timeout=0.1) as tx, serial.Serial(args.mega_port, 115200,
                                                             timeout=0.2) as mega:
            tx.reset_input_buffer()
            tx.reset_output_buffer()
            mega.reset_input_buffer()
            time.sleep(1.0)

            # B01: a valid 512-slot frame, one byte at a time, 1 ms gaps.
            ramp = bytes((0x19 + i) & 255 for i in range(512))
            start = time.monotonic()
            command(mega, "EXPECT RAMP 25")
            send_bytewise(tx, dmx_frame(ramp), 0.001)
            line = measure(mega, "EXPECT RAMP 25")
            result = fields(line)
            record("bytewise_1ms", result.get("checks", 0) > 0 and result.get("fail", -1) == 0,
                   f"elapsed={time.monotonic() - start:.1f}s {line}")

            # B02/B04: deterministic header splits followed by immediate frames.
            const = dmx_frame(bytes([0x4A]) * 512)
            command(mega, "EXPECT CONST 115")
            send_chunks(tx, const, [1, 1, 1, 1])
            for value in (0x51, 0x62, 0x73):
                tx.write(dmx_frame(bytes([value]) * 512))
            tx.flush()
            line = measure(mega, "EXPECT CONST 115")
            result = fields(line)
            record("header_splits_back_to_back", result.get("checks", 0) > 0 and result.get("fail", -1) == 0, line)

            # B03: 100 deterministic frames with varied chunk boundaries. The
            # monitor checks the final state; no mixed frame may be promoted.
            rng = random.Random(0xF801)
            command(mega, "EXPECT CONST 131")
            for sequence in range(100):
                value = (0x20 + sequence) & 255
                data = dmx_frame(bytes([value]) * 512)
                sizes = [rng.randint(1, 80) for _ in range(8)]
                send_chunks(tx, data, sizes)
                time.sleep(0.012)
            line = measure(mega, "EXPECT CONST 131")
            result = fields(line)
            record("100_random_chunk_frames", result.get("checks", 0) > 0 and result.get("fail", -1) == 0, line)
    except Exception as exc:
        record("runner", False, repr(exc))

    (args.run_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
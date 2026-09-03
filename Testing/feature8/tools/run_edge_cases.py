#!/usr/bin/env python3
"""Bounded Feature 8 ENTTEC parser edge-case hardware runner.

The runner intentionally uses only the existing transmitter and Mega monitor
ports. It does not deploy firmware and never opens a receiver programming
port. Every case has bounded ACK/result waits and is written to the results
directory as soon as it completes.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import serial

from enttec_protocol import dmx_frame, frame


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


def measure(mega: serial.Serial, expectation: str, seconds: int = 2) -> str:
    command(mega, expectation)
    command(mega, f"START 0 {seconds}")
    return wait_for(mega, "RESULT ", seconds + 5.0)


def result_fields(line: str) -> dict[str, int]:
    fields: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = int(value.rstrip("ms"))
    return fields


def send(tx: serial.Serial, data: bytes) -> None:
    tx.write(data)
    tx.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)

    cases = [
        ("valid_1_slot", dmx_frame(bytes([0x11])), "EXPECT SHORT 1 17"),
        ("valid_37_slots", dmx_frame(bytes((0x22 + i) & 255 for i in range(37))), "EXPECT SHORT 37 34"),
        ("valid_255_slots", dmx_frame(bytes((0x33 + i) & 255 for i in range(255))), "EXPECT SHORT 255 51"),
        ("valid_256_slots", dmx_frame(bytes((0x44 + i) & 255 for i in range(256))), "EXPECT SHORT 256 68"),
        ("valid_511_slots", dmx_frame(bytes((0x55 + i) & 255 for i in range(511))), "EXPECT SHORT 511 85"),
        ("valid_512_slots", dmx_frame(bytes((0x66 + i) & 255 for i in range(512))), "EXPECT RAMP 102"),
        ("zero_length_then_valid", frame(0x06, b"") + dmx_frame(bytes([0x77] * 512)), "EXPECT CONST 119"),
        ("one_length_then_valid", frame(0x06, b"\x00") + dmx_frame(bytes([0x88] * 512)), "EXPECT CONST 136"),
        ("wrong_label_preserves", frame(0x05, b"\x00" + bytes([0x99] * 512)), "EXPECT CONST 136"),
        ("nonzero_start_code_preserves", dmx_frame(bytes([0xAA] * 512), start_code=1), "EXPECT CONST 136"),
        ("wrong_terminator_preserves", dmx_frame(bytes([0xBB] * 512))[:-1] + b"\x00", "EXPECT CONST 136"),
        ("noise_then_valid", bytes([0x00, 0xE7, 0x55, 0x7E]) + dmx_frame(bytes([0xCC] * 512)), "EXPECT CONST 204"),
        ("oversize_then_valid", frame(0x06, b"\x00" + bytes([0xDD] * 513)) + dmx_frame(bytes([0xEE] * 512)), "EXPECT CONST 238"),
    ]

    summary = {"tx_port": args.tx_port, "mega_port": args.mega_port, "passed": True, "results": []}
    try:
        with serial.Serial(args.tx_port, 57600, bytesize=8, parity=serial.PARITY_NONE,
                           stopbits=serial.STOPBITS_TWO, timeout=0.1) as tx, \
             serial.Serial(args.mega_port, 115200, timeout=0.2) as mega:
            tx.reset_input_buffer()
            tx.reset_output_buffer()
            mega.reset_input_buffer()
            time.sleep(1.0)
            for name, payload, expectation in cases:
                try:
                    send(tx, payload)
                    # Allow the transmitter's non-blocking scheduler to submit
                    # the complete RF frame before starting the measurement.
                    time.sleep(1.2)
                    line = measure(mega, expectation)
                    fields = result_fields(line)
                    passed = fields.get("checks", 0) > 0 and fields.get("fail", -1) == 0
                    detail = line
                except Exception as exc:  # preserve partial-run evidence
                    passed = False
                    detail = repr(exc)
                item = {"name": name, "passed": passed, "detail": detail}
                summary["results"].append(item)
                summary["passed"] = summary["passed"] and passed
                (args.run_dir / f"{len(summary['results']):02d}_{name}.json").write_text(
                    json.dumps(item, indent=2) + "\n"
                )
    except Exception as exc:
        summary["passed"] = False
        summary["error"] = repr(exc)

    (args.run_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
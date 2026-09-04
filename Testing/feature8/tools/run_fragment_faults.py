#!/usr/bin/env python3
"""Feature 8 fragment fault-injection runner.

Each hook is compiled/flashed independently, exercised through the existing
transmitter and Mega monitor, and followed by a production-image restore. The
receiver programming port is intentionally never opened.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import serial

from enttec_protocol import dmx_frame

ROOT = Path(__file__).resolve().parents[3]
FLASH_SCRIPT = ROOT / "flash_transmitter.sh"


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


def mega_command(mega: serial.Serial, text: str, prefix: str = "ACK ") -> str:
    mega.write((text + "\n").encode())
    mega.flush()
    return wait_for(mega, prefix, 5.0)


def parse_result(line: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for token in line.split()[1:]:
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = int(value.rstrip("ms"))
    return result


def measure(mega: serial.Serial, expectation: str, settle: int = 3,
            seconds: int = 3) -> tuple[str, dict[str, int]]:
    mega_command(mega, expectation)
    mega_command(mega, f"START {settle} {seconds}")
    line = wait_for(mega, "RESULT ", settle + seconds + 5.0)
    return line, parse_result(line)


def flash(port: str, run_dir: Path, name: str, define: str | None) -> None:
    command = [str(FLASH_SCRIPT), "-f", "--port", port]
    if define:
        command += ["--define", f"-D{define}"]
    log_path = run_dir / f"deploy_{name}.log"
    try:
        completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   timeout=180)
        log_path.write_text(completed.stdout)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        log_path.write_text(output if isinstance(output, str) else output.decode(errors="replace"))
        raise TimeoutError(f"flash timeout for {name}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"flash failed for {name}; see {log_path}")


def send_constant(tx: serial.Serial, value: int) -> None:
    tx.write(dmx_frame(bytes([value]) * 512))
    tx.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)

    # The expected outcome is deliberately explicit. Corruption is an
    # informational limitation test: production has no payload checksum, so a
    # corrupted promoted universe is the expected observation.
    cases = [
        ("reorder", "TEST_REORDER_FRAGMENTS", "target", 0xA1, 3),
        ("duplicate_1", "TEST_DUPLICATE_FRAGMENT_INDEX=1", "target", 0xA2, 3),
        ("drop_0", "TEST_DROP_FRAGMENT_INDEX=0", "baseline", 0xA3, 3),
        ("drop_1", "TEST_DROP_FRAGMENT_INDEX=1", "baseline", 0xA4, 3),
        ("drop_2", "TEST_DROP_FRAGMENT_INDEX=2", "baseline", 0xA5, 3),
        ("corrupt_1", "TEST_CORRUPT_FRAGMENT_INDEX=1", "corruption_observed", 0xA6, 3),
        ("delayed", "TEST_DELAYED_FRAGMENT", "target", 0xA7, 6),
    ]
    baseline = 0x3C
    summary = {"tx_port": args.tx_port, "mega_port": args.mega_port,
               "passed": True, "results": []}

    def record(name: str, passed: bool, detail: str) -> None:
        item = {"name": name, "passed": bool(passed), "detail": detail}
        summary["results"].append(item)
        summary["passed"] = summary["passed"] and bool(passed)
        (args.run_dir / f"{len(summary['results']):02d}_{name}.json").write_text(
            json.dumps(item, indent=2) + "\n"
        )

    try:
        for name, define, expected_mode, target, settle in cases:
            stop_after_case = False
            try:
                # Establish a known active baseline using the current production
                # image before applying the next fault image.
                with serial.Serial(args.tx_port, 115200, bytesize=8,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                                   timeout=0.1) as tx, serial.Serial(args.mega_port,
                                                                     115200, timeout=0.2) as mega:
                    tx.reset_input_buffer()
                    tx.reset_output_buffer()
                    mega.reset_input_buffer()
                    time.sleep(1.0)
                    mega_command(mega, f"EXPECT CONST {baseline}")
                    send_constant(tx, baseline)
                    line, result = measure(mega, f"EXPECT CONST {baseline}", settle=2)
                    if result.get("checks", 0) == 0 or result.get("fail", -1) != 0:
                        raise RuntimeError(f"baseline failed before {name}: {line}")

                flash(args.tx_port, args.run_dir, name, define)
                # A freshly flashed transmitter restarts its sequence at zero;
                # allow the receiver's documented reset-recovery window to
                # expire before judging the new fault image.
                time.sleep(3.5)
                with serial.Serial(args.tx_port, 115200, bytesize=8,
                                   parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                                   timeout=0.1) as tx, serial.Serial(args.mega_port,
                                                                     115200, timeout=0.2) as mega:
                    tx.reset_input_buffer()
                    tx.reset_output_buffer()
                    mega.reset_input_buffer()
                    time.sleep(1.0)
                    expected_value = target if expected_mode != "baseline" else baseline
                    mega_command(mega, f"EXPECT CONST {expected_value}")
                    send_constant(tx, target)
                    line, result = measure(mega, f"EXPECT CONST {expected_value}", settle=settle)
                checks = result.get("checks", 0)
                failures = result.get("fail", -1)
                if expected_mode == "corruption_observed":
                    passed = checks > 0 and failures > 0
                    detail = f"expected production limitation; {line}"
                else:
                    passed = checks > 0 and failures == 0
                    detail = line
                record(name, passed, detail)
            except Exception as exc:
                record(name, False, repr(exc))
                # Do not run another fault image after a failed case; cleanup in
                # finally still restores the production transmitter.
                stop_after_case = True
            finally:
                try:
                    flash(args.tx_port, args.run_dir, f"restore_after_{name}", None)
                except Exception as exc:
                    record(f"restore_after_{name}", False, repr(exc))
                    stop_after_case = True
            if stop_after_case:
                break
    except Exception as exc:
        record("runner", False, repr(exc))
    finally:
        # A final restore is intentionally attempted even if opening the ports
        # or a prior restore failed.
        try:
            flash(args.tx_port, args.run_dir, "final_production_restore", None)
        except Exception as exc:
            record("final_production_restore", False, repr(exc))

    (args.run_dir / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
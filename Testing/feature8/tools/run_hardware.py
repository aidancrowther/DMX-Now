#!/usr/bin/env python3
"""Feature 8 ENTTEC serial-to-DMX hardware runner (TX ttyUSB0, Mega ttyUSB1)."""
from __future__ import annotations
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import serial
from enttec_protocol import frame, dmx_frame
ROOT = Path(__file__).resolve().parents[3]
class Results:
    def __init__(self, directory: Path):
        self.directory = directory
        self.items = []
        directory.mkdir(parents=True, exist_ok=True)

    def add(self, name: str, passed: bool, detail: str) -> None:
        item = {"name": name, "passed": bool(passed), "detail": detail}
        self.items.append(item)
        (self.directory / f"{len(self.items):02d}_{name}.json").write_text(
            json.dumps(item, indent=2) + "\n"
        )

    def write(self, args) -> dict:
        output = {
            "run_utc": self.directory.name,
            "tx_port": args.tx_port,
            "mega_port": args.mega_port,
            "passed": all(item["passed"] for item in self.items),
            "results": self.items,
        }
        (self.directory / "manifest.json").write_text(json.dumps(output, indent=2) + "\n")
        return output


def wait_line(port, prefix: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic()<deadline:
        line=port.readline().decode(errors='replace').strip()
        if line: seen.append(line)
        if line.startswith(prefix): return line
    raise TimeoutError(f"waiting for {prefix}: {seen}")


def command(port, text: str, prefix: str) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return wait_line(port, prefix, 5)


def measure(mega, expectation: str, seconds: int = 3) -> tuple[str, int, int]:
    command(mega, expectation, "ACK EXPECT")
    command(mega, f"START 1 {seconds}", "ACK START")
    line = wait_line(mega, "RESULT", seconds + 5)
    fields = dict(field.rstrip("ms").split("=", 1) for field in line.split()[1:] if "=" in field)
    return line, int(fields.get("checks", 0)), int(fields.get("fail", -1))


def send(tx, data: bytes, chunks=()) -> None:
    offset = 0
    for size in chunks:
        tx.write(data[offset:offset + size])
        tx.flush()
        offset += size
        time.sleep(0.008)
    tx.write(data[offset:])
    tx.flush()


def deploy(args, results: Results) -> None:
    commands = [
        ("deploy_tx.log", ["./flash_transmitter.sh", "-f", "--port", args.tx_port]),
        ("deploy_mega.log", ["./flash_enttec_dmx_monitor.sh", "-f", "--port", args.mega_port]),
    ]
    for name, command_line in commands:
        process = subprocess.run(command_line, cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
        (results.directory / name).write_text(process.stdout)
        if process.returncode:
            raise RuntimeError(f"{name} failed")


def suite(args, results: Results) -> None:
    if args.deploy:
        deploy(args, results)
    with serial.Serial(args.tx_port, 115200, bytesize=8, parity=serial.PARITY_NONE,
                       stopbits=serial.STOPBITS_TWO, timeout=0.1) as tx, \
         serial.Serial(args.mega_port, 115200, timeout=0.2) as mega:
        tx.reset_input_buffer()
        tx.reset_output_buffer()
        mega.reset_input_buffer()
        time.sleep(1)
        # Full 512 slots, fragmented host writes: proves non-blocking parser/DMX path.
        ramp = bytes((0x31 + i) & 255 for i in range(512))
        send(tx, dmx_frame(ramp), [1, 2, 4, 73])
        line, checks, failures = measure(mega, "EXPECT RAMP 49")
        results.add("full_512_split_input", checks > 0 and failures == 0, line)
        # A short input must actively clear the trailing 475 channels.
        short = bytes((0xA0 + i) & 255 for i in range(37))
        send(tx, dmx_frame(short), [2, 4, 10])
        line, checks, failures = measure(mega, "EXPECT SHORT 37 160")
        results.add("short_universe_zero_fill", checks > 0 and failures == 0, line)
        # Invalid packets must not overwrite the last accepted universe.
        send(tx, dmx_frame(bytes([0x55]) * 512, start_code=1))
        send(tx, frame(0x06, b"\0\x99")[:-1] + b"\0")
        send(tx, bytes((0x7e, 0x06, 0x10, 0x03)) + bytes(784) + bytes((0xe7,)))
        line, checks, failures = measure(mega, "EXPECT SHORT 37 160")
        results.add("malformed_preserves_active", checks > 0 and failures == 0, line)
        # A valid frame immediately following corruption proves resynchronization.
        send(tx, dmx_frame(bytes([0x66]) * 512), [7, 9, 127])
        line, checks, failures = measure(mega, "EXPECT CONST 102")
        results.add("parser_recovers_after_malformed", checks > 0 and failures == 0, line)
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    directory = args.run_dir or ROOT / "Testing/feature8/runs" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = Results(directory)
    try:
        suite(args, results)
    except Exception as exception:
        results.add("runner", False, repr(exception))
    summary = results.write(args)
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

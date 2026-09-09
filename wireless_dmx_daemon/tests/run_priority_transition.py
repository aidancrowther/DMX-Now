#!/usr/bin/env python3
"""Validate normal DMX before/after a targeted priority transaction with Mega."""

from __future__ import annotations

import argparse
import os
import sys
import time
import threading
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
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            print("MEGA " + line, flush=True)
            if line.startswith(prefix):
                return line
    raise TimeoutError(f"waiting for {prefix!r}")


def mega_measure(mega: serial.Serial, client: serial.Serial, frame: bytes,
                 value: int, settle: int, seconds: int) -> dict[str, int]:
    mega.write(f"EXPECT CONST {value}\n".encode())
    mega.flush()
    wait_line(mega, "ACK EXPECT", 5)
    mega.write(f"START {settle} {seconds}\n".encode())
    mega.flush()
    wait_line(mega, "ACK START", 5)
    stream_thread = threading.Thread(target=stream, args=(client, frame, settle + seconds), daemon=True)
    stream_thread.start()
    result = wait_line(mega, "RESULT ", seconds + settle + 10)
    stream_thread.join(timeout=2)
    values = {}
    for token in result.split()[1:]:
        if "=" in token:
            key, value_text = token.split("=", 1)
            values[key] = int(value_text.rstrip("ms%"))
    return values


def stream(client: serial.Serial, frame: bytes, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    next_send = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_send:
            client.write(frame)
            next_send += 0.05
        time.sleep(0.001)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--expected-receiver", action="append", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    path = f"/tmp/wireless-dmx-priority-transition-{os.getpid()}"
    service = WirelessDmxService(
        DaemonConfig(transmitter_device=args.tx_port, virtual_port_path=path,
                     artnet_enabled=False, telemetry_interval_seconds=1.0,
                     priority_max_attempts=5),
        virtual_backend=LinuxPtyBackend(path),
    )
    mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
    client = None
    summary = {"passed": False, "expected_receivers": args.expected_receiver}
    service.start()
    try:
        required = set(args.expected_receiver)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            online = {r.receiver_id for r in service.snapshot().receivers
                      if r.link_state.value == "online"}
            if required <= online and service.snapshot().telemetry.cache_clear_acknowledged:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("expected receivers did not become online")

        service.seed_priority_ids((int(time.time()) ^ (os.getpid() << 16)) & 0xFFFFFFFF)
        client = serial.Serial(service.virtual.path, 115200, bytesize=8,
                               parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                               timeout=0.1)

        wait_line(mega, "READY ENTTEC_DMX_MONITOR", 8)
        normal = encode_dmx(bytes([77]) * 512)
        priority = encode_dmx(bytes([99]) * 512)

        service.set_manual_universe(bytes([77]) * 512)
        normal_before = mega_measure(mega, client, normal, 77, 1, 5)

        service.set_manual_universe(bytes([99]) * 512)
        priority_id = service.send_manual(priority=True, repeat_count=3,
                                          ttl_seconds=5.0,
                                          reason="Mega priority transition")
        priority_result = mega_measure(mega, client, priority, 99, 1, 7)
        event_deadline = time.monotonic() + 12
        while time.monotonic() < event_deadline and not service._priority_events[priority_id]["terminal"]:
            time.sleep(0.05)
        event = service._priority_events[priority_id]

        service.set_manual_universe(bytes([77]) * 512)
        # Allow the transmitter lead-out and the receiver's physical DMX
        # refresh to settle before judging normal-stream resumption.
        normal_after = mega_measure(mega, client, normal, 77, 3, 8)

        summary.update({"normal_before": normal_before, "priority": priority_result,
                        "normal_after": normal_after, "event": event})
        summary["passed"] = bool(
            normal_before.get("fail", 1) == 0 and
            priority_result.get("checks", 0) > 0 and
            priority_result.get("pass", 0) > 0 and
            normal_after.get("fail", 1) == 0 and
            event.get("ack_complete") and
            not event.get("receiver_states", {}).get(next(iter(required)), {}).get("failed", False)
        )
        print(summary, flush=True)
        if args.output:
            import json
            args.output.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
        return 0 if summary["passed"] else 1
    except Exception as exc:
        summary["error"] = repr(exc)
        print(summary, flush=True)
        return 1
    finally:
        if client:
            client.close()
        service.stop()
        mega.close()


if __name__ == "__main__":
    raise SystemExit(main())
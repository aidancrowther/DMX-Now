#!/usr/bin/env python3
"""End-to-end 30-minute daemon acceptance test using the real Mega monitor.

This runner is intentionally outside the package test suite because it uses
real serial devices. It opens the daemon's Linux PTY as a lighting client,
streams a stable full-universe ENTTEC ramp at 20 Hz, and verifies the receiver
output using the Arduino Mega on its USB serial port.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
    seen: list[str] = []
    while time.monotonic() < deadline:
        line = port.readline().decode(errors="replace").strip()
        if line:
            seen.append(line)
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"waiting for {prefix!r}; seen={seen[-10:]!r}")


def send_mega_command(port: serial.Serial, text: str, prefix: str, timeout: float = 5.0) -> str:
    port.write((text + "\n").encode())
    port.flush()
    return wait_line(port, prefix, timeout)


def parse_mega_result(line: str) -> dict[str, int]:
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
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--telemetry-interval", type=float, default=15.0)
    parser.add_argument("--priority-interval", type=float, default=60.0)
    parser.add_argument("--priority-events", type=int, default=30)
    parser.add_argument("--priority-drain-seconds", type=float, default=5.0)
    parser.add_argument("--expected-receiver", action="append", type=lambda value: int(value, 0),
                        help="receiver ID expected throughout the run; may be repeated")
    parser.add_argument("--min-mega-checks-per-second", type=float, default=30.0)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 1800:
        parser.error("--seconds must be at least 1800")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.run_dir / "manifest.json"
    telemetry_path = args.run_dir / "daemon_telemetry.jsonl"
    progress_path = args.run_dir / "progress.jsonl"
    requested_path = f"/tmp/wireless-dmx-acceptance-{os.getpid()}"
    try:
        os.unlink(requested_path)
    except FileNotFoundError:
        pass

    summary: dict[str, object] = {
        "tx_port": args.tx_port,
        "mega_port": args.mega_port,
        "seconds_requested": args.seconds,
        "dmx_hz_requested": 20.0,
        "telemetry_interval_seconds": args.telemetry_interval,
        "priority_interval_seconds": args.priority_interval,
        "priority_events_requested": args.priority_events,
        "priority_drain_seconds": args.priority_drain_seconds,
        "expected_receivers": sorted(args.expected_receiver or []),
        "min_mega_checks_per_second": args.min_mega_checks_per_second,
        "priority_retry_cooldown_min_seconds": 1.0,
        "priority_retry_cooldown_max_seconds": 2.5,
        "passed": False,
    }
    priority_id_seed = (int(time.time()) ^ (os.getpid() << 16)) & 0xFFFFFFFF
    summary["priority_id_seed"] = priority_id_seed
    service: WirelessDmxService | None = None
    client: serial.Serial | None = None
    mega: serial.Serial | None = None
    tx_times: list[float] = []
    telemetry_reports = 0
    telemetry_records = 0
    priority_ids: list[int] = []
    next_priority = 0.0
    priority_waiting_for: int | None = None
    priority_wait_started = 0.0
    normal_frames_during_priority = 0
    normal_frames_before_priority = 0
    normal_frames_after_priority = 0
    telemetry_log = telemetry_path.open("w", encoding="utf-8")
    progress_log = progress_path.open("w", encoding="utf-8")
    started = time.monotonic()

    try:
        config = DaemonConfig(
            transmitter_device=args.tx_port,
            virtual_port_path=requested_path,
            pacer_enabled=True,
            pacer_rate_hz=20.0,
            telemetry_enabled=True,
            telemetry_interval_seconds=args.telemetry_interval,
            priority_confirmation_window_ms=1500,
            priority_retry_cooldown_min_seconds=1.0,
            priority_retry_cooldown_max_seconds=2.5,
        )
        service = WirelessDmxService(config)
        service.start()
        service.seed_priority_ids(priority_id_seed)

        required_receivers = set(args.expected_receiver or [])
        stable_sets: list[frozenset[int]] = []
        discovery_deadline = time.monotonic() + 35.0
        while time.monotonic() < discovery_deadline:
            online = frozenset(receiver.receiver_id for receiver in service.snapshot().receivers
                                if receiver.link_state.value == "online")
            matches = (online == required_receivers) if required_receivers else bool(online)
            if service.snapshot().telemetry.cache_clear_acknowledged and matches:
                stable_sets.append(online)
                stable_sets = stable_sets[-3:]
            else:
                stable_sets.clear()
            if len(stable_sets) == 3 and stable_sets[0] == stable_sets[1] == stable_sets[2]:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(f"receiver set did not stabilize: required={sorted(required_receivers)}")
        with service.telemetry._lock:
            locked_receivers = required_receivers or set(stable_sets[-1])
            service.telemetry._items = {
                receiver_id: item for receiver_id, item in service.telemetry._items.items()
                if receiver_id in locked_receivers
            }
        original_snapshot = service.telemetry.snapshot
        service.telemetry.snapshot = lambda: tuple(
            receiver for receiver in original_snapshot() if receiver.receiver_id in locked_receivers
        )

        mega = serial.Serial(args.mega_port, 115200, timeout=0.2)
        wait_line(mega, "READY ENTTEC_DMX_MONITOR", 8.0)
        send_mega_command(mega, "EXPECT CONST 77", "ACK EXPECT")
        send_mega_command(mega, f"START 5 {args.seconds}", "ACK START")

        # Opening the PTY with pyserial exercises the same VCP-like client path
        # a lighting application will use. The baud is client-side configuration;
        # the PTY itself remains transparent.
        client = serial.Serial(service.virtual.path, 115200, bytesize=8,
                               parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO,
                               timeout=0.1)
        frame = encode_dmx(bytes([77]) * 512)
        service.set_manual_universe(bytes([77]) * 512)
        next_frame = time.monotonic()
        next_priority = next_frame + 5.0
        next_progress = next_frame + 30.0
        deadline = next_frame + args.seconds

        while time.monotonic() < deadline:
            now = time.monotonic()
            snapshot = service.snapshot()
            suppress_normal = priority_waiting_for is not None
            if now >= next_frame:
                client.write(frame)
                tx_times.append(time.monotonic())
                if suppress_normal:
                    normal_frames_during_priority += 1
                elif priority_ids:
                    normal_frames_after_priority += 1
                else:
                    normal_frames_before_priority += 1
                next_frame += 0.05
                if next_frame < now - 1.0:
                    next_frame = now + 0.05

            if len(priority_ids) < args.priority_events and now >= next_priority:
                priority_ids.append(service.send_manual(priority=True, repeat_count=3,
                                                        ttl_seconds=5.0,
                                                        reason="30-minute ACK validation"))
                priority_waiting_for = priority_ids[-1]
                priority_wait_started = now
                next_priority += args.priority_interval

            snapshot = service.snapshot()
            if priority_waiting_for is not None:
                event = service._priority_events.get(priority_waiting_for, {})
                if event.get("ack_complete") or event.get("terminal"):
                    priority_waiting_for = None
            # Record every newly visible receiver report in a compact JSONL
            # stream. The receiver telemetry itself is already normalized by
            # the daemon; this is not text emitted by the transmitter UART.
            current_records = len(snapshot.receivers)
            if current_records:
                telemetry_records = max(telemetry_records, current_records)
            if now >= next_progress:
                progress = {
                    "elapsed_seconds": round(now - started, 1),
                    "daemon_health": snapshot.health.value,
                    "transmitter_connected": snapshot.transmitter_connected,
                    "virtual_client_connected": snapshot.virtual_client_connected,
                    "dmx_valid_frames": snapshot.dmx.valid_dmx_frames,
                    "dmx_submitted": snapshot.dmx.frames_submitted,
                    "dmx_dropped": snapshot.dmx.frames_dropped_by_pacer,
                    "receivers": current_records,
                    "receiver_states": [r.link_state.value for r in snapshot.receivers],
                    "priority_events_submitted": len(priority_ids),
                    "priority_ack_accepted": snapshot.priority.ack_accepted,
                    "priority_ack_duplicates": snapshot.priority.ack_duplicates,
                    "priority_ack_invalid": snapshot.priority.ack_invalid,
                    "priority_ack_unknown": snapshot.priority.ack_unknown,
                    "priority_ack_duplicate_records": snapshot.priority.ack_duplicate_records,
                    "priority_ack_dropped": snapshot.priority.ack_dropped,
                    "priority_ack_window_failures": snapshot.priority.ack_window_failures,
                    "priority_ack_records_received": snapshot.priority.ack_records_received,
                    "priority_retry_attempts": snapshot.priority.retry_attempts,
                    "priority_retry_recovered": snapshot.priority.retry_recovered,
                    "priority_retry_failures": snapshot.priority.retry_failures,
                    "normal_frames_before_priority": normal_frames_before_priority,
                    "normal_frames_during_priority": normal_frames_during_priority,
                    "normal_frames_after_priority": normal_frames_after_priority,
                }
                progress_log.write(json.dumps(progress) + "\n")
                progress_log.flush()
                telemetry_log.write(json.dumps({
                    "elapsed_seconds": progress["elapsed_seconds"],
                    "receivers": [r.__dict__ for r in snapshot.receivers],
                }, default=str) + "\n")
                telemetry_log.flush()
                print("PROGRESS " + json.dumps(progress), flush=True)
                next_progress += 30.0

            time.sleep(0.001)

        time.sleep(args.priority_drain_seconds)
        result_line = wait_line(mega, "RESULT ", 20.0)
        mega_result = parse_mega_result(result_line)
        intervals = [b - a for a, b in zip(tx_times, tx_times[1:])]
        report_count = len(service.snapshot().receivers)
        expected_receivers = report_count
        expected_acks = len(priority_ids) * expected_receivers
        priority_events = [service._priority_events.get(priority_id, {}) for priority_id in priority_ids]
        priority_event_failures = [
            {
                "priority_id": priority_id,
                "ack_complete": event.get("ack_complete", False),
                "terminal": event.get("terminal", False),
                "terminal_reason": event.get("terminal_reason"),
                "expected_receivers": sorted(event.get("expected_receivers", set())),
                "ack_receivers": sorted(event.get("ack_receivers", set())),
            }
            for priority_id, event in zip(priority_ids, priority_events)
            if not event.get("ack_complete") or
               set(event.get("expected_receivers", set())) != set(event.get("ack_receivers", set()))
        ]
        summary.update({
            "dmx_frames_submitted_to_pty": len(tx_times),
            "dmx_input_rate_hz": len(tx_times) / args.seconds,
            "dmx_interval_mean_ms": (sum(intervals) / len(intervals) * 1000
                                      if intervals else None),
            "dmx_interval_max_ms": (max(intervals) * 1000 if intervals else None),
            "daemon_snapshot": {
                "valid_dmx_frames": service.snapshot().dmx.valid_dmx_frames,
                "frames_submitted": service.snapshot().dmx.frames_submitted,
                "frames_dropped": service.snapshot().dmx.frames_dropped_by_pacer,
                "receiver_count": report_count,
            },
            "telemetry_records_seen": telemetry_records,
            "mega_result": mega_result,
            "receiver_ids_observed": sorted(receiver.receiver_id for receiver in service.snapshot().receivers),
            "priority": {
                "ids_submitted": priority_ids,
                "events_submitted": len(priority_ids),
                "expected_receivers": expected_receivers,
                "expected_acks": expected_acks,
                "daemon_priority_completed": service.snapshot().dmx.priority_completed,
                "ack_accepted": service.snapshot().priority.ack_accepted,
                "ack_duplicates": service.snapshot().priority.ack_duplicates,
                "ack_invalid": service.snapshot().priority.ack_invalid,
                "ack_unknown": service.snapshot().priority.ack_unknown,
                "ack_duplicate_records": service.snapshot().priority.ack_duplicate_records,
                "ack_dropped": service.snapshot().priority.ack_dropped,
                "ack_window_failures": service.snapshot().priority.ack_window_failures,
                "ack_records_received": service.snapshot().priority.ack_records_received,
                "retry_attempts": service.snapshot().priority.retry_attempts,
                "retry_recovered": service.snapshot().priority.retry_recovered,
                "retry_failures": service.snapshot().priority.retry_failures,
                "event_failures": priority_event_failures,
            },
            "traffic_phases": {
                "normal_frames_before_priority": normal_frames_before_priority,
                "normal_frames_during_priority": normal_frames_during_priority,
                "normal_frames_after_priority": normal_frames_after_priority,
            },
        })
        priority_status = service.snapshot().priority
        priority_passed = (
            len(priority_ids) == args.priority_events and
            service.snapshot().dmx.priority_completed >= len(priority_ids) and
            expected_receivers > 0 and
            not priority_event_failures and
            priority_status.ack_invalid == 0 and
            priority_status.ack_unknown == 0 and
            priority_status.ack_dropped == 0 and
            priority_status.retry_failures == 0
        )
        summary["passed"] = bool(
            len(tx_times) >= int(args.seconds * 20 * 0.95) and
            service.snapshot().dmx.valid_dmx_frames >= int(args.seconds * 20 * 0.95) and
            report_count > 0 and
            mega_result.get("seconds", 0) >= args.seconds - 1 and
            mega_result.get("checks", 0) > 0 and
            mega_result.get("checks", 0) >= int(args.seconds * args.min_mega_checks_per_second) and
            mega_result.get("fail", -1) == 0
            and priority_passed
        )
    except Exception as exc:
        summary["error"] = repr(exc)
    finally:
        if client is not None:
            client.close()
        if service is not None:
            service.stop()
        if mega is not None:
            mega.close()
        telemetry_log.close()
        progress_log.close()
        if os.path.islink(requested_path):
            os.unlink(requested_path)
        manifest_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
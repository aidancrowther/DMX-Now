#!/usr/bin/env python3
"""Short live priority soak using the transmitter and attached receivers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wireless_dmx.app import WirelessDmxService
from wireless_dmx.models import DaemonConfig
from wireless_dmx.virtual_serial.linux_pty import LinuxPtyBackend


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tx-port", default="/dev/ttyUSB0")
    parser.add_argument("--events", type=int, default=10)
    parser.add_argument("--spacing", type=float, default=10.0)
    parser.add_argument("--expected-receiver", action="append", type=lambda value: int(value, 0),
                        help="receiver ID expected after discovery; may be repeated")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    path = f"/tmp/wireless-dmx-priority-soak-{os.getpid()}"
    config = DaemonConfig(
        transmitter_device=args.tx_port,
        virtual_port_path=path,
        artnet_enabled=False,
        telemetry_interval_seconds=1.0,
        telemetry_response_timeout_seconds=1.0,
        priority_confirmation_window_ms=1500,
        priority_lead_in_ms=500,
        priority_lead_out_ms=500,
        priority_retry_cooldown_min_seconds=1.0,
        priority_retry_cooldown_max_seconds=1.0,
        priority_max_attempts=5,
    )
    service = WirelessDmxService(config, virtual_backend=LinuxPtyBackend(path))
    seed = (int(time.time()) ^ (os.getpid() << 16)) & 0xFFFFFFFF
    results = []
    service.start()
    try:
        required = set(args.expected_receiver or [])
        deadline = time.monotonic() + 30
        stable_sets = []
        while time.monotonic() < deadline:
            snapshot = service.snapshot()
            online = frozenset(receiver.receiver_id for receiver in snapshot.receivers
                                if receiver.link_state.value == "online")
            if snapshot.telemetry.cache_clear_acknowledged and online and (not required or required <= online):
                stable_sets.append(online)
                stable_sets = stable_sets[-3:]
            else:
                stable_sets.clear()
            if len(stable_sets) == 3 and stable_sets[0] == stable_sets[1] == stable_sets[2]:
                break
            time.sleep(0.1)
        snapshot = service.snapshot()
        expected = required or (set(stable_sets[-1]) if stable_sets else set())
        if not expected:
            raise RuntimeError("no fresh online receivers discovered")
        service.seed_priority_ids(seed)
        service.set_manual_universe(bytes([0x5A]) * 512)

        for index in range(args.events):
            priority_id = service.send_manual(priority=True, repeat_count=3,
                                              ttl_seconds=5.0,
                                              reason="priority short soak")
            # Allow every configured attempt to complete: confirmation window,
            # retry cooldown, and lead-in/lead-out overhead all contribute to
            # the end-to-end time before an event can become terminal.
            event_timeout = (
                config.priority_max_attempts *
                (config.priority_confirmation_window_ms / 1000.0 +
                 config.priority_retry_cooldown_max_seconds +
                 (config.priority_lead_in_ms + config.priority_lead_out_ms) / 1000.0)
                + 2.0
            )
            deadline = time.monotonic() + event_timeout
            while time.monotonic() < deadline:
                event = service._priority_events[priority_id]
                if event.get("terminal"):
                    break
                time.sleep(0.05)
            event = service._priority_events[priority_id]
            result = {
                "index": index,
                "priority_id": priority_id,
                "expected_receivers": sorted(expected),
                "first_attempt_ack_receivers": sorted(event.get("first_attempt_ack_receivers", set())),
                "ack_receivers": sorted(event.get("ack_receivers", set())),
                "attempt": event["attempt"],
                "retry_count": event["retry_count"],
                "ack_complete": event.get("ack_complete", False),
                "terminal": event["terminal"],
                "terminal_reason": event.get("terminal_reason"),
            }
            results.append(result)
            print("EVENT " + json.dumps(result), flush=True)
            if not result["ack_complete"]:
                print("ABORT missed priority event " + json.dumps(result), flush=True)
                break
            if index + 1 < args.events:
                time.sleep(max(args.spacing, 5.0))

        summary = {
            "seed": seed,
            "events": len(results),
            "first_attempt_successes": sum(set(r["first_attempt_ack_receivers"]) >= expected for r in results),
            "retry_recovered_events": sum(r["ack_complete"] and r["retry_count"] > 0 for r in results),
            "failed_events": sum(not r["ack_complete"] for r in results),
            "unknown_acks": service.snapshot().priority.ack_unknown,
            "invalid_acks": service.snapshot().priority.ack_invalid,
            "duplicate_ack_records": service.snapshot().priority.ack_duplicate_records,
            "retry_failures": service.snapshot().priority.retry_failures,
            "results": results,
        }
        print("SUMMARY " + json.dumps(summary), flush=True)
        if summary["failed_events"] or summary["unknown_acks"] or summary["invalid_acks"] or summary["retry_failures"]:
            return 1
        if args.output:
            args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return 0
    finally:
        service.stop()


if __name__ == "__main__":
    raise SystemExit(main())
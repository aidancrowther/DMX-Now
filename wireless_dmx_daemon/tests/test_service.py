import os
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.app import WirelessDmxService
from wireless_dmx.enttec.protocol import encode_dmx
from wireless_dmx.models import DaemonConfig, ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.protocols import (MANAGEMENT_CACHE_CLEARED, MANAGEMENT_PRIORITY_ACKS,
                                    MANAGEMENT_RECEIVER_TELEMETRY, MANAGEMENT_SYNC, crc16_ccitt)
from wireless_dmx.transmitter.management import ACK_HEADER, ACK_RECORD, PART_HEADER, RECORD
from wireless_dmx.virtual_serial.linux_pty import LinuxPtyBackend


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.closed = False
        self.reads = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size=1):
        return self.reads.pop(0) if self.reads else b""

    def close(self):
        self.closed = True


def telemetry_part():
    record = RECORD.pack(7, bytes.fromhex("18fe34000007"), 1, 0, -25, -30,
                         100, 9, 10, 1, 0, 2, 100, 1, 1, 0, 4)
    payload = PART_HEADER.pack(1, 0, 1, 1, 4) + record
    body = bytes((1, MANAGEMENT_RECEIVER_TELEMETRY)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


class ServiceTests(unittest.TestCase):
    def test_service_forwards_normalized_pty_dmx_to_fake_transmitter(self):
        backend = LinuxPtyBackend()
        fake = FakeSerial()
        factory = lambda: fake
        # Empty requested path is invalid, so use a temporary PTY without a link.
        config = DaemonConfig(virtual_port_path="/tmp/wireless-dmx-service-test")
        service = WirelessDmxService(config, serial_factory=factory, virtual_backend=backend)
        service.start()
        try:
            with open(backend.path, "wb", buffering=0) as client:
                client.write(encode_dmx(bytes([0x44]) * 512))
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline and service.snapshot().dmx.frames_submitted < 1:
                    time.sleep(0.01)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not any(write.startswith(b"~\x06") for write in fake.writes):
                time.sleep(0.01)
            self.assertTrue(any(write.startswith(b"~\x06") for write in fake.writes))
            self.assertEqual(service.snapshot().dmx.valid_dmx_frames, 1)
        finally:
            service.stop()

    def test_transmitter_management_data_updates_snapshot(self):
        backend = LinuxPtyBackend()
        fake = FakeSerial()
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-service-test-2"),
            serial_factory=lambda: fake, virtual_backend=backend)
        service._on_transmitter_data(telemetry_part())
        snapshot = service.snapshot()
        self.assertEqual(len(snapshot.receivers), 1)
        self.assertEqual(snapshot.receivers[0].receiver_id, 7)
        self.assertEqual(snapshot.receivers[0].transmitter_rssi, -25)

    def test_service_start_clears_telemetry_store(self):
        service = WirelessDmxService(DaemonConfig(virtual_port_path="/tmp/wireless-dmx-clear"),
                                     serial_factory=lambda: FakeSerial(),
                                     virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-clear"))
        service.telemetry.update(ReceiverTelemetry(7, "00:00:00:00:00:07", ReceiverLinkState.ONLINE,
                                                   False, -1, -1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1))
        service.start()
        try:
            self.assertEqual(service.snapshot().receivers, ())
        finally:
            service.stop()

    def test_service_waits_for_cache_clear_before_polling(self):
        fake = FakeSerial()
        service = WirelessDmxService(DaemonConfig(virtual_port_path="/tmp/wireless-dmx-cache-handshake"),
                                     serial_factory=lambda: fake,
                                     virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-cache-handshake"))
        service.start()
        try:
            time.sleep(0.05)
            self.assertFalse(service.snapshot().telemetry.cache_clear_acknowledged)
            self.assertFalse(any(write[3] == 0x81 for write in fake.writes if len(write) > 3))
            body = bytes((1, MANAGEMENT_CACHE_CLEARED, 0, 0))
            fake.reads.append(MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body)))
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and not service.snapshot().telemetry.cache_clear_acknowledged:
                time.sleep(0.01)
            self.assertTrue(service.snapshot().telemetry.cache_clear_acknowledged)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline and service.snapshot().telemetry.requests_sent == 0:
                time.sleep(0.01)
            self.assertGreater(service.snapshot().telemetry.requests_sent, 0)
        finally:
            service.stop()

    def test_priority_ack_updates_snapshot_and_deduplicates_records(self):
        fake = FakeSerial()
        service = WirelessDmxService(DaemonConfig(virtual_port_path="/tmp/wireless-dmx-acks"),
                                     serial_factory=lambda: fake, virtual_backend=LinuxPtyBackend())
        service._priority_submissions[42] = time.monotonic()
        record = ACK_RECORD.pack(42, 7, 99, 1, 1, 3, -41, 1234, 37)
        payload = ACK_HEADER.pack(1, 1, 5, 1, 0, 0, 0) + record
        body = bytes((1, MANAGEMENT_PRIORITY_ACKS)) + struct.pack("<H", len(payload)) + payload
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        service._on_transmitter_data(frame + frame)
        priority = service.snapshot().priority
        self.assertEqual(priority.ack_accepted, 1)
        self.assertEqual(priority.ack_duplicate_records, 1)
        self.assertEqual(priority.ack_unknown, 0)

    def test_priority_ack_with_new_frame_sequence_is_still_a_duplicate_event(self):
        fake = FakeSerial()
        service = WirelessDmxService(DaemonConfig(virtual_port_path="/tmp/wireless-dmx-acks-seq"),
                                     serial_factory=lambda: fake, virtual_backend=LinuxPtyBackend())
        service._priority_submissions[42] = time.monotonic()
        records = (
            ACK_RECORD.pack(42, 7, 99, 1, 1, 3, -41, 1234, 37),
            ACK_RECORD.pack(42, 7, 100, 1, 1, 3, -41, 1240, 41),
        )
        payload = ACK_HEADER.pack(1, 2, 6, 2, 0, 0, 0) + b"".join(records)
        body = bytes((1, MANAGEMENT_PRIORITY_ACKS)) + struct.pack("<H", len(payload)) + payload
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        service._on_transmitter_data(frame)
        priority = service.snapshot().priority
        self.assertEqual(priority.ack_accepted, 2)
        self.assertEqual(priority.ack_duplicate_records, 1)

    def test_unmatched_ack_timing_sentinel_is_not_a_window_failure(self):
        fake = FakeSerial()
        service = WirelessDmxService(DaemonConfig(virtual_port_path="/tmp/wireless-dmx-ack-sentinel"),
                                     serial_factory=lambda: fake, virtual_backend=LinuxPtyBackend())
        service._priority_submissions[42] = time.monotonic()
        record = ACK_RECORD.pack(42, 7, 99, 1, 1, 3, -41, 1234, 0xFFFF)
        payload = ACK_HEADER.pack(1, 1, 5, 1, 0, 0, 0) + record
        body = bytes((1, MANAGEMENT_PRIORITY_ACKS)) + struct.pack("<H", len(payload)) + payload
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        service._on_transmitter_data(frame)
        self.assertEqual(service.snapshot().priority.ack_window_failures, 0)

    def test_manual_channel_and_priority_submission(self):
        fake = FakeSerial()
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-manual-test"),
            serial_factory=lambda: fake,
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-manual-test"),
        )
        service.set_manual_channel(1, 255)
        self.assertEqual(service.manual_universe_snapshot()[0], 255)
        with self.assertRaises(ValueError):
            service.set_manual_channel(513, 1)
        priority_id = service.send_manual(priority=True, repeat_count=1, ttl_seconds=1)
        self.assertEqual(priority_id, 0)
        self.assertEqual(service.pacer.priority_status().queue_depth, 1)

    def test_priority_id_seed_is_used_before_submission(self):
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-seed-test"),
            serial_factory=lambda: FakeSerial(),
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-seed-test"),
        )
        service.seed_priority_ids(0x12345678)
        self.assertEqual(service.send_manual(priority=True, repeat_count=1, ttl_seconds=1), 0x12345678)

    def test_priority_retry_increments_attempt_without_changing_id(self):
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-retry-test",
                         priority_confirmation_window_ms=10,
                         priority_retry_cooldown_min_seconds=0,
                         priority_retry_cooldown_max_seconds=0),
            serial_factory=lambda: FakeSerial(),
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-retry-test"),
        )
        priority_id = service.send_manual(priority=True, repeat_count=1, ttl_seconds=1)
        event = service._priority_events[priority_id]
        service.pacer._priority_queue.clear()
        now = event["last_attempt_at"] + 1
        service._service_priority_retries(now)
        service._service_priority_retries(event["retry_due_at"])
        self.assertEqual(service.snapshot().priority.retry_attempts, 1)
        self.assertEqual(service._priority_events[priority_id]["attempt"], 2)
        self.assertEqual(service._priority_events[priority_id]["expected_receivers"], set())
        self.assertFalse(service._priority_events[priority_id]["ack_complete"])

    def test_priority_retry_waits_for_configured_cooldown(self):
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-retry-cooldown",
                         priority_confirmation_window_ms=10,
                         priority_retry_cooldown_min_seconds=2,
                         priority_retry_cooldown_max_seconds=2),
            serial_factory=lambda: FakeSerial(),
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-retry-cooldown"),
        )
        priority_id = service.send_manual(priority=True, repeat_count=1, ttl_seconds=1)
        event = service._priority_events[priority_id]
        service.pacer._priority_queue.clear()
        expired = event["last_attempt_at"] + 1
        service._service_priority_retries(expired)
        self.assertEqual(service.snapshot().priority.retry_attempts, 0)
        self.assertIsNotNone(event["retry_due_at"])
        service._service_priority_retries(event["retry_due_at"] - 0.001)
        self.assertEqual(service.snapshot().priority.retry_attempts, 0)
        service._service_priority_retries(event["retry_due_at"])
        self.assertEqual(service.snapshot().priority.retry_attempts, 1)

    def test_priority_ack_on_retry_recovers_same_receiver_event(self):
        fake = FakeSerial()
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-retry-ack-test"),
            serial_factory=lambda: fake,
            virtual_backend=LinuxPtyBackend(),
        )
        service._priority_submissions[42] = time.monotonic()
        service._priority_events[42] = {
            "universe": bytes(512), "repeat_count": 1, "ttl_seconds": 1.0,
            "reason": "test", "attempt": 2, "last_attempt_at": time.monotonic(),
            "retry_count": 1, "terminal": False, "expected_receivers": {7},
            "ack_complete": False, "ack_receivers": set(),
            "first_attempt_ack_receivers": set(), "ack_completed_at": None,
        }
        record = ACK_RECORD.pack(42, 7, 101, 2, 1, 1, -41, 1234, 37)
        payload = ACK_HEADER.pack(1, 1, 7, 1, 0, 0, 0) + record
        body = bytes((1, MANAGEMENT_PRIORITY_ACKS)) + struct.pack("<H", len(payload)) + payload
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        service._on_transmitter_data(frame)
        priority = service.snapshot().priority
        self.assertEqual(priority.ack_records_received, 1)
        self.assertEqual(priority.retry_recovered, 1)
        self.assertEqual(priority.ack_duplicate_records, 0)
        self.assertTrue(service._priority_events[42]["ack_complete"])
        self.assertEqual(service._priority_events[42]["ack_receivers"], {7})

    def test_management_queue_does_not_evict_dmx(self):
        fake = FakeSerial()
        from wireless_dmx.transmitter.connection import TransmitterConnection
        connection = TransmitterConnection(DaemonConfig(), lambda data: None, lambda: fake)
        connection.send_latest(b"dmx")
        connection.send_immediate(b"mgmt")
        connection.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and len(fake.writes) < 2:
            time.sleep(0.01)
        connection.stop()
        self.assertEqual(fake.writes[:2], [b"mgmt", b"dmx"])

    def test_management_queue_preserves_priority_marker_order(self):
        fake = FakeSerial()
        from wireless_dmx.transmitter.connection import TransmitterConnection
        connection = TransmitterConnection(DaemonConfig(), lambda data: None, lambda: fake)
        connection.send_immediate(b"marker")
        connection.send_immediate(b"ack-poll")
        connection.start()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and len(fake.writes) < 2:
            time.sleep(0.01)
        connection.stop()
        self.assertEqual(fake.writes[:2], [b"marker", b"ack-poll"])

    def test_telemetry_request_is_reissued_after_timeout(self):
        fake = FakeSerial()
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-telemetry-timeout",
                         telemetry_interval_seconds=0.05,
                         telemetry_response_timeout_seconds=0.01),
            serial_factory=lambda: fake,
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-telemetry-timeout"),
        )
        service.start()
        try:
            body = bytes((1, MANAGEMENT_CACHE_CLEARED, 0, 0))
            fake.reads.append(MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body)))
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and service.snapshot().telemetry.requests_sent < 3:
                time.sleep(0.01)
            snapshot = service.snapshot()
            self.assertGreaterEqual(snapshot.telemetry.requests_sent, 3)
            self.assertGreaterEqual(snapshot.telemetry.consecutive_failures, 1)
            self.assertLessEqual(snapshot.telemetry.requests_sent, 8)
        finally:
            service.stop()

    def test_telemetry_report_clears_in_flight_request(self):
        fake = FakeSerial()
        service = WirelessDmxService(
            DaemonConfig(virtual_port_path="/tmp/wireless-dmx-telemetry-success"),
            serial_factory=lambda: fake,
            virtual_backend=LinuxPtyBackend("/tmp/wireless-dmx-telemetry-success"),
        )
        service._telemetry_request_started = time.monotonic()
        service._telemetry_requests_sent = 1
        service._on_transmitter_data(telemetry_part())
        # The report is complete and should be counted even when injected by a
        # fake transport rather than received by the background thread.
        self.assertEqual(service.snapshot().telemetry.reports_received, 1)
        self.assertFalse(service.snapshot().telemetry.request_in_flight)


if __name__ == "__main__":
    unittest.main()
import os
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.app import WirelessDmxService
from wireless_dmx.enttec.protocol import encode_dmx
from wireless_dmx.models import DaemonConfig
from wireless_dmx.protocols import MANAGEMENT_RECEIVER_TELEMETRY, MANAGEMENT_SYNC, crc16_ccitt
from wireless_dmx.transmitter.management import PART_HEADER, RECORD
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
                         100, 9, 10, 1, 0, 2, 100, 1, 1, 0)
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


if __name__ == "__main__":
    unittest.main()
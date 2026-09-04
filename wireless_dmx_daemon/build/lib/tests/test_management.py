import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.models import ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.protocols import MANAGEMENT_RECEIVER_TELEMETRY, MANAGEMENT_SYNC, crc16_ccitt
from wireless_dmx.transmitter.management import ManagementParser, PART_HEADER, RECORD, get_telemetry_request


def make_part(sequence, index, count, records):
    payload = PART_HEADER.pack(1, index, count, len(records), sequence)
    for record in records:
        payload += RECORD.pack(record.receiver_id, bytes.fromhex(record.mac_address.replace(":", "")),
                               1, int(record.battery_low), record.transmitter_rssi,
                               record.receiver_last_rssi, record.uptime_seconds,
                               record.last_active_sequence, record.complete_universes,
                               record.incomplete_universes, record.malformed_packets,
                               record.time_since_last_universe_ms, record.transmitter_last_seen_ms,
                               record.firmware_version, record.protocol_version, 0)
    body = bytes((1, MANAGEMENT_RECEIVER_TELEMETRY)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


class ManagementTests(unittest.TestCase):
    def test_request_has_valid_crc(self):
        request = get_telemetry_request()
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_fragmented_multipart_response(self):
        record = ReceiverTelemetry(1, "18:fe:34:00:00:01", ReceiverLinkState.ONLINE, False,
                                   -30, -31, 10, 2, 3, 0, 0, 2, 100, 1, 1, 0)
        first = make_part(8, 0, 2, [record])
        second = make_part(8, 1, 2, [])
        parser = ManagementParser()
        parts = []
        for byte in first + second:
            parts.extend(parser.feed(bytes([byte])))
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].part_index, 0)
        self.assertEqual(parts[0].records[0].receiver_id, 1)
        self.assertEqual(parts[1].part_index, 1)

    def test_bad_crc_is_ignored(self):
        parser = ManagementParser()
        frame = bytearray(make_part(1, 0, 1, []))
        frame[-1] ^= 0xFF
        self.assertEqual(parser.feed(bytes(frame)), [])


if __name__ == "__main__":
    unittest.main()
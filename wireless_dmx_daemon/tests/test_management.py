import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.models import ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.models import PriorityAck
from wireless_dmx.protocols import (MANAGEMENT_PRIORITY_ACKS, MANAGEMENT_RECEIVER_TELEMETRY,
                                    MANAGEMENT_SYNC, crc16_ccitt)
from wireless_dmx.transmitter.management import (ACK_HEADER, ACK_RECORD, ManagementParser,
                                                 PART_HEADER, RECORD, get_priority_acks_request,
                                                  clear_receiver_cache_request, get_telemetry_request,
                                                   mark_next_priority, set_receiver_failsafe_request)


def make_part(sequence, index, count, records):
    payload = PART_HEADER.pack(1, index, count, len(records), sequence)
    for record in records:
        payload += RECORD.pack(record.receiver_id, bytes.fromhex(record.mac_address.replace(":", "")),
                               1, int(record.battery_low), record.transmitter_rssi,
                               record.receiver_last_rssi, record.uptime_seconds,
                               record.last_active_sequence, record.complete_universes,
                               record.incomplete_universes, record.malformed_packets,
                               record.time_since_last_universe_ms, record.transmitter_last_seen_ms,
                               record.firmware_version, record.protocol_version, 0,
                               record.telemetry_sequence, {"hold": 0, "blackout": 1,
                               "disable_line": 2}[record.failsafe_mode],
                               int(record.failsafe_active), record.failsafe_timeout_seconds,
                               record.failsafe_generation, record.failsafe_activations)
    body = bytes((1, MANAGEMENT_RECEIVER_TELEMETRY)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


class ManagementTests(unittest.TestCase):
    def test_request_has_valid_crc(self):
        request = get_telemetry_request()
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_priority_ack_request_has_valid_crc(self):
        request = get_priority_acks_request()
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_priority_marker_can_carry_gate_mask(self):
        request = mark_next_priority(42, 3, 2, 7, bytes([0x01]) + bytes(63))
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(struct.unpack_from("<H", request, 4)[0], 75)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_clear_cache_request_has_valid_crc(self):
        request = clear_receiver_cache_request()
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_failsafe_request_has_valid_crc(self):
        request = set_receiver_failsafe_request("disable_line", 60, 17)
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(struct.unpack_from("<H", request, 4)[0], 8)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_clear_cache_response_is_parsed(self):
        body = bytes((1, 0x84, 0, 0))
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        response = ManagementParser().feed(frame)[0]
        self.assertTrue(response.acknowledged)

    def test_priority_ack_report_round_trip(self):
        record = ACK_RECORD.pack(42, 7, 99, 1, 1, 3, -41, 1234, 37)
        payload = ACK_HEADER.pack(1, 1, 5, 8, 2, 1, 0) + record
        body = bytes((1, MANAGEMENT_PRIORITY_ACKS)) + struct.pack("<H", len(payload)) + payload
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        report = ManagementParser().feed(frame)[0]
        self.assertEqual(report.report_sequence, 5)
        self.assertEqual(report.accepted_count, 8)
        self.assertEqual(report.records[0].priority_id, 42)
        self.assertEqual(report.records[0].receiver_id, 7)
        self.assertEqual(report.records[0].received_at_ms, 1234)
        self.assertEqual(report.records[0].ack_delay_ms, 37)

    def test_fragmented_multipart_response(self):
        record = ReceiverTelemetry(1, "18:fe:34:00:00:01", ReceiverLinkState.ONLINE, False,
                                   -30, -31, 10, 2, 3, 0, 0, 2, 100, 1, 1, 0x12345678)
        first = make_part(8, 0, 2, [record])
        second = make_part(8, 1, 2, [])
        parser = ManagementParser()
        parts = []
        for byte in first + second:
            parts.extend(parser.feed(bytes([byte])))
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0].part_index, 0)
        self.assertEqual(parts[0].records[0].receiver_id, 1)
        self.assertEqual(parts[0].records[0].telemetry_sequence, 0x12345678)
        self.assertEqual(parts[1].part_index, 1)

    def test_extended_telemetry_record_round_trip(self):
        record = ReceiverTelemetry(1, "18:fe:34:00:00:01", ReceiverLinkState.ONLINE, False,
                                   -30, -31, 10, 2, 3, 0, 0, 2, 100, 2, 1, 0x12345678,
                                   "blackout", True, 60, 9, 4)
        frame = make_part(9, 0, 1, [record])
        parsed = ManagementParser().feed(frame)[0].records[0]
        self.assertEqual(parsed.failsafe_mode, "blackout")
        self.assertTrue(parsed.failsafe_active)
        self.assertEqual(parsed.failsafe_generation, 9)

    def test_bad_crc_is_ignored(self):
        parser = ManagementParser()
        frame = bytearray(make_part(1, 0, 1, []))
        frame[-1] ^= 0xFF
        self.assertEqual(parser.feed(bytes(frame)), [])


if __name__ == "__main__":
    unittest.main()
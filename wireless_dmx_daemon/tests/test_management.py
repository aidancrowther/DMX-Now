import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.models import ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.models import PriorityAck
from wireless_dmx.protocols import (MANAGEMENT_PRIORITY_ACKS, MANAGEMENT_RECEIVER_TELEMETRY,
                                    MANAGEMENT_OBSERVED_UNIVERSE, MANAGEMENT_SYNC, crc16_ccitt)
from wireless_dmx.transmitter.management import (ACK_HEADER, ACK_RECORD, ManagementParser,
                                                 PART_HEADER, RECORD, get_priority_acks_request,
                                                  clear_receiver_cache_request, get_telemetry_request,
                                                   get_observed_universe_request,
                                                    mark_next_priority, set_receiver_failsafe_request,
                                                    set_receiver_output_request, locate_receiver_request)
from wireless_dmx.transmitter.management import (TransmitterModeResponse, get_transmitter_mode_request,
                                                 set_transmitter_mode_request)
from wireless_dmx.receiver_diagnostic import (DIAGNOSTIC_MAGIC, ReceiverDiagnosticParser,
                                               mask_accounting, parse_summary_line)
from wireless_dmx.retransmitter_patterns import dynamic_mismatches, dynamic_universe


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
    def test_observed_universe_request_has_management_crc(self):
        request = get_observed_universe_request()
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(request[3], 0x0A)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_observed_universe_multipart_parts_round_trip(self):
        header = struct.Struct("<BBBBIIH6s")
        universe = bytes(range(256)) * 2
        parser = ManagementParser()
        parts = []
        for index, offset in enumerate((0, 180, 360)):
            data = universe[offset:offset + (180 if index < 2 else 152)]
            payload = header.pack(1, index, 3, 0, 77, 12, offset, bytes.fromhex("18fe34000001")) + data
            body = bytes((1, MANAGEMENT_OBSERVED_UNIVERSE)) + struct.pack("<H", len(payload)) + payload
            frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
            parts.extend(parser.feed(frame))
        self.assertEqual([part.offset for part in parts], [0, 180, 360])
        self.assertEqual(b"".join(part.data for part in parts), universe)
    def test_rds1_summary_parser_and_mask_accounting(self):
        values = parse_summary_line("RDS1 m001=2 m111=5 qrx_evictions=0")
        self.assertEqual(values["m001"], 2)
        self.assertEqual(values["qrx_evictions"], 0)
        self.assertEqual(mask_accounting({1: 2, 3: 1, 7: 5}), {
            "observed_frames": 8, "fragment_0": 8, "fragment_1": 6, "fragment_2": 5})

    def test_acceptance_summary_maps_fragment_diagnostics(self):
        values = parse_summary_line("RDS1 rx0=10 rx1=9 rx2=8 m101=3 unseen_sequences=4")
        self.assertEqual(values["rx0"], 10)
        self.assertEqual(values["m101"], 3)
        self.assertEqual(values["unseen_sequences"], 4)

    def test_rds1_summary_parser_maps_transmitter_diagnostics(self):
        values = parse_summary_line("RDS1 txdiag=8 txa0=100 txe1=99 txf2=1 txcbfail=2")
        self.assertEqual(values["txdiag"], 8)
        self.assertEqual(values["txa0"], 100)
        self.assertEqual(values["txe1"], 99)
        self.assertEqual(values["txf2"], 1)
        self.assertEqual(values["txcbfail"], 2)

    def test_rds1_summary_parser_rejects_wrong_prefix(self):
        with self.assertRaises(ValueError):
            parse_summary_line("STATUS capture=idle")

    def test_dynamic_partial_pattern_is_coherent_and_zero_filled(self):
        universe = dynamic_universe(91, 236, 17)
        self.assertEqual(dynamic_mismatches(universe, 91, 236), [])
        self.assertEqual(universe[236:], bytes(276))

    def test_dynamic_pattern_rejects_torn_fragment_and_tail_corruption(self):
        universe = bytearray(dynamic_universe(91, 237, 17))
        universe[236] ^= 0x01
        self.assertTrue(dynamic_mismatches(bytes(universe), 91, 237))
        universe = bytearray(dynamic_universe(91, 237, 17))
        universe[400] = 1
        self.assertTrue(dynamic_mismatches(bytes(universe), 91, 237))

    def test_receiver_diagnostic_parser_round_trip_and_resynchronizes(self):
        universe = bytes([77]) * 512
        source_mac = bytes.fromhex("18fe34daff38")
        body = DIAGNOSTIC_MAGIC + bytes((1,)) + (42).to_bytes(4, "little") + source_mac + universe
        frame = body + crc16_ccitt(body).to_bytes(2, "little")
        parser = ReceiverDiagnosticParser()
        records = parser.feed(b"noise" + frame[:80])
        records += parser.feed(frame[80:])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].sequence, 42)
        self.assertEqual(records[0].source_mac, source_mac)
        self.assertEqual(records[0].universe, universe)

    def test_receiver_diagnostic_parser_rejects_bad_crc(self):
        body = (DIAGNOSTIC_MAGIC + bytes((1,)) + (1).to_bytes(4, "little") +
                bytes.fromhex("18fe34daff38") + bytes(512))
        frame = bytearray(body + crc16_ccitt(body).to_bytes(2, "little"))
        frame[-1] ^= 0xFF
        parser = ReceiverDiagnosticParser()
        self.assertEqual(parser.feed(bytes(frame)), [])
        self.assertEqual(parser.records_bad_crc, 1)
    def test_transmitter_mode_request_has_valid_crc(self):
        request = set_transmitter_mode_request(1)
        self.assertEqual(request[3], 0x08)
        self.assertEqual(request[6], 1)
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_transmitter_mode_query_has_valid_crc(self):
        request = get_transmitter_mode_request()
        self.assertEqual(request[3], 0x09)
        self.assertEqual(request[4:6], b"\x00\x00")
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_transmitter_mode_request_rejects_invalid_mode(self):
        with self.assertRaises(ValueError):
            set_transmitter_mode_request(2)

    def test_transmitter_mode_response_is_parsed(self):
        body = bytes((1, 0x88, 2, 0, 1, 1))
        frame = MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))
        response = ManagementParser().feed(frame)[0]
        self.assertIsInstance(response, TransmitterModeResponse)
        self.assertFalse(response.accepted)
        self.assertEqual(response.mode, 1)
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

    def test_output_request_layout_and_crc(self):
        request = set_receiver_output_request(False, 0x12345678, 0xAABBCCDD)
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(request[3], 0x06)
        self.assertEqual(struct.unpack_from("<H", request, 4)[0], 10)
        self.assertEqual(request[6:16], bytes.fromhex("000078563412DDCCBBAA"))
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_locate_request_layout_and_crc(self):
        request = locate_receiver_request(0x12345678, 15, 0xAABBCCDD)
        self.assertEqual(request[:2], MANAGEMENT_SYNC)
        self.assertEqual(request[3], 0x07)
        self.assertEqual(struct.unpack_from("<H", request, 4)[0], 10)
        self.assertEqual(request[6:16], bytes.fromhex("785634120F00DDCCBBAA"))
        self.assertEqual(crc16_ccitt(request[2:-2]), struct.unpack("<H", request[-2:])[0])

    def test_locate_request_defaults_to_fifteen_seconds(self):
        request = locate_receiver_request(1)
        self.assertEqual(request[6:16], bytes.fromhex("010000000F0000000000"))

    def test_locate_request_rejects_invalid_duration(self):
        with self.assertRaises(ValueError):
            locate_receiver_request(1, 0)
        with self.assertRaises(ValueError):
            locate_receiver_request(1, 16)

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
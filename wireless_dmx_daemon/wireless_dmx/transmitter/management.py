"""Feature 11 management frame codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..models import PriorityAck, ReceiverLinkState, ReceiverTelemetry
from ..protocols import (
    MANAGEMENT_GET_RECEIVER_TELEMETRY, MANAGEMENT_PROTO_VERSION,
    MANAGEMENT_MARK_NEXT_PRIORITY,
    MANAGEMENT_GET_PRIORITY_ACKS, MANAGEMENT_PRIORITY_ACKS,
    MANAGEMENT_CLEAR_RECEIVER_CACHE, MANAGEMENT_CACHE_CLEARED,
    MANAGEMENT_RECEIVER_TELEMETRY, MANAGEMENT_SYNC, ProtocolError, crc16_ccitt,
)
from ..protocols import DMX_GATE_MASK_SIZE

PART_HEADER = struct.Struct("<BBBBI")
RECORD = struct.Struct("<I6sBBbb7I HBBI".replace(" ", ""))
ACK_HEADER = struct.Struct("<BBIIIII")
ACK_RECORD = struct.Struct("<I I I BBBb I H".replace(" ", ""))


@dataclass(frozen=True)
class TelemetryReportPart:
    report_version: int
    part_index: int
    part_count: int
    report_sequence: int
    records: tuple[ReceiverTelemetry, ...]


@dataclass(frozen=True)
class PriorityAckReport:
    report_sequence: int
    accepted_count: int
    duplicate_count: int
    invalid_count: int
    dropped_count: int
    records: tuple[PriorityAck, ...]


@dataclass(frozen=True)
class CacheClearedResponse:
    acknowledged: bool = True


def get_telemetry_request() -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, MANAGEMENT_GET_RECEIVER_TELEMETRY, 0, 0))
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def get_priority_acks_request() -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, MANAGEMENT_GET_PRIORITY_ACKS, 0, 0))
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def clear_receiver_cache_request() -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, MANAGEMENT_CLEAR_RECEIVER_CACHE, 0, 0))
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def mark_next_priority(priority_id: int, repeat_count: int = 3, attempt: int = 1,
                       target_receiver_id: int = 0,
                       hard_gate_mask: bytes | None = None) -> bytes:
    """Tell the transmitter to classify the next complete ENTTEC universe."""
    if hard_gate_mask is None:
        payload = struct.pack("<IIBB", priority_id & 0xFFFFFFFF,
                              target_receiver_id & 0xFFFFFFFF,
                              repeat_count & 0xFF, attempt & 0xFF)
    else:
        if len(hard_gate_mask) != DMX_GATE_MASK_SIZE:
            raise ValueError("hard gate mask must contain 64 bytes")
        payload = struct.pack("<IIBBB", priority_id & 0xFFFFFFFF,
                              target_receiver_id & 0xFFFFFFFF,
                              repeat_count & 0xFF, attempt & 0xFF, 1) + hard_gate_mask
    body = bytes((MANAGEMENT_PROTO_VERSION, MANAGEMENT_MARK_NEXT_PRIORITY)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def _frame(payload: bytes, opcode: int = MANAGEMENT_RECEIVER_TELEMETRY) -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, opcode)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def parse_management_frame(frame: bytes) -> TelemetryReportPart:
    if len(frame) < 8 or frame[:2] != MANAGEMENT_SYNC:
        raise ProtocolError("invalid management frame")
    version, opcode = frame[2:4]
    length = struct.unpack_from("<H", frame, 4)[0]
    if version != MANAGEMENT_PROTO_VERSION:
        raise ProtocolError("unexpected management response")
    if len(frame) != 8 + length:
        raise ProtocolError("management length mismatch")
    if crc16_ccitt(frame[2:6 + length]) != struct.unpack_from("<H", frame, 6 + length)[0]:
        raise ProtocolError("management CRC mismatch")
    if opcode == MANAGEMENT_PRIORITY_ACKS:
        if length < ACK_HEADER.size:
            raise ProtocolError("missing priority ACK header")
        report_version, record_count, sequence, accepted, duplicates, invalid, dropped = ACK_HEADER.unpack_from(frame, 6)
        if report_version != 1 or record_count > 9 or length != ACK_HEADER.size + record_count * ACK_RECORD.size:
            raise ProtocolError("invalid priority ACK report")
        records = []
        for offset in range(6 + ACK_HEADER.size, 6 + length, ACK_RECORD.size):
            values = ACK_RECORD.unpack_from(frame, offset)
            records.append(PriorityAck(*values, received_monotonic=0.0))
        return PriorityAckReport(sequence, accepted, duplicates, invalid, dropped, tuple(records))
    if opcode == MANAGEMENT_CACHE_CLEARED:
        if length != 0:
            raise ProtocolError("invalid cache clear response")
        return CacheClearedResponse()
    if opcode != MANAGEMENT_RECEIVER_TELEMETRY:
        raise ProtocolError("unexpected management response")
    if length < PART_HEADER.size:
        raise ProtocolError("missing telemetry part header")
    report_version, index, count, record_count, sequence = PART_HEADER.unpack_from(frame, 6)
    if count == 0 or index >= count or record_count > 4:
        raise ProtocolError("invalid telemetry part indexes")
    record_data = frame[6 + PART_HEADER.size:6 + length]
    if len(record_data) != record_count * RECORD.size:
        raise ProtocolError("invalid telemetry record count")
    records = []
    for offset in range(0, len(record_data), RECORD.size):
        f = RECORD.unpack_from(record_data, offset)
        records.append(ReceiverTelemetry(
            receiver_id=f[0], mac_address=f[1].hex(":"),
            link_state=ReceiverLinkState({1: "online", 2: "stale", 3: "offline"}.get(f[2], "unknown")),
            battery_low=bool(f[3]), transmitter_rssi=f[4], receiver_last_rssi=f[5],
            uptime_seconds=f[6], last_active_sequence=f[7], complete_universes=f[8],
            incomplete_universes=f[9], malformed_packets=f[10], time_since_last_universe_ms=f[11],
            transmitter_last_seen_ms=f[12], firmware_version=f[13], protocol_version=f[14],
            # f[15] is the packed record's reserved byte; telemetrySequence is
            # the final uint32 field at f[16]. Keeping this explicit prevents
            # fresh receiver reports from being mistaken for sequence zero.
            telemetry_sequence=f[16],
        ))
    return TelemetryReportPart(report_version, index, count, sequence, tuple(records))


class ManagementParser:
    """Streaming parser for management responses using a bounded buffer."""

    def __init__(self, max_payload: int = 240) -> None:
        self.max_payload = max_payload
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[TelemetryReportPart]:
        self._buffer.extend(data)
        parts: list[TelemetryReportPart] = []
        while True:
            start = self._buffer.find(MANAGEMENT_SYNC)
            if start < 0:
                if self._buffer[-1:] == MANAGEMENT_SYNC[:1]:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                return parts
            del self._buffer[:start]
            if len(self._buffer) < 6:
                return parts
            length = self._buffer[4] | self._buffer[5] << 8
            if length > self.max_payload:
                del self._buffer[0]
                continue
            total = 8 + length
            if len(self._buffer) < total:
                return parts
            frame = bytes(self._buffer[:total])
            del self._buffer[:total]
            try:
                parts.append(parse_management_frame(frame))
            except ProtocolError:
                continue
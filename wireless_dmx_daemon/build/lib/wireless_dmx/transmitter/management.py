"""Feature 11 management frame codec."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..models import ReceiverLinkState, ReceiverTelemetry
from ..protocols import (
    MANAGEMENT_GET_RECEIVER_TELEMETRY, MANAGEMENT_PROTO_VERSION,
    MANAGEMENT_RECEIVER_TELEMETRY, MANAGEMENT_SYNC, ProtocolError, crc16_ccitt,
)

PART_HEADER = struct.Struct("<BBBBI")
RECORD = struct.Struct("<I6sBBbb7I HBB".replace(" ", ""))


@dataclass(frozen=True)
class TelemetryReportPart:
    report_version: int
    part_index: int
    part_count: int
    report_sequence: int
    records: tuple[ReceiverTelemetry, ...]


def get_telemetry_request() -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, MANAGEMENT_GET_RECEIVER_TELEMETRY, 0, 0))
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def _frame(payload: bytes, opcode: int = MANAGEMENT_RECEIVER_TELEMETRY) -> bytes:
    body = bytes((MANAGEMENT_PROTO_VERSION, opcode)) + struct.pack("<H", len(payload)) + payload
    return MANAGEMENT_SYNC + body + struct.pack("<H", crc16_ccitt(body))


def parse_management_frame(frame: bytes) -> TelemetryReportPart:
    if len(frame) < 8 or frame[:2] != MANAGEMENT_SYNC:
        raise ProtocolError("invalid management frame")
    version, opcode = frame[2:4]
    length = struct.unpack_from("<H", frame, 4)[0]
    if opcode != MANAGEMENT_RECEIVER_TELEMETRY or version != MANAGEMENT_PROTO_VERSION:
        raise ProtocolError("unexpected management response")
    if len(frame) != 8 + length:
        raise ProtocolError("management length mismatch")
    if crc16_ccitt(frame[2:6 + length]) != struct.unpack_from("<H", frame, 6 + length)[0]:
        raise ProtocolError("management CRC mismatch")
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
            telemetry_sequence=0,
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
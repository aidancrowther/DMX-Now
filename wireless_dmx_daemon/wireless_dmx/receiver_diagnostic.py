"""Decoder for the receiver diagnostic UART stream."""

from __future__ import annotations

from dataclasses import dataclass

from .protocols import crc16_ccitt

DIAGNOSTIC_MAGIC = b"RDX1"
DIAGNOSTIC_NORMAL = 1
DIAGNOSTIC_PRIORITY = 2
DIAGNOSTIC_RECORD_SIZE = 4 + 1 + 4 + 512 + 2


@dataclass(frozen=True)
class DiagnosticUniverse:
    record_type: int
    sequence: int
    universe: bytes


class ReceiverDiagnosticParser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.records_bad_crc = 0
        self.records_unknown_type = 0

    def feed(self, data: bytes) -> list[DiagnosticUniverse]:
        self._buffer.extend(data)
        records: list[DiagnosticUniverse] = []
        while True:
            start = self._buffer.find(DIAGNOSTIC_MAGIC)
            if start < 0:
                self._buffer[:] = self._buffer[-3:]
                return records
            if start:
                del self._buffer[:start]
            if len(self._buffer) < DIAGNOSTIC_RECORD_SIZE:
                return records
            frame = bytes(self._buffer[:DIAGNOSTIC_RECORD_SIZE])
            del self._buffer[:DIAGNOSTIC_RECORD_SIZE]
            if crc16_ccitt(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                self.records_bad_crc += 1
                continue
            record_type = frame[4]
            if record_type not in (DIAGNOSTIC_NORMAL, DIAGNOSTIC_PRIORITY):
                self.records_unknown_type += 1
                continue
            records.append(DiagnosticUniverse(record_type,
                           int.from_bytes(frame[5:9], "little"), frame[9:521]))
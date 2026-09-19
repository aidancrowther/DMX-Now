"""Decoder for the receiver diagnostic UART stream."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .protocols import crc16_ccitt

DIAGNOSTIC_MAGIC = b"RDX1"
DIAGNOSTIC_NORMAL = 1
DIAGNOSTIC_PRIORITY = 2
DIAGNOSTIC_RECORD_SIZE = 4 + 1 + 4 + 6 + 512 + 2


@dataclass(frozen=True)
class DiagnosticUniverse:
    record_type: int
    sequence: int
    source_mac: bytes
    universe: bytes


def parse_summary_line(line: str, prefix: str = "RDS1") -> dict[str, int | float | str]:
    """Parse a compact receiver summary without imposing field ordering."""
    tokens = line.strip().split()
    if not tokens or tokens[0] != prefix:
        raise ValueError(f"expected {prefix} summary")
    values: dict[str, int | float | str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, raw = token.split("=", 1)
        if not key or not raw:
            raise ValueError(f"invalid summary token: {token}")
        try:
            values[key] = int(raw, 10)
        except ValueError:
            try:
                values[key] = float(raw)
            except ValueError:
                values[key] = raw
    return values


def mask_accounting(mask_counts: Mapping[int, int]) -> dict[str, int]:
    """Return unique fragment totals implied by final frame masks."""
    result = {"observed_frames": 0, "fragment_0": 0, "fragment_1": 0, "fragment_2": 0}
    for mask, count in mask_counts.items():
        if mask < 1 or mask > 7 or count < 0:
            raise ValueError("masks must be 1..7 and counts nonnegative")
        result["observed_frames"] += count
        for index in range(3):
            if mask & (1 << index):
                result[f"fragment_{index}"] += count
    return result


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
            if crc16_ccitt(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
                self.records_bad_crc += 1
                # The apparent magic may have occurred inside a corrupted
                # record. Discard only that byte and search again, preserving
                # any later real record boundary in the candidate window.
                del self._buffer[:1]
                continue
            del self._buffer[:DIAGNOSTIC_RECORD_SIZE]
            record_type = frame[4]
            if record_type not in (DIAGNOSTIC_NORMAL, DIAGNOSTIC_PRIORITY):
                self.records_unknown_type += 1
                continue
            records.append(DiagnosticUniverse(record_type,
                           int.from_bytes(frame[5:9], "little"), frame[9:15], frame[15:527]))
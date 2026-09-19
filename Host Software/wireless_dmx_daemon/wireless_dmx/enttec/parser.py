"""Bounded streaming ENTTEC parser."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import DmxStatistics
from ..protocols import ENTTEC_END, ENTTEC_SEND_DMX_PACKET, ENTTEC_START
from .protocol import EnttecFrame


@dataclass
class EnttecParser:
    max_payload: int = 513
    stats: DmxStatistics = field(default_factory=DmxStatistics)
    _buffer: bytearray = field(default_factory=bytearray, init=False)
    _expected: int | None = field(default=None, init=False)

    def feed(self, data: bytes) -> list[EnttecFrame]:
        self.stats.bytes_received += len(data)
        self._buffer.extend(data)
        result: list[EnttecFrame] = []
        while True:
            if self._expected is None:
                try:
                    start = self._buffer.index(ENTTEC_START)
                except ValueError:
                    self._buffer.clear()
                    return result
                if start:
                    del self._buffer[:start]
                if len(self._buffer) < 4:
                    return result
                length = self._buffer[2] | self._buffer[3] << 8
                if length > self.max_payload:
                    self.stats.invalid_frames += 1
                    del self._buffer[0]
                    continue
                self._expected = 5 + length
            if len(self._buffer) < self._expected:
                return result
            frame = bytes(self._buffer[:self._expected])
            del self._buffer[:self._expected]
            self._expected = None
            if frame[-1] != ENTTEC_END:
                self.stats.invalid_frames += 1
                # Keep searching from any delimiter in the discarded frame.
                self._buffer = bytearray(frame[1:-1]) + self._buffer
                continue
            parsed = EnttecFrame(frame[1], frame[4:-1])
            self.stats.frames_received += 1
            if parsed.label == ENTTEC_SEND_DMX_PACKET and parsed.is_dmx:
                self.stats.valid_dmx_frames += 1
                self.stats.last_frame_monotonic = __import__("time").monotonic()
                result.append(parsed)
            elif parsed.label != ENTTEC_SEND_DMX_PACKET:
                self.stats.unsupported_commands += 1
            else:
                self.stats.invalid_frames += 1
        return result
"""Parser for raw 512-byte DMX universe bursts."""

from __future__ import annotations

from dataclasses import dataclass
import time


RAW_DMX_UNIVERSE_SIZE = 512


@dataclass(frozen=True)
class RawDmxFrame:
    data: bytes


class RawDmxParser:
    """Accumulate complete 512-byte universes from a byte stream.

    The sender is expected to write exactly one universe per burst. PTYs do not
    preserve write boundaries, so this parser deliberately frames by length and
    supports partial and concatenated reads as well.
    """

    def __init__(self, timeout_seconds: float = 1.0) -> None:
        self._buffer = bytearray()
        self.timeout_seconds = timeout_seconds
        self._last_data_at: float | None = None
        self.invalid_bursts = 0

    def feed(self, data: bytes, now: float | None = None) -> tuple[RawDmxFrame, ...]:
        timestamp = time.monotonic() if now is None else now
        if data:
            self._buffer.extend(data)
            self._last_data_at = timestamp
        count, remainder = divmod(len(self._buffer), RAW_DMX_UNIVERSE_SIZE)
        frames = tuple(
            RawDmxFrame(bytes(self._buffer[index * RAW_DMX_UNIVERSE_SIZE:(index + 1) * RAW_DMX_UNIVERSE_SIZE]))
            for index in range(count)
        )
        if remainder:
            self._buffer = self._buffer[count * RAW_DMX_UNIVERSE_SIZE:]
        else:
            self._buffer.clear()
            self._last_data_at = None
        return frames

    def expire(self, now: float | None = None) -> bool:
        """Abandon an incomplete burst after the configured quiet interval."""
        if not self._buffer or self._last_data_at is None:
            return False
        timestamp = time.monotonic() if now is None else now
        if timestamp - self._last_data_at < self.timeout_seconds:
            return False
        self.discard_partial()
        return True

    def discard_partial(self) -> None:
        if self._buffer:
            self.invalid_bursts += 1
            self._buffer.clear()
        self._last_data_at = None
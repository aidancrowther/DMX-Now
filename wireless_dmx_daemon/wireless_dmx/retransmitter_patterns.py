"""Frame-unique patterns used by retransmitter live acceptance tests."""

from __future__ import annotations


def dynamic_universe(base: int, slots: int, epoch: int) -> bytes:
    """Return the frame-unique pattern emitted by the Mega test source."""
    values = bytearray(512)
    for channel in range(1, 513):
        values[channel - 1] = (epoch if channel == 1 else
                               (base + epoch * 29 + channel * 37 +
                                (channel >> 3) * 11) & 0xFF)
        if channel > slots:
            values[channel - 1] = 0
    return bytes(values)


def dynamic_mismatches(universe: bytes, base: int, slots: int) -> list[tuple[int, int, int]]:
    """Return (one-based channel, actual, expected) mismatches."""
    expected = dynamic_universe(base, slots, universe[0])
    return [(index + 1, actual, wanted)
            for index, (actual, wanted) in enumerate(zip(universe, expected))
            if actual != wanted]
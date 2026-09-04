"""ENTTEC DMX USB Pro frame helpers."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..protocols import DMX_UNIVERSE_SIZE, ENTTEC_END, ENTTEC_SEND_DMX_PACKET, ENTTEC_START, ProtocolError


@dataclass(frozen=True)
class EnttecFrame:
    label: int
    payload: bytes

    @property
    def is_dmx(self) -> bool:
        return self.label == ENTTEC_SEND_DMX_PACKET and len(self.payload) >= 2 and self.payload[0] == 0

    def universe(self) -> bytes:
        if not self.is_dmx or len(self.payload) > DMX_UNIVERSE_SIZE + 1:
            raise ProtocolError("unsupported ENTTEC DMX payload")
        return self.payload[1:] + bytes(DMX_UNIVERSE_SIZE - len(self.payload) + 1)


def encode_frame(label: int, payload: bytes = b"") -> bytes:
    if not 0 <= label <= 255 or len(payload) > 0xFFFF:
        raise ValueError("invalid ENTTEC frame")
    return bytes((ENTTEC_START, label)) + struct.pack("<H", len(payload)) + payload + bytes((ENTTEC_END,))


def encode_dmx(universe: bytes) -> bytes:
    if not 1 <= len(universe) <= DMX_UNIVERSE_SIZE:
        raise ValueError("DMX universe must contain 1..512 channels")
    return encode_frame(ENTTEC_SEND_DMX_PACKET, bytes((0,)) + universe)
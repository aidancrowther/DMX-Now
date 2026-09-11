"""Protocol contracts and constants.

These constants provide one stable import location for the service, tests, and
future adapters.
"""

from __future__ import annotations

from typing import Final

ENTTEC_START: Final[int] = 0x7E
ENTTEC_END: Final[int] = 0xE7
ENTTEC_SEND_DMX_PACKET: Final[int] = 0x06
DMX_UNIVERSE_SIZE: Final[int] = 512

MANAGEMENT_SYNC: Final[bytes] = b"\xA5\x5A"
MANAGEMENT_PROTO_VERSION: Final[int] = 1
MANAGEMENT_GET_RECEIVER_TELEMETRY: Final[int] = 0x01
MANAGEMENT_MARK_NEXT_PRIORITY: Final[int] = 0x02
MANAGEMENT_GET_PRIORITY_ACKS: Final[int] = 0x03
MANAGEMENT_CLEAR_RECEIVER_CACHE: Final[int] = 0x04
MANAGEMENT_SET_RECEIVER_FAILSAFE: Final[int] = 0x05
MANAGEMENT_SET_RECEIVER_OUTPUT: Final[int] = 0x06
MANAGEMENT_LOCATE_RECEIVER: Final[int] = 0x07
MANAGEMENT_RECEIVER_TELEMETRY: Final[int] = 0x81
MANAGEMENT_PRIORITY_ACKS: Final[int] = 0x83
MANAGEMENT_CACHE_CLEARED: Final[int] = 0x84
MANAGEMENT_ERROR: Final[int] = 0xE0
RECEIVER_FAILSAFE_CONFIG_PACKET_TYPE: Final[int] = 8
RECEIVER_OUTPUT_CONTROL_PACKET_TYPE: Final[int] = 9
RECEIVER_LOCATE_PACKET_TYPE: Final[int] = 10
DMX_GATE_MASK_SIZE: Final[int] = DMX_UNIVERSE_SIZE // 8
PRIORITY_COMPLETE_GATE_APPLIED: Final[int] = 5


class ProtocolError(ValueError):
    """Raised when a protocol frame is structurally invalid."""


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """Return the CRC-16/CCITT used by Feature 11 management frames."""

    crc = initial & 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
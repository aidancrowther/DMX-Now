"""Minimal ENTTEC DMX USB Pro framing helpers for Feature 8 verification."""
import struct
START, END, SEND_DMX_PACKET = 0x7E, 0xE7, 0x06

def frame(label: int, payload: bytes = b"") -> bytes:
    if not 0 <= label <= 0xFF or len(payload) > 0xFFFF:
        raise ValueError("invalid ENTTEC frame")
    return bytes((START, label)) + struct.pack("<H", len(payload)) + payload + bytes((END,))

def dmx_frame(channels: bytes, start_code: int = 0) -> bytes:
    if not 1 <= len(channels) <= 512:
        raise ValueError("DMX channel count must be 1..512")
    return frame(SEND_DMX_PACKET, bytes((start_code,)) + channels)

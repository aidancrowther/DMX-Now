"""Art-Net ArtDMX UDP input adapter."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from .models import DmxStatistics

ARTNET_ID = b"Art-Net\x00"
ARTDMX_OPCODE = 0x5000
ARTNET_PROTOCOL_VERSION = 14


@dataclass(frozen=True)
class ArtDmxFrame:
    universe: int
    sequence: int
    data: bytes
    source: tuple[str, int] | None = None


class ArtNetParser:
    def __init__(self, universe: int = 0, stats: DmxStatistics | None = None) -> None:
        self.universe = universe
        self.stats = stats or DmxStatistics()

    def parse(self, packet: bytes, source: tuple[str, int] | None = None) -> ArtDmxFrame | None:
        self.stats.artnet_packets += 1
        if len(packet) < 18 or packet[:8] != ARTNET_ID:
            self.stats.artnet_invalid_packets += 1
            return None
        opcode = struct.unpack_from("<H", packet, 8)[0]
        version = struct.unpack_from(">H", packet, 10)[0]
        sequence = packet[12]
        universe = struct.unpack_from("<H", packet, 14)[0]
        length = struct.unpack_from(">H", packet, 16)[0]
        if opcode != ARTDMX_OPCODE or version < ARTNET_PROTOCOL_VERSION or universe != self.universe:
            self.stats.artnet_invalid_packets += 1
            return None
        if length < 2 or length > 512 or len(packet) != 18 + length:
            self.stats.artnet_invalid_packets += 1
            return None
        self.stats.artnet_valid_frames += 1
        return ArtDmxFrame(universe, sequence, packet[18:18 + length], source)


def encode_artdmx(data: bytes, universe: int = 0, sequence: int = 1) -> bytes:
    if not 1 <= len(data) <= 512 or not 0 <= universe <= 32767:
        raise ValueError("invalid ArtDMX data or universe")
    header = ARTNET_ID + struct.pack("<H", ARTDMX_OPCODE) + struct.pack(">H", ARTNET_PROTOCOL_VERSION)
    return header + bytes((sequence & 255, 0)) + struct.pack("<H", universe) + struct.pack(">H", len(data)) + data


class ArtNetListener:
    def __init__(self, bind_host: str, port: int, parser: ArtNetParser) -> None:
        self.bind_host, self.port, self.parser = bind_host, port, parser
        self.socket: socket.socket | None = None

    def start(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.bind_host, self.port))
        self.socket.setblocking(False)

    def receive(self) -> list[ArtDmxFrame]:
        if self.socket is None:
            return []
        frames = []
        while True:
            try: packet, source = self.socket.recvfrom(2048)
            except BlockingIOError: break
            frame = self.parser.parse(packet, source)
            if frame is not None: frames.append(frame)
        return frames

    def stop(self) -> None:
        if self.socket is not None: self.socket.close()
        self.socket = None
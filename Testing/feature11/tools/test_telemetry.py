#!/usr/bin/env python3
"""Feature 11 smoke test for transmitter receiver-telemetry reporting.

The transmitter UART is 115200 8N2. The test sends one binary management request
and validates the complete multipart response. It intentionally does not send
ENTTEC data, so it is safe to run while one receiver is already operating.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time

SYNC = b"\xA5\x5A"
PROTO = 1
GET_TELEMETRY = 0x01
TELEMETRY_RESPONSE = 0x81
PART_HEADER = struct.Struct("<BBBBI")
RECORD = struct.Struct("<I6sBBbb7I HBB".replace(" ", ""))


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def request() -> bytes:
    body = bytes((PROTO, GET_TELEMETRY, 0, 0))
    value = crc16(body)
    return SYNC + body + struct.pack("<H", value)


def extract_frames(buffer: bytearray):
    frames = []
    while True:
        start = buffer.find(SYNC)
        if start < 0:
            if buffer and buffer[-1] == SYNC[0]:
                del buffer[:-1]
            else:
                buffer.clear()
            return frames
        if start:
            del buffer[:start]
        if len(buffer) < 6:
            return frames
        length = buffer[4] | (buffer[5] << 8)
        total = 6 + length + 2
        if length > 240:
            del buffer[0]
            continue
        if len(buffer) < total:
            return frames
        frame = bytes(buffer[:total])
        del buffer[:total]
        frames.append(frame)


def parse_frame(frame: bytes):
    if frame[:2] != SYNC:
        raise ValueError("bad management sync")
    version, opcode, length = frame[2], frame[3], struct.unpack_from("<H", frame, 4)[0]
    payload = frame[6:6 + length]
    received_crc = struct.unpack_from("<H", frame, 6 + length)[0]
    if crc16(frame[2:6 + length]) != received_crc:
        raise ValueError("bad management CRC")
    if version != PROTO or opcode != TELEMETRY_RESPONSE:
        raise ValueError("unexpected response version/opcode")
    if len(payload) < PART_HEADER.size:
        raise ValueError("response payload is shorter than part header")
    part = PART_HEADER.unpack_from(payload)
    report_version, part_index, part_count, record_count, report_sequence = part
    records_payload = payload[PART_HEADER.size:]
    if report_version != 1:
        raise ValueError("unsupported report version")
    if part_count == 0 or part_index >= part_count:
        raise ValueError("invalid multipart indexes")
    if record_count > 4 or len(records_payload) != record_count * RECORD.size:
        raise ValueError("invalid record count or payload length")
    records = []
    for offset in range(0, len(records_payload), RECORD.size):
        fields = RECORD.unpack_from(records_payload, offset)
        receiver_id = fields[0]
        mac = fields[1]
        link_state = fields[2]
        battery_low = fields[3]
        tx_rssi = fields[4]
        rx_rssi = fields[5]
        uptime = fields[6]
        last_sequence = fields[7]
        complete = fields[8]
        incomplete = fields[9]
        malformed = fields[10]
        since_universe = fields[11]
        last_seen = fields[12]
        firmware = fields[13]
        protocol_version = fields[14]
        if link_state not in (1, 2, 3) or battery_low not in (0, 1):
            raise ValueError(f"receiver {receiver_id:08X}: invalid state")
        if protocol_version != PROTO:
            raise ValueError(f"receiver {receiver_id:08X}: invalid receiver protocol")
        records.append({"id": receiver_id, "mac": mac.hex(":"), "link": link_state,
                        "battery": battery_low, "tx_rssi": tx_rssi, "rx_rssi": rx_rssi,
                        "uptime": uptime, "last_sequence": last_sequence,
                        "complete": complete, "incomplete": incomplete,
                        "malformed": malformed, "since_universe": since_universe,
                        "last_seen": last_seen, "firmware": firmware})
    return part_index, part_count, report_sequence, records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    try:
        import serial
    except ImportError:
        print("FAIL: pyserial is required (pip install pyserial)", file=sys.stderr)
        return 2

    try:
        with serial.Serial(args.port, 115200, bytesize=8, parity=serial.PARITY_NONE,
                           stopbits=serial.STOPBITS_TWO, timeout=0.1) as port:
            port.reset_input_buffer()
            buffer = bytearray()
            frames = []
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                # Receiver telemetry is intentionally periodic. Retry the
                # request so a valid empty report obtained just before the
                # next receiver beacon does not make the smoke test flaky.
                port.write(request())
                port.flush()
                retry_deadline = min(deadline, time.monotonic() + 1.0)
                while time.monotonic() < retry_deadline:
                    buffer.extend(port.read(128))
                    frames.extend(extract_frames(buffer))
                    if frames:
                        break
                if frames:
                    try:
                        if any(parse_frame(frame)[3] for frame in frames):
                            break
                    except ValueError:
                        pass
    except Exception as exc:
        print(f"FAIL: serial communication: {exc}", file=sys.stderr)
        return 1

    if not frames:
        print("FAIL: no telemetry response received")
        return 1

    try:
        parsed = [parse_frame(frame) for frame in frames]
        # A retry window may collect more than one valid report. Select the
        # first complete report by report sequence rather than confusing
        # successive one-part reports with one multipart response.
        reports = {}
        for part in parsed:
            reports.setdefault(part[2], []).append(part)
        selected = None
        for report_sequence, parts in reports.items():
            part_count = parts[0][1]
            if (len(parts) == part_count and
                    sorted(p[0] for p in parts) == list(range(part_count))):
                selected = (report_sequence, parts)
                break
        if selected is None:
            raise ValueError("no complete multipart report received")
        report_sequence, selected_parts = selected
        part_count = selected_parts[0][1]
        records = [record for part in selected_parts for record in part[3]]
        if not records:
            raise ValueError("response was valid but contained no receivers")
    except ValueError as exc:
        print(f"FAIL: invalid telemetry response: {exc}")
        return 1

    print(f"PASS: report={report_sequence} parts={part_count} receivers={len(records)}")
    for record in records:
        print("  RX-{id:08X} mac={mac} link={link} battery={battery} "
              "tx_rssi={tx_rssi} last_seen={last_seen}ms complete={complete}".format(**record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
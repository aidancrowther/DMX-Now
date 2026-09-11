import os
import sys
import time
import tty
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.pacer import DmxPacer
from wireless_dmx.raw_dmx import RawDmxParser
from wireless_dmx.virtual_serial.linux_pty import LinuxPtyBackend


class PacerAndPtyTests(unittest.TestCase):
    def test_raw_dmx_parser_requires_complete_universe(self):
        parser = RawDmxParser()
        universe = bytes(range(256)) * 2
        self.assertEqual(parser.feed(universe[:200]), ())
        frames = parser.feed(universe[200:])
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].data, universe)

    def test_raw_dmx_parser_handles_concatenated_bursts(self):
        parser = RawDmxParser()
        first = bytes([1]) * 512
        second = bytes([2]) * 512
        frames = parser.feed(first + second)
        self.assertEqual(tuple(frame.data for frame in frames), (first, second))

    def test_raw_dmx_parser_retains_incomplete_tail(self):
        parser = RawDmxParser()
        parser.feed(bytes([3]) * 511)
        self.assertEqual(parser.invalid_bursts, 0)
        frames = parser.feed(bytes([3]) + bytes([4]) * 512)
        self.assertEqual(tuple(frame.data for frame in frames),
                         (bytes([3]) * 512, bytes([4]) * 512))

    def test_raw_dmx_parser_expires_partial_universe(self):
        parser = RawDmxParser(timeout_seconds=1.0)
        parser.feed(bytes([9]) * 200, now=10.0)
        self.assertFalse(parser.expire(now=10.999))
        self.assertTrue(parser.expire(now=11.0))
        self.assertEqual(parser.invalid_bursts, 1)
        self.assertEqual(parser.feed(bytes([7]) * 512, now=12.0)[0].data,
                         bytes([7]) * 512)

    def test_pacer_replaces_pending_state(self):
        sent = []
        pacer = DmxPacer(50, sent.append)
        pacer.submit(bytes([1]) * 512)
        pacer.submit(bytes([2]) * 512)
        pacer.start()
        time.sleep(0.06)
        pacer.stop()
        self.assertIn(bytes([2]) * 512, sent)
        self.assertGreaterEqual(pacer.stats.frames_dropped_by_pacer, 1)

    def test_pacer_handles_sustained_40hz_input_at_20hz(self):
        sent = []
        pacer = DmxPacer(20, sent.append)
        pacer.start()
        try:
            deadline = time.monotonic() + 1.0
            value = 0
            while time.monotonic() < deadline:
                pacer.submit(bytes([value & 255]) * 512)
                value += 1
                time.sleep(0.025)
        finally:
            pacer.stop()
        self.assertGreaterEqual(len(sent), 15)
        self.assertLessEqual(len(sent), 25)
        self.assertGreater(pacer.stats.frames_dropped_by_pacer, 0)

    def test_linux_pty_round_trip(self):
        backend = LinuxPtyBackend()
        backend.start()
        try:
            client_fd = os.open(backend.path, os.O_RDWR | os.O_NOCTTY)
            try:
                tty.setraw(client_fd)
                client = os.fdopen(client_fd, "r+b", buffering=0)
                client_fd = None
                client.write(b"hello")
                deadline = time.monotonic() + 1
                received = b""
                while time.monotonic() < deadline and received != b"hello":
                    received += backend.read(32)
                    time.sleep(0.005)
                self.assertEqual(received, b"hello")
                backend.write_to_client(b"world")
                self.assertEqual(client.read(5), b"world")
                client.close()
            finally:
                if client_fd is not None:
                    os.close(client_fd)
        finally:
            backend.stop()
        self.assertFalse(os.path.exists(backend.path) if backend._path else False)


if __name__ == "__main__":
    unittest.main()
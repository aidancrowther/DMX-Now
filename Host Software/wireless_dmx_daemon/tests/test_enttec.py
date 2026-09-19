import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.enttec.parser import EnttecParser
from wireless_dmx.enttec.protocol import encode_dmx, encode_frame
from wireless_dmx.protocols import ENTTEC_SEND_DMX_PACKET


class EnttecTests(unittest.TestCase):
    def test_full_universe_with_embedded_delimiters(self):
        channels = bytes((0x7E if i == 10 else 0xE7 if i == 11 else i & 255) for i in range(512))
        parser = EnttecParser()
        frames = parser.feed(encode_dmx(channels))
        self.assertEqual([frame.universe() for frame in frames], [channels])

    def test_partial_and_concatenated_frames(self):
        first = encode_dmx(bytes([1]))
        second = encode_dmx(bytes([2]) * 512)
        parser = EnttecParser()
        self.assertEqual(parser.feed(first[:3]), [])
        frames = parser.feed(first[3:] + second)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].universe()[0], 1)
        self.assertEqual(frames[0].universe()[1], 0)
        self.assertEqual(frames[1].universe(), bytes([2]) * 512)

    def test_short_frame_zero_fills(self):
        frame = EnttecParser().feed(encode_dmx(bytes([0x55]) * 37))[0]
        self.assertEqual(frame.universe(), bytes([0x55]) * 37 + bytes(475))

    def test_unsupported_label_does_not_create_dmx(self):
        parser = EnttecParser()
        self.assertEqual(parser.feed(encode_frame(0x03, b"hello")), [])
        self.assertEqual(parser.stats.unsupported_commands, 1)

    def test_bad_terminator_recovers(self):
        parser = EnttecParser()
        bad = encode_dmx(bytes([3]))[:-1] + b"\x00"
        good = encode_dmx(bytes([4]))
        frames = parser.feed(bad + good)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].universe()[0], 4)


if __name__ == "__main__":
    unittest.main()
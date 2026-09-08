import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.artnet import ARTDMX_OPCODE, ARTNET_ID, ArtNetListener, ArtNetParser, encode_artdmx
from wireless_dmx.config import load_config, save_config
from wireless_dmx.config_editor import EDITABLE_FIELDS, update_field
from wireless_dmx.models import DaemonConfig


class ArtNetConfigTests(unittest.TestCase):
    def test_artdmx_round_trip_and_zero_fill(self):
        parser = ArtNetParser(universe=1)
        packet = encode_artdmx(bytes([0x44]) * 37, universe=1, sequence=7)
        frame = parser.parse(packet, ("127.0.0.1", 6454))
        self.assertIsNotNone(frame)
        self.assertEqual(frame.sequence, 7)
        self.assertEqual(frame.data, bytes([0x44]) * 37)
        self.assertEqual(parser.stats.artnet_valid_frames, 1)

    def test_invalid_artdmx_is_rejected(self):
        parser = ArtNetParser(universe=0)
        self.assertIsNone(parser.parse(b"bad"))
        packet = bytearray(encode_artdmx(bytes(2)))
        packet[8:10] = b"\x01\x00"
        self.assertIsNone(parser.parse(bytes(packet)))
        self.assertEqual(parser.stats.artnet_invalid_packets, 2)

    def test_udp_listener_receives_packet(self):
        parser = ArtNetParser(universe=0)
        listener = ArtNetListener("127.0.0.1", 0, parser)
        listener.start()
        try:
            port = listener.socket.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.sendto(encode_artdmx(bytes([9]) * 512), ("127.0.0.1", port))
            deadline = time.monotonic() + 1
            frames = []
            while time.monotonic() < deadline and not frames:
                frames = listener.receive()
                time.sleep(0.005)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].data, bytes([9]) * 512)
        finally:
            listener.stop()

    def test_input_combinations_validate(self):
        DaemonConfig(virtual_serial_enabled=True, artnet_enabled=False).validate()
        DaemonConfig(virtual_serial_enabled=False, artnet_enabled=True, virtual_port_path="").validate()
        DaemonConfig(virtual_serial_enabled=True, artnet_enabled=True).validate()
        with self.assertRaisesRegex(ValueError, "at least one"):
            DaemonConfig(virtual_serial_enabled=False, artnet_enabled=False, virtual_port_path="").validate()

    def test_save_and_reload_artnet_config(self):
        config = DaemonConfig(virtual_serial_enabled=False, virtual_port_path="",
                             artnet_bind_host="127.0.0.1", artnet_port=6455,
                             artnet_universe=12, input_source_policy="artnet")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved.conf"
            save_config(config, str(path))
            loaded = load_config(str(path))
            self.assertEqual(loaded.artnet_port, 6455)
            self.assertEqual(loaded.artnet_universe, 12)
            self.assertFalse(loaded.virtual_serial_enabled)
            self.assertEqual(loaded.input_source_policy, "artnet")

    def test_setup_editor_updates_artnet_fields(self):
        config = DaemonConfig()
        port_index = next(i for i, item in enumerate(EDITABLE_FIELDS) if item[1] == "artnet_port")
        enabled_index = next(i for i, item in enumerate(EDITABLE_FIELDS) if item[1] == "artnet_enabled")
        config = update_field(config, port_index, "6455")
        config = update_field(config, enabled_index, "false")
        self.assertEqual(config.artnet_port, 6455)
        self.assertFalse(config.artnet_enabled)


if __name__ == "__main__":
    unittest.main()
import sys
import tempfile
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.config import load_config
from wireless_dmx.models import ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.telemetry import TelemetryStore


class ConfigTelemetryTests(unittest.TestCase):
    def test_toml_config_loads_nested_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[transmitter]\ndevice="/dev/test"\nbaud=115200\n[pacer]\nrate_hz=20\n')
            config = load_config(str(path))
            self.assertEqual(config.transmitter_device, "/dev/test")
            self.assertEqual(config.pacer_rate_hz, 20)

    def test_receiver_becomes_offline(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        record = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                   -1, -1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0)
        store.update(record)
        time.sleep(0.05)
        self.assertEqual(store.snapshot()[0].link_state, ReceiverLinkState.OFFLINE)


if __name__ == "__main__":
    unittest.main()
import sys
import tempfile
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.config import load_config, save_config
from wireless_dmx.models import ReceiverLinkState, ReceiverTelemetry
from wireless_dmx.telemetry import TelemetryStore


class ConfigTelemetryTests(unittest.TestCase):
    def test_channel_gates_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            config = load_config()
            config = config.__class__(**{**config.__dict__,
                "management_only_channels": (1, 7), "locked_channels": (100, 101)})
            save_config(config, str(path))
            loaded = load_config(str(path))
            self.assertEqual(tuple(loaded.management_only_channels), (1, 7))
            self.assertEqual(tuple(loaded.locked_channels), (100, 101))

    def test_channel_gate_lists_must_not_overlap(self):
        config = load_config()
        with self.assertRaises(ValueError):
            config.__class__(**{**config.__dict__, "management_only_channels": (1,), "locked_channels": (1,)}).validate()
    def test_toml_config_loads_nested_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[transmitter]\ndevice="/dev/test"\nbaud=115200\n[pacer]\nrate_hz=20\n')
            config = load_config(str(path))
            self.assertEqual(config.transmitter_device, "/dev/test")
            self.assertEqual(config.pacer_rate_hz, 20)

    def test_priority_receiver_budget_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[priority]\nreceiver_budget_seconds=1.5\n')
            self.assertEqual(load_config(str(path)).priority_receiver_budget_seconds, 1.5)

    def test_receiver_becomes_offline(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        record = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                   -1, -1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0)
        store.update(record)
        time.sleep(0.05)
        self.assertEqual(store.snapshot()[0].link_state, ReceiverLinkState.OFFLINE)

    def test_cached_same_sequence_does_not_refresh_liveness(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        record = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                   -1, -1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 7)
        store.update(record)
        time.sleep(0.02)
        store.update(record)
        time.sleep(0.02)
        self.assertEqual(store.snapshot()[0].link_state, ReceiverLinkState.OFFLINE)

    def test_new_sequence_refreshes_liveness(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        first = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                  -1, -1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 7)
        second = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                   -1, -1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 8)
        store.update(first)
        time.sleep(0.02)
        store.update(second)
        self.assertEqual(store.snapshot()[0].link_state, ReceiverLinkState.ONLINE)

    def test_receiver_reboot_with_uptime_regression_refreshes_liveness(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        before_reset = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                         -1, -1, 120, 0, 100, 0, 0, 0, 0, 1, 1, 400)
        after_reset = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                        -1, -1, 2, 0, 0, 0, 0, 0, 0, 1, 1, 0)
        store.update(before_reset)
        time.sleep(0.02)
        store.update(after_reset)
        snapshot = store.snapshot()
        self.assertEqual(snapshot[0].link_state, ReceiverLinkState.ONLINE)
        self.assertEqual(snapshot[0].telemetry_sequence, 0)

    def test_lower_sequence_without_uptime_regression_is_rejected(self):
        store = TelemetryStore(stale_seconds=0.01, offline_seconds=0.03)
        current = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                    -1, -1, 120, 0, 100, 0, 0, 0, 0, 1, 1, 400)
        old = ReceiverTelemetry(1, "00:00:00:00:00:01", ReceiverLinkState.UNKNOWN, False,
                                -1, -1, 121, 0, 101, 0, 0, 0, 0, 1, 1, 3)
        store.update(current)
        time.sleep(0.04)
        store.update(old)
        self.assertEqual(store.snapshot()[0].link_state, ReceiverLinkState.OFFLINE)


if __name__ == "__main__":
    unittest.main()
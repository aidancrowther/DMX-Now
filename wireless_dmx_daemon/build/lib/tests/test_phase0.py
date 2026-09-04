import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import unittest

from wireless_dmx.models import DaemonConfig, DaemonHealth, DaemonSnapshot, ReceiverLinkState
from wireless_dmx.protocols import MANAGEMENT_SYNC, crc16_ccitt


class Phase0Tests(unittest.TestCase):
    def test_default_config_is_validated_for_deployment(self):
        config = DaemonConfig()
        config.validate()
        self.assertEqual(config.transmitter_baud, 115200)
        self.assertEqual(config.pacer_rate_hz, 20.0)

    def test_experimental_rate_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "allow_experimental_rates"):
            DaemonConfig(pacer_maximum_rate_hz=40.0).validate()

    def test_invalid_freshness_thresholds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale threshold"):
            DaemonConfig(telemetry_stale_seconds=30, telemetry_offline_seconds=15).validate()

    def test_snapshot_is_frontend_friendly(self):
        snapshot = DaemonSnapshot(health=DaemonHealth.RUNNING, virtual_port="/dev/pts/7")
        self.assertIs(snapshot.health, DaemonHealth.RUNNING)
        self.assertEqual(snapshot.receivers, ())
        self.assertEqual(snapshot.dmx.frames_submitted, 0)

    def test_protocol_crc_matches_known_vector(self):
        self.assertEqual(MANAGEMENT_SYNC, b"\xA5\x5A")
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)
        self.assertEqual(ReceiverLinkState.ONLINE.value, "online")


if __name__ == "__main__":
    unittest.main()
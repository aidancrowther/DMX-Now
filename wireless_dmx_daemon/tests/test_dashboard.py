import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.dashboard import (ADVANCED_COMMANDS, MAIN_COMMANDS, MANUAL_COMMANDS, SETUP_COMMANDS,
                                    DashboardController, bar, build_parser,
                                    receiver_display_segments, rssi_quality)
from wireless_dmx.models import DaemonConfig, ReceiverLinkState, ReceiverTelemetry


class DashboardTests(unittest.TestCase):
    def test_dashboard_parser_defaults(self):
        args = build_parser().parse_args([])
        self.assertEqual(args.mega_port, "/dev/ttyUSB1")
        self.assertFalse(args.no_daemon)

    def test_controller_starts_without_hardware_when_not_started(self):
        controller = DashboardController(DaemonConfig(virtual_port_path="/tmp/dashboard-test"))
        try:
            self.assertIsNone(controller.service)
            self.assertIn("dashboard", controller.events) if controller.events else None
        finally:
            controller.close()

    def test_visualization_helpers_are_bounded(self):
        self.assertEqual(bar(0, 100, 8), "[........]")
        self.assertEqual(bar(100, 100, 8), "[########]")
        self.assertEqual(bar(200, 100, 8), "[########]")
        self.assertEqual(rssi_quality(-30)[0], "GOOD")
        self.assertEqual(rssi_quality(-90)[0], "WEAK")

    def test_low_battery_field_does_not_overlap_rssi_field(self):
        receiver = ReceiverTelemetry(
            7, "18:fe:34:00:00:07", ReceiverLinkState.ONLINE, True,
            -39, -40, 1, 2, 3, 4, 0, 5, 6, 1, 1, 0,
        )
        receiver_id, link, battery, rssi, counters = receiver_display_segments(receiver)
        self.assertEqual(battery, "LOW")
        self.assertIn("-39dBm", rssi)
        self.assertIn("GOOD", rssi)
        self.assertNotIn("LOW", rssi)
        self.assertTrue(counters.startswith("      6ms"))

    def test_all_dashboard_command_legends_include_settings(self):
        self.assertIn("[s]", MAIN_COMMANDS)
        self.assertIn("SETTINGS", MAIN_COMMANDS)
        self.assertIn("[u]", MAIN_COMMANDS)
        self.assertIn("MANUAL DMX", MAIN_COMMANDS)
        self.assertIn("[a]", MANUAL_COMMANDS)
        self.assertIn("[w]", SETUP_COMMANDS)
        self.assertIn("[x]", ADVANCED_COMMANDS)


if __name__ == "__main__":
    unittest.main()
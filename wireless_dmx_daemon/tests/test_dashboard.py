import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.dashboard import (ADVANCED_COMMANDS, MAIN_COMMANDS, MANUAL_COMMANDS, SETUP_COMMANDS,
                                    DashboardController, bar, build_parser, channel_gate_color,
                                    channel_gate_selected_color,
                                     priority_feedback, receiver_display_segments, rssi_quality)
from wireless_dmx.models import ChannelGate, DaemonConfig, ReceiverLinkState, ReceiverTelemetry


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

    def test_channel_gate_colors_are_consistent(self):
        self.assertEqual(channel_gate_color(ChannelGate.OPEN), "muted")
        self.assertEqual(channel_gate_color(ChannelGate.MANAGEMENT_ONLY), "warning")
        self.assertEqual(channel_gate_color(ChannelGate.LOCKED), "critical")
        self.assertEqual(channel_gate_selected_color(ChannelGate.OPEN), "gate_open_selected")
        self.assertEqual(channel_gate_selected_color(ChannelGate.MANAGEMENT_ONLY), "gate_management_selected")
        self.assertEqual(channel_gate_selected_color(ChannelGate.LOCKED), "gate_locked_selected")

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
        self.assertIn("FS:hold/60s", counters)

    def test_all_dashboard_command_legends_include_settings(self):
        self.assertIn("[s]", MAIN_COMMANDS)
        self.assertIn("SETTINGS", MAIN_COMMANDS)
        self.assertIn("[u]", MAIN_COMMANDS)
        self.assertIn("MANUAL DMX", MAIN_COMMANDS)
        self.assertIn("[a]", MANUAL_COMMANDS)
        self.assertIn("[z] reset zero", MANUAL_COMMANDS)
        self.assertIn("[r] repeats", MANUAL_COMMANDS)
        self.assertIn("[t] TTL", MANUAL_COMMANDS)
        self.assertIn("[q] quit", MANUAL_COMMANDS)
        self.assertIn("[w]", SETUP_COMMANDS)
        self.assertIn("[q] quit", SETUP_COMMANDS)
        self.assertIn("[x]", ADVANCED_COMMANDS)
        self.assertIn("[l]", MANUAL_COMMANDS)

    def test_priority_feedback_lists_acknowledged_receivers(self):
        text = priority_feedback({
            "priority_id": 42,
            "expected_receivers": {7, 9},
            "ack_receivers": {7},
            "gate_applied_receivers": {7},
            "hard_gate_mask": bytes(64),
            "ack_complete": False,
            "terminal": False,
            "retry_count": 1,
        })
        self.assertIn("PRIORITY 42 WAITING", text)
        self.assertIn("ACK 00000007", text)
        self.assertIn("EXPECT 00000007,00000009", text)
        self.assertIn("GATE 00000007", text)


if __name__ == "__main__":
    unittest.main()
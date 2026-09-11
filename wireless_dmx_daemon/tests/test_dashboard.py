import os
import sys
import unittest
import tempfile
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

    def test_default_config_is_read_only_and_save_as_switches_file(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = DashboardController(DaemonConfig(), config_path="default.conf")
            try:
                with self.assertRaises(PermissionError):
                    controller.save_configuration()
                with self.assertRaises(PermissionError):
                    controller.save_as(str(Path(directory) / "default.conf"))
                target = str(Path(directory) / "show.toml")
                controller.save_as(target)
                self.assertEqual(controller.config_path, target)
                self.assertTrue(Path(target).exists())
                self.assertIn("configuration saved as", controller.events[0])
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

    def test_receiver_display_includes_friendly_name_and_id(self):
        receiver = ReceiverTelemetry(
            7, "18:fe:34:00:00:07", ReceiverLinkState.ONLINE, False,
            -39, -40, 1, 2, 3, 4, 0, 5, 6, 1, 1, 0,
        )
        identity, *_ = receiver_display_segments(receiver, {7: "Front Truss"})
        self.assertEqual(identity, "Front Truss      [00000007]")

    def test_long_receiver_display_name_scrolls_in_sixteen_character_window(self):
        receiver = ReceiverTelemetry(
            7, "18:fe:34:00:00:07", ReceiverLinkState.ONLINE, False,
            -39, -40, 1, 2, 3, 4, 0, 5, 6, 1, 1, 0,
        )
        first, *_ = receiver_display_segments(receiver, {7: "A very long receiver name"}, now=0.0)
        second, *_ = receiver_display_segments(receiver, {7: "A very long receiver name"}, now=3.0)
        self.assertEqual(len(first), 27)
        self.assertEqual(len(second), 27)
        self.assertNotEqual(first, second)
        self.assertIn("[00000007]", first)

    def test_all_dashboard_command_legends_include_settings(self):
        self.assertIn("[s]", MAIN_COMMANDS)
        self.assertIn("SETTINGS", MAIN_COMMANDS)
        self.assertIn("[u]", MAIN_COMMANDS)
        self.assertIn("MANUAL DMX", MAIN_COMMANDS)
        self.assertIn("[n] names", MAIN_COMMANDS)
        self.assertIn("[o] output", MAIN_COMMANDS)
        self.assertIn("[i] locate", MAIN_COMMANDS)
        self.assertIn("[p] priority", MAIN_COMMANDS)
        self.assertIn("[a]", MANUAL_COMMANDS)
        self.assertIn("[z] reset zero", MANUAL_COMMANDS)
        self.assertIn("[r] repeats", MANUAL_COMMANDS)
        self.assertIn("[t] TTL", MANUAL_COMMANDS)
        self.assertIn("[0-9] type value", MANUAL_COMMANDS)
        self.assertIn("[Enter] apply/send", MANUAL_COMMANDS)
        self.assertNotIn("[o] output", MANUAL_COMMANDS)
        self.assertNotIn("[i] locate", MANUAL_COMMANDS)
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

    def test_management_feedback_is_complete_not_failed(self):
        for action in ("OUTPUT", "LOCATE"):
            text = priority_feedback({
                "priority_id": action,
                "expected_receivers": {0xDB07D7},
                "ack_receivers": {0xDB07D7},
                "retry_count": 0,
                "management_complete": True,
                "terminal": True,
                "terminal_reason": "management packet sent",
            })
            self.assertIn(f"PRIORITY {action} COMPLETE", text)
            self.assertNotIn("FAILED", text)


if __name__ == "__main__":
    unittest.main()
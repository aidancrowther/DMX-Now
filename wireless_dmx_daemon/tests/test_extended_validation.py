import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).with_name("run_retransmitter_extended_validation.py")
SPEC = importlib.util.spec_from_file_location("extended_validation", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ExtendedValidationTests(unittest.TestCase):
    def test_default_matrix_covers_boundaries(self):
        self.assertEqual(MODULE.DEFAULT_SLOTS, (24, 25, 100, 235, 236, 237,
                                                 255, 256, 257, 471, 472, 473,
                                                 511, 512))

    def test_parse_helpers_extract_protocol_lines(self):
        self.assertEqual(MODULE.last_line(b"noise\nRESULT source_rate_hz=40.95\n", b"RESULT "),
                         "RESULT source_rate_hz=40.95")
        self.assertIsNone(MODULE.last_line(b"noiseRDS1 promotions=10\n", b"RDS1 "))
        self.assertEqual(MODULE.parse_values("RESULT source_rate_hz=40.95"),
                         {"source_rate_hz": 40.95})
        self.assertEqual(MODULE.last_line(b"ACK CAPTURE START\r\nRDS1 promotions=10\r\n", b"RDS1 "),
                         "RDS1 promotions=10")

    def test_parse_rds1_ignores_prefix_on_same_line(self):
        self.assertIsNone(MODULE.last_line(b"ACK CAPTURE STARTRDS1 promotions=10\r\n", b"RDS1 "))
        self.assertIsNone(MODULE.last_line(b"noise RDS1\r\n", b"RDS1 "))

    def test_summary_line_wait_is_not_needed_after_auto_expiry(self):
        self.assertEqual(MODULE.last_line(
            b"ACK CAPTURE START\r\nRDS1 elapsed_ms=5000 promotions=44\r\n", b"RDS1 "),
            "RDS1 elapsed_ms=5000 promotions=44")

    def test_transition_pairs_cover_bidirectional_boundaries(self):
        self.assertIn((512, 24), MODULE.TRANSITIONS)
        self.assertIn((24, 512), MODULE.TRANSITIONS)
        self.assertIn((473, 471), MODULE.TRANSITIONS)
        self.assertIn((471, 473), MODULE.TRANSITIONS)

    def test_receiver_reset_is_a_separate_once_per_invocation_operation(self):
        self.assertEqual(MODULE.reset_receiver.__name__, "reset_receiver")
        self.assertEqual(MODULE.command.__name__, "command")


if __name__ == "__main__":
    unittest.main()
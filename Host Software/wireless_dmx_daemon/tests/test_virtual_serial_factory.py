import os
import sys
import time
import tty
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from wireless_dmx.virtual_serial.factory import create_pty_backend, pty_backend_class
from wireless_dmx.virtual_serial.linux_pty import LinuxPtyBackend
from wireless_dmx.virtual_serial.macos_pty import MacOSPtyBackend


class VirtualSerialFactoryTests(unittest.TestCase):
    def test_linux_platform_selects_linux_backend(self):
        self.assertIs(pty_backend_class("linux"), LinuxPtyBackend)
        self.assertIs(pty_backend_class("linux2"), LinuxPtyBackend)

    def test_macos_platform_selects_macos_backend(self):
        self.assertIs(pty_backend_class("darwin"), MacOSPtyBackend)
        backend = create_pty_backend("/tmp/test-macos-pty", platform="darwin")
        self.assertIsInstance(backend, MacOSPtyBackend)
        self.assertEqual(backend.requested_path, "/tmp/test-macos-pty")

    def test_unsupported_platform_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unsupported host platform"):
            pty_backend_class("win32")

    def test_macos_backend_round_trip(self):
        backend = create_pty_backend(platform="darwin")
        backend.start()
        client_fd = os.open(backend.path, os.O_RDWR | os.O_NOCTTY)
        try:
            tty.setraw(client_fd)
            client = os.fdopen(client_fd, "r+b", buffering=0)
            client_fd = None
            client.write(b"macos")
            deadline = time.monotonic() + 1.0
            received = b""
            while time.monotonic() < deadline and received != b"macos":
                received += backend.read(32)
                time.sleep(0.005)
            self.assertEqual(received, b"macos")
            backend.write_to_client(b"pty")
            self.assertEqual(client.read(3), b"pty")
            client.close()
        finally:
            if client_fd is not None:
                os.close(client_fd)
            backend.stop()


if __name__ == "__main__":
    unittest.main()
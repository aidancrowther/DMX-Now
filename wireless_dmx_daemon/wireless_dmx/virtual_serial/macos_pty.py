"""macOS PTY virtual serial backend."""

from __future__ import annotations

from .linux_pty import LinuxPtyBackend


class MacOSPtyBackend(LinuxPtyBackend):
    """Lightweight macOS PTY backend using the shared binary PTY behavior."""

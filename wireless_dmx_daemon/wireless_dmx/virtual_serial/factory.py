"""Platform selection for virtual serial PTY backends."""

from __future__ import annotations

import sys

from .base import VirtualSerialBackend
from .linux_pty import LinuxPtyBackend
from .macos_pty import MacOSPtyBackend


def pty_backend_class(platform: str | None = None) -> type[VirtualSerialBackend]:
    """Return the PTY backend appropriate for a host platform."""
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        return LinuxPtyBackend
    if platform == "darwin":
        return MacOSPtyBackend
    raise RuntimeError(f"unsupported host platform for virtual serial PTY: {platform}")


def create_pty_backend(requested_path: str | None = None,
                       platform: str | None = None) -> VirtualSerialBackend:
    """Create the host-selected PTY backend."""
    return pty_backend_class(platform)(requested_path)

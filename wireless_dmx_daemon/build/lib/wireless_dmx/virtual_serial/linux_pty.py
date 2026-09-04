"""Linux PTY virtual serial backend."""

from __future__ import annotations

import errno
import os
import pty
import select
import termios
import threading


class LinuxPtyBackend:
    def __init__(self, requested_path: str | None = None) -> None:
        self.requested_path = requested_path
        self.master_fd: int | None = None
        self.slave_fd: int | None = None
        self._path: str | None = None
        self._client_connected = False
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        if not self._path:
            raise RuntimeError("PTY is not started")
        return self._path

    @property
    def client_connected(self) -> bool:
        return self._client_connected

    def start(self) -> None:
        if self.master_fd is not None:
            return
        master, slave = pty.openpty()
        self.master_fd, self.slave_fd = master, slave
        self._path = os.ttyname(slave)
        # Lighting software sends arbitrary binary ENTTEC frames. Raw mode is
        # essential: canonical mode would wait for newlines and translate or
        # consume control bytes.
        tty_attrs = termios.tcgetattr(slave)
        tty_attrs[0] = 0
        tty_attrs[1] = tty_attrs[1] | termios.CLOCAL | termios.CREAD
        tty_attrs[2] = tty_attrs[2] | termios.CS8
        tty_attrs[3] = 0
        termios.tcsetattr(slave, termios.TCSANOW, tty_attrs)
        os.close(slave)
        self.slave_fd = None
        if self.requested_path:
            if os.path.lexists(self.requested_path):
                raise FileExistsError(self.requested_path)
            os.symlink(self._path, self.requested_path)

    def read(self, size: int = 4096) -> bytes:
        if self.master_fd is None:
            return b""
        ready, _, _ = select.select([self.master_fd], [], [], 0)
        if not ready:
            return b""
        try:
            data = os.read(self.master_fd, size)
            self._client_connected = True
            return data
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                self._client_connected = False
                return b""
            raise

    def write_to_client(self, data: bytes) -> int:
        if self.master_fd is None:
            return 0
        try:
            written = os.write(self.master_fd, data)
            self._client_connected = True
            return written
        except OSError as exc:
            if exc.errno == errno.EIO:
                self._client_connected = False
                return 0
            raise

    def stop(self) -> None:
        for fd in (self.master_fd, self.slave_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if self.requested_path and os.path.islink(self.requested_path):
            os.unlink(self.requested_path)
        self.master_fd = self.slave_fd = None
        self._path = None
        self._client_connected = False
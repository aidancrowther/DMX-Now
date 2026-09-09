"""Threaded transmitter serial adapter."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Protocol

from ..models import DaemonConfig


class SerialLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def read(self, size: int = 1) -> bytes: ...
    def close(self) -> None: ...


class TransmitterConnection:
    def __init__(self, config: DaemonConfig, on_read: Callable[[bytes], None], serial_factory=None) -> None:
        self.config = config
        self._on_read = on_read
        self._serial_factory = serial_factory or self._default_factory
        self._serial: SerialLike | None = None
        self._dmx_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)
        self._management_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_error: str | None = None

    def _default_factory(self):
        import serial
        return serial.Serial(self.config.transmitter_device, self.config.transmitter_baud,
                             bytesize=self.config.transmitter_data_bits,
                             parity=getattr(serial, "PARITY_" + self.config.transmitter_parity.upper()),
                             stopbits=self.config.transmitter_stop_bits, timeout=0.05,
                             write_timeout=0.2)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="transmitter-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._close()

    def send_latest(self, data: bytes) -> None:
        try:
            self._dmx_queue.put_nowait(bytes(data))
        except queue.Full:
            try:
                self._dmx_queue.get_nowait()
            except queue.Empty:
                pass
            self._dmx_queue.put_nowait(bytes(data))

    def send_immediate(self, data: bytes) -> None:
        # Management commands are ordered: replacing a pending priority marker
        # with a telemetry poll can silently turn a priority universe into a
        # normal universe. The bounded queue is large enough for the polling
        # cadence and preserves every marker.
        try:
            self._management_queue.put_nowait(bytes(data))
        except queue.Full:
            self.last_error = "management queue full"

    def _close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.connected = False

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._serial is None:
                try:
                    self._serial = self._serial_factory()
                    self.connected = True
                    self.last_error = None
                except Exception as exc:
                    self.last_error = str(exc)
                    self._stop.wait(1.0)
                    continue
            try:
                try:
                    try:
                        data = self._management_queue.get_nowait()
                    except queue.Empty:
                        data = self._dmx_queue.get(timeout=0.02)
                    self._serial.write(data)
                except queue.Empty:
                    pass
                incoming = self._serial.read(255)
                if incoming:
                    self._on_read(incoming)
            except Exception as exc:
                self.last_error = str(exc)
                self._close()
                self._stop.wait(0.5)
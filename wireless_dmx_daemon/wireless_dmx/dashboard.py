"""btop-like terminal dashboard for the DMX Now system."""

from __future__ import annotations

import argparse
import curses
import json
import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path

import serial

from .app import WirelessDmxService
from .config import apply_args, load_config
from .config_editor import EDITABLE_FIELDS, field_value, save_edited_config, update_field
from .models import ChannelGate, DaemonConfig, DaemonHealth, DaemonSnapshot


COLOR_PAIRS = {
    "healthy": 1,
    "warning": 2,
    "critical": 3,
    "accent": 4,
    "muted": 5,
    "gate_open_selected": 6,
    "gate_management_selected": 7,
    "gate_locked_selected": 8,
}


def init_colors() -> None:
    """Initialize semantic dashboard colors when the terminal supports them."""
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    curses.init_pair(COLOR_PAIRS["healthy"], curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_PAIRS["warning"], curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_PAIRS["critical"], curses.COLOR_RED, -1)
    curses.init_pair(COLOR_PAIRS["accent"], curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_PAIRS["muted"], curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_PAIRS["gate_open_selected"], curses.COLOR_WHITE, curses.COLOR_CYAN)
    curses.init_pair(COLOR_PAIRS["gate_management_selected"], curses.COLOR_YELLOW, curses.COLOR_CYAN)
    curses.init_pair(COLOR_PAIRS["gate_locked_selected"], curses.COLOR_RED, curses.COLOR_CYAN)


def color_attr(name: str, bold: bool = False) -> int:
    attr = curses.color_pair(COLOR_PAIRS.get(name, COLOR_PAIRS["muted"])) if curses.has_colors() else 0
    return attr | (curses.A_BOLD if bold else 0)


def channel_gate_color(gate: ChannelGate) -> str:
    """Return the consistent manual-editor color for a channel gate."""
    return {
        ChannelGate.OPEN: "muted",
        ChannelGate.MANAGEMENT_ONLY: "warning",
        ChannelGate.LOCKED: "critical",
    }[ChannelGate(gate)]


def channel_gate_selected_color(gate: ChannelGate) -> str:
    """Return the selected-entry pair: gate foreground on cyan background."""
    return {
        ChannelGate.OPEN: "gate_open_selected",
        ChannelGate.MANAGEMENT_ONLY: "gate_management_selected",
        ChannelGate.LOCKED: "gate_locked_selected",
    }[ChannelGate(gate)]


def bar(value: float, maximum: float, width: int = 12) -> str:
    """Return a compact Unicode-independent ASCII bar for narrow terminals."""
    if maximum <= 0:
        filled = 0
    else:
        filled = max(0, min(width, int(round(value / maximum * width))))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def rssi_quality(rssi: int) -> tuple[str, float]:
    """Convert RSSI dBm into a display label and normalized bar value."""
    quality = max(0.0, min(1.0, (rssi + 90) / 60.0))
    label = "GOOD" if quality >= 0.66 else "FAIR" if quality >= 0.33 else "WEAK"
    return label, quality


def receiver_display_segments(receiver) -> tuple[str, str, str, str, str]:
    """Return non-overlapping receiver display fields.

    Keeping these fields separate prevents battery status text from overwriting
    the RSSI quality/bar visualization in narrow terminal layouts.
    """
    quality, quality_value = rssi_quality(receiver.transmitter_rssi)
    return (
        f"RX-{receiver.receiver_id:08X}",
        receiver.link_state.value,
        "LOW" if receiver.battery_low else "OK",
        f"{receiver.transmitter_rssi:>3}dBm {quality:<4}{bar(quality_value, 1, 8)}",
        f"{receiver.transmitter_last_seen_ms:>7}ms {receiver.complete_universes:>9} {receiver.incomplete_universes:>9} "
        f"FS:{receiver.failsafe_mode}{'*' if receiver.failsafe_active else ''}/{receiver.failsafe_timeout_seconds}s",
    )


def priority_feedback(event: dict | None) -> str:
    """Return concise live acknowledgement feedback for a priority event."""
    if not event:
        return "PRIORITY: idle"
    priority_id = event.get("priority_id", "?")
    expected = sorted(event.get("expected_receivers", set()))
    acknowledged = sorted(event.get("ack_receivers", set()))
    gate_applied = sorted(event.get("gate_applied_receivers", set()))
    status = "COMPLETE" if event.get("ack_complete") or event.get("management_complete") else "WAITING"
    if event.get("terminal") and not event.get("ack_complete") and not event.get("management_complete"):
        status = f"FAILED:{event.get('terminal_reason', 'unknown')}"
    ack_text = ",".join(f"{receiver:08X}" for receiver in acknowledged) or "none"
    expected_text = ",".join(f"{receiver:08X}" for receiver in expected) or "broadcast"
    text = f"PRIORITY {priority_id} {status} ACK {ack_text} EXPECT {expected_text} RETRIES {event.get('retry_count', 0)}"
    if event.get("hard_gate_mask") is not None:
        gate_text = ",".join(f"{receiver:08X}" for receiver in gate_applied) or "none"
        text += f" GATE {gate_text}"
    return text


MAIN_COMMANDS = "[d] daemon  [r] telemetry  [s] SETTINGS  [u] MANUAL DMX  [o] output  [i] locate  [p] priority  [x] advanced  [l] logs  [q] quit"
SETUP_COMMANDS = "[↑/↓/j/k] select  [e] edit  [w] write config  [x] cancel"
ADVANCED_COMMANDS = "[m] Mega  [a] acceptance  [b] abort Mega  [x] main  [q] quit"
SETUP_COMMANDS = "[↑/↓/j/k] select  [e] edit  [w] write config  [x] discard  [q] quit"
MANUAL_COMMANDS = "[↑/↓/j/k] select  [←/→] grid  [a] jump  [e] value  [+/-] nudge  [l] gate  [n/p] priority  [r] repeats  [t] TTL  [Enter] send  [c] clear  [z] reset zero  [u] full  [g] grid  [x] main  [q] quit"


def grid_position(channel: int, columns: int = 16) -> tuple[int, int]:
    """Return zero-based row/column for a 1-based DMX channel."""
    if not 1 <= channel <= 512 or columns < 1:
        raise ValueError("channel must be 1..512 and columns must be positive")
    index = channel - 1
    return index // columns, index % columns


def _read_line_blocking(stdscr, y: int, x: int, width: int) -> str:
    """Read editable text while temporarily overriding dashboard nonblocking mode."""
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    stdscr.timeout(-1)
    try:
        return stdscr.getstr(y, x, width).decode(errors="replace")
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(250)


class MegaMonitorController:
    """Non-blocking controller for the existing Arduino Mega DMX monitor."""

    def __init__(self, port: str = "/dev/ttyUSB1") -> None:
        self.port_name = port
        self.port: serial.Serial | None = None
        self.state = "disconnected"
        self.result: dict[str, int] = {}
        self.last_line = ""
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        if self.port is not None:
            return
        self.port = serial.Serial(self.port_name, 115200, timeout=0.2)
        self.port.reset_input_buffer()
        self.state = "ready"
        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, name="mega-monitor", daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        while not self._stop.is_set() and self.port is not None:
            try:
                line = self.port.readline().decode(errors="replace").strip()
                if not line:
                    continue
                with self._lock:
                    self.last_line = line
                    if line.startswith("RESULT "):
                        self.result = self._fields(line)
                        self.state = "complete"
            except Exception as exc:
                self.error = str(exc)
                self.state = "error"
                return

    @staticmethod
    def _fields(line: str) -> dict[str, int]:
        result = {}
        for token in line.split()[1:]:
            if "=" in token:
                key, value = token.split("=", 1)
                result[key] = int(value.rstrip("ms"))
        return result

    def _command(self, command: str) -> None:
        if self.port is None:
            self.connect()
        assert self.port is not None
        self.port.write((command + "\n").encode())
        self.port.flush()

    def start_measurement(self, seconds: int = 1800, ramp_base: int = 23) -> None:
        self._command(f"EXPECT RAMP {ramp_base}")
        self._command(f"START 5 {seconds}")
        self.state = f"measuring {seconds}s"
        self.result = {}

    def abort(self) -> None:
        if self.port is not None:
            self._command("ABORT")
        self.state = "ready"

    def snapshot(self) -> dict:
        with self._lock:
            return {"port": self.port_name, "state": self.state, "last_line": self.last_line,
                    "result": dict(self.result), "error": self.error}

    def close(self) -> None:
        self._stop.set()
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1)
        self.port = None


class DashboardController:
    def __init__(self, config: DaemonConfig, mega_port: str = "/dev/ttyUSB1", config_path: str = "default.conf") -> None:
        self.config = config
        self.config_path = config_path
        self.service: WirelessDmxService | None = None
        self.mega = MegaMonitorController(mega_port)
        self.events: deque[str] = deque(maxlen=80)
        self.acceptance: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def save_configuration(self) -> None:
        save_edited_config(self.config, self.config_path)
        self.log(f"configuration saved to {self.config_path}")

    def log(self, message: str) -> None:
        with self._lock:
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} {message}")

    def start_daemon(self) -> None:
        if self.service is not None:
            self.log("daemon already running")
            return
        self.service = WirelessDmxService(self.config)
        self.service.start()
        self.log(f"daemon started; PTY={self.service.virtual.path}")

    def stop_daemon(self) -> None:
        if self.service is None:
            self.log("daemon already stopped")
            return
        self.service.stop()
        self.service = None
        self.log("daemon stopped")

    def request_telemetry(self) -> None:
        if self.service is None:
            self.log("cannot request telemetry: daemon stopped")
            return
        self.service._last_telemetry_request = 0.0
        self.log("telemetry request scheduled")

    def start_mega(self) -> None:
        try:
            self.mega.connect()
            self.mega.start_measurement()
            self.log(f"Mega measurement started on {self.mega.port_name}")
        except Exception as exc:
            self.log(f"Mega error: {exc}")

    def start_acceptance(self) -> None:
        if self.acceptance and self.acceptance.poll() is None:
            self.log("acceptance runner already active")
            return
        root = Path(__file__).resolve().parents[1]
        run_dir = root / "runs" / "dashboard-acceptance"
        command = ["python3", str(root / "tests" / "run_30min_acceptance.py"),
                   "--tx-port", self.config.transmitter_device, "--mega-port", self.mega.port_name,
                   "--seconds", "1800", "--run-dir", str(run_dir)]
        self.acceptance = subprocess.Popen(command, cwd=root, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL)
        self.log(f"acceptance runner started pid={self.acceptance.pid}")

    def snapshot(self) -> DaemonSnapshot:
        return self.service.snapshot() if self.service else DaemonSnapshot(health=DaemonHealth.READY)

    def close(self) -> None:
        if self.acceptance and self.acceptance.poll() is None:
            self.acceptance.terminate()
        self.mega.close()
        self.stop_daemon()


def _safe_add(stdscr, y: int, x: int, text: str, attr=0, width: int | None = None) -> None:
    height, columns = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= columns:
        return
    text = text if width is None else text[:width]
    try:
        stdscr.addnstr(y, x, text, max(0, columns - x - 1) if width is None else width, attr)
    except curses.error:
        pass


def _box(stdscr, top: int, left: int, bottom: int, right: int, title: str) -> None:
    try:
        stdscr.addch(top, left, curses.ACS_ULCORNER)
        stdscr.hline(top, left + 1, curses.ACS_HLINE, max(0, right - left - 1))
        stdscr.addch(top, right, curses.ACS_URCORNER)
        stdscr.vline(top + 1, left, curses.ACS_VLINE, max(0, bottom - top - 1))
        stdscr.vline(top + 1, right, curses.ACS_VLINE, max(0, bottom - top - 1))
        stdscr.addch(bottom, left, curses.ACS_LLCORNER)
        stdscr.hline(bottom, left + 1, curses.ACS_HLINE, max(0, right - left - 1))
        stdscr.addch(bottom, right, curses.ACS_LRCORNER)
        _safe_add(stdscr, top, left + 2, f" {title} ", curses.A_BOLD)
    except curses.error:
        pass


def latest_priority_event(controller: DashboardController) -> dict | None:
    if controller.service and controller.service._priority_events:
        return controller.service._priority_events[next(reversed(controller.service._priority_events))]
    return None


def _online_receiver_ids(controller: DashboardController) -> list[int]:
    return [receiver.receiver_id for receiver in controller.snapshot().receivers
            if receiver.link_state.value == "online"]


def render_receiver_modal(stdscr, controller: DashboardController, action: str,
                          selected_index: int, selected_ids: set[int], message: str = "") -> None:
    """Render a centered multi-select receiver management menu."""
    height, width = stdscr.getmaxyx()
    ids = _online_receiver_ids(controller)
    entries = [0] + ids
    selected_index = max(0, min(selected_index, len(entries) - 1))
    box_width = min(max(48, width - 8), 76)
    box_height = min(max(9, len(entries) + 7), max(9, height - 4))
    top = max(1, (height - box_height) // 2)
    left = max(1, (width - box_width) // 2)
    bottom = min(height - 2, top + box_height - 1)
    right = min(width - 2, left + box_width - 1)
    _box(stdscr, top, left, bottom, right, "RECEIVER MANAGEMENT")
    verb = "MAX3485 OUTPUT" if action == "output" else "LOCATE RECEIVERS"
    _safe_add(stdscr, top + 1, left + 3, f"{verb} - select one or more online receivers", color_attr("accent", True))
    _safe_add(stdscr, top + 2, left + 3, "Space: toggle   Enter: continue   x/Esc: cancel", curses.A_DIM)
    visible = max(1, bottom - top - 5)
    first = max(0, min(selected_index - visible // 2, len(entries) - visible))
    for offset, receiver_id in enumerate(entries[first:first + visible]):
        index = first + offset
        marker = "[x]" if receiver_id in selected_ids else "[ ]"
        label = "ALL ONLINE RECEIVERS" if receiver_id == 0 else f"Receiver {receiver_id:08X}"
        attr = color_attr("gate_open_selected", True) if index == selected_index else 0
        _safe_add(stdscr, top + 4 + offset, left + 3, f"{marker} {label}", attr)
    if message:
        _safe_add(stdscr, bottom - 1, left + 3, message, color_attr("warning", True), right - left - 5)


def render_priority_modal(stdscr, event: dict | None, countdown: float | None = None) -> None:
    """Render a centered, readable priority transaction alert."""
    height, width = stdscr.getmaxyx()
    timer = f"AUTO-CLOSE IN {max(0, int(countdown + 0.999))}s" if countdown is not None else "AUTO-CLOSE DISABLED"
    lines = ["PRIORITY TRAFFIC STATUS", priority_feedback(event), timer,
             "c: keep open   Enter/x/Esc: close"]
    box_width = min(max(60, max(len(line) for line in lines) + 6), width - 4)
    box_height = min(len(lines) + 4, height - 4)
    top = max(1, (height - box_height) // 2)
    left = max(1, (width - box_width) // 2)
    _box(stdscr, top, left, top + box_height - 1, left + box_width - 1, "PRIORITY ALERT")
    for offset, line in enumerate(lines):
        attr = color_attr("warning", True) if offset == 1 else color_attr("accent", True) if offset == 0 else curses.A_DIM
        _safe_add(stdscr, top + 2 + offset, left + 3, line, attr, box_width - 6)


def priority_event_finished(event: dict | None) -> bool:
    return bool(event and (event.get("ack_complete") or event.get("terminal") or
                           event.get("management_complete")))


def render(stdscr, controller: DashboardController, show_logs: bool) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    snapshot = controller.snapshot()
    mega = controller.mega.snapshot()
    title = "DMX NOW CONTROL CENTER"
    _safe_add(stdscr, 0, 2, title, color_attr("accent", True) | curses.A_REVERSE)
    _safe_add(stdscr, 0, max(2, width - 26), time.strftime("%Y-%m-%d %H:%M:%S"), curses.A_DIM)
    _box(stdscr, 2, 1, 7, width // 2 - 1, "DAEMON")
    _box(stdscr, 2, width // 2, 7, width - 2, "DMX / PACER")
    health_color = "healthy" if snapshot.health.value == "running" else "critical"
    tx_color = "healthy" if snapshot.transmitter_connected else "critical"
    client_color = "healthy" if snapshot.virtual_client_connected else "warning"
    _safe_add(stdscr, 3, 3, f"Health       : {snapshot.health.value}", color_attr(health_color, True))
    _safe_add(stdscr, 4, 3, f"Transmitter  : {'CONNECTED' if snapshot.transmitter_connected else 'OFFLINE'}", color_attr(tx_color, True))
    _safe_add(stdscr, 5, 3, f"Virtual PTY  : {snapshot.virtual_port or '-'}", color_attr("accent"))
    _safe_add(stdscr, 6, 3, f"Lighting app : {'CONNECTED' if snapshot.virtual_client_connected else 'WAITING'}", color_attr(client_color, True))
    x = width // 2 + 2
    _safe_add(stdscr, 3, x, f"Input        : {snapshot.dmx.valid_dmx_frames:>8} {bar(snapshot.dmx.valid_dmx_frames, max(1, snapshot.dmx.valid_dmx_frames))}")
    _safe_add(stdscr, 4, x, f"Submitted    : {snapshot.dmx.frames_submitted:>8} {bar(snapshot.dmx.frames_submitted, max(1, snapshot.dmx.valid_dmx_frames))}", color_attr("healthy"))
    drop_color = "warning" if snapshot.dmx.frames_dropped_by_pacer else "healthy"
    _safe_add(stdscr, 5, x, f"Dropped      : {snapshot.dmx.frames_dropped_by_pacer:>8} {bar(snapshot.dmx.frames_dropped_by_pacer, max(1, snapshot.dmx.valid_dmx_frames))}", color_attr(drop_color))
    _safe_add(stdscr, 6, x, f"Target rate  : {controller.config.pacer_rate_hz:.1f} Hz  Art-Net: "
              f"{'ON' if controller.config.artnet_enabled else 'OFF'}:{controller.config.artnet_port}", color_attr("accent", True))
    priority_event = latest_priority_event(controller)
    _safe_add(stdscr, 7, 3, priority_feedback(priority_event), color_attr("warning" if priority_event and not priority_event.get("ack_complete") else "accent", True))
    _box(stdscr, 8, 1, max(10, 11 + len(snapshot.receivers)), width - 2, "RECEIVERS")
    row = 9
    _safe_add(stdscr, row, 3, "ID         LINK     BATTERY  RSSI             LAST SEEN  COMPLETE  INCOMPLETE", color_attr("accent", True))
    for receiver in snapshot.receivers:
        row += 1
        link_color = "healthy" if receiver.link_state.value == "online" else "warning" if receiver.link_state.value == "stale" else "critical"
        battery_color = "warning" if receiver.battery_low else "healthy"
        receiver_id, link, battery, rssi, counters = receiver_display_segments(receiver)
        _safe_add(stdscr, row, 3, receiver_id, color_attr("accent", True))
        _safe_add(stdscr, row, 15, f"{link:<8}", color_attr(link_color, True))
        _safe_add(stdscr, row, 24, f"{battery:<8}", color_attr(battery_color, True))
        _safe_add(stdscr, row, 33, rssi, color_attr("healthy" if receiver.transmitter_rssi >= -55 else "warning"))
        _safe_add(stdscr, row, 54, counters)
    log_top = max(12 + len(snapshot.receivers), height - 8) if show_logs else height - 3
    if show_logs and log_top < height - 2:
        _box(stdscr, log_top, 1, height - 3, width - 2, "EVENTS")
        for index, event in enumerate(list(controller.events)[:max(0, height - log_top - 4)]):
            _safe_add(stdscr, log_top + 1 + index, 3, event)
    _safe_add(stdscr, height - 2, 2, MAIN_COMMANDS, color_attr("accent", True))
    telemetry = snapshot.telemetry
    telemetry_state = "WAITING" if telemetry.request_in_flight else "ACTIVE" if telemetry.enabled else "OFF"
    cache_state = "CLEAR-ACK" if telemetry.cache_clear_acknowledged else "CLEAR-WAIT"
    _safe_add(stdscr, height - 1, 2, f"TELEMETRY: {telemetry_state} {cache_state} req={telemetry.requests_sent} reports={telemetry.reports_received} failures={telemetry.consecutive_failures}  MEGA: {mega['state']}", curses.A_DIM)
    stdscr.refresh()


def render_advanced(stdscr, controller: DashboardController) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    _safe_add(stdscr, 0, 2, "WIRELESS DMX ADVANCED / HARDWARE TESTING", color_attr("warning", True) | curses.A_REVERSE)
    _box(stdscr, 2, 1, min(height - 4, 10), width - 2, "MEGA MONITOR")
    mega = controller.mega.snapshot()
    _safe_add(stdscr, 3, 3, f"Port       : {mega['port']}")
    _safe_add(stdscr, 4, 3, f"State      : {mega['state']}", color_attr("healthy" if mega['state'] in ('ready', 'complete') else "warning", True))
    _safe_add(stdscr, 5, 3, f"Last line  : {mega.get('last_line', '-')}")
    result = mega.get("result", {})
    _safe_add(stdscr, 6, 3, f"Checks     : {result.get('checks', '-')}")
    _safe_add(stdscr, 7, 3, f"Pass/fail  : {result.get('pass', '-')} / {result.get('fail', '-')}")
    _safe_add(stdscr, 8, 3, f"No-data    : {result.get('no_data', '-')} ms")
    _box(stdscr, 12, 1, min(height - 4, 18), width - 2, "ACTIONS")
    _safe_add(stdscr, 14, 3, "[m] connect Mega and start 30-minute-style measurement", color_attr("warning", True))
    _safe_add(stdscr, 15, 3, "[a] launch external 30-minute acceptance runner", color_attr("warning", True))
    _safe_add(stdscr, 16, 3, "[b] abort Mega measurement", color_attr("warning", True))
    _safe_add(stdscr, 17, 3, "[x] return to main dashboard", color_attr("accent", True))
    _safe_add(stdscr, height - 2, 2, ADVANCED_COMMANDS, color_attr("accent", True))
    _safe_add(stdscr, height - 1, 2, "Hardware validation controls are intentionally hidden from the normal dashboard.", curses.A_DIM)
    stdscr.refresh()


def render_setup(stdscr, controller: DashboardController, selected: int, message: str) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    _safe_add(stdscr, 0, 2, "WIRELESS DMX SETUP", color_attr("accent", True) | curses.A_REVERSE)
    _safe_add(stdscr, 1, 2, f"File: {controller.config_path}", curses.A_DIM)
    top, bottom = 3, max(4, height - 4)
    _box(stdscr, top, 1, bottom, width - 2, "CONFIGURATION")
    visible = max(1, bottom - top - 2)
    first = max(0, min(selected - visible + 1, len(EDITABLE_FIELDS) - visible))
    for row, index in enumerate(range(first, min(len(EDITABLE_FIELDS), first + visible)), top + 1):
        label, _, _ = EDITABLE_FIELDS[index]
        attr = color_attr("accent", True) if index == selected else 0
        _safe_add(stdscr, row, 3, f"{label:<28} {field_value(controller.config, index)}", attr)
    if message:
        _safe_add(stdscr, height - 2, 2, message, color_attr("warning", True))
    _safe_add(stdscr, height - 1, 2, SETUP_COMMANDS, color_attr("accent", True))
    stdscr.refresh()


def render_manual(stdscr, controller: DashboardController, channel: int, priority: bool,
                  repeat_count: int, ttl_seconds: float, full_mode: bool, grid_mode: bool,
                  message: str) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    _safe_add(stdscr, 0, 2, "WIRELESS DMX MANUAL TRANSMISSION", color_attr("accent", True) | curses.A_REVERSE)
    service = controller.service
    universe = service.manual_universe_snapshot() if service else bytes(512)
    mode = "HIGH PRIORITY" if priority else "NORMAL"
    mode_color = "warning" if priority else "healthy"
    _safe_add(stdscr, 1, 2, f"Mode: {mode}   Repeat: {repeat_count}   TTL: {ttl_seconds:.1f}s   "
              f"Priority queue: {service.snapshot().priority.queue_depth if service else 0}", color_attr(mode_color, True))
    if priority:
        _safe_add(stdscr, 2, 2, "WARNING: priority mode uses the bounded priority scheduler; receiver confirmation is not enabled yet.", color_attr("warning", True))
    if full_mode and grid_mode:
        _box(stdscr, 4, 1, max(5, height - 4), width - 2, "FULL UNIVERSE HEX GRID")
        columns = 16
        cell_width = max(5, min(8, (width - 8) // columns))
        visible_rows = max(1, height - 8)
        selected_row, _ = grid_position(channel, columns)
        first_row = max(0, min(selected_row - visible_rows // 2, 32 - visible_rows))
        for grid_row in range(first_row, min(32, first_row + visible_rows)):
            y = 5 + grid_row - first_row
            _safe_add(stdscr, y, 3, f"{grid_row * columns + 1:03d}: ", curses.A_DIM)
            for grid_col in range(columns):
                index = grid_row * columns + grid_col
                if index >= 512:
                    break
                gate = service.channel_gate(index + 1) if service else ChannelGate.OPEN
                attr = color_attr(channel_gate_selected_color(gate), True) if index == channel - 1 else color_attr(channel_gate_color(gate))
                _safe_add(stdscr, y, 8 + grid_col * cell_width,
                          f"{universe[index]:02X}", attr, cell_width - 1)
    elif full_mode:
        _box(stdscr, 4, 1, max(5, height - 4), width - 2, "FULL UNIVERSE")
        visible = max(1, height - 8)
        first = max(0, min(channel - 1 - visible // 2, 512 - visible))
        for row, index in enumerate(range(first, first + visible), 5):
            gate = service.channel_gate(index + 1) if service else ChannelGate.OPEN
            attr = color_attr(channel_gate_selected_color(gate), True) if index == channel - 1 else color_attr(channel_gate_color(gate))
            _safe_add(stdscr, row, 4, f"{index + 1:03d}       {universe[index]:03d}       0x{universe[index]:02X}", attr)
    else:
        _box(stdscr, 4, 1, 12, width - 2, "CHANNEL EDITOR")
        _safe_add(stdscr, 6, 4, f"Channel: {channel:03d} / 512", color_attr("accent", True))
        gate = service.channel_gate(channel) if service else ChannelGate.OPEN
        gate_attr = color_attr(channel_gate_color(gate), True)
        _safe_add(stdscr, 7, 4, f"Value:   {universe[channel - 1]:03d}   Gate: {gate.value}", gate_attr)
        _safe_add(stdscr, 8, 4, f"Hex:     0x{universe[channel - 1]:02X}", gate_attr)
        _safe_add(stdscr, 10, 4, "Enter sends the complete 512-channel manual universe.")
    if message:
        _safe_add(stdscr, height - 3, 2, message, color_attr("warning", True))
    _safe_add(stdscr, height - 2, 2, MANUAL_COMMANDS, color_attr("accent", True))
    stdscr.refresh()


def run_dashboard(stdscr, controller: DashboardController) -> None:
    curses.curs_set(0)
    init_colors()
    stdscr.nodelay(True)
    stdscr.timeout(250)
    show_logs = True
    advanced = False
    setup = False
    setup_selected = 0
    setup_message = ""
    manual = False
    manual_channel = 1
    manual_priority = False
    manual_repeat = controller.config.priority_default_repeat_count
    manual_ttl = controller.config.priority_default_ttl_seconds
    manual_full = False
    manual_grid = False
    manual_message = ""
    management = False
    management_action = "output"
    management_index = 0
    management_selected: set[int] = set()
    management_message = ""
    priority_alert = False
    priority_alert_manual = False
    priority_alert_close_at = 0.0
    priority_alert_event: dict | None = None
    controller.start_daemon()
    while True:
        if (priority_alert and not priority_alert_manual and priority_alert_close_at and
                time.monotonic() >= priority_alert_close_at):
            priority_alert = False
            priority_alert_event = None
        if priority_alert:
            stdscr.erase()
            event = priority_alert_event or latest_priority_event(controller)
            if not priority_alert_manual and priority_event_finished(event):
                if not priority_alert_close_at:
                    priority_alert_close_at = time.monotonic() + 10.0
                else:
                    priority_alert_close_at = min(priority_alert_close_at, time.monotonic() + 10.0)
            remaining = (priority_alert_close_at - time.monotonic()
                         if priority_alert_close_at and not priority_alert_manual else None)
            render_priority_modal(stdscr, event, remaining)
            stdscr.refresh()
        elif management:
            stdscr.erase()
            if management_action == "output_state":
                render_receiver_modal(stdscr, controller, "output", management_index, management_selected,
                                      "Press o for ON, f for OFF, or x to cancel")
            else:
                render_receiver_modal(stdscr, controller, management_action, management_index,
                                      management_selected, management_message)
            stdscr.refresh()
        elif manual:
            render_manual(stdscr, controller, manual_channel, manual_priority, manual_repeat,
                          manual_ttl, manual_full, manual_grid, manual_message)
        elif setup:
            render_setup(stdscr, controller, setup_selected, setup_message)
        elif advanced:
            render_advanced(stdscr, controller)
        else:
            render(stdscr, controller, show_logs)
        key = stdscr.getch()
        if key < 0:
            continue
        height, width = stdscr.getmaxyx()
        if key in (ord("q"), ord("Q")):
            return
        if key in (ord("x"), ord("X"), 27):
            if priority_alert:
                priority_alert = False
                priority_alert_event = None
            elif management:
                management = False
                management_message = ""
                management_selected.clear()
            elif manual:
                manual = False
                manual_message = ""
            elif setup:
                setup = False
                setup_message = "changes discarded"
            else:
                advanced = not advanced
            continue
        if priority_alert:
            if key in (ord("c"), ord("C")) and not priority_alert_manual:
                priority_alert_manual = True
                priority_alert_close_at = 0.0
            elif key in (ord("p"), ord("P"), curses.KEY_ENTER, 10, 13):
                priority_alert = False
                priority_alert_event = None
            continue
        if management:
            ids = [0] + _online_receiver_ids(controller)
            if key in (curses.KEY_UP, ord("k")):
                management_index = max(0, management_index - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                management_index = min(max(0, len(ids) - 1), management_index + 1)
            elif management_action == "output_state" and key in (ord("o"), ord("O"), ord("f"), ord("F")):
                enabled = key in (ord("o"), ord("O"))
                targets = tuple(management_selected)
                try:
                    if 0 in targets:
                        targets = controller.service.set_receiver_output(enabled, 0) if controller.service else ()
                    else:
                        for receiver_id in targets:
                            if controller.service:
                                controller.service.set_receiver_output(enabled, receiver_id)
                    management_message = f"output {'on' if enabled else 'off'} requested for {len(targets)} receiver(s)"
                    priority_alert_event = {"priority_id": "OUTPUT", "expected_receivers": set(targets),
                                            "ack_receivers": set(targets), "retry_count": 0,
                                            "management_complete": True, "terminal": True,
                                            "terminal_reason": "management packet sent"}
                    priority_alert = True
                    priority_alert_manual = False
                    priority_alert_close_at = time.monotonic() + 10.0
                    management = False
                except (ValueError, RuntimeError) as exc:
                    management_action = "output"
                    management_message = str(exc)
            elif key == ord(" ") and ids:
                receiver_id = ids[management_index]
                if receiver_id == 0:
                    management_selected = {0}
                elif 0 in management_selected:
                    management_selected.clear()
                    management_selected.add(receiver_id)
                elif receiver_id in management_selected:
                    management_selected.remove(receiver_id)
                else:
                    management_selected.add(receiver_id)
            elif key in (curses.KEY_ENTER, 10, 13) and management_selected:
                if management_action == "output":
                    management_action = "output_state"
                else:
                    try:
                        targets = tuple(management_selected)
                        if 0 in targets:
                            targets = controller.service.locate_receiver(0, 15) if controller.service else ()
                        else:
                            for receiver_id in targets:
                                if controller.service:
                                    controller.service.locate_receiver(receiver_id, 15)
                        management_message = f"locate requested for {len(targets)} receiver(s); DMX interrupted for 15 seconds"
                        priority_alert_event = {"priority_id": "LOCATE", "expected_receivers": set(targets),
                                                "ack_receivers": set(targets), "retry_count": 0,
                                                "management_complete": True, "terminal": True,
                                                "terminal_reason": "management packet sent"}
                        priority_alert = True
                        priority_alert_manual = False
                        priority_alert_close_at = time.monotonic() + 10.0
                        management = False
                    except (ValueError, RuntimeError) as exc:
                        management_message = str(exc)
            continue
        if key in (ord("s"), ord("S")) and not advanced and not setup:
            setup = True
            setup_selected = 0
            setup_message = ""
            continue
        if key in (ord("u"), ord("U")) and not advanced and not setup and not manual:
            manual = True
            manual_message = ""
            continue
        if manual:
            if key in (curses.KEY_UP, ord("k")):
                manual_channel = max(1, manual_channel - (16 if manual_full and manual_grid else 1))
            elif key in (curses.KEY_DOWN, ord("j")):
                manual_channel = min(512, manual_channel + (16 if manual_full and manual_grid else 1))
            elif key == curses.KEY_LEFT and manual_full and manual_grid:
                manual_channel = max(1, manual_channel - 1)
            elif key == curses.KEY_RIGHT and manual_full and manual_grid:
                manual_channel = min(512, manual_channel + 1)
            elif key in (ord("a"), ord("A")):
                _safe_add(stdscr, height - 1, 2, "Jump to channel 1-512: "); stdscr.refresh()
                try:
                    target = int(_read_line_blocking(stdscr, height - 1, 23, 3))
                    if not 1 <= target <= 512:
                        raise ValueError("channel must be 1-512")
                    manual_channel = target
                    manual_message = f"jumped to channel {target}"
                except (ValueError, PermissionError, curses.error) as exc:
                    manual_message = f"invalid channel: {exc}"
            elif key in (ord("+"), ord("=")) and controller.service:
                try:
                    controller.service.set_manual_channel(manual_channel, min(255, controller.service.manual_universe[manual_channel - 1] + 1))
                except PermissionError as exc:
                    manual_message = str(exc)
            elif key in (ord("-"), ord("_")) and controller.service:
                try:
                    controller.service.set_manual_channel(manual_channel, max(0, controller.service.manual_universe[manual_channel - 1] - 1))
                except PermissionError as exc:
                    manual_message = str(exc)
            elif key in (ord("n"), ord("N")):
                manual_priority = False
            elif key in (ord("p"), ord("P")):
                manual_priority = True
            elif key in (ord("c"), ord("C")) and controller.service:
                controller.service.clear_manual_universe()
                manual_message = "manual universe cleared"
            elif key in (ord("z"), ord("Z")) and controller.service:
                controller.service.clear_manual_universe()
                manual_message = "manual universe reset to zero"
            elif key in (ord("l"), ord("L")) and controller.service:
                from .models import ChannelGate
                gates = (ChannelGate.OPEN, ChannelGate.MANAGEMENT_ONLY, ChannelGate.LOCKED)
                current = controller.service.channel_gate(manual_channel)
                controller.service.set_channel_gate(manual_channel, gates[(gates.index(current) + 1) % len(gates)])
                manual_message = f"channel {manual_channel} gate: {controller.service.channel_gate(manual_channel).value}"
            elif key in (ord("r"), ord("R")):
                manual_repeat = manual_repeat % controller.config.priority_max_repeat_count + 1
            elif key in (ord("u"), ord("U")):
                manual_full = not manual_full
                if not manual_full:
                    manual_grid = False
            elif key in (ord("g"), ord("G")):
                # Grid mode is a view within the full-universe editor. Keep
                # this key independent of channel-gate handling and make the
                # transition explicit so a stale grid flag cannot hide the
                # editor after toggling full-universe mode.
                manual_full = True
                manual_grid = not manual_grid
            elif key in (curses.KEY_ENTER, 10, 13) and controller.service:
                try:
                    priority_id = controller.service.send_manual(manual_priority, manual_repeat, manual_ttl)
                    if manual_priority:
                        manual_message = priority_feedback(controller.service._priority_events.get(priority_id))
                        priority_alert_event = controller.service._priority_events.get(priority_id)
                        priority_alert = True
                        priority_alert_manual = False
                        priority_alert_close_at = 0.0
                    else:
                        manual_message = "sent normal universe"
                except Exception as exc:
                    manual_message = f"send failed: {exc}"
            elif key in (ord("e"), ord("E")) and controller.service:
                _safe_add(stdscr, height - 1, 2, "Enter value 0-255: "); stdscr.refresh()
                try:
                    value = int(_read_line_blocking(stdscr, height - 1, 22, 3))
                    controller.service.set_manual_channel(manual_channel, value)
                    manual_message = f"channel {manual_channel} set to {value}"
                except PermissionError as exc:
                    manual_message = f"edit blocked: {exc}"
                except (ValueError, curses.error) as exc:
                    manual_message = f"invalid value: {exc}"
                finally:
                    pass
            continue
        if setup:
            if key in (curses.KEY_UP, ord("k")):
                setup_selected = max(0, setup_selected - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                setup_selected = min(len(EDITABLE_FIELDS) - 1, setup_selected + 1)
            elif key in (ord("e"), ord("E")):
                label, _, _ = EDITABLE_FIELDS[setup_selected]
                curses.echo()
                curses.curs_set(1)
                _safe_add(stdscr, height - 1, 2, f"Enter {label}: ")
                stdscr.refresh()
                try:
                    text = stdscr.getstr(height - 1, min(width - 2, 2 + len(label) + 8), 80).decode()
                    controller.config = update_field(controller.config, setup_selected, text)
                    setup_message = f"updated {label}"
                except (ValueError, curses.error) as exc:
                    setup_message = f"invalid value: {exc}"
                finally:
                    curses.noecho()
                    curses.curs_set(0)
            elif key in (ord("w"), ord("W")):
                try:
                    controller.save_configuration()
                    setup_message = f"saved {controller.config_path}; restart daemon to apply"
                except Exception as exc:
                    setup_message = f"save failed: {exc}"
            continue
        if advanced:
            if key in (ord("m"), ord("M")):
                controller.start_mega()
            elif key in (ord("a"), ord("A")):
                controller.start_acceptance()
            elif key in (ord("b"), ord("B")):
                controller.mega.abort()
                controller.log("Mega measurement aborted")
            continue
        if key in (ord("d"), ord("D")):
            if controller.service:
                controller.stop_daemon()
            else:
                controller.start_daemon()
        elif key in (ord("r"), ord("R")):
            controller.request_telemetry()
        elif key in (ord("l"), ord("L")):
            show_logs = not show_logs
        elif key in (ord("o"), ord("O")):
            management = True
            management_action = "output"
            management_index = 0
            management_selected.clear()
            management_message = ""
        elif key in (ord("i"), ord("I")):
            management = True
            management_action = "locate"
            management_index = 0
            management_selected.clear()
            management_message = "WARNING: locating interrupts DMX for 5 seconds; use only off-fixture"
        elif key in (ord("p"), ord("P")):
            priority_alert = True
            priority_alert_manual = True
            priority_alert_close_at = 0.0
            priority_alert_event = latest_priority_event(controller)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wireless-dmx-dashboard")
    parser.add_argument("--config")
    parser.add_argument("--mega-port", default="/dev/ttyUSB1")
    parser.add_argument("--no-daemon", action="store_true")
    parser.add_argument("--config-path", help="path to save from setup editor; defaults to selected config")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config_path = args.config or "default.conf"
    config = load_config(args.config)
    controller = DashboardController(config, args.mega_port, args.config_path or config_path)
    try:
        if args.no_daemon:
            controller.log("dashboard started without daemon")
        curses.wrapper(run_dashboard, controller)
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""Install a per-user macOS LaunchAgent for the DMX Now daemon."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.dmxnow.daemon"
DAEMON_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = DAEMON_ROOT / "configs" / "default.conf"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LOG_DIRECTORY = Path.home() / "Library" / "Logs" / "DMX Now"
PLIST_PATH = LAUNCH_AGENTS / f"{LABEL}.plist"


def build_plist(config_path: Path, python_executable: str,
                daemon_root: Path = DAEMON_ROOT,
                log_directory: Path = LOG_DIRECTORY) -> dict:
    """Build a launchd plist dictionary using absolute paths."""
    return {
        "Label": LABEL,
        "ProgramArguments": [python_executable, "-m", "wireless_dmx",
                              "--config", str(config_path), "run"],
        "WorkingDirectory": str(daemon_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_directory / "daemon.log"),
        "StandardErrorPath": str(log_directory / "daemon.error.log"),
    }


def install(config_path: Path, plist_path: Path = PLIST_PATH,
            log_directory: Path = LOG_DIRECTORY) -> Path:
    config_path = config_path.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {config_path}")
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_directory.mkdir(parents=True, exist_ok=True)
    plist = build_plist(config_path, sys.executable, DAEMON_ROOT, log_directory)
    plist_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=False))
    return plist_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help=f"daemon config path (default: {DEFAULT_CONFIG})")
    parser.add_argument("--unload", action="store_true",
                        help="unload the existing agent before installing")
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        print("warning: generating a macOS LaunchAgent on a non-macOS host", file=sys.stderr)
    if args.unload and PLIST_PATH.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST_PATH)],
                       check=False)
    path = install(args.config)
    print(f"Wrote {path}")
    print(f"Load:   launchctl bootstrap gui/$(id -u) {path}")
    print(f"Unload: launchctl bootout gui/$(id -u) {path}")
    print(f"Status: launchctl print gui/$(id -u)/{LABEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
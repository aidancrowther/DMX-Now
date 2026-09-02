#!/usr/bin/env python3
"""Run an automated Feature 7 TX sweep using the silent MEGA monitor."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FLASH_TX = ROOT / "flash_espnow_tx.sh"
FLASH_MONITOR = ROOT / "flash_dmx_monitor.sh"
FLASH_PICO_MONITOR = ROOT / "flash_pico_dmx_monitor.sh"
ANALYZER = Path(__file__).with_name("analyze.py")


def require_port(port):
    if not Path(port).exists():
        raise RuntimeError(f"serial port is not present: {port}")


def flash_tx(port, hz, overhead, timeout):
    command = [str(FLASH_TX), "-f", "--port", port,
               "--define", f"-DWIRELESS_REFRESH_HZ={hz}",
               "--define", f"-DWIRELESS_TX_OVERHEAD_MS={overhead}",
               "--define", f"-DWIRELESS_TX_DRAIN_TIMEOUT_MS={timeout}"]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def capture(port, settle, seconds, output):
    try:
        import serial
    except ImportError as exc:
        raise RuntimeError("pyserial is required for hardware runs") from exc
    with serial.Serial(port, 115200, timeout=0.2) as ser:
        ser.reset_input_buffer()
        data = bytearray()
        # Opening the MEGA port commonly asserts reset. Wait briefly for READY
        # when it is available, but do not require it: native Pico USB CDC
        # often remains attached to an already-running sketch and does not
        # replay its boot banner when the host opens the port.
        boot_deadline = time.monotonic() + 8
        while time.monotonic() < boot_deadline and b"READY" not in data:
            chunk = ser.read(256)
            if chunk:
                data.extend(chunk)

        # Synchronize after boot (or with an already-running Pico). USB-serial
        # adapters can lose the first host write while the USB receive path
        # settles, so require a response and retry before starting a run.
        time.sleep(0.5)
        status_ok = False
        for _ in range(4):
            ser.write(b"STATUS\n")
            ser.flush()
            status_deadline = time.monotonic() + 1
            while time.monotonic() < status_deadline:
                chunk = ser.read(256)
                if chunk:
                    data.extend(chunk)
                    if b"STATUS state=" in data:
                        status_ok = True
                        break
            if status_ok:
                break
            time.sleep(0.25)
        if not status_ok:
            output.write_bytes(data)
            return False

        ser.write(f"START {settle} {seconds}\n".encode("ascii"))
        ser.flush()
        deadline = time.monotonic() + settle + seconds + 15
        while time.monotonic() < deadline:
            chunk = ser.read(256)
            if chunk:
                data.extend(chunk)
                if b"RESULT seconds=" in data:
                    break
        output.write_bytes(data)
    if b"RESULT seconds=" not in data:
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tx-port", default="/dev/ttyUSB0")
    ap.add_argument("--monitor-port", default="/dev/ttyUSB1")
    ap.add_argument("--monitor-type", choices=("mega", "pico"), default="mega",
                    help="DMX monitor hardware (default: mega)")
    ap.add_argument("--rates", default="5,10,15,20,22,25,27,30,32,35,37,40")
    ap.add_argument("--settle", type=int, default=10)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--overhead", type=int, default=27)
    ap.add_argument("--drain-timeout", type=int, default=100)
    ap.add_argument("--flash-monitor", action="store_true")
    ap.add_argument("--continue-on-error", action="store_true")
    args = ap.parse_args()
    if args.settle < 0 or args.seconds <= 0 or args.overhead < 0 or args.drain_timeout <= 0:
        ap.error("settle >= 0, seconds > 0, overhead >= 0, and drain-timeout > 0 are required")
    rates = [int(v) for v in args.rates.split(",") if v.strip()]
    if not rates or any(v <= 0 for v in rates):
        ap.error("rates must be positive integers")
    require_port(args.tx_port)
    require_port(args.monitor_port)
    monitor_flash = FLASH_PICO_MONITOR if args.monitor_type == "pico" else FLASH_MONITOR
    for script in (FLASH_TX, monitor_flash):
        if not script.is_file() or not os.access(script, os.X_OK):
            raise RuntimeError(f"required executable is missing or not executable: {script}")
    if args.flash_monitor:
        result = subprocess.run([str(monitor_flash), "-f", "--port", args.monitor_port], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode

    run_dir = ROOT / "Testing" / "feature7" / "runs" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"started_utc": datetime.now(timezone.utc).isoformat(),
                "tx_port": args.tx_port, "monitor_port": args.monitor_port,
                "monitor_type": args.monitor_type,
                "rates": rates, "settle_seconds": args.settle,
                "measure_seconds": args.seconds, "overhead_ms": args.overhead,
                "drain_timeout_ms": args.drain_timeout, "receiver_modified": False,
                "results": []}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for index, hz in enumerate(rates, 1):
        log = run_dir / f"{index:02d}_{hz:02d}hz.log"
        entry = {"hz": hz, "log": log.name, "started_utc": datetime.now(timezone.utc).isoformat()}
        rc = flash_tx(args.tx_port, hz, args.overhead, args.drain_timeout)
        entry["flash_returncode"] = rc
        if rc == 0:
            try:
                entry["capture_ok"] = capture(args.monitor_port, args.settle, args.seconds, log)
            except RuntimeError as exc:
                entry["capture_ok"] = False
                entry["error"] = str(exc)
        else:
            entry["capture_ok"] = False
        manifest["results"].append(entry)
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if not entry["capture_ok"] and not args.continue_on_error:
            print(f"stopping after failed rate {hz} Hz; artifacts: {run_dir}", file=sys.stderr)
            return 1
    subprocess.run([sys.executable, str(ANALYZER), str(run_dir)], cwd=ROOT, check=False)
    print(f"run artifacts: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
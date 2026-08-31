#!/usr/bin/env python3
"""
Feature 7 host helper: capture the MEGA DMX refresh-monitor's per-second
metric lines from a serial port and summarize them per rate point.

Usage:
    python3 Testing/feature7_capture.py --port /dev/ttyUSB0 --hz 5 --seconds 60
    python3 Testing/feature7_capture.py --port /dev/ttyUSB0 --hz 10 --seconds 60 --out Testing/feature7_10hz.log

If pyserial is not installed, either `pip3 install pyserial` or capture the
lines with any serial terminal (e.g. `minicom`, `screen /dev/ttyUSB0 115200`,
VS Code serial monitor) and feed the saved text to:

    python3 Testing/feature7_capture.py --from-file Testing/feature7_10hz.log
"""

import argparse
import re
import statistics
import sys
import time

LINE_RE = re.compile(
    r"t=(?P<t>\d+)\s+"
    r"updates=(?P<updates>\d+)\s+"
    r"rate=(?P<rate>[\d.]+)Hz\s+"
    r"lost=(?P<lost>\d+)\s+"
    r"gaps=(?P<gaps>\d+)\s+"
    r"loss=(?P<loss>[\d.]+)%\s+"
    r"pat_err=(?P<paterr>\d+)\s+"
    r"max_gap=(?P<maxgap>\d+)ms\s+"
    r"last_seq8=(?P<seq8>\d+)\s+"
    r"no_data=(?P<nodata>\d+)ms"
)


def summarize(rows, expected_hz):
    rates = [r["rate"] for r in rows]
    losses = [r["loss"] for r in rows]
    maxgaps = [r["maxgap"] for r in rows]
    total_updates = sum(r["updates"] for r in rows)
    total_lost = sum(r["lost"] for r in rows)
    total_paterr = sum(r["paterr"] for r in rows)
    total_gaps = sum(r["gaps"] for r in rows)

    mean_rate = statistics.fmean(rates) if rates else 0.0
    mean_loss = statistics.fmean(losses) if losses else 0.0
    worst_gap = max(maxgaps) if maxgaps else 0
    overall_loss = (100.0 * total_lost / (total_updates + total_lost)) if (total_updates + total_lost) else 0.0

    print("\n===== SUMMARY (expected %.1f Hz) =====" % expected_hz)
    print("seconds captured     : %d" % len(rows))
    print("mean rate            : %.2f Hz" % mean_rate)
    print("mean per-s loss      : %.1f %%" % mean_loss)
    print("overall loss         : %.1f %%  (%d lost / %d updates)" % (overall_loss, total_lost, total_updates))
    print("worst inter-update   : %d ms" % worst_gap)
    print("sequence gaps        : %d (total skipped %d)" % (total_gaps, total_lost))
    print("pattern errors       : %d" % total_paterr)

    if total_paterr == 0 and overall_loss <= 5.0:
        print("VERDICT: RELIABLE at requested rate")
    elif total_paterr == 0 and overall_loss <= 15.0:
        print("VERDICT: MARGINAL (loss %.1f%%) — usable with care" % overall_loss)
    else:
        print("VERDICT: NOT RELIABLE at requested rate")
    print("=" * 40)


def parse_line(line):
    m = LINE_RE.search(line)
    if not m:
        return None
    d = m.groupdict()
    return {
        "t": int(d["t"]),
        "updates": int(d["updates"]),
        "rate": float(d["rate"]),
        "lost": int(d["lost"]),
        "gaps": int(d["gaps"]),
        "loss": float(d["loss"]),
        "paterr": int(d["paterr"]),
        "maxgap": int(d["maxgap"]),
        "seq8": int(d["seq8"]),
        "nodata": int(d["nodata"]),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port of the MEGA (e.g. /dev/ttyUSB1)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--hz", type=float, default=1.0, help="requested WIRELESS_REFRESH_HZ for this run")
    ap.add_argument("--seconds", type=int, default=60, help="capture duration")
    ap.add_argument("--out", help="also write raw lines to this file")
    ap.add_argument("--from-file", help="summarize a previously saved capture instead of reading the port")
    args = ap.parse_args()

    rows = []
    raw = []

    if args.from_file:
        with open(args.from_file) as f:
            for line in f:
                raw.append(line.rstrip("\n"))
                r = parse_line(line)
                if r:
                    rows.append(r)
    else:
        if not args.port:
            ap.error("--port is required (or use --from-file)")
        try:
            import serial
        except ImportError:
            sys.exit("pyserial not installed. Use `pip3 install pyserial` or --from-file.")
        ser = serial.Serial(args.port, args.baud, timeout=1)
        print("reading %s @ %d for %d s (ctrl-c to stop early)..." % (args.port, args.baud, args.seconds))
        deadline = time.time() + args.seconds
        buf = ""
        while time.time() < deadline:
            chunk = ser.read(1024).decode("utf-8", "replace")
            if not chunk:
                continue
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                raw.append(line)
                r = parse_line(line)
                if r:
                    rows.append(r)
                    print(line, flush=True)
                elif not line.startswith(("=== DMX", "DMX input", "Telemetry", "Pattern", "READY")):
                    print("(unparsed) " + line, file=sys.stderr)
        ser.close()

    if args.out and not args.from_file:
        with open(args.out, "w") as f:
            for line in raw:
                f.write(line + "\n")
        print("raw lines saved to %s" % args.out)

    if not rows:
        print("no metric lines captured — check wiring/port and that the MEGA is running")
        return 1

    summarize(rows, args.hz)
    return 0


if __name__ == "__main__":
    sys.exit(main())

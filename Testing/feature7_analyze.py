#!/usr/bin/env python3
"""
Feature 7 sweep analysis.

For each rate-point log (Testing/feature7_<N>hz.log) it computes the
steady-state delivered rate (excluding the first few settling seconds and any
zero-update windows), loss, and worst gap -- then derives the transmitter's
per-frame overhead by comparing the requested rate to the measured rate.

TX period model (from tests/espnow_universe_tx/espnow_universe_tx.ino +
libraries/WirelessDMX/src/wireless_protocol.h):

    WIRELESS_REFRESH_INTERVAL_MS = 1000 / Hz          (integer division)
    period_ms  = interval_ms + overhead_ms
      where overhead_ms = generate + submit 3 fragments + drain
                          (wait for 3 onDataSent confirmations, else 200 ms timeout)
    measured_hz = 1000 / period_ms

So:   overhead_ms ~= (1000 / measured_hz) - interval_ms
"""

import glob
import os
import re
import statistics

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


def parse(path):
    rows = []
    with open(path) as f:
        for line in f:
            m = LINE_RE.search(line)
            if m:
                d = m.groupdict()
                rows.append({
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
                })
    return rows


def steady(rows, warmup=3):
    """Drop the first `warmup` metric windows (stream settling) and any
    zero-update windows, then compute steady-state stats."""
    sel = [r for r in rows[warmup:] if r["updates"] > 0]
    if not sel:
        sel = [r for r in rows if r["updates"] > 0]
    tot_upd = sum(r["updates"] for r in sel)
    tot_lost = sum(r["lost"] for r in sel)
    tot_gaps = sum(r["gaps"] for r in sel)
    tot_pat = sum(r["paterr"] for r in sel)
    span_s = sum(1 for r in sel)  # each window is ~1 s
    mean_rate = tot_upd / span_s if span_s else 0.0
    overall_loss = (100.0 * tot_lost / (tot_upd + tot_lost)) if (tot_upd + tot_lost) else 0.0
    worst_gap = max((r["maxgap"] for r in sel), default=0)
    return {
        "windows": len(sel),
        "tot_upd": tot_upd,
        "tot_lost": tot_lost,
        "tot_gaps": tot_gaps,
        "tot_pat": tot_pat,
        "mean_rate": mean_rate,
        "overall_loss": overall_loss,
        "worst_gap": worst_gap,
    }


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    files = sorted(glob.glob(os.path.join(base, "feature7_*hz.log")))
    # order by numeric rate
    def rate_of(p):
        m = re.search(r"feature7_(\d+)hz", os.path.basename(p))
        return int(m.group(1)) if m else 0
    files.sort(key=rate_of)

    print("%-6s %-9s %-9s %-9s %-8s %-7s %-8s %-9s %-9s" % (
        "req", "steadyHz", "interval", "period", "overhead", "loss%", "patErr", "worstGap", "gaps"))
    print("-" * 82)

    overheads = []
    for path in files:
        req = rate_of(path)
        interval_ms = 1000 // req          # integer division, exactly as the firmware
        st = steady(parse(path))
        if st["mean_rate"] <= 0:
            print("%-6d  (no steady data)  %s" % (req, os.path.basename(path)))
            continue
        period_ms = 1000.0 / st["mean_rate"]
        overhead_ms = period_ms - interval_ms
        if overhead_ms > 0:
            overheads.append(overhead_ms)
        print("%-6d %-9.3f %-9d %-9.1f %-8.1f %-7.2f %-8d %-9d %-9d" % (
            req, st["mean_rate"], interval_ms, period_ms, overhead_ms,
            st["overall_loss"], st["tot_pat"], st["worst_gap"], st["tot_gaps"]))

    print("-" * 82)
    if len(overheads) >= 2:
        print("Derived TX overhead:  min=%.0f  median=%.0f  max=%.0f  ms  (n=%d)" % (
            min(overheads), statistics.median(overheads), max(overheads), len(overheads)))
        med = statistics.median(overheads)
        print("  -> implies an achievable ceiling of ~%.1f Hz  (1000 / (interval -> 0) + overhead)" %
              (1000.0 / med))
    print()
    print("Note: 'steadyHz' drops the first 3 windows (settling) and zero-update windows.")
    print("'overhead' = period - interval; it is the TX generate+submit+drain cost,")
    print("           which is ADDED to the 1000/Hz interval (see TX state machine).")


if __name__ == "__main__":
    main()

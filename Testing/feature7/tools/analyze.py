#!/usr/bin/env python3
"""Analyze Feature 7 silent-monitor result logs."""
import argparse
import json
import re
from pathlib import Path

RESULT = re.compile(
    r"RESULT\s+seconds=(?P<seconds>\d+)\s+updates=(?P<updates>\d+)\s+"
    r"rate=(?P<rate>[\d.]+)\s+lost=(?P<lost>\d+)\s+gaps=(?P<gaps>\d+)\s+"
    r"loss=(?P<loss>[\d.]+)%\s+pat_err=(?P<paterr>\d+)\s+"
    r"max_gap=(?P<maxgap>\d+)\s+last_seq8=(?P<seq8>\d+)\s+"
    r"no_data=(?P<nodata>\d+)ms"
)


def parse(path):
    text = Path(path).read_text(errors="replace")
    matches = list(RESULT.finditer(text))
    if not matches:
        raise ValueError(f"no RESULT line in {path}")
    m = matches[-1]
    row = {k: int(v) if k not in ("rate", "loss") else float(v)
           for k, v in m.groupdict().items()}
    row["source"] = str(path)
    row["reliable"] = row["loss"] <= 5.0 and row["paterr"] == 0
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="result logs or run directories")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    paths = []
    for value in args.paths:
        p = Path(value)
        paths.extend(sorted(p.glob("*.log")) if p.is_dir() else [p])
    rows = []
    errors = []
    for path in paths:
        try:
            rows.append(parse(path))
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    if args.json:
        print(json.dumps({"results": rows, "errors": errors}, indent=2))
    else:
        print("rate  seconds  updates  lost  loss%  pat_err  max_gap  verdict  source")
        for r in rows:
            print(f"{r['rate']:5.2f} {r['seconds']:8d} {r['updates']:8d} "
                  f"{r['lost']:5d} {r['loss']:6.2f} {r['paterr']:8d} "
                  f"{r['maxgap']:8d} {'RELIABLE' if r['reliable'] else 'NOT-RELIABLE':11s} "
                  f"{r['source']}")
        for error in errors:
            print(f"ERROR: {error}")
    return 0 if rows and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
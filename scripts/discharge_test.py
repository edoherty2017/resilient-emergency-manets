#!/usr/bin/env python3
"""Overnight discharge test (anchor 1.4 / decisions C5+G2): compute the real
average drain of a Meshtastic node from its own battery telemetry.

Protocol:
  1. Charge the node full. Unplug it. GPS off, screen off, LongFast idle —
     the always-listening relay state.
  2. Leave the phone app or head-node collector logging DeviceTelemetry
     overnight (battery_level=..., voltage=... lines every ~2 min).
  3. Run this on the JSONL stream (or --follow it live).

Output: discharge curve, %/hour, and — given the cell's Wh — the measured
average drain in mA, i.e. the number that replaces rx_listen_ma in
config/sim/wmnf_sim.yaml.

Run: .venv/bin/python scripts/discharge_test.py path/to/telemetry_stream.jsonl \
        --cell-wh 12.6   # e.g. 3400 mAh 18650 at 3.7 V
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

RX = re.compile(r"battery_level=(\d+), voltage=([\d.]+)")


def parse(path: Path, node: str | None):
    pts = []
    with open(path, errors="ignore") as fh:
        for line in fh:
            if "battery_level" not in line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if node and e.get("node_id") != node:
                continue
            m = RX.search(e.get("line", ""))
            if not m:
                continue
            lvl = int(m.group(1))
            if lvl > 100:
                continue                      # 101 = external power; not discharge
            pts.append((datetime.fromisoformat(e["timestamp_utc"]),
                        lvl, float(m.group(2))))
    pts.sort()
    return pts


def analyze(pts, cell_wh: float, batt_v: float):
    if len(pts) < 5:
        return None
    # longest monotone-ish discharge run
    runs, run = [], [pts[0]]
    for p in pts[1:]:
        if p[1] <= run[-1][1] + 1:
            run.append(p)
        else:
            runs.append(run)
            run = [p]
    runs.append(run)
    best = max(runs, key=lambda r: (r[-1][0] - r[0][0]).total_seconds())
    (t0, l0, v0), (t1, l1, v1) = best[0], best[-1]
    hours = (t1 - t0).total_seconds() / 3600.0
    if hours < 1.0 or l0 <= l1:
        return None
    pct_per_h = (l0 - l1) / hours
    wh_per_h = cell_wh * pct_per_h / 100.0
    ma = wh_per_h / batt_v * 1000.0
    return {"from": f"{t0:%m-%d %H:%M} {l0}% {v0:.2f}V",
            "to": f"{t1:%m-%d %H:%M} {l1}% {v1:.2f}V",
            "hours": round(hours, 2), "pct_per_hour": round(pct_per_h, 2),
            "measured_avg_ma": round(ma, 1),
            "n_points": len(best),
            "projected_runtime_h_full": round(100.0 / pct_per_h, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Node discharge-rate analyzer")
    ap.add_argument("stream", help="telemetry_stream.jsonl path")
    ap.add_argument("--node", default=None, help="filter node_id")
    ap.add_argument("--cell-wh", type=float, required=True,
                    help="battery energy (Wh), e.g. 3.4 Ah x 3.7 V = 12.6")
    ap.add_argument("--batt-v", type=float, default=3.7)
    ap.add_argument("--follow", action="store_true",
                    help="re-analyze every 5 min as data arrives")
    args = ap.parse_args()

    while True:
        pts = parse(Path(args.stream), args.node)
        r = analyze(pts, args.cell_wh, args.batt_v)
        if r is None:
            print(f"[{datetime.now():%H:%M}] {len(pts)} on-battery points — "
                  "need a >1 h declining run (is it unplugged?)")
        else:
            print(json.dumps(r, indent=2))
            print(f"\n→ set rx_listen_ma: {r['measured_avg_ma']} in "
                  "config/sim/wmnf_sim.yaml (replaces the 68 mA bracket default)")
        if not args.follow:
            return 0 if r else 1
        time.sleep(300)


if __name__ == "__main__":
    raise SystemExit(main())

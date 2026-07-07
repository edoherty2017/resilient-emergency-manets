#!/usr/bin/env python3
"""Service-layer cellular availability collector (the 'World' leg of Mesh vs World).

Per the methodology note (TODO-ANCHOR P4 / docs/academic-rigor-review): comparing
LoRa RSSI to cellular RSRP is a category error. The defensible cross-technology
metric is *service-layer availability* — can a packet actually get through, and at
what latency. This pings a reachable host through the cellular interface every N
seconds and logs RTT + reachability, null-safe on timeout.

Records append to cellular_telemetry.jsonl with fields:
  timestamp_utc, cell_ping_rtt_ms (null if unreachable), cell_available (bool),
  cell_carrier, cell_tech, lat, lon, elev_m, target, interface

Runs on the Pi (tethered to the Verizon MiFi) or any host with the cellular
interface. Position is left null here and filled by merge_cellular_into_telemetry.py
from the GPS-bearing telemetry stream (single source of position truth).

Usage:
  python3 scripts/cellular_ping_collector.py --interface ppp0 --interval-s 30 \
      --out /home/pump/telemetry_head/cellular_telemetry.jsonl
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def ping_once(target: str, interface: str | None, timeout_s: int) -> float | None:
    """Return RTT in ms, or None if unreachable/timed out."""
    system = platform.system()
    cmd = ["ping", "-c", "1"]
    if system == "Darwin":
        cmd += ["-t", str(timeout_s)]
        if interface:
            cmd += ["-b", interface]
    else:  # Linux
        cmd += ["-W", str(timeout_s)]
        if interface:
            cmd += ["-I", interface]
    cmd.append(target)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    m = re.search(r"time[=<]([\d.]+)\s*ms", out.stdout)
    return float(m.group(1)) if m else None


def query_mifi(admin_url: str | None) -> dict:
    """Best-effort carrier/tech from a MiFi admin API; null on any failure."""
    if not admin_url:
        return {"cell_carrier": None, "cell_tech": None}
    try:
        import requests
        r = requests.get(admin_url, timeout=5)
        j = r.json()
        return {
            "cell_carrier": j.get("carrier") or j.get("operator"),
            "cell_tech": j.get("tech") or j.get("network_type"),
        }
    except Exception:
        return {"cell_carrier": None, "cell_tech": None}


def main() -> int:
    ap = argparse.ArgumentParser(description="Cellular service-layer availability collector")
    ap.add_argument("--target", default="1.1.1.1", help="Host to ping (reachable, low-jitter)")
    ap.add_argument("--interface", default=None, help="Cellular interface (e.g. ppp0, wwan0)")
    ap.add_argument("--interval-s", type=float, default=30.0)
    ap.add_argument("--timeout-s", type=int, default=4)
    ap.add_argument("--mifi-admin-url", default=None, help="Optional MiFi admin JSON endpoint for carrier/tech")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--out", default="cellular_telemetry.jsonl")
    ap.add_argument("--once", action="store_true", help="Emit a single sample and exit (for tests)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def sample() -> dict:
        rtt = ping_once(args.target, args.interface, args.timeout_s)
        carrier = query_mifi(args.mifi_admin_url)
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "trial_id": args.trial_id,
            "target": args.target,
            "interface": args.interface,
            "cell_ping_rtt_ms": rtt,
            "cell_available": rtt is not None,
            "cell_carrier": carrier["cell_carrier"],
            "cell_tech": carrier["cell_tech"],
            "lat": None, "lon": None, "elev_m": None,  # filled at merge time
        }

    with out_path.open("a") as f:
        while True:
            rec = sample()
            f.write(json.dumps(rec) + "\n")
            f.flush()
            print(json.dumps(rec))
            if args.once:
                break
            time.sleep(args.interval_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

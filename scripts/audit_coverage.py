#!/usr/bin/env python3
"""SAR-coverage audit: is every region actually covered?

Two falsifiable criteria:
  1. Backhaul connectivity — every fixed site must reach an MQTT gateway
     through a chain of usable links (ITM q90 RSSI ≥ sensitivity). Sites in a
     connected component with no gateway are STRANDED.
  2. Trail coverage — along every rental route, the fraction of track samples
     whose best loss to any fixed site closes the link budget
     (loss ≤ EIRP − sensitivity). A route below --trail-threshold is flagged.

Reads the link matrix + topology + routes; writes audit JSON and prints a
region-by-region verdict. Exit code 1 if any site is stranded or any route is
under-covered — so 'fully covered' is a testable state, not a claim.

Run: .venv/bin/python scripts/audit_coverage.py --suffix _statewide
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

EIRP_DBM = 26.3
RX_SENS_DBM = -131.0
MAX_LOSS_DB = EIRP_DBM - RX_SENS_DBM   # 157.3 dB closes the budget


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit SAR coverage (connectivity + trails)")
    ap.add_argument("--suffix", default="_statewide")
    ap.add_argument("--routes", default=None,
                    help="Routes file for trail coverage (default routes<suffix>.json)")
    ap.add_argument("--trail-threshold", type=float, default=0.85,
                    help="Minimum fraction of route samples in mesh range")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    topo = json.loads((ROOT / f"artifacts/sim/topology{args.suffix}.json").read_text())
    links = pd.read_csv(ROOT / f"artifacts/sim/link_matrix{args.suffix}.csv")
    sites = topo["sites"]

    # ── 1. connected components over usable links ────────────────────────────
    parent = {n: n for n in sites}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for _, r in links[links["usable_q90"]].iterrows():
        a, b = r["link"].split("<->")
        union(a, b)

    comps: dict[str, list[str]] = {}
    for n in sites:
        comps.setdefault(find(n), []).append(n)

    stranded, component_rows = [], []
    for root, members in sorted(comps.items(), key=lambda kv: -len(kv[1])):
        gws = [m for m in members if sites[m].get("mqtt_uplink")]
        ok = bool(gws)
        component_rows.append({
            "n_sites": len(members), "gateways": gws, "reaches_backhaul": ok,
            "members": sorted(members),
        })
        if not ok:
            stranded.extend(members)

    # ── 2. trail coverage from the routes file ────────────────────────────────
    # Only sites that themselves reach a gateway count: being heard by a
    # stranded relay is not coverage.
    reachable = {n for n in sites if find(n) in
                 {find(g) for g in sites if sites[g].get("mqtt_uplink")}}
    routes_path = args.routes or f"artifacts/sim/routes{args.suffix}.json"
    trail_rows = []
    rp = ROOT / routes_path
    if rp.exists():
        rj = json.loads(rp.read_text())
        for rname, r in rj["routes"].items():
            n = len(r["loss_t_s"])
            in_range = 0
            usable_sites = [s for s in r["loss_db_q50"] if s in reachable]
            for i in range(n):
                best = min((r["loss_db_q50"][s][i] for s in usable_sites),
                           default=999.0)
                if best <= MAX_LOSS_DB:
                    in_range += 1
            frac = in_range / n if n else 0.0
            trail_rows.append({"route": rname, "geometry": r.get("geometry", "?"),
                               "samples": n, "coverage": round(frac, 3),
                               "ok": frac >= args.trail_threshold})

    n_stranded = len(stranded)
    bad_routes = [t for t in trail_rows if not t["ok"]]
    verdict = "PASS" if (n_stranded == 0 and not bad_routes) else "FAIL"

    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "criteria": {
            "usable_link": "ITM q90 RSSI >= -131 dBm",
            "max_loss_db": MAX_LOSS_DB,
            "trail_threshold": args.trail_threshold,
        },
        "n_sites": len(sites),
        "n_components": len(comps),
        "components": component_rows,
        "stranded_sites": sorted(stranded),
        "trail_coverage": sorted(trail_rows, key=lambda t: t["coverage"]),
        "verdict": verdict,
    }
    out = ROOT / (args.out or f"artifacts/sim/coverage_audit{args.suffix}.json")
    out.write_text(json.dumps(audit, indent=2))

    print(f"sites {len(sites)}  components {len(comps)}  "
          f"stranded {n_stranded}  routes-under-threshold {len(bad_routes)}")
    for c in component_rows:
        tag = "OK  " if c["reaches_backhaul"] else "DEAD"
        head = ", ".join(c["members"][:5]) + ("…" if c["n_sites"] > 5 else "")
        print(f"  [{tag}] {c['n_sites']:3d} sites  gw={len(c['gateways'])}  {head}")
    if trail_rows:
        print("trail coverage (worst first):")
        for t in sorted(trail_rows, key=lambda t: t["coverage"])[:24]:
            print(f"  {'OK ' if t['ok'] else 'LOW'} {t['route']:26s} "
                  f"{t['coverage']*100:5.1f}%  [{t['geometry']}]")
    print("VERDICT:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

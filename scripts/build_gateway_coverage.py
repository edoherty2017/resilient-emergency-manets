#!/usr/bin/env python3
"""Statewide ITM coverage rasters for every MQTT gateway.

Reuses render_sim_viewer.coverage_layer (60x60 ITM grid per gateway, cached
as artifacts/sim/coverage_<name>.npz) over the statewide DEM, and writes one
index — artifacts/sim/coverage_overlays.json — that render_year_arena.py
embeds as a toggleable heatmap layer group. Pad is sized to the 12 km
max-link radius of the statewide build (vs the pilot's 5 km).

Run: .venv/bin/python scripts/build_gateway_coverage.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem  # noqa: E402
from render_sim_viewer import coverage_layer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topology", default="artifacts/sim/topology_statewide.json")
    ap.add_argument("--dem-npz",
                    default="artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    ap.add_argument("--out", default="artifacts/sim/coverage_overlays.json")
    ap.add_argument("--pad-lat", type=float, default=0.11)   # ~12 km
    ap.add_argument("--pad-lon", type=float, default=0.15)
    ap.add_argument("--only", default=None, help="single gateway (timing test)")
    args = ap.parse_args()

    topo = json.loads((ROOT / args.topology).read_text())
    dem = Dem(ROOT / args.dem_npz)
    gws = {n: s for n, s in topo["sites"].items() if s.get("mqtt_uplink")}
    if args.only:
        gws = {args.only: gws[args.only]}
    layers = []
    t0 = time.time()
    for i, (n, s) in enumerate(sorted(gws.items())):
        t1 = time.time()
        layers.append(coverage_layer(dem, n, s["lat"], s["lon"], s["hg_m"],
                                     pad=(args.pad_lat, args.pad_lon)))
        print(f"[{i+1}/{len(gws)}] {n}  {time.time()-t1:.1f}s", flush=True)
    (ROOT / args.out).write_text(json.dumps(layers))
    print(f"wrote {args.out}: {len(layers)} gateway rasters "
          f"in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

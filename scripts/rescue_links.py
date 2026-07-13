#!/usr/bin/env python3
"""Fine-DEM link rescue for strands the 74 m statewide DEM can't resolve.

The statewide screening DEM (~74 m/px) systematically kills short ridge hops:
sub-km summit-to-summit links vanish because the profile smooths the saddle
and the knife-edge alike. The Presidentials work showed such links often close
on ~10 m terrain. This pass, for every stranded site from audit_coverage:

  1. take candidate partners within --max-km, nearest first (reachable sites
     preferred, same-strand members allowed for chaining)
  2. fetch a small USGS 3DEP tile (~10 m/px) around each candidate pair
     (cached in artifacts/dem/cache/rescue_*.npz)
  3. recompute Longley-Rice q90 on the fine profile
  4. admit the link into topology/link-matrix ONLY if usable on fine terrain,
     tagged dem=fine_3dep — an auditable override, not a fudge

Reachability is recomputed between passes so chains resolve transitively.

Run: .venv/bin/python scripts/rescue_links.py --suffix _statewide
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import (  # noqa: E402
    Dem, itm_p2p_loss, haversine_m, RX_POWER_REF_DBM, RX_SENS_DBM, PLANNING_DBM,
)

FINE_WIDTH_PX = 1100
PAD_DEG = 0.012


def fetch_fine_dem(lat_lo, lat_hi, lon_lo, lon_hi, name) -> Path | None:
    npz = ROOT / f"artifacts/dem/cache/{name}.npz"
    if npz.exists():
        return npz
    import time
    for attempt, backoff in enumerate((2, 6, 15)):
        time.sleep(backoff)              # 3DEP API dislikes rapid fire
        r = subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/dem_3dep.py"),
             "--lat-min", f"{lat_lo:.5f}", "--lat-max", f"{lat_hi:.5f}",
             "--lon-min", f"{lon_lo:.5f}", "--lon-max", f"{lon_hi:.5f}",
             "--width", str(FINE_WIDTH_PX), "--name", name],
            capture_output=True, text=True, timeout=300)
        # dem_3dep exits 1 when its Mt-Washington sanity point is outside the
        # tile — the artifact is still valid; trust the npz, not the rc.
        if npz.exists():
            return npz
        if attempt == 2:
            err = (r.stderr.strip() or r.stdout.strip())[-160:]
            print(f"    fine-DEM fetch failed for {name}: {err}")
    return None


def reachable_set(sites: dict, usable_pairs: set) -> set:
    parent = {n: n for n in sites}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in usable_pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    gw_roots = {find(g) for g, s in sites.items() if s.get("mqtt_uplink")}
    return {n for n in sites if find(n) in gw_roots}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fine-DEM rescue of stranded links")
    ap.add_argument("--suffix", default="_statewide")
    ap.add_argument("--max-km", type=float, default=9.0)
    ap.add_argument("--max-candidates", type=int, default=6)
    ap.add_argument("--passes", type=int, default=3)
    args = ap.parse_args()

    topo_p = ROOT / f"artifacts/sim/topology{args.suffix}.json"
    lm_p = ROOT / f"artifacts/sim/link_matrix{args.suffix}.csv"
    topo = json.loads(topo_p.read_text())
    lm = pd.read_csv(lm_p)
    sites = topo["sites"]

    usable = set()
    for _, r in lm[lm["usable_q90"]].iterrows():
        a, b = r["link"].split("<->")
        usable.add((a, b))

    admitted = []
    for pass_i in range(args.passes):
        reach = reachable_set(sites, usable)
        stranded = [n for n in sites if n not in reach]
        if not stranded:
            break
        print(f"pass {pass_i + 1}: {len(stranded)} stranded: {stranded}")
        progress = False
        for s in stranded:
            ss = sites[s]
            cands = sorted(
                ((haversine_m(ss["lat"], ss["lon"], so["lat"], so["lon"]), n)
                 for n, so in sites.items() if n != s),
                key=lambda x: x[0])
            cands = [(d, n) for d, n in cands if d <= args.max_km * 1000.0]
            # prefer partners that already reach backhaul
            cands.sort(key=lambda x: (x[1] not in reach, x[0]))
            for d_m, partner in cands[:args.max_candidates]:
                if (s, partner) in usable or (partner, s) in usable:
                    continue
                po = sites[partner]
                lat_lo = min(ss["lat"], po["lat"]) - PAD_DEG
                lat_hi = max(ss["lat"], po["lat"]) + PAD_DEG
                lon_lo = min(ss["lon"], po["lon"]) - PAD_DEG * 1.35
                lon_hi = max(ss["lon"], po["lon"]) + PAD_DEG * 1.35
                name = f"rescue_{min(s,partner)}_{max(s,partner)}"[:60]
                npz = fetch_fine_dem(lat_lo, lat_hi, lon_lo, lon_hi, name)
                if npz is None:
                    continue
                dem = Dem(npz)
                dd, prof = dem.profile(ss["lat"], ss["lon"], po["lat"], po["lon"])
                try:
                    itm = itm_p2p_loss(dd / 1000.0, prof, (ss["hg_m"], po["hg_m"]))
                except Exception as e:
                    print(f"    ITM failed {s}<->{partner}: {e}")
                    continue
                rssi90 = RX_POWER_REF_DBM - itm["loss_db_q90"]
                verdict = ("USABLE" if rssi90 >= RX_SENS_DBM else "dead")
                print(f"  {s} <-> {partner} {d_m/1000:.2f} km fine-DEM "
                      f"q90 {rssi90:7.1f} dBm -> {verdict}")
                if rssi90 >= RX_SENS_DBM:
                    key = f"{s}|{partner}"
                    topo["links"][key] = {
                        "loss_db_q50": round(itm["loss_db_q50"], 1),
                        "loss_db_q90": round(itm["loss_db_q90"], 1),
                        "distance_km": round(d_m / 1000.0, 3),
                        "dem": "fine_3dep",
                    }
                    lm.loc[len(lm)] = {
                        "link": f"{s}<->{partner}",
                        "distance_km": round(d_m / 1000.0, 2),
                        "path_type": itm["path_type"],
                        "pred_rssi_dbm_q50": round(RX_POWER_REF_DBM - itm["loss_db_q50"], 1),
                        "pred_rssi_dbm_q90": round(rssi90, 1),
                        "worst_fresnel_fraction": np.nan,
                        "usable_q90": True,
                        "planning_ok_q90": bool(rssi90 >= PLANNING_DBM),
                    }
                    usable.add((s, partner))
                    admitted.append({"link": f"{s}<->{partner}",
                                     "rssi_q90": round(rssi90, 1),
                                     "distance_km": round(d_m / 1000.0, 2)})
                    progress = True
                    break                      # this site is rescued; next
        if not progress:
            break

    reach = reachable_set(sites, usable)
    still = [n for n in sites if n not in reach]
    topo["fine_dem_rescue"] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "admitted_links": admitted,
        "still_stranded": still,
    }
    topo_p.write_text(json.dumps(topo))
    lm.to_csv(lm_p, index=False)
    print(f"\nadmitted {len(admitted)} fine-DEM links; still stranded: {still or 'NONE'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

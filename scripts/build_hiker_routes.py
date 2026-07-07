#!/usr/bin/env python3
"""Build realistic hiker day-hike tracks for the rental-fleet simulation.

Six canonical Presidential Range day hikes, each defined as a waypoint chain
along the real trail corridor (site coordinates + known junctions, ±150 m).
Between waypoints the track is interpolated over the DEM every ~150 m and
walked at Tobler's hiking-function speed (terrain-slope aware), so timing is
realistic: steep climbs are slow, flats are ~5 km/h.

For each track sample (every ~600 m) the Longley-Rice ITM loss to every fixed
site within range is computed, giving mesh_sim per-second link quality for
every rented node on every route.

Output: artifacts/sim/routes.json
Run: .venv/bin/python scripts/build_hiker_routes.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, itm_p2p_loss, haversine_m  # noqa: E402

HIKER_HG_M = 1.5
SAMPLE_M = 150.0          # track interpolation step
LOSS_EVERY_N = 4          # ITM loss every 4th sample (~600 m), interp between
MAX_LINK_KM = 9.0         # skip ITM beyond this (loss ~ certainly dead)
DEAD_DB = 300.0

# waypoint chains: (lat, lon). Kiosk = where the node is rented/returned.
ROUTES = {
    "ammo_jewell_loop": {
        "kiosk": "gateway_marshfield", "return_kiosk": "gateway_marshfield",
        "waypoints": [(44.26790, -71.35970), (44.26616, -71.32348),
                      (44.25890, -71.31870), (44.27060, -71.30330),
                      (44.29030, -71.31870), (44.28376, -71.33583),
                      (44.26790, -71.35970)],
    },
    "tuckerman_loop": {
        "kiosk": "pinkham_notch_vc", "return_kiosk": "pinkham_notch_vc",
        "waypoints": [(44.25730, -71.25320), (44.26030, -71.28460),
                      (44.26370, -71.29750), (44.27060, -71.30330),
                      (44.26610, -71.29260), (44.26030, -71.28460),
                      (44.25730, -71.25320)],
    },
    "crawford_traverse": {
        "kiosk": "highland_center", "return_kiosk": "gateway_marshfield",
        "waypoints": [(44.21790, -71.41140), (44.22580, -71.38120),
                      (44.24130, -71.35020), (44.25540, -71.32100),
                      (44.25890, -71.31870), (44.27060, -71.30330),
                      (44.26616, -71.32348), (44.26790, -71.35970)],
    },
    "valley_way_madison": {
        "kiosk": "appalachia_th", "return_kiosk": "appalachia_th",
        "waypoints": [(44.37190, -71.28950), (44.34500, -71.29000),
                      (44.32770, -71.28320), (44.32840, -71.27720),
                      (44.32770, -71.28320), (44.34500, -71.29000),
                      (44.37190, -71.28950)],
    },
    "carter_wildcat": {
        "kiosk": "glen_house", "return_kiosk": "pinkham_notch_vc",
        "waypoints": [(44.28800, -71.22460), (44.25910, -71.19580),
                      (44.26370, -71.21830), (44.25900, -71.22600),
                      (44.25730, -71.25320)],
    },
    "great_gulf_osgood": {
        "kiosk": "great_gulf_th", "return_kiosk": "great_gulf_th",
        "waypoints": [(44.31350, -71.25550), (44.32500, -71.27000),
                      (44.32840, -71.27720), (44.32770, -71.28320),
                      (44.32840, -71.27720), (44.32500, -71.27000),
                      (44.31350, -71.25550)],
    },
    # ── statewide routes (kiosks exist only in the statewide topology; routes
    #    are skipped automatically when their kiosk is absent) ────────────────
    "franconia_ridge_loop": {
        "kiosk": "lafayette_place", "return_kiosk": "lafayette_place",
        "waypoints": [(44.14180, -71.68110), (44.16090, -71.66020),
                      (44.16080, -71.64450), (44.14480, -71.64520),
                      (44.14180, -71.68110)],
    },
    "lonesome_lake_family": {
        "kiosk": "lafayette_place", "return_kiosk": "lafayette_place",
        "waypoints": [(44.14180, -71.68110), (44.13810, -71.70330),
                      (44.14180, -71.68110)],
    },
    "pemi_bonds_long": {
        "kiosk": "lincoln_woods_th", "return_kiosk": "lincoln_woods_th",
        "waypoints": [(44.06360, -71.58880), (44.14100, -71.54360),
                      (44.16250, -71.53400), (44.14100, -71.54360),
                      (44.06360, -71.58880)],
    },
    "moosilauke_gorge_brook": {
        "kiosk": "ravine_lodge", "return_kiosk": "ravine_lodge",
        "waypoints": [(43.99870, -71.81570), (44.01810, -71.83900),
                      (44.02440, -71.83140), (44.01810, -71.83900),
                      (43.99870, -71.81570)],
    },
    "osceola_greeley": {
        "kiosk": "waterville_valley", "return_kiosk": "waterville_valley",
        "waypoints": [(43.95060, -71.50310), (44.02010, -71.51730),
                      (43.98410, -71.53370), (44.02010, -71.51730),
                      (43.95060, -71.50310)],
    },
    "chocorua_piper": {
        "kiosk": "piper_th", "return_kiosk": "piper_th",
        "waypoints": [(43.95230, -71.36980), (43.95440, -71.39750),
                      (43.95230, -71.36980)],
    },
    "carrigain_signal_ridge": {
        "kiosk": "sawyer_river_th", "return_kiosk": "sawyer_river_th",
        "waypoints": [(44.06840, -71.42500), (44.08900, -71.45300),
                      (44.09430, -71.44660), (44.08900, -71.45300),
                      (44.06840, -71.42500)],
    },
    "monadnock_white_dot": {
        "kiosk": "monadnock_hq", "return_kiosk": "monadnock_hq",
        "waypoints": [(42.84510, -72.08770), (42.86110, -72.10810),
                      (42.84510, -72.08770)],
    },
    "cardigan_west_ridge": {
        "kiosk": "cardigan_lodge", "return_kiosk": "cardigan_lodge",
        "waypoints": [(43.64990, -71.88450), (43.64960, -71.91470),
                      (43.64990, -71.88450)],
    },
    "belknap_range_walk": {
        "kiosk": "gunstock_top", "return_kiosk": "gunstock_top",
        "waypoints": [(43.52520, -71.36610), (43.50810, -71.42640),
                      (43.51340, -71.38480), (43.52520, -71.36610)],
    },
    "kearsarge_winslow": {
        "kiosk": "winslow_hq", "return_kiosk": "winslow_hq",
        "waypoints": [(43.39160, -71.86200), (43.38310, -71.85740),
                      (43.39160, -71.86200)],
    },
    "pack_monadnock_loop": {
        "kiosk": "miller_hq", "return_kiosk": "miller_hq",
        "waypoints": [(42.85830, -71.88940), (42.86160, -71.87810),
                      (42.85830, -71.88940)],
    },
    # ── round-6 validation routes (new regions) ──────────────────────────────
    "squam_morgan_percival": {
        "kiosk": "rockywold_camps", "return_kiosk": "rockywold_camps",
        "waypoints": [(43.77900, -71.53800), (43.78980, -71.55210),
                      (43.78620, -71.50820), (43.77900, -71.53800)],
    },
    "rumney_rattlesnake": {
        "kiosk": "rumney_village", "return_kiosk": "rumney_village",
        "waypoints": [(43.80530, -71.81260), (43.79680, -71.75900),
                      (43.80530, -71.81260)],
    },
    "owls_head_marathon": {
        "kiosk": "lincoln_woods_th", "return_kiosk": "lincoln_woods_th",
        "waypoints": [(44.06360, -71.58880), (44.09000, -71.58700),
                      (44.12300, -71.60130), (44.09000, -71.58700),
                      (44.06360, -71.58880)],
    },
    "isolation_glen_boulder": {
        "kiosk": "glen_ellis", "return_kiosk": "glen_ellis",
        "waypoints": [(44.24150, -71.25330), (44.25000, -71.28300),
                      (44.22160, -71.31600), (44.25000, -71.28300),
                      (44.24150, -71.25330)],
    },
    "hale_zealand_loop": {
        "kiosk": "twin_mountain_village", "return_kiosk": "twin_mountain_village",
        "waypoints": [(44.25880, -71.54360), (44.22550, -71.47870),
                      (44.18450, -71.51830), (44.19640, -71.49400),
                      (44.22550, -71.47870), (44.25880, -71.54360)],
    },
    "baldface_wild_river": {
        "kiosk": "wild_river_cg", "return_kiosk": "wild_river_cg",
        "waypoints": [(44.30640, -71.05610), (44.24480, -71.07840),
                      (44.23480, -71.06850), (44.30640, -71.05610)],
    },
    "bear_brook_loop": {
        "kiosk": "bear_brook_hq", "return_kiosk": "bear_brook_hq",
        "waypoints": [(43.16600, -71.39400), (43.15800, -71.36700),
                      (43.16600, -71.39400)],
    },
}


def tobler_kmh(slope: float) -> float:
    return float(np.clip(6.0 * math.exp(-3.5 * abs(slope + 0.05)), 0.5, 6.0))


def interpolate_track(dem: Dem, waypoints):
    """Densify the waypoint chain over the DEM and time it with Tobler pace."""
    lats, lons = [waypoints[0][0]], [waypoints[0][1]]
    for (la1, lo1), (la2, lo2) in zip(waypoints, waypoints[1:]):
        d = haversine_m(la1, lo1, la2, lo2)
        n = max(int(d / SAMPLE_M), 1)
        for k in range(1, n + 1):
            f = k / n
            lats.append(la1 + (la2 - la1) * f)
            lons.append(lo1 + (lo2 - lo1) * f)
    lats, lons = np.array(lats), np.array(lons)
    elev = dem.sample(lats, lons)
    t = [0.0]
    for i in range(1, len(lats)):
        d = haversine_m(lats[i - 1], lons[i - 1], lats[i], lons[i])
        slope = (elev[i] - elev[i - 1]) / max(d, 1.0)
        v_ms = tobler_kmh(slope) / 3.6
        t.append(t[-1] + d / v_ms)
    return lats, lons, elev, np.array(t)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build hiker route tracks + ITM losses")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_presidentials_wide.npz")
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--out", default="artifacts/sim/routes.json")
    args = ap.parse_args()

    dem = Dem(ROOT / args.dem_npz)
    topo = json.loads((ROOT / args.topology).read_text())
    sites = topo["sites"]

    out = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
           "tobler_pacing": True, "routes": {}}
    from osm_trails import trail_polyline
    for name, r in ROUTES.items():
        if r["kiosk"] not in sites:
            continue                    # region not in this topology
        poly, geom_src = trail_polyline(r["waypoints"])
        lats, lons, elev, t = interpolate_track(dem, poly)
        # ITM loss to nearby sites at every LOSS_EVERY_N-th sample
        idxs = list(range(0, len(lats), LOSS_EVERY_N))
        if idxs[-1] != len(lats) - 1:
            idxs.append(len(lats) - 1)
        losses = {s: [] for s in sites}
        for i in idxs:
            for sname, s in sites.items():
                d_m = haversine_m(s["lat"], s["lon"], lats[i], lons[i])
                if d_m > MAX_LINK_KM * 1000.0:
                    losses[sname].append(DEAD_DB)
                    continue
                if d_m < 30.0:
                    losses[sname].append(30.0)
                    continue
                try:
                    dd, prof = dem.profile(s["lat"], s["lon"], lats[i], lons[i])
                    itm = itm_p2p_loss(dd / 1000.0, prof, (s["hg_m"], HIKER_HG_M))
                    losses[sname].append(round(itm["loss_db_q50"], 1))
                except Exception:
                    losses[sname].append(DEAD_DB)
        t_loss = [float(t[i]) for i in idxs]
        out["routes"][name] = {
            "kiosk": r["kiosk"], "return_kiosk": r["return_kiosk"],
            "geometry": geom_src,
            "duration_s": round(float(t[-1]), 1),
            "distance_km": round(sum(haversine_m(lats[i-1], lons[i-1], lats[i], lons[i])
                                     for i in range(1, len(lats))) / 1000.0, 2),
            "t_s": [round(float(v), 1) for v in t],
            "lat": [round(float(v), 6) for v in lats],
            "lon": [round(float(v), 6) for v in lons],
            "loss_t_s": t_loss,
            "loss_db_q50": losses,
        }
        print(f"{name:22s} {out['routes'][name]['distance_km']:6.2f} km  "
              f"{out['routes'][name]['duration_s']/3600:5.2f} h  [{geom_src}]  "
              f"({len(idxs)} loss samples x {len(sites)} sites)")

    (ROOT / args.out).write_text(json.dumps(out))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the WMNF simulation topology: sites, ITM link matrix, hiker path.

Proposed network (all inside the 3DEP DEM AOI, Presidential Range):
  - summit_shermanadams  MQTT backhaul #1 — Sherman Adams building / MWObs
                         (year-round grid power + internet; 6 m building mount)
  - gateway_marshfield   MQTT backhaul #2 — Cog Railway Marshfield Base Station
                         (grid power, seasonal internet; western trailhead)
  - lakes_hut            AMC Lakes of the Clouds hut (seasonal hut power)
  - ammo_relay           Ammonoosuc treeline relay (solar, 3 m mast)
  - jewell_relay         Jewell Trail treeline relay (solar, 3 m mast)
  - clay_relay           Gulfside ridge near Mt. Clay (solar; bridges
                         jewell/summit/northern ridge)
  - hermit_lake          Hermit Lake caretaker site, Tuckerman (AMC solar)
  - madison_hut          AMC Madison Spring hut (seasonal hut power; northern
                         extension)
  + hiker_alpha          mobile node replaying the Trial 1 Garmin GPX track.

Outputs:
  artifacts/sim/topology.json   sites + directed ITM losses + horizon masks
                                + time-indexed hiker losses (mesh_sim input)
  artifacts/sim/link_matrix.csv human-readable link table

Run: .venv/bin/python scripts/build_sim_topology.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import (  # noqa: E402
    Dem, itm_p2p_loss, fresnel_analysis, load_garmin_gpx, haversine_m,
    EIRP_DBM, RX_SENS_DBM, PLANNING_DBM,
)
from solar_model import horizon_mask  # noqa: E402

# 32 deliberately placed sites (4× build-out, decision-driven, not random):
#   gateway — grid power + internet exists today → MQTT backhaul (4, one per road
#             corridor: summit, Cog base/west, Pinkham/east, Crawford/south)
#   hut     — AMC/RMC huts with seasonal power + staff (5)
#   shelter — caretaker camps (3)
#   ridge   — treeline/summit solar relays placed for LOS along trail corridors (12)
#   valley  — trailhead nodes at road corridors (8)
# Coordinates are map-derived (±~150 m); survey on deployment. hg_m: buildings 4–6 m,
# masts 3 m.
def _s(lat, lon, hg, power, mqtt, cat, label):
    return {"lat": lat, "lon": lon, "hg_m": hg, "power": power,
            "mqtt_uplink": mqtt, "category": cat, "label": label}

SITES = {
    # ── gateways (grid + internet) ────────────────────────────────────────────
    "summit_shermanadams": _s(44.27060, -71.30330, 6.0, "grid", True, "gateway",
                              "Sherman Adams summit bldg (MWObs, year-round net)"),
    "gateway_marshfield":  _s(44.26790, -71.35970, 3.0, "grid", True, "gateway",
                              "Cog Marshfield Base Station (west corridor)"),
    "pinkham_notch_vc":    _s(44.25730, -71.25320, 4.0, "grid", True, "gateway",
                              "AMC Pinkham Notch Visitor Center (Rt 16, east)"),
    "highland_center":     _s(44.21790, -71.41140, 4.0, "grid", True, "gateway",
                              "AMC Highland Center, Crawford Notch (south)"),
    # ── huts (seasonal power) ─────────────────────────────────────────────────
    "lakes_hut":           _s(44.25890, -71.31870, 3.0, "solar", False, "hut",
                              "AMC Lakes of the Clouds hut"),
    "madison_hut":         _s(44.32770, -71.28320, 3.0, "solar", False, "hut",
                              "AMC Madison Spring hut"),
    "mizpah_hut":          _s(44.21960, -71.36960, 3.0, "solar", False, "hut",
                              "AMC Mizpah Spring hut"),
    "carter_notch_hut":    _s(44.25910, -71.19580, 4.0, "solar", False, "hut",
                              "AMC Carter Notch hut (building mount)"),
    "grayknob_cabin":      _s(44.31160, -71.31230, 3.0, "solar", False, "hut",
                              "RMC Gray Knob cabin (year-round caretaker)"),
    # ── caretaker shelters ────────────────────────────────────────────────────
    "hermit_lake":         _s(44.26030, -71.28460, 3.0, "solar", False, "shelter",
                              "Hermit Lake caretaker site (Tuckerman)"),
    "crag_camp":           _s(44.31450, -71.30620, 3.0, "solar", False, "shelter",
                              "RMC Crag Camp (King Ravine rim)"),
    "dolly_copp":          _s(44.33690, -71.25320, 3.0, "solar", False, "shelter",
                              "Dolly Copp campground (Rt 16 north)"),
    # ── ridge relays (solar, 3 m mast, placed for corridor LOS) ───────────────
    "ammo_relay":          _s(44.26616, -71.32348, 3.0, "solar", False, "ridge",
                              "Ammonoosuc treeline relay"),
    "jewell_relay":        _s(44.28376, -71.33583, 3.0, "solar", False, "ridge",
                              "Jewell Trail treeline relay"),
    "clay_relay":          _s(44.29030, -71.31870, 3.0, "solar", False, "ridge",
                              "Gulfside ridge nr Mt. Clay"),
    "monroe_flank":        _s(44.25540, -71.32100, 3.0, "solar", False, "ridge",
                              "Mt. Monroe flank (Crawford Path)"),
    "lion_head":           _s(44.26610, -71.29260, 3.0, "solar", False, "ridge",
                              "Lion Head (Tuckerman rim)"),
    "boott_spur":          _s(44.25650, -71.29350, 3.0, "solar", False, "ridge",
                              "Boott Spur ridge"),
    "jefferson_lawn":      _s(44.30320, -71.31690, 3.0, "solar", False, "ridge",
                              "Monticello Lawn nr Mt. Jefferson"),
    "thunderstorm_jct":    _s(44.31990, -71.29130, 3.0, "solar", False, "ridge",
                              "Thunderstorm Junction nr Mt. Adams"),
    "eisenhower_relay":    _s(44.24130, -71.35020, 3.0, "solar", False, "ridge",
                              "Mt. Eisenhower shoulder"),
    "pierce_relay":        _s(44.22580, -71.38120, 3.0, "solar", False, "ridge",
                              "Mt. Pierce (Crawford Path S end)"),
    "wildcat_d":           _s(44.25900, -71.22600, 3.0, "solar", False, "ridge",
                              "Wildcat D summit (gondola top)"),
    "nelson_crag":         _s(44.27600, -71.29600, 3.0, "solar", False, "ridge",
                              "Nelson Crag (Auto Rd flank)"),
    # ── valley / trailhead nodes ──────────────────────────────────────────────
    "appalachia_th":       _s(44.37190, -71.28950, 3.0, "solar", False, "valley",
                              "Appalachia trailhead (Rt 2)"),
    "caps_ridge_th":       _s(44.29770, -71.35380, 3.0, "solar", False, "valley",
                              "Caps Ridge trailhead (Jefferson Notch Rd)"),
    "glen_ellis":          _s(44.24150, -71.25330, 3.0, "solar", False, "valley",
                              "Glen Ellis trailhead (Rt 16)"),
    "great_gulf_th":       _s(44.31350, -71.25550, 3.0, "solar", False, "valley",
                              "Great Gulf trailhead (Rt 16)"),
    "glen_house":          _s(44.28800, -71.22460, 3.0, "solar", False, "valley",
                              "Glen House / Auto Rd base (Rt 16)"),
    "jackson_summit":      _s(44.20390, -71.37520, 3.0, "solar", False, "ridge",
                              "Mt. Jackson summit"),
    "webster_cliff":       _s(44.19900, -71.38900, 3.0, "solar", False, "ridge",
                              "Mt. Webster cliff line"),
    "cog_skyline":         _s(44.27500, -71.33500, 3.0, "solar", False, "valley",
                              "Cog railway mid-line (Skyline switch)"),
    # ── gap-fix relays (added after link-matrix iteration 1: each fixes a
    #    specific ITM-verified dead spot, not a guess) ─────────────────────────
    "wildcat_a":           _s(44.26370, -71.21830, 3.0, "solar", False, "ridge",
                              "Wildcat A (above Carter Notch hut)"),
    "madison_summit":      _s(44.32840, -71.27720, 3.0, "solar", False, "ridge",
                              "Mt. Madison summit (col + Great Gulf LOS)"),
    "durand_ridge":        _s(44.34500, -71.29000, 3.0, "solar", False, "ridge",
                              "Durand Ridge ledge (Appalachia corridor)"),
}

HIKER_HG_M = 1.5
SHORT_LINK_M = 1350.0        # ITM validity floor ~1 km; policy region below this
SHORT_LINK_NLOS_DB = 26.0    # FSPL + this allowance for sub-floor ridge hops


def main() -> int:
    import yaml
    ap = argparse.ArgumentParser(description="Build WMNF sim topology + ITM link matrix")
    ap.add_argument("--config", default="config/sim/wmnf_sim.yaml")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_presidentials_wide.npz")
    ap.add_argument("--hiker-gpx", default=str(Path.home() / "MANET/activity_22989412258.gpx"))
    ap.add_argument("--hiker-sample-s", type=float, default=120.0,
                    help="Resample interval along the GPX for hiker link losses")
    ap.add_argument("--out-dir", default="artifacts/sim")
    ap.add_argument("--statewide", action="store_true",
                    help="Add statewide_sites.py catalog (full NH F&G SAR terrain)")
    ap.add_argument("--max-link-km", type=float, default=12.0,
                    help="Skip ITM for pairs beyond this (treated as no-link)")
    ap.add_argument("--suffix", default="", help="Output filename suffix")
    args = ap.parse_args()

    sites_def = dict(SITES)
    if args.statewide:
        from statewide_sites import STATEWIDE_SITES
        sites_def.update(STATEWIDE_SITES)

    cfg = yaml.safe_load((ROOT / args.config).read_text())
    dem = Dem(ROOT / args.dem_npz)
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    solar_cfg = cfg["solar"]
    sites: dict[str, dict] = {}
    for name, s in sites_def.items():
        elev = float(dem.sample(np.array([s["lat"]]), np.array([s["lon"]]))[0])
        hz = horizon_mask(dem, s["lat"], s["lon"],
                          solar_cfg["horizon_azimuths"], solar_cfg["horizon_max_range_m"])
        sites[name] = {**s, "elev_m": round(elev, 1),
                       "horizon_deg": [round(float(a), 2) for a in hz]}
        print(f"site {name:22s} elev {elev:7.1f} m  horizon mean {hz.mean():5.2f}°")

    # ── Pairwise ITM link matrix (fixed sites) ────────────────────────────────
    names = list(sites)
    rows = []
    links: dict[str, dict] = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa, sb = sites[a], sites[b]
            if haversine_m(sa["lat"], sa["lon"], sb["lat"], sb["lon"]) > args.max_link_km * 1000.0:
                continue
            d_m, prof = dem.profile(sa["lat"], sa["lon"], sb["lat"], sb["lon"])
            itm = itm_p2p_loss(d_m / 1000.0, prof, (sa["hg_m"], sb["hg_m"]))
            fres = fresnel_analysis(d_m, prof, (sa["hg_m"], sb["hg_m"]))
            model = "itm"
            if d_m <= SHORT_LINK_M:
                # ITM's documented validity floor is ~1 km; below it the model
                # extrapolates absurd losses on rough profiles. Short ridge
                # hops use FSPL + a fixed NLOS allowance (Trial-1 deep-shadow
                # residual scale) instead, taking the less lossy of the two.
                fspl = (20 * math.log10(d_m) + 20 * math.log10(915.0) - 27.55
                        + SHORT_LINK_NLOS_DB)
                if fspl < itm["loss_db_q50"]:
                    itm = {**itm, "loss_db_q50": fspl, "loss_db_q90": fspl,
                           "path_type": "short_link_policy"}
                    model = "short_link_fspl"
            rssi50 = EIRP_DBM - itm["loss_db_q50"]
            rssi90 = EIRP_DBM - itm["loss_db_q90"]
            links[f"{a}|{b}"] = {"loss_db_q50": round(itm["loss_db_q50"], 1),
                                 "loss_db_q90": round(itm["loss_db_q90"], 1),
                                 "distance_km": round(d_m / 1000.0, 3),
                                 "model": model}
            rows.append({
                "link": f"{a}<->{b}", "distance_km": round(d_m / 1000.0, 2),
                "path_type": itm["path_type"],
                "pred_rssi_dbm_q50": round(rssi50, 1),
                "pred_rssi_dbm_q90": round(rssi90, 1),
                "worst_fresnel_fraction": round(fres["worst_fresnel_fraction"], 2),
                "usable_q90": bool(rssi90 >= RX_SENS_DBM),
                "planning_ok_q90": bool(rssi90 >= PLANNING_DBM),
            })
            print(f"  {a:>20s} <-> {b:22s} {d_m/1000.0:5.2f} km  "
                  f"q50 {rssi50:7.1f}  q90 {rssi90:7.1f} dBm  "
                  f"{'OK ' if rssi90 >= PLANNING_DBM else ('marginal' if rssi90 >= RX_SENS_DBM else 'DEAD')}")
    links_df = pd.DataFrame(rows).sort_values("pred_rssi_dbm_q90", ascending=False)
    links_df.to_csv(out_dir / f"link_matrix{args.suffix}.csv", index=False)

    # ── Hiker path: per-waypoint ITM loss to every fixed site ─────────────────
    hiker = None
    gpx_path = Path(args.hiker_gpx) if args.hiker_gpx else None
    if gpx_path and gpx_path.is_file():
        gpx = load_garmin_gpx(gpx_path)
        t0 = gpx["timestamp_utc"].iloc[0]
        gpx["t_s"] = (gpx["timestamp_utc"] - t0).dt.total_seconds()
        gpx["bucket"] = (gpx["t_s"] // args.hiker_sample_s).astype(int)
        wp = gpx.groupby("bucket").first().reset_index(drop=True)
        print(f"hiker path: {len(wp)} waypoints @ {args.hiker_sample_s:.0f}s "
              f"({wp['t_s'].iloc[-1]/3600:.1f} h track) — computing ITM to {len(names)} sites ...")
        losses = {n: [] for n in names}
        for _, r in wp.iterrows():
            for n in names:
                s = sites[n]
                if haversine_m(s["lat"], s["lon"], r["lat"], r["lon"]) > args.max_link_km * 1000.0:
                    losses[n].append(300.0)
                    continue
                d_m, prof = dem.profile(s["lat"], s["lon"], r["lat"], r["lon"])
                if d_m < 30.0:
                    losses[n].append(30.0)  # co-located: nominal near-field loss
                    continue
                try:
                    itm = itm_p2p_loss(d_m / 1000.0, prof, (s["hg_m"], HIKER_HG_M))
                    losses[n].append(round(itm["loss_db_q50"], 1))
                except Exception:
                    losses[n].append(300.0)
        hiker = {
            "gpx": str(gpx_path), "sample_s": args.hiker_sample_s,
            "t_s": [round(float(v), 1) for v in wp["t_s"]],
            "lat": [round(float(v), 6) for v in wp["lat"]],
            "lon": [round(float(v), 6) for v in wp["lon"]],
            "loss_db_q50": {n: v for n, v in losses.items()},
        }

    topo = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dem": args.dem_npz,
        "propagation": "Longley-Rice ITM q50 (itmlogic 1.2) over USGS 3DEP",
        "radio": {"eirp_dbm": EIRP_DBM, "rx_sensitivity_dbm": RX_SENS_DBM,
                  "planning_threshold_dbm": PLANNING_DBM},
        "sites": sites,
        "links": links,
        "hiker": hiker,
    }
    (out_dir / f"topology{args.suffix}.json").write_text(json.dumps(topo))
    print(f"wrote {out_dir}/topology{args.suffix}.json, link_matrix{args.suffix}.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

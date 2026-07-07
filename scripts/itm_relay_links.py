#!/usr/bin/env python3
"""ITM/Longley-Rice terrain-profile analysis of the proposed relay infrastructure.

Replaces the FSPL + flat terrain-class screening model for deployment decisions
(review P2 item 12). For each proposed link, and for the hiker positions during
the Trial 1 collector gap (09:36-12:24 EDT), this computes:

- Longley-Rice ITM point-to-point basic transmission loss (median + 90%/99%
  reliability) over the real USGS 3DEP terrain profile, via the `itmlogic`
  reference implementation (Oughton et al. 2020, JOSS, doi:10.21105/joss.02266).
- Geometric line-of-sight and worst first-Fresnel-zone clearance fraction with
  4/3 effective Earth radius.

Radio assumptions follow config/airmap/model-baseline.yaml: 915 MHz, EIRP
26.3 dBm (22 dBm + 2x2.15 dBi), LongFast sensitivity -131 dBm, planning
threshold -100 dBm. ITM models terrain diffraction but NOT vegetation; each
result reports the fraction of the path below treeline (~1200 m) so canopy
excess loss can be budgeted separately.

Run inside .venv (requires artifacts/dem/cache/usgs_3dep_mtwashington.npz from
scripts/dem_3dep.py):
    python scripts/itm_relay_links.py --head-gpx ~/MANET/activity_22989412258.gpx
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from itmlogic.misc.qerfi import qerfi
from itmlogic.preparatory_subroutines.qlrpfl import qlrpfl
from itmlogic.statistics.avar import avar

FREQ_MHZ = 915.0
TX_DBM = 22.0
ANT_GAIN_DBI = 2.15
EIRP_DBM = TX_DBM + 2 * ANT_GAIN_DBI
RX_SENS_DBM = -131.0       # LongFast SF11/BW250
PLANNING_DBM = -100.0      # sensitivity + ~31 dB fade margin
TREELINE_M = 1200.0
EFFECTIVE_EARTH_R_M = 6371000.0 * 4.0 / 3.0

SITES = {
    "summit":      {"lat": 44.27060, "lon": -71.30330, "hg_m": 1.5, "label": "Mt. Washington summit (hiker, handheld)"},
    "ammo_relay":  {"lat": 44.26616, "lon": -71.32348, "hg_m": 3.0, "label": "Ammo Trail Relay (treeline, 3 m mast)"},
    "jewell_relay": {"lat": 44.28376, "lon": -71.33583, "hg_m": 3.0, "label": "Jewell Trail Relay (treeline, 3 m mast)"},
    "gateway":     {"lat": 44.26700, "lon": -71.36083, "hg_m": 3.0, "label": "Trailhead Gateway (3 m mast)"},
}

LINKS = [
    ("ammo_relay", "summit"),
    ("jewell_relay", "summit"),
    ("ammo_relay", "gateway"),
    ("jewell_relay", "gateway"),
    ("ammo_relay", "jewell_relay"),
]


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class Dem:
    def __init__(self, npz_path: Path):
        data = np.load(npz_path)
        self.lat = data["lat_axis"]
        self.lon = data["lon_axis"]
        self.z = data["dem"]

    def sample(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """Bilinear interpolation of elevation at given coordinates."""
        fi = np.interp(lats, self.lat, np.arange(len(self.lat)))
        fj = np.interp(lons, self.lon, np.arange(len(self.lon)))
        i0 = np.clip(fi.astype(int), 0, len(self.lat) - 2)
        j0 = np.clip(fj.astype(int), 0, len(self.lon) - 2)
        di, dj = fi - i0, fj - j0
        return (
            self.z[i0, j0] * (1 - di) * (1 - dj)
            + self.z[i0 + 1, j0] * di * (1 - dj)
            + self.z[i0, j0 + 1] * (1 - di) * dj
            + self.z[i0 + 1, j0 + 1] * di * dj
        )

    def profile(self, lat1, lon1, lat2, lon2, step_m: float = 15.0):
        d = haversine_m(lat1, lon1, lat2, lon2)
        n = max(int(d / step_m) + 1, 50)
        t = np.linspace(0.0, 1.0, n)
        lats = lat1 + (lat2 - lat1) * t
        lons = lon1 + (lon2 - lon1) * t
        elev = self.sample(lats, lons)
        return d, elev


def itm_p2p_loss(d_km: float, profile_m: np.ndarray, hg: tuple[float, float],
                 qr_levels=(50, 90, 99), freq_mhz: float = FREQ_MHZ) -> dict:
    """Longley-Rice point-to-point basic transmission loss at reliability levels.

    Driver follows the itmlogic reference p2p runner (qkpfl): continental
    temperate climate (klim=5), Ns=301 N-units, average ground (eps=15,
    sigma=0.005 S/m), vertical polarization, 50% confidence.
    """
    prop = {
        "fmhz": freq_mhz,
        "d": d_km,
        "hg": list(hg),
        "ipol": 1,
        "eps": 15,
        "sgm": 0.005,
        "klim": 5,
        "ens0": 301,
        "lvar": 5,
        "gma": 157e-9,
        "kwx": 0,
        "klimx": 0,
        "mdvarx": 11,
    }
    pfl = [len(profile_m) - 1, 0.0] + [float(v) for v in profile_m]
    pfl[1] = d_km * 1000.0 / pfl[0]
    prop["pfl"] = pfl
    prop["wn"] = prop["fmhz"] / 47.7
    prop["ens"] = prop["ens0"]
    prop["gme"] = prop["gma"] * (1 - 0.04665 * math.exp(prop["ens"] / 179.3))
    zq = complex(prop["eps"], 376.62 * prop["sgm"] / prop["wn"])
    prop["zgnd"] = np.sqrt(zq - 1)
    if prop["ipol"] != 0:
        prop["zgnd"] = prop["zgnd"] / zq

    zr = qerfi([x / 100 for x in qr_levels])
    zc = qerfi([0.5])  # 50% confidence

    prop = qlrpfl(prop)
    db = 8.685890
    fs_db = db * np.log(2 * prop["wn"] * prop["dist"])

    # Path classification per the reference runner
    q = prop["dist"] - prop["dlsa"]
    q = max(q - 0.5 * pfl[1], 0) - max(-q - 0.5 * pfl[1], 0)
    if q < 0:
        path_type = "line_of_sight"
    elif q == 0:
        path_type = "single_horizon"
    else:
        path_type = "double_horizon"

    losses = {}
    for jr, level in enumerate(qr_levels):
        avar1, prop = avar(zr[jr], 0, zc[0], prop)
        losses[f"loss_db_q{level}"] = float(fs_db + avar1)
    return {"fspl_itm_db": float(fs_db), "path_type": path_type, **losses}


def fresnel_analysis(d_m: float, profile_m: np.ndarray, hg: tuple[float, float],
                     freq_mhz: float = FREQ_MHZ) -> dict:
    """Geometric LOS + worst first-Fresnel clearance with 4/3 effective Earth."""
    n = len(profile_m)
    x = np.linspace(0.0, d_m, n)
    h_tx = profile_m[0] + hg[0]
    h_rx = profile_m[-1] + hg[1]
    ray = h_tx + (h_rx - h_tx) * (x / d_m)
    bulge = x * (d_m - x) / (2.0 * EFFECTIVE_EARTH_R_M)
    terrain_eff = profile_m + bulge
    lam = 299.792458 / freq_mhz  # wavelength in m
    interior = slice(1, n - 1)
    r1 = np.sqrt(lam * x[interior] * (d_m - x[interior]) / d_m)
    clearance = ray[interior] - terrain_eff[interior]
    frac = clearance / r1
    worst = int(np.argmin(frac))
    return {
        "geometric_los": bool(np.all(clearance > 0)),
        "worst_fresnel_fraction": float(frac[worst]),
        "worst_obstruction_dist_m": float(x[interior][worst]),
        "fraction_path_below_treeline": float(np.mean(profile_m < TREELINE_M)),
    }


def load_garmin_gpx(path: Path) -> pd.DataFrame:
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    rows = []
    for p in root.findall(f".//{prefix}trkpt"):
        time_el = p.find(f"{prefix}time")
        if time_el is None:
            continue
        rows.append({
            "timestamp_utc": pd.Timestamp(time_el.text).tz_convert("UTC"),
            "lat": float(p.get("lat")),
            "lon": float(p.get("lon")),
        })
    return pd.DataFrame(rows).sort_values("timestamp_utc").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="ITM terrain-profile analysis of proposed relay links")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_mtwashington.npz")
    ap.add_argument("--head-gpx", default=None, help="Trial 1 Garmin GPX for gap-segment analysis")
    ap.add_argument("--gap-start-utc", default="2026-05-23T13:36:00Z")
    ap.add_argument("--gap-end-utc", default="2026-05-23T16:24:00Z")
    ap.add_argument("--gap-sample-s", type=float, default=120.0)
    ap.add_argument("--hiker-hg-m", type=float, default=1.5)
    ap.add_argument("--out-dir", default="artifacts/itm")
    args = ap.parse_args()

    dem_path = Path(args.dem_npz)
    if not dem_path.exists():
        raise SystemExit(f"DEM cache missing: {dem_path}; run scripts/dem_3dep.py first")
    dem = Dem(dem_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Proposed link table ───────────────────────────────────────────────────
    link_rows = []
    for a_key, b_key in LINKS:
        a, b = SITES[a_key], SITES[b_key]
        d_m, prof = dem.profile(a["lat"], a["lon"], b["lat"], b["lon"])
        hg = (a["hg_m"], b["hg_m"])
        itm = itm_p2p_loss(d_m / 1000.0, prof, hg)
        fres = fresnel_analysis(d_m, prof, hg)
        row = {
            "link": f"{a_key}->{b_key}",
            "distance_km": round(d_m / 1000.0, 3),
            "endpoint_a_elev_m": round(float(prof[0]), 1),
            "endpoint_b_elev_m": round(float(prof[-1]), 1),
            **{k: round(v, 1) for k, v in itm.items() if isinstance(v, float)},
            "path_type": itm["path_type"],
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in fres.items()},
        }
        for level in (50, 90, 99):
            pr = EIRP_DBM - itm[f"loss_db_q{level}"]
            row[f"pred_rssi_dbm_q{level}"] = round(pr, 1)
        row["meets_planning_threshold_q90"] = bool(row["pred_rssi_dbm_q90"] >= PLANNING_DBM)
        row["meets_sensitivity_q99"] = bool(row["pred_rssi_dbm_q99"] >= RX_SENS_DBM)
        link_rows.append(row)
        print(f"{row['link']:28s} {row['distance_km']:6.2f} km  {row['path_type']:15s} "
              f"q50 {row['pred_rssi_dbm_q50']:7.1f}  q90 {row['pred_rssi_dbm_q90']:7.1f}  "
              f"q99 {row['pred_rssi_dbm_q99']:7.1f} dBm  "
              f"fresnel {row['worst_fresnel_fraction']:6.2f}")
    links_df = pd.DataFrame(link_rows)
    links_df.to_csv(out_dir / "relay_links_itm.csv", index=False)

    # ── Collector-gap segment coverage ────────────────────────────────────────
    gap_summary = None
    if args.head_gpx:
        gpx = load_garmin_gpx(Path(args.head_gpx))
        t0 = pd.Timestamp(args.gap_start_utc)
        t1 = pd.Timestamp(args.gap_end_utc)
        seg = gpx[(gpx["timestamp_utc"] >= t0) & (gpx["timestamp_utc"] <= t1)].copy()
        if seg.empty:
            print("WARNING: no GPX points in the gap window; check timestamps")
        else:
            seg["bucket"] = (
                (seg["timestamp_utc"] - t0).dt.total_seconds() // args.gap_sample_s
            ).astype(int)
            seg = seg.groupby("bucket").first().reset_index()
            gap_rows = []
            for _, r in seg.iterrows():
                best = None
                for relay_key in ("ammo_relay", "jewell_relay"):
                    relay = SITES[relay_key]
                    d_m, prof = dem.profile(relay["lat"], relay["lon"], r["lat"], r["lon"])
                    if d_m < 30.0:
                        entry = {"relay": relay_key, "distance_km": d_m / 1000.0,
                                 "pred_rssi_dbm_q90": EIRP_DBM,  # co-located
                                 "path_type": "co_located", "geometric_los": True,
                                 "worst_fresnel_fraction": np.inf}
                    else:
                        itm = itm_p2p_loss(d_m / 1000.0, prof, (relay["hg_m"], args.hiker_hg_m))
                        fres = fresnel_analysis(d_m, prof, (relay["hg_m"], args.hiker_hg_m))
                        entry = {"relay": relay_key, "distance_km": d_m / 1000.0,
                                 "pred_rssi_dbm_q90": EIRP_DBM - itm["loss_db_q90"],
                                 "path_type": itm["path_type"],
                                 "geometric_los": fres["geometric_los"],
                                 "worst_fresnel_fraction": fres["worst_fresnel_fraction"]}
                    if best is None or entry["pred_rssi_dbm_q90"] > best["pred_rssi_dbm_q90"]:
                        best = entry
                gap_rows.append({
                    "timestamp_utc": r["timestamp_utc"].isoformat(),
                    "lat": r["lat"], "lon": r["lon"],
                    "best_relay": best["relay"],
                    "distance_km": round(best["distance_km"], 3),
                    "path_type": best["path_type"],
                    "geometric_los": best["geometric_los"],
                    "worst_fresnel_fraction": round(float(best["worst_fresnel_fraction"]), 3),
                    "pred_rssi_dbm_q90": round(best["pred_rssi_dbm_q90"], 1),
                    "meets_planning_threshold": bool(best["pred_rssi_dbm_q90"] >= PLANNING_DBM),
                    "meets_sensitivity": bool(best["pred_rssi_dbm_q90"] >= RX_SENS_DBM),
                })
            gap_df = pd.DataFrame(gap_rows)
            gap_df.to_csv(out_dir / "gap_segment_itm_coverage.csv", index=False)
            n = len(gap_df)
            gap_summary = {
                "n_sample_points": n,
                "sample_interval_s": args.gap_sample_s,
                "pct_meets_planning_threshold": round(100.0 * gap_df["meets_planning_threshold"].mean(), 1),
                "pct_meets_sensitivity": round(100.0 * gap_df["meets_sensitivity"].mean(), 1),
                "pct_geometric_los": round(100.0 * gap_df["geometric_los"].mean(), 1),
                "worst_point": gap_df.loc[gap_df["pred_rssi_dbm_q90"].idxmin()].to_dict(),
            }
            print(json.dumps(gap_summary, indent=2, default=str))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "Longley-Rice ITM v7.0 (itmlogic 1.2, Oughton et al. 2020, doi:10.21105/joss.02266)",
        "model_params": {
            "freq_mhz": FREQ_MHZ, "polarization": "vertical", "climate": "continental_temperate(5)",
            "surface_refractivity_n": 301, "eps": 15, "sgm_s_per_m": 0.005,
            "confidence_pct": 50, "reliability_pct": [50, 90, 99],
        },
        "radio": {"eirp_dbm": EIRP_DBM, "rx_sensitivity_dbm": RX_SENS_DBM,
                  "planning_threshold_dbm": PLANNING_DBM},
        "dem": str(dem_path),
        "limitations": [
            "ITM models terrain diffraction only — vegetation/canopy excess loss is NOT included; "
            "budget separately for paths below treeline (see fraction_path_below_treeline)",
            "antenna heights assumed: relays/gateway 3 m mast, hiker handheld 1.5 m",
            "profiles sampled at ~15 m from ~7 m 3DEP export; sub-pixel knife edges may be smoothed",
        ],
        "links": link_rows,
        "gap_segment": gap_summary,
    }
    (out_dir / "itm_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"wrote {out_dir}/relay_links_itm.csv, itm_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

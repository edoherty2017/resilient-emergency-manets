#!/usr/bin/env python3
"""Build the Trial 2 field-day prospective prediction pack (weekend rev).

Parameterized successor to trial2_predictions.py for beacon sites that are not
simulation-topology relays: the beacon is a node placed by hand on the walked
route itself (no mast — ~1.2 m boulder/trekking-pole mount), at a point chosen
by a pre-declared elevation rule, and retrieved on the descent of an
out-and-back route.

For each field day this script:
  1. densifies the route's waypoint chain over a real USGS 3DEP DEM tile
     (reusing build_hiker_routes.interpolate_track — identical geometry logic
     to every other route in the project);
  2. selects the beacon point by rule: the first ascending sample at or above
     the declared target elevation (recorded in the manifest — not hand-picked);
  3. computes Longley–Rice ITM q50 loss from the beacon (1.2 m) to every route
     sample (receiver 1.5 m) over the DEM profile;
  4. emits per distance-band × treeline-stratum × radio-config rows in the
     same schema as artifacts/trial2/predictions.csv, plus a manifest binding
     the rule, coordinates, heights, DEM hashes, and git state.

Same caveats as the original pack: the exceedance probability is
P(received power > assumed threshold) under an 8 dB Gaussian shadowing
placeholder — not a calibrated packet-success probability. Freeze the output
(commit + freeze_trial2_prereg.py) BEFORE field collection.

Run: .venv/bin/python scripts/trial2_predictions_field.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from itm_relay_links import Dem, itm_p2p_loss, haversine_m  # noqa: E402
from build_hiker_routes import ROUTES, interpolate_track  # noqa: E402
from radio_link_budget import RX_POWER_REFERENCE_DBM  # noqa: E402

CONFIGS = {
    "LongFast_candidate": {"sens": -131.0, "snr_demod": -17.5, "note": "SF11/BW250"},
    "500kHz_candidate": {"sens": -117.0, "snr_demod": -7.5, "note": "SF7/BW500-class"},
}
SIGMA_DB = 8.0
TREELINE_M = 1100.0
BANDS_M = [(0, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]
BEACON_HG_M = 1.2   # no-mast mount: boulder top / strapped trekking pole
HIKER_HG_M = 1.5    # chest-strap receiver
MIN_LINK_M = 30.0   # below this, treat as free 30 dB like build_hiker_routes

FIELD_DAYS = [
    {
        "day": "2026-07-19",
        "route": "moosilauke_gorge_brook",
        "dem": "artifacts/dem/cache/usgs_3dep_moosilauke.npz",
        "beacon_rule_target_elev_m": 1300.0,
        "beacon_name": "moosilauke_treeline_beacon",
        "trial_id": "trial2-moosilauke-20260719",
    },
    {
        "day": "deferred-future-field-day",
        "route": "kearsarge_winslow",
        "dem": "artifacts/dem/cache/usgs_3dep_kearsarge.npz",
        "beacon_rule_target_elev_m": 750.0,
        "beacon_name": "kearsarge_midslope_beacon",
        "trial_id": "trial2-kearsarge-20260719",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def p_threshold_exceedance(margin_db: float) -> float:
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(margin_db / (SIGMA_DB * sqrt(2.0))))


def main() -> int:
    rows = []
    manifest_days = []
    for fd in FIELD_DAYS:
        dem = Dem(ROOT / fd["dem"])
        waypoints = ROUTES[fd["route"]]["waypoints"]
        lats, lons, elevs, t_s = interpolate_track(dem, waypoints)

        # beacon rule: first ascending sample at/above the target elevation
        idx = next(i for i, e in enumerate(elevs)
                   if e >= fd["beacon_rule_target_elev_m"])
        b_lat, b_lon, b_elev = float(lats[idx]), float(lons[idx]), float(elevs[idx])

        losses = np.full(len(lats), np.nan)
        for i in range(len(lats)):
            d_m = haversine_m(b_lat, b_lon, float(lats[i]), float(lons[i]))
            if d_m < MIN_LINK_M:
                losses[i] = 30.0
                continue
            dd, prof = dem.profile(b_lat, b_lon, float(lats[i]), float(lons[i]))
            itm = itm_p2p_loss(dd / 1000.0, prof, (BEACON_HG_M, HIKER_HG_M))
            losses[i] = itm["loss_db_q50"]

        dists = np.array([haversine_m(b_lat, b_lon, la, lo)
                          for la, lo in zip(lats, lons)])
        for (d0, d1) in BANDS_M:
            for above in (True, False):
                m = (dists >= d0) & (dists < d1) & \
                    ((elevs >= TREELINE_M) == above)
                if m.sum() < 2:
                    continue
                sample_rssi = RX_POWER_REFERENCE_DBM - losses[m]
                rssi = float(np.median(sample_rssi))
                for cname, c in CONFIGS.items():
                    model_p = float(np.mean([
                        p_threshold_exceedance(float(v - c["sens"]))
                        for v in sample_rssi
                    ]))
                    rows.append({
                        "day": fd["day"], "route": fd["route"],
                        "beacon": fd["beacon_name"],
                        "band_m": f"{d0}-{d1}",
                        "stratum": "above_treeline" if above else "below_treeline",
                        "n_samples": int(m.sum()),
                        "config": cname,
                        "pred_median_rssi_dbm": round(rssi, 1),
                        "model_p_rssi_above_threshold": round(model_p, 3),
                    })
        manifest_days.append({
            **{k: fd[k] for k in ("day", "route", "dem", "beacon_name",
                                  "beacon_rule_target_elev_m", "trial_id")},
            "beacon_lat": round(b_lat, 6), "beacon_lon": round(b_lon, 6),
            "beacon_dem_elev_m": round(b_elev, 1),
            "beacon_sample_index": int(idx),
            "dem_sha256": sha256_file(ROOT / fd["dem"]),
            "route_samples": int(len(lats)),
            "route_walk_time_h_tobler": round(float(t_s[-1]) / 3600.0, 2),
        })
        print(f"{fd['day']} {fd['route']}: beacon at ({b_lat:.5f}, {b_lon:.5f}) "
              f"elev {b_elev:.0f} m (rule: first ascent sample >= "
              f"{fd['beacon_rule_target_elev_m']:.0f} m), "
              f"{len(lats)} samples, Tobler walk ~{t_s[-1]/3600.0:.1f} h")

    import pandas as pd
    df = pd.DataFrame(rows)
    out = ROOT / "artifacts/trial2"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "predictions_fieldday.csv", index=False)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.strip() != ""
    manifest = {
        "generator": "scripts/trial2_predictions_field.py",
        "git_commit": commit, "git_worktree_dirty": dirty,
        "beacon_hg_m": BEACON_HG_M, "hiker_hg_m": HIKER_HG_M,
        "sigma_db_placeholder": SIGMA_DB, "treeline_m": TREELINE_M,
        "rx_power_reference_dbm": RX_POWER_REFERENCE_DBM,
        "mount": "no-mast: boulder top or strapped trekking pole, measured in field",
        "days": manifest_days,
        "note": ("Prospective MODEL-ONLY predictions. Freeze via commit + "
                 "freeze_trial2_prereg.py before collection; record the "
                 "field-measured beacon height/coords as-built."),
    }
    (out / "predictions_fieldday_manifest.json").write_text(
        json.dumps(manifest, indent=2))
    print(f"wrote {out/'predictions_fieldday.csv'} ({len(df)} rows) + manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Prospective prediction pack for the DRIVE-UP beacon day at Pack Monadnock.

Protocol variant (2026-08-07): the beacon (Heltec Mesh Node T114, stock
Meshtastic) is placed at the summit BY CAR via the Miller SP auto road, the
hiker walks ``pack_monadnock_loop`` with the receiver (ascent + descent
passes), and the beacon is retrieved by car the same day.

This script deliberately does NOT touch scripts/trial2_predictions_field.py or
its outputs: that generator and both of its artifacts are hash-sealed by
``artifacts/trial2/prereg_manifest_fieldday.json`` and re-running it would
break the seal (it rewrites its outputs unconditionally, and its manifest
embeds the current git HEAD). Instead the sealed generator is imported as a
library so every constant and formula here is single-sourced from the sealed
bytes, and outputs go to NEW files:

    artifacts/trial2/predictions_packmonadnock.csv
    artifacts/trial2/predictions_packmonadnock_manifest.json

Method notes, stated up front for the freeze record:
  * Track = interpolate_track over the ROUTES['pack_monadnock_loop'] waypoints
    (straight-chord densification at 150 m), the same method the sealed pack
    used for its three routes — NOT the OSM-snapped polyline. The hiker walks
    the real trail; the chord track is the registered model geometry.
  * DEM = artifacts/dem/cache/rescue_miller_hq_pack_monadnock.npz (~4 m grid,
    bbox covers the whole loop). usgs_3dep_monadnock.npz is GRAND Monadnock
    and must never be used here: Dem.sample clamps out-of-bbox coordinates
    silently.
  * Beacon rule target 680.0 m selects the summit waypoint itself (track max
    is 689.4 m; a "700 m" target would exceed every sample and crash).
  * Heights stay BEACON_HG_M=1.2 / HIKER_HG_M=1.5 for comparability with the
    sealed pack; the car-placed mount (boulder/tripod at the summit) is
    recorded as-built on the day.
  * Sample counts double-count geometry (descent chord retraces ascent);
    opportunity accounting at scoring time uses scheduled transmissions, not
    these n_samples.
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

import trial2_predictions_field as base  # noqa: E402  (sealed generator, import-safe)
from itm_relay_links import Dem, itm_p2p_loss, haversine_m  # noqa: E402
from build_hiker_routes import ROUTES, interpolate_track  # noqa: E402
from radio_link_budget import RX_POWER_REFERENCE_DBM  # noqa: E402

# Byte-level guard: the sealed fieldday artifacts must be identical before and
# after this script runs, or something has gone badly wrong.
SEALED = {
    "artifacts/trial2/predictions_fieldday.csv":
        "a85e4d0803c95cc826b3ed9783c6f5a0ceca2aac517077544651267a28cf3bbb",
    "artifacts/trial2/predictions_fieldday_manifest.json":
        "3e6df03fe8e8030c46cae965e65c073e825188b848a2eb4da7983ab56700326e",
}

FIELD_DAY = {
    "day": "future-drive-up-field-day",
    "route": "pack_monadnock_loop",
    "dem": "artifacts/dem/cache/rescue_miller_hq_pack_monadnock.npz",
    "beacon_rule_target_elev_m": 680.0,
    "beacon_name": "packmonadnock_summit_beacon",
    "trial_id": "trial2-packmonadnock-driveup",
}


def assert_seal_intact() -> None:
    for rel, want in SEALED.items():
        got = base.sha256_file(ROOT / rel)
        if got != want:
            raise SystemExit(
                f"SEAL VIOLATION: {rel} sha256 {got} != sealed {want}; aborting"
            )


def main() -> int:
    assert_seal_intact()
    fd = FIELD_DAY
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
        if d_m < base.MIN_LINK_M:
            losses[i] = 30.0
            continue
        dd, prof = dem.profile(b_lat, b_lon, float(lats[i]), float(lons[i]))
        itm = itm_p2p_loss(dd / 1000.0, prof, (base.BEACON_HG_M, base.HIKER_HG_M))
        losses[i] = itm["loss_db_q50"]

    dists = np.array([haversine_m(b_lat, b_lon, la, lo)
                      for la, lo in zip(lats, lons)])
    rows = []
    for (d0, d1) in base.BANDS_M:
        for above in (True, False):
            m = (dists >= d0) & (dists < d1) & \
                ((elevs >= base.TREELINE_M) == above)
            if m.sum() < 2:
                continue
            sample_rssi = RX_POWER_REFERENCE_DBM - losses[m]
            rssi = float(np.median(sample_rssi))
            for cname, c in base.CONFIGS.items():
                model_p = float(np.mean([
                    base.p_threshold_exceedance(float(v - c["sens"]))
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

    print(f"{fd['day']} {fd['route']}: beacon at ({b_lat:.5f}, {b_lon:.5f}) "
          f"elev {b_elev:.0f} m (rule: first ascent sample >= "
          f"{fd['beacon_rule_target_elev_m']:.0f} m), "
          f"{len(lats)} samples, Tobler walk ~{t_s[-1]/3600.0:.1f} h")

    import pandas as pd
    df = pd.DataFrame(rows)
    out = ROOT / "artifacts/trial2"
    df.to_csv(out / "predictions_packmonadnock.csv", index=False)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.strip() != ""
    manifest = {
        "generator": "scripts/trial2_predictions_packmonadnock.py",
        "base_generator": {
            "path": "scripts/trial2_predictions_field.py",
            "sha256": base.sha256_file(ROOT / "scripts/trial2_predictions_field.py"),
        },
        "git_commit": commit, "git_worktree_dirty": dirty,
        "beacon_hg_m": base.BEACON_HG_M, "hiker_hg_m": base.HIKER_HG_M,
        "sigma_db_placeholder": base.SIGMA_DB, "treeline_m": base.TREELINE_M,
        "rx_power_reference_dbm": RX_POWER_REFERENCE_DBM,
        "mount": ("car-placed at summit: boulder top or tripod ~1.2 m, "
                  "measured as-built in field"),
        "protocol_variant": ("drive-up: beacon placed and retrieved by car via "
                             "the Miller SP auto road; hiker walks the loop "
                             "with the receiver; same-day retrieval"),
        "beacon_hardware": ("Heltec Mesh Node T114 (HELTEC_MESH_NODE_T114, "
                            "nRF52840 + SX1262), stock Meshtastic firmware, "
                            "LongFast — photograph FCC ID label at placement"),
        "days": [{
            **{k: fd[k] for k in ("day", "route", "dem", "beacon_name",
                                  "beacon_rule_target_elev_m", "trial_id")},
            "beacon_lat": round(b_lat, 6), "beacon_lon": round(b_lon, 6),
            "beacon_dem_elev_m": round(b_elev, 1),
            "beacon_sample_index": int(idx),
            "dem_sha256": base.sha256_file(ROOT / fd["dem"]),
            "route_samples": int(len(lats)),
            "route_walk_time_h_tobler": round(float(t_s[-1]) / 3600.0, 2),
        }],
        "note": ("Prospective MODEL-ONLY predictions. Freeze via commit + "
                 "freeze_trial2_prereg.py --pack packmonadnock before "
                 "collection; record the field-measured beacon height/coords "
                 "as-built."),
    }
    (out / "predictions_packmonadnock_manifest.json").write_text(
        json.dumps(manifest, indent=2))
    print(f"wrote {out/'predictions_packmonadnock.csv'} ({len(df)} rows) + manifest")
    assert_seal_intact()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

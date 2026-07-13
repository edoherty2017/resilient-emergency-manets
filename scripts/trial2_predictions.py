#!/usr/bin/env python3
"""Build a prospective Trial 2 prediction pack.

Generating these files does not itself create an immutable preregistration.
They must be versioned or independently timestamped, hashed, and frozen before
field collection, together with their inputs and scoring rules.

For each planned beacon site and the Ammo–Jewell walk route, produce per
terrain stratum (distance band × above/below treeline):
  - ITM-predicted median received power at the walking receiver
  - probability that received power exceeds an assumed sensitivity threshold
    under an independent Gaussian shadowing term (sigma 8 dB placeholder)
for BOTH candidate radio configs:
  - LongFast (SF11/BW250, sens −131 dBm)
  - ShortTurbo-class 500 kHz (SF7/BW500, sens ≈ −117 dBm)

The names are technical candidates, not declarations of regulatory compliance.
That determination depends on the exact certified device configuration and the
chosen authorization basis.

Output: docs/trial2-preregistration.md + artifacts/trial2/predictions.csv.
Proposed engineering screen to freeze before fieldwork: flag a stratum when
measured median RSSI differs by more than 12 dB or measured PDR differs by more
than 0.15 from the threshold-exceedance probability. The PDR comparison is a
mechanistic diagnostic, not a calibrated packet-success prediction or a
statistical equivalence test. The propagation KPI is held-out RSSI RMSE.

Run: .venv/bin/python scripts/trial2_predictions.py
"""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from radio_link_budget import RX_POWER_REFERENCE_DBM, metadata as radio_metadata

ROOT = Path(__file__).resolve().parents[1]

CONFIGS = {
    "LongFast_candidate": {"sens": -131.0, "snr_demod": -17.5, "note": "SF11/BW250"},
    "500kHz_candidate": {"sens": -117.0, "snr_demod": -7.5, "note": "SF7/BW500-class"},
}
BEACONS = ["ammo_relay", "jewell_relay"]
ROUTE = "ammo_jewell_loop"
SIGMA_DB = 8.0
RX_POWER_REF_DBM = RX_POWER_REFERENCE_DBM
TREELINE_M = 1100.0
BANDS_M = [(0, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]


def p_threshold_exceedance(margin_db: float) -> float:
    return 0.5 * (1.0 + math.erf(margin_db / (SIGMA_DB * math.sqrt(2.0))))


def main() -> int:
    routes = json.loads((ROOT / "artifacts/sim/routes.json").read_text())["routes"]
    topo = json.loads((ROOT / "artifacts/sim/topology.json").read_text())
    r = routes[ROUTE]
    sites = topo["sites"]

    # elevation along the route from the loss-table sampling times
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from itm_relay_links import Dem, haversine_m
    dem = Dem(ROOT / "artifacts/dem/cache/usgs_3dep_presidentials_wide.npz")
    lats = np.interp(r["loss_t_s"], r["t_s"], r["lat"])
    lons = np.interp(r["loss_t_s"], r["t_s"], r["lon"])
    elevs = dem.sample(lats, lons)

    rows = []
    for beacon in BEACONS:
        b = sites[beacon]
        losses = np.array(r["loss_db_q50"][beacon])
        dists = np.array([haversine_m(b["lat"], b["lon"], la, lo)
                          for la, lo in zip(lats, lons)])
        for (d0, d1) in BANDS_M:
            for above in (True, False):
                m = (dists >= d0) & (dists < d1) & \
                    ((elevs >= TREELINE_M) == above)
                if m.sum() < 2:
                    continue
                sample_rssi = RX_POWER_REF_DBM - losses[m]
                rssi = float(np.median(sample_rssi))
                for cname, c in CONFIGS.items():
                    model_p = float(np.mean([
                        p_threshold_exceedance(float(value - c["sens"]))
                        for value in sample_rssi
                    ]))
                    rows.append({
                        "beacon": beacon, "band_m": f"{d0}-{d1}",
                        "stratum": "above_treeline" if above else "below_treeline",
                        "n_samples": int(m.sum()),
                        "config": cname,
                        "pred_median_rssi_dbm": round(rssi, 1),
                        "model_p_rssi_above_threshold": round(model_p, 3),
                    })

    import pandas as pd
    df = pd.DataFrame(rows)
    out = ROOT / "artifacts/trial2"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "predictions.csv", index=False)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    dirty = bool(subprocess.run(
        ["git", "status", "--porcelain=v1"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip())
    radio = radio_metadata()
    md = ["# Trial 2 Prospective Prediction Record — NOT YET FROZEN",
          "",
          f"Generated {datetime.now(timezone.utc).isoformat()} from Git commit `{commit}`",
          f"(worktree dirty: `{str(dirty).lower()}`). Model: Longley-Rice ITM q50 over USGS 3DEP",
          f"+ lognormal shadowing σ={SIGMA_DB} dB (prospective placeholder;",
          "any fitted σ is a post-trial estimate, not part of the frozen prediction).",
          f"TX EIRP {radio['tx_eirp_dbm']:.2f} dBm; RX antenna gain",
          f"{radio['rx_antenna_gain_dbi']:.2f} dBi; receiver-power reference",
          f"{radio['rx_power_reference_dbm']:.2f} dBm. Heights: beacon 3 m mast,",
          "receiver 1.5 m handheld. Feed losses are presently assumed 0 dB and must",
          "be measured or reported as an assumption.",
          "",
          "**Provenance warning:** the commit above is only the worktree's base",
          "commit. Generating this document does not commit or timestamp it, the",
          "generator, its inputs, or the ignored `artifacts/trial2/predictions.csv`.",
          "Before fieldwork, commit/version the complete pack, record SHA-256 hashes",
          "for every input and output, verify a clean worktree, and preserve later",
          "amendments rather than overwriting the frozen record.",
          "",
          "**Proposed engineering screen to freeze before collection:** flag a",
          "stratum when measured median RSSI differs by more than 12 dB or measured",
          "PDR differs by more than 0.15 from the model's threshold-exceedance",
          "probability. This is a diagnostic tolerance, not a statistical",
          "equivalence test. Report exact scheduled-opportunity denominators.",
          "Packet-level Wilson intervals may be shown only as descriptive intervals",
          "under an independence assumption; primary uncertainty must respect",
          "within-pass dependence using whole-pass summaries or a pass/block-aware",
          "interval. The propagation model's primary KPI is",
          "out-of-sample RMSE across eligible field strata. Any recalibrated model",
          "must be evaluated on entire held-out passes or days.",
          "",
          "The probability in the table is not an empirically calibrated",
          "packet-success probability. It is P(received power > assumed receiver",
          f"threshold), averaged over the stratum's modeled route samples, under an",
          f"independent Gaussian {SIGMA_DB:.0f} dB shadowing term. It omits",
          "interference, collisions, protocol behavior, hardware",
          "variation, body/antenna effects, and temporal correlation. Measured direct",
          "packet delivery ratio is the field outcome.",
          "",
          "**Feasible protocol (Amendment 1, 2026-07-13, before fieldwork):** one",
          "surveyed static beacon site per field day, fixed 30 s cadence, sequence",
          "numbers, and `hops_away == 0` filtering. Walk the fixed route at normal",
          "pace; never stop to manufacture a quota. Target ≥40 scheduled packet",
          "opportunities per primary stratum across independent passes. Strata with",
          "fewer than 40 are retained and reported as underpowered/descriptive.",
          "Repeat a full segment in the opposite direction only when time and safety",
          "permit; observations within one pass are not independent replicates.",
          "The original 600–1,000 packets/stratum requirement was infeasible: at a",
          "30 s cadence it requires 5–8.3 hours in every stratum.",
          "",
          "The two radio rows below are candidate configurations, not claims that",
          "either configuration is legally authorized as deployed.",
          ""]
    for beacon in BEACONS:
        md.append(f"\n## Beacon: {beacon} ({sites[beacon]['label']})\n")
        md.append("| band (m) | stratum | model route samples | config | pred RSSI (dBm) | model P(RSSI > threshold) |")
        md.append("|---|---|---|---|---|---|")
        for _, row in df[df.beacon == beacon].iterrows():
            md.append(f"| {row.band_m} | {row.stratum} | {row.n_samples} "
                      f"| {row.config} | {row.pred_median_rssi_dbm} "
                      f"| {row.model_p_rssi_above_threshold} |")
    (ROOT / "docs/trial2-preregistration.md").write_text("\n".join(md) + "\n")
    print(df.to_string(index=False))
    print("\nwrote docs/trial2-preregistration.md, artifacts/trial2/predictions.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Trial 2 pre-registration pack: falsifiable predictions committed BEFORE
the field days.

For each planned beacon site and the Ammo–Jewell walk route, produce per
terrain stratum (distance band × above/below treeline):
  - ITM-predicted median RSSI and ESP at the walking receiver
  - predicted packet-success probability through the calibrated shadowing
    model (sigma 8 dB placeholder — itself a pre-registered value)
for BOTH candidate radio configs:
  - LongFast (SF11/BW250, sens −131 dBm) — the Part 97 path
  - ShortTurbo-class 500 kHz (SF7/BW500, sens ≈ −117 dBm) — the Part 15 path

Output: docs/trial2-preregistration.md + artifacts/trial2/predictions.csv.
Scoring rule (pre-registered): field stratum passes if measured median RSSI
is within ±12 dB of prediction AND measured PDR within ±0.15 of predicted
packet-success; the AIRMap-accuracy KPI is the held-out RMSE across strata.

Run: .venv/bin/python scripts/trial2_predictions.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

CONFIGS = {
    "LongFast_Part97": {"sens": -131.0, "snr_demod": -17.5, "note": "SF11/BW250"},
    "500kHz_Part15": {"sens": -117.0, "snr_demod": -7.5, "note": "SF7/BW500-class"},
}
BEACONS = ["ammo_relay", "jewell_relay"]
ROUTE = "ammo_jewell_loop"
SIGMA_DB = 8.0
EIRP = 26.3
TREELINE_M = 1100.0
BANDS_M = [(0, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]


def p_success(margin_db: float) -> float:
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
                med_loss = float(np.median(losses[m]))
                rssi = EIRP - med_loss
                for cname, c in CONFIGS.items():
                    margin = rssi - c["sens"]
                    rows.append({
                        "beacon": beacon, "band_m": f"{d0}-{d1}",
                        "stratum": "above_treeline" if above else "below_treeline",
                        "n_samples": int(m.sum()),
                        "config": cname,
                        "pred_median_rssi_dbm": round(rssi, 1),
                        "pred_median_esp_dbm": round(rssi, 1),
                        "pred_p_packet_success": round(p_success(margin), 3),
                    })

    import pandas as pd
    df = pd.DataFrame(rows)
    out = ROOT / "artifacts/trial2"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "predictions.csv", index=False)

    md = ["# Trial 2 Pre-Registration — Predictions Committed Before Fieldwork",
          "",
          f"Generated {datetime.now(timezone.utc).isoformat()} — commit hash is",
          "the timestamp of record. Model: Longley-Rice ITM q50 over USGS 3DEP",
          f"+ lognormal shadowing σ={SIGMA_DB} dB (pre-registered placeholder;",
          "Trial 2 fits the real σ). EIRP 26.3 dBm; heights: beacon 3 m mast,",
          "receiver 1.5 m handheld.",
          "",
          "**Scoring rule (fixed now):** a stratum PASSES if measured median",
          "RSSI is within ±12 dB of prediction and measured PDR within ±0.15",
          "of predicted packet success. KPI = held-out RMSE across strata.",
          "",
          "**Protocol:** surveyed static beacon, fixed 30 s cadence, sequence",
          "numbers, hops_away==0 filtering, 600–1,000 packets/stratum, ≥2",
          "repeat runs. Radio config per decision A2 (both tabled below).",
          ""]
    for beacon in BEACONS:
        md.append(f"\n## Beacon: {beacon} ({sites[beacon]['label']})\n")
        md.append("| band (m) | stratum | n | config | pred RSSI (dBm) | pred P(success) |")
        md.append("|---|---|---|---|---|---|")
        for _, row in df[df.beacon == beacon].iterrows():
            md.append(f"| {row.band_m} | {row.stratum} | {row.n_samples} "
                      f"| {row.config} | {row.pred_median_rssi_dbm} "
                      f"| {row.pred_p_packet_success} |")
    (ROOT / "docs/trial2-preregistration.md").write_text("\n".join(md) + "\n")
    print(df.to_string(index=False))
    print("\nwrote docs/trial2-preregistration.md, artifacts/trial2/predictions.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

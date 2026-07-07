#!/usr/bin/env python3
"""Pre-registered ITM link predictions for the Brenta Dolomites trek (EU868).

Computes Longley-Rice point-to-point predictions for every pair of planned
node sites on the 4-day Madonna di Campiglio -> Molveno hut-to-hut route,
over the Copernicus GLO-30 surface model, at the Meshtastic EU_868 frequency
(869.525 MHz).

These predictions are FROZEN BEFORE TRAVEL (pre-registration): commit the
output artifacts before the trek; the field PDR/ESP measurements then test
the model rather than tune it.

Site coordinates from OSM/Nominatim (2026-06-12); verify each with the Garmin
at placement time and record the surveyed position in the field log.

Run inside .venv (requires artifacts/dem/cache/copernicus_glo30_brenta.npz):
    python scripts/brenta_itm_plan.py
"""
from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from itm_relay_links import Dem, itm_p2p_loss, fresnel_analysis, EIRP_DBM, RX_SENS_DBM, PLANNING_DBM

FREQ_EU_MHZ = 869.525  # Meshtastic EU_868 primary channel

# hg_m: hut nodes assumed window/railing mounted ~2.5 m; pass beacon on a cairn ~2 m.
SITES = {
    "campiglio":  {"lat": 46.22699, "lon": 10.82702, "hg_m": 2.5, "label": "Madonna di Campiglio (start town)"},
    "groste":     {"lat": 46.21551, "lon": 10.90265, "hg_m": 2.0, "label": "Passo del Groste (Day 1 beacon drop)"},
    "tuckett":    {"lat": 46.19202, "lon": 10.88215, "hg_m": 2.5, "label": "Rifugio Tuckett (night 1)"},
    "alimonta":   {"lat": 46.17393, "lon": 10.89201, "hg_m": 2.5, "label": "Rifugio Alimonta (night 2)"},
    "agostini":   {"lat": 46.14243, "lon": 10.86948, "hg_m": 2.5, "label": "Rifugio Agostini (night 3)"},
    "molveno":    {"lat": 46.14211, "lon": 10.96378, "hg_m": 2.5, "label": "Molveno (end town)"},
}

# The links that matter operationally, in trek order; full matrix also computed.
PRIMARY_LINKS = [
    ("campiglio", "groste"),
    ("groste", "tuckett"),
    ("tuckett", "alimonta"),
    ("alimonta", "agostini"),
    ("agostini", "molveno"),
    ("groste", "molveno"),   # long-shot: can a single high beacon bridge the massif?
]


def main() -> int:
    dem_path = Path("artifacts/dem/cache/copernicus_glo30_brenta.npz")
    if not dem_path.exists():
        raise SystemExit("run scripts/dem_copernicus.py first")
    dem = Dem(dem_path)
    out_dir = Path("artifacts/itm")
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for a_key, b_key in itertools.combinations(SITES, 2):
        a, b = SITES[a_key], SITES[b_key]
        d_m, prof = dem.profile(a["lat"], a["lon"], b["lat"], b["lon"], step_m=30.0)
        hg = (a["hg_m"], b["hg_m"])
        itm = itm_p2p_loss(d_m / 1000.0, prof, hg, freq_mhz=FREQ_EU_MHZ)
        fres = fresnel_analysis(d_m, prof, hg, freq_mhz=FREQ_EU_MHZ)
        row = {
            "link": f"{a_key}->{b_key}",
            "primary": (a_key, b_key) in PRIMARY_LINKS,
            "distance_km": round(d_m / 1000.0, 2),
            "elev_a_m": round(float(prof[0]), 0),
            "elev_b_m": round(float(prof[-1]), 0),
            "path_type": itm["path_type"],
            "geometric_los": fres["geometric_los"],
            "worst_fresnel_fraction": round(fres["worst_fresnel_fraction"], 2),
            "pred_rssi_dbm_q50": round(EIRP_DBM - itm["loss_db_q50"], 1),
            "pred_rssi_dbm_q90": round(EIRP_DBM - itm["loss_db_q90"], 1),
            "pred_rssi_dbm_q99": round(EIRP_DBM - itm["loss_db_q99"], 1),
            "meets_planning_q90": bool(EIRP_DBM - itm["loss_db_q90"] >= PLANNING_DBM),
            "meets_sensitivity_q90": bool(EIRP_DBM - itm["loss_db_q90"] >= RX_SENS_DBM),
        }
        rows.append(row)
        if row["primary"]:
            print(f"{row['link']:24s} {row['distance_km']:6.2f} km  "
                  f"q90 {row['pred_rssi_dbm_q90']:7.1f} dBm  "
                  f"LOS={row['geometric_los']} F1={row['worst_fresnel_fraction']:6.2f}  "
                  f"{'PLAN-OK' if row['meets_planning_q90'] else ('SENS-ONLY' if row['meets_sensitivity_q90'] else 'DEAD')}")

    df = pd.DataFrame(rows).sort_values(["primary", "link"], ascending=[False, True])
    df.to_csv(out_dir / "brenta_links_itm.csv", index=False)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PRE-REGISTERED PREDICTION — frozen before travel; do not edit after the trek begins",
        "model": "Longley-Rice ITM v7.0 (itmlogic 1.2)",
        "freq_mhz": FREQ_EU_MHZ,
        "region_note": "Meshtastic EU_868 (869.4-869.65 MHz, 10% duty cycle); US 915 MHz is NOT legal in Italy",
        "radio": {"eirp_dbm": EIRP_DBM, "rx_sensitivity_dbm": RX_SENS_DBM,
                  "planning_threshold_dbm": PLANNING_DBM},
        "dem": "copernicus_glo30_brenta.npz (DSM — includes canopy below treeline; conservative)",
        "sites": SITES,
        "links": rows,
    }
    (out_dir / "brenta_itm_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"wrote {out_dir}/brenta_links_itm.csv, brenta_itm_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

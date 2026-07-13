#!/usr/bin/env python3
"""Compare the five routing algorithms across their statewide year runs.

Reads artifacts/sim/algo_year/summary_<mode>.json (from mesh_sim) and emits:
  algo_comparison.csv    one row per mode: PDR, SOS, util, energy, fairness
  algo_comparison.png    fleet SOC p10/median band over the year per mode
                         + bar panels for Gini / SOC σ / deaths / energy
  algo_comparison.json   the table + design-expectations document reference
                         commit-timestamped design expectations

Run: .venv/bin/python scripts/build_algo_comparison.py
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODES = ["flood", "min_hop", "etx", "energy_aware", "lb_energy",
         "lb_energy_r", "duty_sync", "duty_adaptive", "rotate_lb"]
COLORS = {"flood": "#888888", "min_hop": "#1f77b4", "etx": "#9467bd",
          "energy_aware": "#2ca02c", "lb_energy": "#d62728",
          "lb_energy_r": "#ff9896", "duty_sync": "#17becf",
          "duty_adaptive": "#e377c2", "rotate_lb": "#bcbd22"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Routing algorithm year comparison")
    ap.add_argument("--dir", default="artifacts/sim/algo_year")
    args = ap.parse_args()
    d = ROOT / args.dir

    rows = []
    series = {}
    for m in MODES:
        p = d / f"summary_{m}.json"
        if not p.exists():
            print(f"  (missing {p.name} — skipped)")
            continue
        s = json.loads(p.read_text())
        fe = s["fleet_energy"]
        tx_wh = sum(v["energy_tx_wh"] for v in s["per_node"].values())
        rows.append({
            "mode": m, "days": s["days"],
            "pdr": s["pdr_overall"],
            "sos": f"{s['sos']['delivered']}/{s['sos']['sent']}",
            "sos_rate": round(s["sos"]["delivered"] / max(s["sos"]["sent"], 1), 4),
            "channel_util": s["channel_utilization"],
            "tx_total": sum(v["tx"] for v in s["per_node"].values()),
            "tx_energy_wh": round(tx_wh, 2),
            "relay_gini": fe["relay_energy_gini"],
            "final_soc_std": fe["final_soc_std"],
            "final_soc_min": fe["final_soc_min"],
            "solar_deaths": fe["deaths_total"],
        })
        series[m] = np.array(fe["soc_series_6h"]) if fe["soc_series_6h"] else None

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(d / "algo_comparison.csv", index=False)
    print(df.to_string(index=False))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(15, 9))
    ax = fig.add_subplot(2, 1, 1)
    for m, arr in series.items():
        if arr is None or not len(arr):
            continue
        t, p10, p50 = arr[:, 0], arr[:, 1], arr[:, 2]
        ax.plot(t, p50, color=COLORS[m], lw=1.6, label=f"{m} (median)")
        ax.fill_between(t, p10, p50, color=COLORS[m], alpha=0.12)
    ax.set_xlabel("simulation day (pinned reanalysis weather sequence)")
    ax.set_ylabel("fleet SOC (solar nodes)")
    ax.set_title("Fleet battery through the year — median line, p10 band below it")
    ax.legend(ncols=5, fontsize=9)
    ax.grid(alpha=0.3)

    panels = [("relay_gini", "relay-energy Gini (0 = even drain)"),
              ("final_soc_std", "final SOC σ"),
              ("solar_deaths", "solar-node deaths"),
              ("tx_energy_wh", "network TX energy (Wh)")]
    for i, (k, label) in enumerate(panels):
        axb = fig.add_subplot(2, 4, 5 + i)
        vals = [r[k] if r[k] is not None else 0 for r in rows]
        axb.bar([r["mode"] for r in rows], vals,
                color=[COLORS[r["mode"]] for r in rows])
        axb.set_title(label, fontsize=9)
        axb.tick_params(axis="x", rotation=45, labelsize=7)
        axb.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(d / "algo_comparison.png", dpi=140)

    out = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
           "claim_status": "EXPLORATORY_UNLESS_ALL_INPUT_RUN_MANIFESTS_PASS",
           "provenance_warning": "Historical pre-audit summaries are superseded; this formatter does not validate their manifests.",
           "table": rows,
           "expectations_doc": "docs/routing-algorithms.md"}
    (d / "algo_comparison.json").write_text(json.dumps(out, indent=2))
    print(f"wrote {d}/algo_comparison.csv, .png, .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

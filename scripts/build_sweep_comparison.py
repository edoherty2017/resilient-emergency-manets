#!/usr/bin/env python3
"""Multi-seed algorithm comparison from fastsim sweep results.

Reads artifacts/sim/sweep/fs_<mode>_s<seed>.json and emits mean ± std for the
decision metrics, a CI figure (fleet SOC bands + metric bars with error bars),
and a markdown table for docs. This is the committee-grade version of the
algorithm comparison: every number carries its seed-to-seed spread.

Run: .venv/bin/python scripts/build_sweep_comparison.py
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODES = ["flood", "min_hop", "etx", "energy_aware", "lb_energy",
         "lb_noretry", "duty_sync", "duty_adaptive", "rotate_lb"]
COLORS = {"flood": "#888888", "min_hop": "#1f77b4", "etx": "#9467bd",
          "energy_aware": "#2ca02c", "lb_energy": "#d62728",
          "lb_noretry": "#ff9896", "duty_sync": "#17becf",
          "duty_adaptive": "#e377c2", "rotate_lb": "#bcbd22"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="artifacts/sim/sweep")
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    d = ROOT / args.dir

    rows = []
    soc_bands = {}
    for mode in MODES:
        runs = []
        for seed in range(1, args.seeds + 1):
            p = d / f"fs_{mode}_s{seed}.json"
            if p.exists():
                runs.append(json.loads(p.read_text()))
        if not runs:
            print(f"  ({mode}: no runs)")
            continue

        def stat(getter):
            vals = np.array([getter(r) for r in runs], dtype=float)
            return float(vals.mean()), float(vals.std())

        pdr = stat(lambda r: r["pdr_overall"])
        sos = stat(lambda r: r["sos"]["delivered"] / max(r["sos"]["sent"], 1))
        util = stat(lambda r: r["channel_utilization"])
        deaths = stat(lambda r: r["fleet_energy"]["deaths_total"])
        gini = stat(lambda r: r["fleet_energy"]["relay_energy_gini"] or 0.0)
        avail = stat(lambda r: r["rental"]["availability"])
        tries = stat(lambda r: r["sos"].get("mean_tries") or 1.0)
        rows.append({
            "mode": mode, "n_seeds": len(runs),
            "pdr_mean": round(pdr[0], 4), "pdr_std": round(pdr[1], 4),
            "sos_rate_mean": round(sos[0], 4), "sos_rate_std": round(sos[1], 4),
            "sos_tries_mean": round(tries[0], 2),
            "util_mean": round(util[0], 4), "util_std": round(util[1], 4),
            "deaths_mean": round(deaths[0], 0), "deaths_std": round(deaths[1], 0),
            "gini_mean": round(gini[0], 3), "gini_std": round(gini[1], 3),
            "rental_avail_mean": round(avail[0], 4),
        })
        # SOC band: median-of-medians across seeds
        series = [np.array(r["fleet_energy"]["soc_series_6h"]) for r in runs
                  if r["fleet_energy"]["soc_series_6h"]]
        if series:
            L = min(len(s) for s in series)
            stack = np.stack([s[:L] for s in series])
            soc_bands[mode] = (stack[0, :, 0],
                               stack[:, :, 2].mean(axis=0),
                               stack[:, :, 1].mean(axis=0))

    import pandas as pd
    df = pd.DataFrame(rows)
    df.to_csv(d / "sweep_comparison.csv", index=False)
    print(df.to_string(index=False))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(16, 10))
    ax = fig.add_subplot(2, 1, 1)
    for m, (t, p50, p10) in soc_bands.items():
        ax.plot(t, p50, color=COLORS[m], lw=1.6, label=m)
        ax.fill_between(t, p10, p50, color=COLORS[m], alpha=0.10)
    ax.set_xlabel("simulation day (real 2025-26 weather)")
    ax.set_ylabel("fleet SOC (solar nodes)")
    ax.set_title("Fleet battery through the year — seed-averaged median "
                 "(band down to p10)")
    ax.legend(ncols=5, fontsize=9)
    ax.grid(alpha=0.3)

    panels = [("pdr", "PDR", 1), ("sos_rate", "SOS delivery rate", 1),
              ("deaths", "solar-node deaths / yr", 0),
              ("gini", "relay-energy Gini", 1),
              ("util", "channel utilization", 1)]
    for i, (k, label, _) in enumerate(panels):
        axb = fig.add_subplot(2, 5, 6 + i)
        ms = [r["mode"] for r in rows]
        vals = [r[f"{k}_mean"] for r in rows]
        errs = [r[f"{k}_std"] for r in rows]
        axb.bar(ms, vals, yerr=errs, capsize=3,
                color=[COLORS[m] for m in ms])
        axb.set_title(f"{label} (±1σ, n=5 seeds)", fontsize=9)
        axb.tick_params(axis="x", rotation=60, labelsize=7)
        axb.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(d / "sweep_comparison.png", dpi=140)

    (d / "sweep_comparison.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "engine": "fastsim (rust), validated vs python at 4-day scale; "
                  "year-scale cross-check pending (python fleet, seed 42)",
        "table": rows}, indent=2))
    print(f"wrote {d}/sweep_comparison.csv, .png, .json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

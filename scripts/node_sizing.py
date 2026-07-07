#!/usr/bin/env python3
"""Battery + solar-panel sizing per deployed node site.

Answers, per site: what panel wattage and battery Wh does this node need to
survive its worst service month, including cloudy stretches, given its actual
terrain horizon and (below treeline) the forest canopy?

Method (deterministic + Monte Carlo):
  load        continuous listen + GPS-off routing duty from config energy
              block (+15% TX overhead) → Wh/day
  harvest     daily_solar_wh at the site's horizon mask with its mounting
              model (pyramid + canopy_tau below treeline), across every day
              of the service season × 400 sampled kt draws per month
  battery     sized so the node rides out the p10 worst H-day harvest
              stretch in the worst month (H = autonomy target) with the
              battery ending above the 20% floor
  panel       sized so median-month harvest ≥ 1.3× daily load (recharge
              surplus after storms)

Grid sites are skipped. Output: artifacts/sim/sizing.csv, sizing.png,
sizing_summary.json.

Run: .venv/bin/python scripts/node_sizing.py --season may-oct
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import solar_model  # noqa: E402

TREELINE_M = 1100.0
AUTONOMY_DAYS = 4          # ride out a 4-day socked-in stretch
MIN_SOC_FLOOR = 0.20
PANEL_MARGIN = 1.3
PANEL_STEPS_W = [2, 4, 6, 10, 15, 20, 30, 50]
BATTERY_STEPS_WH = [18.5, 37.0, 74.0, 111.0, 148.0, 222.0]  # 1..12x 18650-class


def daily_load_wh(cfg) -> float:
    e = cfg["energy"]
    listen_w = e["rx_listen_ma"] / 1000.0 * e["battery_v"]
    return listen_w * 24.0 * 1.15          # +15% TX/overhead


def season_months(season: str) -> list[int]:
    return list(range(5, 11)) if season == "may-oct" else list(range(1, 13))


def main() -> int:
    import yaml
    ap = argparse.ArgumentParser(description="Per-site battery/panel sizing")
    ap.add_argument("--config", default="config/sim/wmnf_sim.yaml")
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--season", choices=["may-oct", "year-round"], default="may-oct")
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--out-dir", default="artifacts/sim")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text())
    topo = json.loads((ROOT / args.topology).read_text())
    solar_cfg = cfg["solar"]
    rng = np.random.default_rng(9)
    load = daily_load_wh(cfg)
    months = season_months(args.season)
    out_dir = ROOT / args.out_dir

    rows = []
    for name, s in topo["sites"].items():
        if s.get("power") == "grid":
            continue
        hz = np.array(s["horizon_deg"])
        below = s["elev_m"] < TREELINE_M
        site_solar = {"geometry": "pyramid",
                      "tilt_deg": solar_cfg["pyramid_tilt_deg"],
                      "canopy_tau": solar_cfg["canopy_tau_16ft"] if below else 1.0}

        # per-1W-panel harvest distribution per month (then scale by panel W)
        month_wh_per_w: dict[int, np.ndarray] = {}
        base = dict(solar_cfg)
        base["panel_w_nominal"] = 1.0
        for m in months:
            mid = datetime(2026, m, 15, tzinfo=timezone.utc)
            kts = np.array([solar_model.sample_daily_kt(m, rng, solar_cfg)
                            for _ in range(args.draws)])
            # harvest is ~linear in kt on the direct component; evaluate a kt
            # grid once and interpolate (12 evals/month instead of 400)
            kt_grid = np.linspace(0.05, 0.85, 12)
            wh_grid = [solar_model.daily_solar_wh(s["lat"], s["lon"], mid, k,
                                                  hz, base, step_s=1200,
                                                  site_solar=site_solar)
                       for k in kt_grid]
            month_wh_per_w[m] = np.interp(kts, kt_grid, wh_grid)

        worst_m = min(months, key=lambda m: float(np.median(month_wh_per_w[m])))
        median_worst = float(np.median(month_wh_per_w[worst_m]))

        # panel: median worst-month harvest must cover load with margin
        panel_w = next((p for p in PANEL_STEPS_W
                        if p * median_worst >= PANEL_MARGIN * load),
                       PANEL_STEPS_W[-1])
        panel_feasible = panel_w * median_worst >= PANEL_MARGIN * load

        # battery: p10 of the H-day cumulative deficit in the worst month
        draws = month_wh_per_w[worst_m]
        stretch = rng.choice(draws, size=(2000, AUTONOMY_DAYS))
        deficit = np.maximum(load - panel_w * stretch, 0.0).sum(axis=1)
        need_wh = float(np.quantile(deficit, 0.90)) / (1.0 - MIN_SOC_FLOOR)
        battery_wh = next((b for b in BATTERY_STEPS_WH if b >= need_wh),
                          BATTERY_STEPS_WH[-1])

        rows.append({
            "site": name, "category": s.get("category", "?"),
            "elev_m": s["elev_m"], "below_treeline": below,
            "canopy_tau": site_solar["canopy_tau"],
            "daily_load_wh": round(load, 2),
            "worst_month": worst_m,
            "harvest_wh_per_w_median": round(median_worst, 3),
            "panel_w": panel_w, "panel_feasible": panel_feasible,
            "battery_need_wh": round(need_wh, 1),
            "battery_wh": battery_wh,
            "battery_mah_3v7": int(battery_wh / 3.7 * 1000),
        })
        print(f"{name:22s} {'forest' if below else 'open ':6s} worst m{worst_m:02d} "
              f"{median_worst:5.2f} Wh/W  -> panel {panel_w:3d} W  "
              f"battery {battery_wh:6.1f} Wh ({int(battery_wh/3.7*1000):6d} mAh)"
              f"{'' if panel_feasible else '  !! PANEL CAP HIT'}")

    import pandas as pd
    df = pd.DataFrame(rows).sort_values(["below_treeline", "panel_w", "battery_wh"])
    df.to_csv(out_dir / "sizing.csv", index=False)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 7))
    colors = df["below_treeline"].map({True: "#2a7d2a", False: "#c98a00"})
    ax.scatter(df["panel_w"], df["battery_wh"], c=colors, s=70,
               edgecolor="k", linewidth=0.5)
    for _, r in df.iterrows():
        ax.annotate(r["site"], (r["panel_w"], r["battery_wh"]), fontsize=7,
                    xytext=(4, 3), textcoords="offset points")
    ax.set_xlabel("required panel (W, pyramid 4-face total)")
    ax.set_ylabel("required battery (Wh)")
    ax.set_title(f"Node sizing — {args.season}, {AUTONOMY_DAYS}-day autonomy, "
                 f"p90 cloudy stretch\ngreen = under forest canopy (τ="
                 f"{solar_cfg['canopy_tau_16ft']}, 16 ft hoist), orange = open/ridge")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "sizing.png", dpi=140)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "season": args.season, "autonomy_days": AUTONOMY_DAYS,
        "daily_load_wh": round(load, 2),
        "assumptions": ["pyramid 4-face mounting at "
                        f"{solar_cfg['pyramid_tilt_deg']}° tilt",
                        f"canopy tau {solar_cfg['canopy_tau_16ft']} below "
                        f"{TREELINE_M} m (16 ft branch hoist) [BENCH-CALIBRATE]",
                        "energy currents BENCH-CALIBRATE (decision G2)"],
        "fleet_bom": {
            "open_sites": {"n": int((~df.below_treeline).sum()),
                           "max_panel_w": int(df[~df.below_treeline].panel_w.max()),
                           "max_battery_wh": float(df[~df.below_treeline].battery_wh.max())},
            "forest_sites": {"n": int(df.below_treeline.sum()),
                             "max_panel_w": int(df[df.below_treeline].panel_w.max()),
                             "max_battery_wh": float(df[df.below_treeline].battery_wh.max())},
        },
        "sites": rows,
    }
    (out_dir / "sizing_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["fleet_bom"], indent=2))
    print(f"wrote {out_dir}/sizing.csv, sizing.png, sizing_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

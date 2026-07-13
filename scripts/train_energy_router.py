#!/usr/bin/env python3
"""ML layer v1: solar-gain prediction + route energy-cost modeling.

Part A — solar-gain predictor (the "expected solar charge gain that day per
  node by location" model). Training data: physics simulation (solar_model over
  the real DEM horizon masks) across sites × May–Oct days × sampled clearness.
  Features a deployed node can actually know: elevation, horizon statistics,
  day-of-year, and a NOISY kt forecast (±0.08 — a realistic cloud-forecast
  error), so reported skill is deployment-realistic, not physics-recovery.

Part B — flood vs energy-aware routing, same seed, 3 days: PDR, network TX
  energy, per-node minimum SOC. This is the quantitative basis for the
  "stick with Meshtastic or go custom" decision.

Part C — route energy-cost surrogate: enumerate loop-free routes (≤4 hops) from
  every origin to an MQTT gateway; label each with analytic delivery
  probability (per-link Gaussian shadowing outage) and expected energy
  (retries included); train a GB regressor on features observable on-device
  (hop count, per-hop RSSI margins, battery SOCs). v1 is a simulator
  surrogate — to be retrained on Trial 2 field data.

Run: .venv/bin/python scripts/train_energy_router.py
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import solar_model  # noqa: E402
from lora_airtime import airtime_ms  # noqa: E402
from radio_link_budget import config_rx_power_reference_dbm  # noqa: E402

KT_FORECAST_NOISE = 0.08
MAX_HOPS = 4


# ── Part A: solar dataset + model ────────────────────────────────────────────
def build_solar_dataset(topo, cfg, rng):
    from datetime import datetime as dt, timezone as tz
    rows = []
    sites = topo["sites"]
    for name, s in sites.items():
        hz = np.array(s["horizon_deg"])
        south = hz[len(hz) // 3: 2 * len(hz) // 3]  # az ~120–240°
        for doy in range(130, 300, 2):              # May 10 – Oct 27
            date = dt(2026, 1, 1, tzinfo=tz.utc) + np.timedelta64(doy - 1, "D").astype("timedelta64[s]").item()
            kt = solar_model.sample_daily_kt(date.month, rng, cfg["solar"])
            wh = solar_model.daily_solar_wh(s["lat"], s["lon"], date, kt, hz,
                                            cfg["solar"], step_s=600)
            rows.append({
                "site": name, "doy": doy,
                "elev_m": s["elev_m"],
                "horizon_mean": float(hz.mean()),
                "horizon_max": float(hz.max()),
                "horizon_south_mean": float(south.mean()),
                "doy_sin": math.sin(2 * math.pi * doy / 365.0),
                "doy_cos": math.cos(2 * math.pi * doy / 365.0),
                "kt_forecast": float(np.clip(kt + rng.normal(0, KT_FORECAST_NOISE), 0.05, 0.9)),
                "wh": wh,
            })
    return rows


def train_solar(rows, out_dir):
    import pandas as pd
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    df = pd.DataFrame(rows)
    feats = ["elev_m", "horizon_mean", "horizon_max", "horizon_south_mean",
             "doy_sin", "doy_cos", "kt_forecast"]
    test = df["doy"] % 10 < 2                     # hold out whole days
    Xtr, ytr = df.loc[~test, feats], df.loc[~test, "wh"]
    Xte, yte = df.loc[test, feats], df.loc[test, "wh"]
    m = GradientBoostingRegressor(n_estimators=400, max_depth=3, learning_rate=0.05,
                                  random_state=0)
    m.fit(Xtr, ytr)
    pred = m.predict(Xte)
    mae = mean_absolute_error(yte, pred)
    r2 = r2_score(yte, pred)
    naive = float(np.mean(np.abs(yte - ytr.mean())))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.scatter(yte, pred, s=12, alpha=0.5)
    lim = [0, max(yte.max(), pred.max()) * 1.05]
    ax.plot(lim, lim, "r--", lw=1)
    ax.set_xlabel("actual daily solar (Wh)"); ax.set_ylabel("predicted (Wh)")
    ax.set_title(f"Solar-gain predictor — held-out days\nMAE {mae:.2f} Wh, R² {r2:.3f}")
    fig.tight_layout(); fig.savefig(out_dir / "solar_pred_scatter.png", dpi=140)

    import joblib
    joblib.dump({"model": m, "features": feats}, out_dir / "solar_model.joblib")
    imp = dict(zip(feats, [round(float(v), 3) for v in m.feature_importances_]))
    return {"n_train": int((~test).sum()), "n_test": int(test.sum()),
            "mae_wh": round(float(mae), 3), "r2": round(float(r2), 4),
            "naive_mae_wh": round(naive, 3), "feature_importance": imp,
            "kt_forecast_noise": KT_FORECAST_NOISE}


# ── Part B: routing-mode comparison ──────────────────────────────────────────
def compare_modes(seed=11, days=3):
    from mesh_sim import run_sim
    out = {}
    for mode in ("flood", "energy_aware"):
        s = run_sim(mode=mode, days=days, seed=seed)
        tx_wh = sum(v["energy_tx_wh"] for v in s["per_node"].values())
        min_soc = min(v["final_soc"] for k, v in s["per_node"].items()
                      if v["power"] != "grid")
        out[mode] = {
            "pdr_overall": s["pdr_overall"],
            "sos_delivered": f"{s['sos']['delivered']}/{s['sos']['sent']}",
            "network_tx_energy_wh": round(tx_wh, 3),
            "total_tx": sum(v["tx"] for v in s["per_node"].values()),
            "channel_utilization": s["channel_utilization"],
            "min_final_soc": min_soc,
            "wh_per_delivered_pkt": round(
                tx_wh / max(1, sum(o["delivered"] for o in s["per_origin"].values())), 5),
        }
    return out


# ── Part C: route energy-cost surrogate ──────────────────────────────────────
def link_success_p(loss_db, radio, sigma_db):
    margin = config_rx_power_reference_dbm(radio) - loss_db - radio["rx_sensitivity_dbm"]
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(margin / (sigma_db * sqrt(2.0))))


def enumerate_routes(topo, radio, sigma_db):
    """All loop-free paths ≤ MAX_HOPS from each site to an MQTT gateway."""
    sites = topo["sites"]
    names = list(sites)
    loss = {}
    for k, v in topo["links"].items():
        a, b = k.split("|")
        loss[(a, b)] = loss[(b, a)] = v["loss_db_q50"]
    gateways = {n for n, s in sites.items() if s.get("mqtt_uplink")}
    # only links with ≥15% single-try success qualify as graph edges, and route
    # count is capped per origin — keeps enumeration tractable on dense meshes
    neigh = {n: [m for m in names if m != n and
                 link_success_p(loss.get((n, m), 300.0), radio, sigma_db) > 0.15]
             for n in names}
    MAX_ROUTES_PER_ORIGIN = 300
    routes = []
    for origin in names:
        if origin in gateways:
            continue
        found = 0
        stack = [(origin,)]
        while stack and found < MAX_ROUTES_PER_ORIGIN:
            path = stack.pop()
            if path[-1] in gateways:
                routes.append(path)
                found += 1
                continue
            if len(path) > MAX_HOPS:
                continue
            for nxt in neigh[path[-1]]:
                if nxt not in path:
                    stack.append(path + (nxt,))
    return routes, loss


def build_route_dataset(topo, cfg, rng):
    radio, sigma = cfg["radio"], cfg["shadowing"]["sigma_db"]
    e = cfg["energy"]
    air_s = airtime_ms(cfg["traffic"]["position_payload_b"], radio["sf"],
                       radio["bw_hz"], radio["cr"], radio["preamble_syms"]) / 1000.0
    etx_wh = e["tx_current_ma"] / 1000.0 * e["battery_v"] * air_s / 3600.0
    routes, loss = enumerate_routes(topo, radio, sigma)
    rows = []
    for path in routes:
        for _ in range(6):                       # random battery states per route
            socs = rng.uniform(0.05, 1.0, size=len(path))
            p_links = [link_success_p(loss.get((path[i], path[i + 1]), 300.0),
                                      radio, sigma) for i in range(len(path) - 1)]
            # expected attempts per hop with up to 3 tries
            p_del, e_wh = 1.0, 0.0
            for p in p_links:
                p_hop = 1.0 - (1.0 - p) ** 3
                exp_tries = (1.0 if p >= 0.999 else
                             min((1.0 - (1.0 - p) ** 3) / max(p, 1e-6), 3.0))
                e_wh += etx_wh * exp_tries
                p_del *= p_hop
            margins = [config_rx_power_reference_dbm(radio)
                       - loss.get((path[i], path[i + 1]), 300.0)
                       - radio["rx_sensitivity_dbm"] for i in range(len(path) - 1)]
            # scarcity-weighted cost: energy spent at low-SOC relays counts more
            scarcity = float(np.mean([1.0 / max(s, 0.05) for s in socs[1:]])) if len(socs) > 1 else 1.0
            rows.append({
                "n_hops": len(path) - 1,
                "worst_margin_db": float(min(margins)),
                "mean_margin_db": float(np.mean(margins)),
                "min_soc": float(min(socs)),
                "mean_soc": float(np.mean(socs)),
                "p_deliver": p_del,
                "e_expected_wh": e_wh,
                "cost_scarcity_wh": e_wh * scarcity,
            })
    return rows, len(routes)


def train_route_cost(rows, out_dir):
    import pandas as pd
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split
    df = pd.DataFrame(rows)
    feats = ["n_hops", "worst_margin_db", "mean_margin_db", "min_soc", "mean_soc"]
    rep = {}
    import joblib
    for target in ("p_deliver", "cost_scarcity_wh"):
        Xtr, Xte, ytr, yte = train_test_split(df[feats], df[target],
                                              test_size=0.25, random_state=0)
        m = GradientBoostingRegressor(n_estimators=300, max_depth=3, random_state=0)
        m.fit(Xtr, ytr)
        pred = m.predict(Xte)
        rep[target] = {"mae": round(float(mean_absolute_error(yte, pred)), 5),
                       "r2": round(float(r2_score(yte, pred)), 4)}
        joblib.dump({"model": m, "features": feats},
                    out_dir / f"route_{target}_model.joblib")
    return rep


def main() -> int:
    import yaml
    ap = argparse.ArgumentParser(description="Train solar + route-cost models")
    ap.add_argument("--config", default="config/sim/wmnf_sim.yaml")
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--out-dir", default="artifacts/sim/ml")
    ap.add_argument("--skip-mode-comparison", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text())
    topo = json.loads((ROOT / args.topology).read_text())
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)

    print("Part A: building solar dataset (physics sim over DEM horizons) ...")
    solar_rows = build_solar_dataset(topo, cfg, rng)
    solar_rep = train_solar(solar_rows, out_dir)
    print(json.dumps(solar_rep, indent=2))

    modes_rep = None
    if not args.skip_mode_comparison:
        print("Part B: flood vs energy_aware (3 days, same seed) ...")
        modes_rep = compare_modes()
        print(json.dumps(modes_rep, indent=2))

    print("Part C: route energy-cost surrogate ...")
    route_rows, n_routes = build_route_dataset(topo, cfg, rng)
    route_rep = train_route_cost(route_rows, out_dir)
    print(f"  {n_routes} routes, {len(route_rows)} samples")
    print(json.dumps(route_rep, indent=2))

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "solar_predictor": solar_rep,
        "routing_mode_comparison": modes_rep,
        "route_cost_surrogate": {"n_routes": n_routes, "n_samples": len(route_rows),
                                 **route_rep},
        "caveats": [
            "v1 models are trained on simulator physics (ITM + solar model), not field data;"
            " retrain on Trial 2 measurements",
            "energy currents are BENCH-CALIBRATE placeholders (config/sim/wmnf_sim.yaml)",
            "kt forecast noise 0.08 approximates a 1-day cloud forecast error",
        ],
    }
    (out_dir / "ml_report.json").write_text(json.dumps(report, indent=2))
    print(f"wrote {out_dir}/ml_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

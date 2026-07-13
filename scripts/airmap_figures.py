#!/usr/bin/env python3
"""Generate AIRMap calibration figure panel for the Trial 1 report.

Outputs: artifacts/airmap/live_trial/airmap_figures.png  (300 dpi, 4-panel)

Panels:
  A  Path loss vs log10(distance) — measured, FSPL, calibrated
  B  Predicted vs Observed RSSI scatter — pre and post calibration
  C  MAE / RMSE by topography class (terrain stratification)
  D  Residual error CDF
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd

from radio_link_budget import RX_POWER_REFERENCE_DBM

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT    = Path(__file__).resolve().parents[1]
OUTDIR  = ROOT / "artifacts/airmap/live_trial"
PRE_PQ  = OUTDIR / "predictions_precalibration.parquet"
POST_PQ = OUTDIR / "predictions_postcalibration.parquet"

# ── Constants (must match airmap_live_trial.py) ────────────────────────────────
FREQ_MHZ    = 915.0
RX_POWER_REF = RX_POWER_REFERENCE_DBM

TOPO_COLORS = {
    "alpine_ridge":  "#1a4a8a",
    "sub_alpine":    "#e67e22",
    "valley_forest": "#1a7a3a",
    "nan":           "#aaaaaa",
    "unknown":       "#aaaaaa",
}
TOPO_LABELS = {
    "alpine_ridge":  "Alpine (≥1500 m)",
    "sub_alpine":    "Sub-alpine (1200–1500 m)",
    "valley_forest": "Forest (<1200 m)",
}


def fspl_db(d_km: float) -> float:
    return 32.44 + 20 * math.log10(max(d_km, 1e-6)) + 20 * math.log10(FREQ_MHZ)


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pre  = pd.read_parquet(PRE_PQ)
    post = pd.read_parquet(POST_PQ)
    # Work with rows that have an observed RSSI and a real distance
    m = pre.dropna(subset=["obs_metric_dbm", "distance_m"]).copy()
    m = m[m["distance_m"] > 1.0].copy()           # drop clipped-to-minimum rows
    m = m[m["distance_m"] < 50_000].copy()        # drop implausible distances (>50 km)
    # Basic path loss is terminal reference minus received input power;
    # receiver sensitivity is a threshold and must not enter this subtraction.
    m["obs_path_loss_db"] = RX_POWER_REF - m["obs_metric_dbm"]
    m["pred_path_loss_db_pre"] = m["pred_path_loss_db"]
    m["topo_str"] = m["topography_class"].astype(str)

    post_m = post.loc[m.index] if all(i in post.index for i in m.index) else post.dropna(subset=["obs_metric_dbm"]).copy()
    post_m = post_m[post_m.index.isin(m.index)] if not post_m.empty else post_m
    m["pred_rssi_post"] = post.loc[m.index, "pred_rssi_dbm"] if all(i in post.index for i in m.index) else np.nan

    return pre, post, m


def panel_path_loss(ax: plt.Axes, m: pd.DataFrame) -> None:
    """Panel A: Path loss vs log10(distance)."""
    d_km = m["distance_m"] / 1000.0

    # scatter colored by topography class
    for topo, grp in m.groupby("topo_str"):
        color = TOPO_COLORS.get(topo, "#aaaaaa")
        label = TOPO_LABELS.get(topo, topo)
        ax.scatter(
            grp["distance_m"] / 1000.0,
            grp["obs_path_loss_db"],
            c=color, s=20, alpha=0.65, label=label, zorder=3,
        )

    # FSPL curve (free space, n=2)
    d_range = np.logspace(np.log10(max(d_km.min(), 0.01)), np.log10(d_km.max() * 1.2), 200)
    fspl_vals = [fspl_db(d) for d in d_range]
    ax.semilogx(d_range, fspl_vals, "k--", lw=1.5, label="FSPL (free space, n=2)", zorder=4)

    # Calibrated model: fit log-distance to observations
    log_d = np.log10(d_km)
    pl    = m["obs_path_loss_db"]
    valid = np.isfinite(log_d) & np.isfinite(pl)
    if valid.sum() >= 3:
        coeffs = np.polyfit(log_d[valid], pl[valid], 1)
        n_fit  = coeffs[0] / 10.0
        fitted_pl = np.polyval(coeffs, np.log10(d_range))
        ax.semilogx(d_range, fitted_pl, color="#c0392b", lw=2.0,
                    label=f"Fitted model (n={n_fit:.2f})", zorder=5)

    ax.set_xlabel("Distance (km)", fontsize=10)
    ax.set_ylabel("Path Loss (dB)", fontsize=10)
    ax.set_title("A  Path Loss vs Distance", fontsize=11, fontweight="bold", loc="left")
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(True, which="both", ls=":", alpha=0.4)
    ax.invert_yaxis()


def panel_pred_vs_obs(ax: plt.Axes, m: pd.DataFrame) -> None:
    """Panel B: Predicted vs Observed RSSI (pre and post calibration)."""
    obs = m["obs_metric_dbm"]

    # pre-calibration
    ax.scatter(obs, m["pred_rssi_dbm"], c="#aaaaaa", s=16, alpha=0.5,
               label="Pre-calibration", zorder=2)

    # post-calibration
    if "pred_rssi_post" in m.columns and m["pred_rssi_post"].notna().any():
        ax.scatter(obs, m["pred_rssi_post"], c="#1a4a8a", s=16, alpha=0.65,
                   label="Post-calibration", zorder=3)

    # perfect-prediction diagonal
    lo = min(obs.min(), m["pred_rssi_dbm"].min()) - 5
    hi = max(obs.max(), m["pred_rssi_dbm"].max()) + 5
    ax.plot([lo, hi], [lo, hi], "k-", lw=1.0, label="Perfect prediction", zorder=4)

    ax.set_xlabel("Observed RSSI (dBm)", fontsize=10)
    ax.set_ylabel("Predicted RSSI (dBm)", fontsize=10)
    ax.set_title("B  Predicted vs Observed RSSI", fontsize=11, fontweight="bold", loc="left")
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(True, ls=":", alpha=0.4)
    ax.set_aspect("equal", adjustable="box")


def panel_stratified(ax: plt.Axes, m: pd.DataFrame) -> None:
    """Panel C: MAE and RMSE by topography class."""
    rows = []
    for topo, grp in m.groupby("topo_str"):
        if len(grp) < 2:
            continue
        err = grp["pred_rssi_dbm"] - grp["obs_metric_dbm"]
        rows.append({
            "topo": TOPO_LABELS.get(topo, topo),
            "mae":  float(err.abs().mean()),
            "rmse": float(np.sqrt((err**2).mean())),
            "n":    len(grp),
            "color": TOPO_COLORS.get(topo, "#aaaaaa"),
        })
    if not rows:
        ax.text(0.5, 0.5, "Insufficient stratified data", ha="center", va="center",
                transform=ax.transAxes, fontsize=10, color="#888")
        ax.set_title("C  Error by Terrain Class", fontsize=11, fontweight="bold", loc="left")
        return

    df = pd.DataFrame(rows)
    x  = np.arange(len(df))
    w  = 0.35
    bars_mae  = ax.bar(x - w/2, df["mae"],  w, color=df["color"], alpha=0.85, label="MAE")
    bars_rmse = ax.bar(x + w/2, df["rmse"], w, color=df["color"], alpha=0.45,
                       edgecolor=df["color"], linewidth=1.5, label="RMSE")

    for bar, n in zip(bars_mae, df["n"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f"n={n}", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(df["topo"], fontsize=8, wrap=True)
    ax.set_ylabel("Error (dB)", fontsize=10)
    ax.set_title("C  Pre-calibration Error by Terrain Class", fontsize=11, fontweight="bold", loc="left")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", ls=":", alpha=0.4)


def panel_cdf(ax: plt.Axes, m: pd.DataFrame) -> None:
    """Panel D: CDF of residual error."""
    pre_err  = m["pred_rssi_dbm"] - m["obs_metric_dbm"]

    def cdf(vals):
        s = np.sort(vals.dropna())
        p = np.arange(1, len(s) + 1) / len(s)
        return s, p

    s_pre, p_pre = cdf(pre_err)
    ax.plot(s_pre, p_pre, color="#aaaaaa", lw=1.5, label="Pre-calibration")

    if "pred_rssi_post" in m.columns and m["pred_rssi_post"].notna().any():
        post_err = m["pred_rssi_post"] - m["obs_metric_dbm"]
        s_post, p_post = cdf(post_err)
        ax.plot(s_post, p_post, color="#1a4a8a", lw=1.5, label="Post-calibration")

    ax.axvline(0, color="k", ls="--", lw=1.0, alpha=0.5, label="Zero error")
    ax.set_xlabel("Prediction Error (dBm)", fontsize=10)
    ax.set_ylabel("CDF", fontsize=10)
    ax.set_title("D  Residual Error CDF", fontsize=11, fontweight="bold", loc="left")
    ax.legend(fontsize=8, framealpha=0.8)
    ax.grid(True, ls=":", alpha=0.4)
    ax.set_ylim(0, 1)


def main() -> None:
    pre, post, m = load()
    print(f"Calibration dataset: {len(m)} rows with distance + RSSI")
    print(f"  distance range: {m['distance_m'].min():.0f}m – {m['distance_m'].max():.0f}m")
    print(f"  topography classes: {m['topo_str'].value_counts().to_dict()}")

    fig = plt.figure(figsize=(13, 10))
    fig.suptitle(
        "AIRMap Calibration Results — Mt. Washington Trial 1 (2026-05-23)\n"
        "915 MHz LoRa · Meshtastic LongFast · HEAD GPS: Garmin external",
        fontsize=12, fontweight="bold", y=0.98,
    )

    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.32,
                           left=0.09, right=0.97, top=0.91, bottom=0.08)

    panel_path_loss(fig.add_subplot(gs[0, 0]), m)
    panel_pred_vs_obs(fig.add_subplot(gs[0, 1]), m)
    panel_stratified(fig.add_subplot(gs[1, 0]), m)
    panel_cdf(fig.add_subplot(gs[1, 1]), m)

    out = OUTDIR / "airmap_figures.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()

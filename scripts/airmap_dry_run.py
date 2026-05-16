#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG_MODEL = ROOT / "config/airmap/model-baseline.yaml"
CFG_EVAL = ROOT / "config/airmap/calibration-and-eval.yaml"
OUT_DIR = ROOT / "artifacts/airmap"


def git_commit() -> str:
    return (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip()
    )


def fspl_db(distance_m: float, freq_mhz: float) -> float:
    d_km = max(distance_m / 1000.0, 1e-6)
    return 32.44 + 20 * math.log10(d_km) + 20 * math.log10(freq_mhz)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def main() -> None:
    model_cfg = yaml.safe_load(CFG_MODEL.read_text())
    eval_cfg = yaml.safe_load(CFG_EVAL.read_text())

    freq_mhz = float(model_cfg["model"]["frequency_mhz"])
    model_name = model_cfg["model"]["name"]
    model_version = model_cfg["model"]["version"]
    model_hash = model_cfg["model"]["hash"]
    recipe_version = model_cfg["features"]["recipe_version"]
    calibration_version = eval_cfg["calibration"]["version"]

    np.random.seed(42)
    n = 40
    base = datetime(2026, 5, 16, 18, 0, tzinfo=timezone.utc)
    trial_id = "week4-dryrun-001"
    head_id = "meshradiohead"
    node_id = "meshhikernode1"

    lat0, lon0 = 44.2706, -71.3033
    lat1, lon1 = 44.2950, -71.2758

    rows = []
    for i in range(n):
        t = i / (n - 1)
        lat = lat0 + (lat1 - lat0) * t
        lon = lon0 + (lon1 - lon0) * t
        dist = haversine_m(lat0, lon0, lat, lon)
        pl = fspl_db(dist + 10, freq_mhz) + np.random.normal(8.0, 2.0)
        pred_rssi = 20 - pl
        pred_snr = pred_rssi - (-110)
        obs_rssi = pred_rssi + np.random.normal(0.0, 4.0)
        obs_snr = pred_snr + np.random.normal(0.0, 3.0)
        rows.append(
            {
                "timestamp_utc": (base + timedelta(seconds=30 * i)).isoformat(),
                "trial_id": trial_id,
                "head_id": head_id,
                "node_id": node_id,
                "segment_id": f"seg-{i:03d}",
                "distance_m": float(dist),
                "pred_path_loss_db": float(pl),
                "pred_rssi_dbm": float(pred_rssi),
                "pred_snr_db": float(pred_snr),
                "obs_rssi_dbm": float(obs_rssi),
                "obs_snr_db": float(obs_snr),
                "topography_class": "alpine_ridge" if i > n // 2 else "valley",
                "weather_tag": "clear",
                "distance_bin": "0-2km" if dist < 2000 else "2-5km",
                "satellite_link_status": "available" if i % 3 else "degraded",
                "material_class": "mixed_forest",
            }
        )

    df = pd.DataFrame(rows)

    # pre/post calibration
    pre = df.copy()
    residual = (pre["obs_rssi_dbm"] - pre["pred_rssi_dbm"]).mean()
    scale = pre["obs_snr_db"].std() / max(pre["pred_snr_db"].std(), 1e-6)

    post = pre.copy()
    post["pred_rssi_dbm"] = post["pred_rssi_dbm"] + residual
    post["pred_snr_db"] = (post["pred_snr_db"] - post["pred_snr_db"].mean()) * scale + post[
        "pred_snr_db"
    ].mean()

    # required metadata fields
    for frame in (pre, post):
        frame["model_name"] = model_name
        frame["model_version"] = model_version
        frame["model_hash"] = model_hash
        frame["feature_recipe_version"] = recipe_version
        frame["calibration_version"] = calibration_version

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pre_path = OUT_DIR / "predictions_precalibration.parquet"
    post_path = OUT_DIR / "predictions_postcalibration.parquet"
    pre.to_parquet(pre_path, index=False)
    post.to_parquet(post_path, index=False)

    join_audit = post[["trial_id", "head_id", "node_id", "timestamp_utc", "segment_id"]].copy()
    join_audit["join_status"] = "matched"
    join_audit.to_csv(OUT_DIR / "prediction_observation_join_audit.csv", index=False)

    def mae(a, b):
        return float(np.mean(np.abs(a - b)))

    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2)))

    metrics_global = {
        "mae_rssi": mae(post["pred_rssi_dbm"], post["obs_rssi_dbm"]),
        "rmse_rssi": rmse(post["pred_rssi_dbm"], post["obs_rssi_dbm"]),
        "mae_snr": mae(post["pred_snr_db"], post["obs_snr_db"]),
        "rmse_snr": rmse(post["pred_snr_db"], post["obs_snr_db"]),
        "n": int(len(post)),
    }
    (OUT_DIR / "metrics_global.json").write_text(json.dumps(metrics_global, indent=2))

    strat = (
        post.groupby(["topography_class", "weather_tag", "distance_bin", "satellite_link_status"], dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "mae_rssi": mae(g["pred_rssi_dbm"], g["obs_rssi_dbm"]),
                    "rmse_rssi": rmse(g["pred_rssi_dbm"], g["obs_rssi_dbm"]),
                }
            )
        )
        .reset_index()
    )
    strat.to_csv(OUT_DIR / "metrics_stratified.csv", index=False)

    post["abs_err_rssi"] = (post["pred_rssi_dbm"] - post["obs_rssi_dbm"]).abs()
    outliers = post.sort_values("abs_err_rssi", ascending=False).head(10)
    outliers.to_csv(OUT_DIR / "outliers.csv", index=False)

    provenance = {
        "run_id": f"dryrun-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "git_commit": git_commit(),
        "model_name": model_name,
        "model_version": model_version,
        "model_hash": model_hash,
        "feature_recipe_version": recipe_version,
        "calibration_version": calibration_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "provenance.json").write_text(json.dumps(provenance, indent=2))

    print(f"Wrote artifacts to {OUT_DIR}")
    print(json.dumps(metrics_global, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def mae(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) == 0:
        return None
    return float(np.mean(np.abs(a - b)))


def rmse(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) == 0:
        return None
    return float(np.sqrt(np.mean((a - b) ** 2)))


def load_df(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise SystemExit(f"unsupported input type: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute global + stratified RF error metrics and outlier triage artifacts")
    ap.add_argument("--input", default="artifacts/qa/sentinel_scored.parquet")
    ap.add_argument("--out-dir", default="artifacts/eval")
    ap.add_argument("--min-samples", type=int, default=200)
    # Falsifiable threshold: post-calibration held-in RMSE for a usable propagation
    # model. Literature shadowing sigma for mountain LoRa is 6-8 dB (Bianco et al.
    # 2021); 12 dB allows headroom. A gate that cannot fail is not evidence — never
    # raise this to make a run pass.
    ap.add_argument("--max-rmse-db", type=float, default=12.0)
    ap.add_argument("--min-stratum-samples", type=int, default=30)
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_df(in_path)
    if df.empty:
        raise SystemExit("input dataframe empty")

    # accepted QA tiers only
    if "quality_tier" in df.columns:
        df = df[df["quality_tier"].isin(["high", "medium"])].copy()

    # Evidence-grade error metrics use calibration-eligible rows only (GPS both
    # ends, verified direct link, plausible power — see airmap_live_trial.py).
    # Rows lacking the column (legacy artifacts) are treated as ineligible-unknown
    # and kept, but the output records that the eligibility filter was unavailable.
    eligibility_filtered = False
    excluded_ineligible = 0
    if "calibration_eligible" in df.columns:
        eligible_mask = df["calibration_eligible"].fillna(False).astype(bool)
        excluded_ineligible = int((~eligible_mask).sum())
        df = df[eligible_mask].copy()
        eligibility_filtered = True

    pred = pd.to_numeric(df.get("pred_rssi_dbm"), errors="coerce")
    obs_rsrp = pd.to_numeric(df.get("rsrp_dbm"), errors="coerce") if "rsrp_dbm" in df.columns else pd.Series([np.nan] * len(df))
    obs_rssi = pd.to_numeric(df.get("rssi_dbm"), errors="coerce") if "rssi_dbm" in df.columns else pd.Series([np.nan] * len(df))
    obs = obs_rsrp.combine_first(obs_rssi)

    src = np.where(obs_rsrp.notna(), "rsrp_dbm", np.where(obs_rssi.notna(), "rssi_dbm", "none"))
    df["obs_metric_dbm"] = obs
    df["obs_metric_source"] = src
    df["pred_metric_dbm"] = pred

    m = df.dropna(subset=["obs_metric_dbm", "pred_metric_dbm"]).copy()
    if m.empty:
        global_metrics = {
            "metric_target": "rsrp_dbm_or_rssi_dbm_fallback",
            "n": 0,
            "mae": None,
            "rmse": None,
            "source_counts": {"rsrp_dbm": 0, "rssi_dbm": 0, "none": int(len(df))},
            "eligibility_filter_applied": eligibility_filtered,
            "excluded_ineligible_rows": excluded_ineligible,
        }
        (out_dir / "metrics_global.json").write_text(json.dumps(global_metrics, indent=2), encoding="utf-8")
        (out_dir / "metrics_stratified.csv").write_text("", encoding="utf-8")
        (out_dir / "outliers.csv").write_text("", encoding="utf-8")
        decision = {"status": "FAIL", "reason": "n=0", "n": 0}
        (out_dir / "eval_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
        print(json.dumps({"metrics_global": global_metrics, "decision": decision}, indent=2))
        return 1

    m["abs_error_db"] = (m["pred_metric_dbm"] - m["obs_metric_dbm"]).abs()

    global_metrics = {
        "metric_target": "rsrp_dbm_or_rssi_dbm_fallback",
        "n": int(len(m)),
        "mae": mae(m["pred_metric_dbm"], m["obs_metric_dbm"]),
        "rmse": rmse(m["pred_metric_dbm"], m["obs_metric_dbm"]),
        "source_counts": {
            "rsrp_dbm": int((m["obs_metric_source"] == "rsrp_dbm").sum()),
            "rssi_dbm": int((m["obs_metric_source"] == "rssi_dbm").sum()),
            "none": int((m["obs_metric_source"] == "none").sum()),
        },
        "eligibility_filter_applied": eligibility_filtered,
        "excluded_ineligible_rows": excluded_ineligible,
    }

    strata_cols = ["topography_class", "weather_tag", "distance_bin", "satellite_link_status"]
    for c in strata_cols:
        if c not in m.columns:
            m[c] = "unknown"

    strat = (
        m.groupby(strata_cols, dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n": len(g),
                    "mae": mae(g["pred_metric_dbm"], g["obs_metric_dbm"]),
                    "rmse": rmse(g["pred_metric_dbm"], g["obs_metric_dbm"]),
                    "obs_rsrp_count": int((g["obs_metric_source"] == "rsrp_dbm").sum()),
                    "obs_rssi_count": int((g["obs_metric_source"] == "rssi_dbm").sum()),
                }
            )
        )
        .reset_index()
    )
    # Strata below the minimum sample count are noise cells: flag them and
    # suppress their error stats so they cannot be cited.
    strat["meets_min_n"] = strat["n"] >= int(args.min_stratum_samples)
    strat.loc[~strat["meets_min_n"], ["mae", "rmse"]] = np.nan

    outliers = m.sort_values("abs_error_db", ascending=False).head(50).copy()
    keep_cols = [
        c
        for c in [
            "timestamp_utc",
            "trial_id",
            "node_id",
            "lat",
            "lon",
            "pred_metric_dbm",
            "obs_metric_dbm",
            "abs_error_db",
            "topography_class",
            "weather_tag",
            "distance_bin",
            "satellite_link_status",
        ]
        if c in outliers.columns
    ]
    outliers = outliers[keep_cols]

    # geojson outlier map artifact
    features = []
    if "lat" in outliers.columns and "lon" in outliers.columns:
        for _, r in outliers.dropna(subset=["lat", "lon"]).iterrows():
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
                    "properties": {
                        "node_id": str(r.get("node_id", "")),
                        "trial_id": str(r.get("trial_id", "")),
                        "abs_error_db": float(r.get("abs_error_db", np.nan)),
                        "topography_class": str(r.get("topography_class", "unknown")),
                        "weather_tag": str(r.get("weather_tag", "unknown")),
                    },
                }
            )

    geojson = {"type": "FeatureCollection", "features": features}

    global_path = out_dir / "metrics_global.json"
    strat_path = out_dir / "metrics_stratified.csv"
    outliers_path = out_dir / "outliers.csv"
    geojson_path = out_dir / "outlier_points.geojson"

    global_path.write_text(json.dumps(global_metrics, indent=2), encoding="utf-8")
    strat.to_csv(strat_path, index=False)
    outliers.to_csv(outliers_path, index=False)
    geojson_path.write_text(json.dumps(geojson, indent=2), encoding="utf-8")

    passed = (global_metrics["n"] >= int(args.min_samples)) and (
        global_metrics["rmse"] is not None and global_metrics["rmse"] <= float(args.max_rmse_db)
    )
    decision = {
        "status": "PASS" if passed else "FAIL",
        "rules": {
            "min_samples": int(args.min_samples),
            "max_rmse_db": float(args.max_rmse_db),
        },
        "observed": {
            "n": global_metrics["n"],
            "rmse": global_metrics["rmse"],
            "mae": global_metrics["mae"],
        },
    }

    reproducibility = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_sha256": {str(in_path): sha256(in_path)},
        "output_sha256": {
            str(global_path): sha256(global_path),
            str(strat_path): sha256(strat_path),
            str(outliers_path): sha256(outliers_path),
            str(geojson_path): sha256(geojson_path),
        },
        "parameters": {"min_samples": int(args.min_samples), "max_rmse_db": float(args.max_rmse_db)},
    }

    (out_dir / "eval_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    (out_dir / "eval_reproducibility.json").write_text(json.dumps(reproducibility, indent=2), encoding="utf-8")

    print(json.dumps({"metrics_global": global_metrics, "decision": decision}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

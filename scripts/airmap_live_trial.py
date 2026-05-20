#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


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


def git_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc")


def time_bin_from_hour(hour: int) -> str:
    if 5 <= hour <= 7:
        return "dawn"
    if 8 <= hour <= 16:
        return "day"
    if 17 <= hour <= 19:
        return "dusk"
    if 20 <= hour <= 22:
        return "evening_peak"
    return "night"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--node-id", default="meshhikernode1")
    ap.add_argument("--head-id", default="meshnodehead")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--lat0", type=float, default=44.2706)
    ap.add_argument("--lon0", type=float, default=-71.3033)
    ap.add_argument("--lat1", type=float, default=44.2950)
    ap.add_argument("--lon1", type=float, default=-71.2758)
    ap.add_argument("--time-window-seconds", type=int, default=5)
    ap.add_argument("--min-observed-samples", type=int, default=200)
    ap.add_argument("--require-rsrp", action="store_true", help="Fail run if no rsrp_dbm samples are present")
    args = ap.parse_args()

    root = Path(args.root)
    model_cfg = yaml.safe_load((root / "config/airmap/model-baseline.yaml").read_text())
    eval_cfg = yaml.safe_load((root / "config/airmap/calibration-and-eval.yaml").read_text())
    out_dir = root / "artifacts/airmap/live_trial"
    out_dir.mkdir(parents=True, exist_ok=True)

    freq_mhz = float(model_cfg["model"]["frequency_mhz"])
    model_name = model_cfg["model"]["name"]
    model_version = model_cfg["model"]["version"]
    model_hash = model_cfg["model"]["hash"]
    recipe_version = model_cfg["features"]["recipe_version"]
    calibration_version = eval_cfg["calibration"]["version"]

    node_path = Path(args.ingest_root) / f"{args.node_id}/jsonl/telemetry_stream.jsonl"
    obs = load_jsonl(node_path)
    if obs.empty:
        raise SystemExit(f"no observation rows found in {node_path}")

    obs = obs[(obs["trial_id"] == args.trial_id) & (obs["node_id"] == args.node_id)].copy()
    if obs.empty:
        raise SystemExit("no rows after trial/node filter")

    # Observed metric fallback chain: prefer RSRP, then RSSI if RSRP is unavailable.
    obs["obs_rsrp_dbm"] = pd.to_numeric(obs.get("rsrp_dbm"), errors="coerce")
    obs["obs_rssi_dbm"] = pd.to_numeric(obs.get("rssi_dbm"), errors="coerce")
    obs["obs_metric_dbm"] = obs["obs_rsrp_dbm"].combine_first(obs["obs_rssi_dbm"])
    obs["obs_metric_source"] = np.where(
        obs["obs_rsrp_dbm"].notna(),
        "rsrp_dbm",
        np.where(obs["obs_rssi_dbm"].notna(), "rssi_dbm", "none"),
    )

    t0 = obs["timestamp_utc"].min()
    t1 = obs["timestamp_utc"].max()
    span = max((t1 - t0).total_seconds(), 1.0)
    frac = (obs["timestamp_utc"] - t0).dt.total_seconds() / span
    obs["lat"] = args.lat0 + (args.lat1 - args.lat0) * frac
    obs["lon"] = args.lon0 + (args.lon1 - args.lon0) * frac
    obs["distance_m"] = obs.apply(lambda r: haversine_m(args.lat0, args.lon0, r["lat"], r["lon"]), axis=1)
    obs["pred_path_loss_db"] = obs["distance_m"].apply(lambda d: fspl_db(float(d) + 10.0, freq_mhz))
    obs["pred_rssi_dbm"] = 20.0 - obs["pred_path_loss_db"]
    obs["pred_snr_db"] = obs["pred_rssi_dbm"] - (-110.0)
    obs["segment_id"] = [f"seg-{i:05d}" for i in range(len(obs))]
    obs["topography_class"] = np.where(frac > 0.5, "alpine_ridge", "valley")
    obs["distance_bin"] = np.where(obs["distance_m"] < 2000.0, "0-2km", "2-5km")
    obs["material_class"] = "mixed_forest"
    obs["local_hour"] = obs["timestamp_utc"].dt.hour.astype("Int64")
    obs["time_bin"] = obs["local_hour"].apply(lambda h: time_bin_from_hour(int(h)) if pd.notna(h) else "unknown")

    # Optional Starlink/satellite quality fields (ingested when available).
    # merge_starlink_into_telemetry.py emits satellite_link_status_starlink to avoid
    # colliding with the MANET connectivity_mode field; alias it here.
    if "satellite_link_status_starlink" in obs.columns and "satellite_link_status" not in obs.columns:
        obs["satellite_link_status"] = obs["satellite_link_status_starlink"]
    elif "satellite_link_status_starlink" in obs.columns:
        obs["satellite_link_status"] = obs["satellite_link_status_starlink"].combine_first(obs["satellite_link_status"])
    for col in (
        "satellite_rtt_ms_p50",
        "satellite_rtt_ms_p95",
        "satellite_down_mbps",
        "satellite_up_mbps",
        "satellite_packet_loss_pct",
        "satellite_obstruction_pct",
        "satellite_outage_seconds",
    ):
        obs[col] = pd.to_numeric(obs.get(col), errors="coerce")

    # Route/time-window join quality audit against head stream timestamps.
    head_path = Path(args.ingest_root) / f"{args.head_id}/jsonl/telemetry_stream.jsonl"
    head = load_jsonl(head_path)
    head = head[(head["trial_id"] == args.trial_id)].copy() if not head.empty else head
    if not head.empty:
        head = head[["timestamp_utc"]].dropna().sort_values("timestamp_utc").copy()
        head = head.rename(columns={"timestamp_utc": "head_timestamp_utc"})
        join = pd.merge_asof(
            obs.sort_values("timestamp_utc"),
            head.sort_values("head_timestamp_utc"),
            left_on="timestamp_utc",
            right_on="head_timestamp_utc",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=args.time_window_seconds),
        )
    else:
        join = obs.copy()
        join["head_timestamp_utc"] = pd.NaT

    join["time_offset_seconds"] = (join["timestamp_utc"] - join["head_timestamp_utc"]).dt.total_seconds().abs()
    join["join_status"] = np.where(
        join["head_timestamp_utc"].isna(),
        "missing_time_window",
        np.where(join["obs_metric_dbm"].notna(), "matched", "missing_observation_metric"),
    )

    pre = join.copy()
    post = join.copy()

    matched = post.dropna(subset=["obs_metric_dbm"]).copy()
    if len(matched) > 0:
        residual = float((matched["obs_metric_dbm"] - matched["pred_rssi_dbm"]).mean())
        post["pred_rssi_dbm"] = post["pred_rssi_dbm"] + residual
        metric_sources = sorted(matched["obs_metric_source"].dropna().unique().tolist())
        calibration_note = f"applied_residual_bias_using:{','.join(metric_sources)}"
    else:
        residual = None
        calibration_note = "no_observed_rsrp_or_rssi_rows_available"

    for frame in (pre, post):
        frame["model_name"] = model_name
        frame["model_version"] = model_version
        frame["model_hash"] = model_hash
        frame["feature_recipe_version"] = recipe_version
        frame["calibration_version"] = calibration_version

    _KNOWN_STR_COLS = {
        "timestamp_utc", "head_timestamp_utc", "trial_id", "node_id", "head_id",
        "segment_id", "topography_class", "distance_bin", "material_class", "time_bin",
        "obs_metric_source", "join_status", "model_name", "model_version",
        "model_hash", "feature_recipe_version", "calibration_version",
        "satellite_link_status", "satellite_link_status_starlink",
    }
    for _frame in (pre, post):
        for _col in list(_frame.select_dtypes(include="object").columns):
            if _col not in _KNOWN_STR_COLS:
                _frame[_col] = pd.to_numeric(_frame[_col], errors="coerce")

    pre.to_parquet(out_dir / "predictions_precalibration.parquet", index=False)
    post.to_parquet(out_dir / "predictions_postcalibration.parquet", index=False)

    join_audit = post[[
        "trial_id",
        "head_id",
        "node_id",
        "timestamp_utc",
        "head_timestamp_utc",
        "time_offset_seconds",
        "segment_id",
        "join_status",
        "obs_metric_source",
    ]].copy()
    join_audit.to_csv(out_dir / "prediction_observation_join_audit.csv", index=False)

    def mae(a, b):
        return float(np.mean(np.abs(a - b))) if len(a) else None

    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2))) if len(a) else None

    m = post.dropna(subset=["obs_metric_dbm"]).copy()
    metrics_global = {
        "metric_target": "rsrp_dbm_or_rssi_dbm_fallback",
        "metric_source_counts": {
            "rsrp_dbm": int((m["obs_metric_source"] == "rsrp_dbm").sum()) if len(m) else 0,
            "rssi_dbm": int((m["obs_metric_source"] == "rssi_dbm").sum()) if len(m) else 0,
        },
        "mae": mae(m["pred_rssi_dbm"], m["obs_metric_dbm"]),
        "rmse": rmse(m["pred_rssi_dbm"], m["obs_metric_dbm"]),
        "n": int(len(m)),
    }

    matched_count = int((post["join_status"] == "matched").sum())
    missing_obs_count = int((post["join_status"] == "missing_observation_metric").sum())
    missing_window_count = int((post["join_status"] == "missing_time_window").sum())
    join_quality = {
        "time_window_seconds": int(args.time_window_seconds),
        "matched_count": matched_count,
        "missing_observation_metric_count": missing_obs_count,
        "missing_time_window_count": missing_window_count,
        "matched_pct": float((matched_count / len(post)) * 100.0) if len(post) else 0.0,
        "unmatched_pct": float(((missing_obs_count + missing_window_count) / len(post)) * 100.0) if len(post) else 0.0,
        "median_time_offset_seconds": float(post["time_offset_seconds"].dropna().median()) if post["time_offset_seconds"].notna().any() else None,
    }
    (out_dir / "metrics_global.json").write_text(json.dumps(metrics_global, indent=2))
    (out_dir / "join_quality.json").write_text(json.dumps(join_quality, indent=2))

    strat = (
        m.groupby(["topography_class", "weather_tag", "distance_bin", "satellite_link_status"], dropna=False)
        .apply(lambda g: pd.Series({"n": len(g), "mae": mae(g["pred_rssi_dbm"], g["obs_metric_dbm"]), "rmse": rmse(g["pred_rssi_dbm"], g["obs_metric_dbm"])}))
        .reset_index()
        if len(m)
        else pd.DataFrame(columns=["topography_class", "weather_tag", "distance_bin", "satellite_link_status", "n", "mae", "rmse"])
    )
    strat.to_csv(out_dir / "metrics_stratified.csv", index=False)

    sat_timebin = (
        post.groupby(["time_bin", "topography_class"], dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n": int(len(g)),
                    "satellite_connected_rows": int(
                        g.get("satellite_link_status", pd.Series(dtype=str))
                        .astype(str)
                        .str.lower()
                        .isin(["connected", "up", "online", "active", "true", "1", "yes"])
                        .sum()
                    ),
                    "satellite_rtt_ms_p50_median": float(g["satellite_rtt_ms_p50"].dropna().median()) if g["satellite_rtt_ms_p50"].notna().any() else None,
                    "satellite_down_mbps_median": float(g["satellite_down_mbps"].dropna().median()) if g["satellite_down_mbps"].notna().any() else None,
                    "satellite_packet_loss_pct_median": float(g["satellite_packet_loss_pct"].dropna().median()) if g["satellite_packet_loss_pct"].notna().any() else None,
                }
            )
        )
        .reset_index()
    )
    sat_timebin.to_csv(out_dir / "satellite_timebin_metrics.csv", index=False)

    sat_events = post[
        [
            "timestamp_utc",
            "trial_id",
            "node_id",
            "head_id",
            "segment_id",
            "time_bin",
            "topography_class",
            "satellite_link_status",
            "satellite_rtt_ms_p95",
            "satellite_packet_loss_pct",
            "satellite_outage_seconds",
            "satellite_obstruction_pct",
        ]
    ].copy()
    sat_events = sat_events[sat_events["satellite_outage_seconds"].fillna(0) > 0]
    sat_events.to_csv(out_dir / "satellite_outage_events.csv", index=False)

    if len(m):
        tmp = m.copy()
        tmp["abs_err"] = (tmp["pred_rssi_dbm"] - tmp["obs_metric_dbm"]).abs()
        tmp.sort_values("abs_err", ascending=False).head(10).to_csv(out_dir / "outliers.csv", index=False)
    else:
        pd.DataFrame(columns=post.columns.tolist() + ["abs_err"]).to_csv(out_dir / "outliers.csv", index=False)

    calibration_deltas = {
        "metric": "rsrp_dbm_or_rssi_dbm_fallback",
        "residual_bias_db": residual,
        "note": calibration_note,
        "sample_count": int(len(matched)),
    }
    (out_dir / "calibration_deltas.json").write_text(json.dumps(calibration_deltas, indent=2))

    warnings = []
    hard_fail_reasons = []
    rsrp_count = int((m["obs_metric_source"] == "rsrp_dbm").sum()) if len(m) else 0
    rssi_count = int((m["obs_metric_source"] == "rssi_dbm").sum()) if len(m) else 0

    if metrics_global["n"] < int(args.min_observed_samples):
        hard_fail_reasons.append(
            f"observed sample count {metrics_global['n']} is below minimum {int(args.min_observed_samples)}"
        )

    if rsrp_count == 0 and rssi_count > 0:
        warnings.append("running on fallback metric rssi_dbm; rsrp_dbm unavailable")

    if args.require_rsrp and rsrp_count == 0:
        hard_fail_reasons.append("require-rsrp enabled but rsrp_dbm sample count is zero")

    quality_gates = {
        "min_observed_samples": int(args.min_observed_samples),
        "require_rsrp": bool(args.require_rsrp),
        "passed": len(hard_fail_reasons) == 0,
        "warnings": warnings,
        "hard_fail_reasons": hard_fail_reasons,
    }
    (out_dir / "quality_gates.json").write_text(json.dumps(quality_gates, indent=2))

    provenance = {
        "run_id": f"live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "git_commit": git_commit(root),
        "model_name": model_name,
        "model_version": model_version,
        "model_hash": model_hash,
        "feature_recipe_version": recipe_version,
        "calibration_version": calibration_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_node_jsonl": str(node_path),
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2))

    summary = {
        "out_dir": str(out_dir),
        "rows_total": int(len(obs)),
        "rows_with_observed_metric": int(len(m)),
        "is_fallback_run": bool(rsrp_count == 0 and rssi_count > 0),
        "metrics_global": metrics_global,
        "join_quality": join_quality,
        "quality_gates": quality_gates,
        "calibration_deltas": calibration_deltas,
    }
    print(json.dumps(summary, indent=2, default=str))
    if not quality_gates["passed"]:
        raise SystemExit("quality gates failed: " + "; ".join(quality_gates["hard_fail_reasons"]))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Emit the digital-twin calibration file from calibrated pipeline outputs.

Proposal deliverable #3 ("Digital Twin Calibration File: calculated Path Loss
Exponents (n) for the specific geology encountered"). Reads the
calibration-eligible predictions, fits the floating-intercept log-distance model
PL = alpha + 10*n*log10(d_m) globally and per terrain class, and writes a
versioned YAML the digital twin / coverage planner can load.

Each fit carries its sample count, R^2, shadowing sigma, bootstrap CI on n, and
explicit validity bounds (distance range, frequency, trial provenance) so a
consumer never extrapolates a fit outside the data that produced it.

Usage:
  python3 scripts/build_calibration_file.py \
      --predictions artifacts/airmap/live_trial/predictions_postcalibration.parquet \
      --calibration-version v1.0.0
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from airmap_live_trial import floating_intercept_fit, moving_block_bootstrap, EIRP_DBM  # noqa: E402

MIN_CLASS_SAMPLES = 30


def _fit_block(df: pd.DataFrame) -> dict | None:
    sub = df.dropna(subset=["distance_m", "obs_path_loss_db"])
    sub = sub[sub["distance_m"] >= 1.0]
    if len(sub) < MIN_CLASS_SAMPLES:
        return {"n_samples": int(len(sub)), "status": "insufficient_samples",
                "min_required": MIN_CLASS_SAMPLES}
    fit = floating_intercept_fit(sub["distance_m"].to_numpy(), sub["obs_path_loss_db"].to_numpy())
    boot = moving_block_bootstrap(sub) if "timestamp_utc" in sub.columns else None
    out = {
        "status": "fitted",
        "n_samples": int(len(sub)),
        "path_loss_exponent_n": round(fit["path_loss_exponent"], 4),
        "intercept_alpha_db": round(fit["alpha_db"], 4),
        "shadowing_sigma_db": round(fit["sigma_db"], 4),
        "r_squared": round(fit["r2"], 4) if fit["r2"] is not None else None,
        "distance_range_m": [float(sub["distance_m"].min()), float(sub["distance_m"].max())],
    }
    if boot:
        out["path_loss_exponent_ci95"] = [round(x, 4) for x in boot["path_loss_exponent_ci95"]]
        out["shadowing_sigma_ci95"] = [round(x, 4) for x in boot["sigma_db_ci95"]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit the digital-twin calibration file")
    ap.add_argument("--predictions", default="artifacts/airmap/live_trial/predictions_postcalibration.parquet")
    ap.add_argument("--provenance", default="artifacts/airmap/live_trial/provenance.json")
    ap.add_argument("--calibration-version", default="v1.0.0")
    ap.add_argument("--freq-mhz", type=float, default=915.0)
    ap.add_argument("--geology-note", default="NH Presidential Range — metamorphic (schist/gneiss), mixed conifer below treeline")
    ap.add_argument("--out", default="config/airmap/digital-twin-calibration.yaml")
    args = ap.parse_args()

    pred_path = ROOT / args.predictions if not Path(args.predictions).is_absolute() else Path(args.predictions)
    if not pred_path.exists():
        raise SystemExit(f"predictions parquet not found: {pred_path}; run airmap_live_trial.py first")

    df = pd.read_parquet(pred_path)
    if "calibration_eligible" in df.columns:
        df = df[df["calibration_eligible"].fillna(False).astype(bool)].copy()
    if "obs_target_dbm" in df.columns:
        df["obs_path_loss_db"] = EIRP_DBM - pd.to_numeric(df["obs_target_dbm"], errors="coerce")
    elif "obs_metric_dbm" in df.columns:
        df["obs_path_loss_db"] = EIRP_DBM - pd.to_numeric(df["obs_metric_dbm"], errors="coerce")
    else:
        raise SystemExit("predictions lack an observed metric column")

    prov = {}
    prov_path = ROOT / args.provenance if not Path(args.provenance).is_absolute() else Path(args.provenance)
    if prov_path.exists():
        prov = json.loads(prov_path.read_text())

    per_class = {}
    if "topography_class" in df.columns:
        for cls, grp in df.groupby("topography_class", dropna=True):
            per_class[str(cls)] = _fit_block(grp)

    calib = {
        "calibration_version": args.calibration_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_form": "PL_db = alpha + 10 * n * log10(distance_m); RSSI = EIRP - PL",
        "eirp_dbm": EIRP_DBM,
        "frequency_mhz": args.freq_mhz,
        "geology_terrain_note": args.geology_note,
        "observable": "ESP (RSSI+SNR) where available, else RSSI; calibration-eligible rows only",
        "provenance": {
            "source_predictions": str(pred_path.relative_to(ROOT)) if pred_path.is_relative_to(ROOT) else str(pred_path),
            "trial_id": prov.get("run_id"),
            "git_commit": prov.get("git_commit"),
            "baseline_predictor": prov.get("baseline_predictor"),
        },
        "global_fit": _fit_block(df),
        "per_terrain_class": per_class,
        "validity": {
            "applies_to": "915 MHz LoRa, Presidential Range terrain classes only",
            "do_not_extrapolate": "outside per-class distance_range_m or to other frequencies/regions",
            "min_samples_per_fit": MIN_CLASS_SAMPLES,
        },
    }

    out_path = ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(calib, sort_keys=False))
    print(yaml.safe_dump(calib, sort_keys=False))
    g = calib["global_fit"]
    if g.get("status") != "fitted":
        print(f"NOTE: global fit {g.get('status')} (n={g.get('n_samples')}). "
              "Expected with Trial 1 — emit again from Trial 2 calibration-grade data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

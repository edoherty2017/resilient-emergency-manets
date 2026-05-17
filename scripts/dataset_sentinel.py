#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_FIELDS = ["timestamp_utc", "trial_id", "node_id", "head_id"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return pd.DataFrame(rows)
    raise SystemExit(f"unsupported input type: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Dataset sentinel: validate, score, quarantine, and gate telemetry/prediction data")
    ap.add_argument("--input", default="artifacts/dem/geology_loss_features.parquet")
    ap.add_argument("--out-dir", default="artifacts/qa")
    ap.add_argument("--max-abs-rssi", type=float, default=200.0)
    ap.add_argument("--min-accepted-pct", type=float, default=85.0)
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_any(in_path)
    if df.empty:
        raise SystemExit("input dataframe is empty")

    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")

    # Missing required fields
    missing_required = []
    for f in REQUIRED_FIELDS:
        if f not in df.columns:
            df[f] = pd.NA
        missing_required.append(df[f].isna())
    missing_required_mask = np.logical_or.reduce(missing_required) if missing_required else np.zeros(len(df), dtype=bool)

    # Range checks
    rssi = pd.to_numeric(df.get("rssi_dbm"), errors="coerce") if "rssi_dbm" in df.columns else pd.Series([np.nan] * len(df))
    lat = pd.to_numeric(df.get("lat"), errors="coerce") if "lat" in df.columns else pd.Series([np.nan] * len(df))
    lon = pd.to_numeric(df.get("lon"), errors="coerce") if "lon" in df.columns else pd.Series([np.nan] * len(df))
    snr = pd.to_numeric(df.get("snr_db"), errors="coerce") if "snr_db" in df.columns else pd.Series([np.nan] * len(df))

    bad_rssi = rssi.notna() & (rssi.abs() > float(args.max_abs_rssi))
    bad_lat = lat.notna() & ((lat < -90) | (lat > 90))
    bad_lon = lon.notna() & ((lon < -180) | (lon > 180))
    bad_snr = snr.notna() & ((snr < -40) | (snr > 40))

    # Light anomaly detector: large jumps in RSSI/Elevation
    elev = pd.to_numeric(df.get("dem_elev_m"), errors="coerce") if "dem_elev_m" in df.columns else pd.Series([np.nan] * len(df))
    rssi_jump = rssi.diff().abs() > 25
    elev_jump = elev.diff().abs() > 120
    anomaly = rssi_jump.fillna(False) | elev_jump.fillna(False)

    # Quality tiering
    reject = missing_required_mask | bad_rssi | bad_lat | bad_lon | bad_snr
    low = (~reject) & anomaly

    # medium/high split based on missing non-critical fields
    optional_sparse = pd.Series(False, index=df.index)
    for f in ["rssi_dbm", "snr_db", "lat", "lon", "dem_elev_m", "expected_loss_db"]:
        if f in df.columns:
            optional_sparse = optional_sparse | df[f].isna()

    medium = (~reject) & (~low) & optional_sparse
    high = (~reject) & (~low) & (~medium)

    tier = np.where(reject, "reject", np.where(low, "low", np.where(medium, "medium", "high")))
    df["quality_tier"] = tier
    df["anomaly_flag"] = anomaly.fillna(False)
    df["reject_reason_missing_required"] = missing_required_mask
    df["reject_reason_bad_rssi"] = bad_rssi
    df["reject_reason_bad_lat"] = bad_lat
    df["reject_reason_bad_lon"] = bad_lon
    df["reject_reason_bad_snr"] = bad_snr

    scored_parquet = out_dir / "sentinel_scored.parquet"
    scored_csv = out_dir / "sentinel_scored.csv"
    quarantine_csv = out_dir / "quarantine_reject_rows.csv"

    df.to_parquet(scored_parquet, index=False)
    df.to_csv(scored_csv, index=False)
    df[df["quality_tier"] == "reject"].to_csv(quarantine_csv, index=False)

    counts = df["quality_tier"].value_counts(dropna=False).to_dict()
    accepted = int(counts.get("high", 0) + counts.get("medium", 0))
    total = int(len(df))
    accepted_pct = (accepted / total * 100.0) if total else 0.0

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(in_path),
        "rows_total": total,
        "quality_counts": counts,
        "accepted_rows": accepted,
        "accepted_pct": accepted_pct,
        "anomaly_rows": int(df["anomaly_flag"].sum()),
        "outputs": {
            "scored_parquet": str(scored_parquet),
            "scored_csv": str(scored_csv),
            "quarantine_csv": str(quarantine_csv),
        },
    }

    decision = {
        "status": "PASS" if accepted_pct >= float(args.min_accepted_pct) else "FAIL",
        "rule": f"accepted_pct >= {float(args.min_accepted_pct):.2f}",
        "accepted_pct": accepted_pct,
        "rows_total": total,
    }

    reproducibility = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": os.getcwd(),
        "input_sha256": {str(in_path): sha256(in_path)},
        "output_sha256": {
            str(scored_parquet): sha256(scored_parquet),
            str(scored_csv): sha256(scored_csv),
            str(quarantine_csv): sha256(quarantine_csv),
        },
        "parameters": {
            "max_abs_rssi": float(args.max_abs_rssi),
            "min_accepted_pct": float(args.min_accepted_pct),
        },
    }

    (out_dir / "sentinel_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "sentinel_decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    (out_dir / "sentinel_reproducibility.json").write_text(json.dumps(reproducibility, indent=2), encoding="utf-8")

    print(json.dumps({"summary": summary, "decision": decision}, indent=2))
    return 0 if decision["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

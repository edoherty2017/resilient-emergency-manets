#!/usr/bin/env python3
"""Package the empirical RF dataset as a standardized, versioned release.

Proposal deliverable #2 ("The 'Presidential Range' Empirical RF Dataset"). Reads
the calibrated predictions parquet, selects the analysis-grade columns, and emits
a self-describing release bundle: CSV + JSON Lines + a data dictionary + a
manifest with schema version, provenance, row counts, and SHA-256 hashes.

Two tiers are exported and counted separately:
  - all_observations: every joined RF observation (engineering/QA view)
  - calibration_grade: rows that passed the eligibility gate (GPS both ends,
    verified direct link, plausible power) — the only rows valid for path-loss
    calibration claims.

Usage:
  python3 scripts/build_dataset_release.py \
      --predictions artifacts/airmap/live_trial/predictions_postcalibration.parquet \
      --trial-id trial-live --release-version v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# (column, unit, description) — the published dataset contract. Columns absent in
# the source are written as null so the schema is stable across trials.
RELEASE_COLUMNS = [
    ("timestamp_utc", "ISO-8601 UTC", "Observation timestamp"),
    ("trial_id", "id", "Trial/run grouping"),
    ("node_id", "id", "Receiving node"),
    ("head_id", "id", "Head aggregation target"),
    ("from_mesh_id", "id", "Source mesh node of the packet"),
    ("segment_id", "id", "Deterministic per-row segment key"),
    ("lat", "deg", "HEAD latitude (decimal degrees)"),
    ("lon", "deg", "HEAD longitude (decimal degrees)"),
    ("src_lat", "deg", "Source node latitude"),
    ("src_lon", "deg", "Source node longitude"),
    ("distance_m", "m", "3D slant link distance (source→head)"),
    ("distance_source", "enum", "How distance was derived (source_to_head_gps is calibration-grade)"),
    ("hops_away", "count", "Mesh relay hops (0 = direct link)"),
    ("rssi_dbm", "dBm", "Received signal strength (last hop)"),
    ("snr_db", "dB", "Signal-to-noise ratio"),
    ("obs_esp_dbm", "dBm", "Effective signal power = RSSI+SNR−10log10(1+10^(SNR/10))"),
    ("obs_target_dbm", "dBm", "Calibration observable (ESP when available, else RSSI)"),
    ("obs_target_source", "enum", "Which metric obs_target_dbm came from"),
    ("pred_path_loss_fspl_db", "dB", "Free-space path loss baseline"),
    ("pred_path_loss_itm_db", "dB", "Longley-Rice ITM path loss over real DEM (when computed)"),
    ("pred_rssi_dbm", "dBm", "Predicted RSSI from the selected baseline model"),
    ("predictor", "enum", "Baseline predictor used (fspl|itm)"),
    ("topography_class", "enum", "alpine_ridge | sub_alpine | valley_forest"),
    ("distance_bin", "enum", "Distance stratum"),
    ("weather_tag", "enum", "Weather state (from weather feed or field log)"),
    ("satellite_link_status", "enum", "Starlink link state when available"),
    ("time_bin", "enum", "Local-time bin (America/New_York)"),
    ("calibration_eligible", "bool", "Passed the calibration eligibility gate"),
    ("src_pos_staleness_s", "s", "Age of the source position fix used for distance"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description="Package the empirical RF dataset release")
    ap.add_argument("--predictions", default="artifacts/airmap/live_trial/predictions_postcalibration.parquet")
    ap.add_argument("--provenance", default="artifacts/airmap/live_trial/provenance.json")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--release-version", default="v1")
    ap.add_argument("--out-dir", default="artifacts/dataset_release")
    ap.add_argument("--min-rows", type=int, default=0,
                    help="Fail if fewer than this many calibration-grade rows (proposal target: 2500)")
    args = ap.parse_args()

    pred_path = ROOT / args.predictions if not Path(args.predictions).is_absolute() else Path(args.predictions)
    if not pred_path.exists():
        raise SystemExit(f"predictions parquet not found: {pred_path}\n"
                         "Run scripts/airmap_live_trial.py first.")

    df = pd.read_parquet(pred_path)
    for col, _, _ in RELEASE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    rel = df[[c for c, _, _ in RELEASE_COLUMNS]].copy()

    elig = rel[rel["calibration_eligible"].fillna(False).astype(bool)].copy()

    out_dir = ROOT / args.out_dir / args.release_version
    out_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    all_csv = out_dir / "rf_dataset_all.csv"
    all_jsonl = out_dir / "rf_dataset_all.jsonl"
    grade_csv = out_dir / "rf_dataset_calibration_grade.csv"
    rel.to_csv(all_csv, index=False)
    rel.to_json(all_jsonl, orient="records", lines=True, date_format="iso")
    elig.to_csv(grade_csv, index=False)
    for p in (all_csv, all_jsonl, grade_csv):
        files[str(p.relative_to(ROOT))] = {"rows": int(len(rel if "all" in p.name else elig)),
                                            "sha256": sha256(p)}

    data_dict = out_dir / "DATA_DICTIONARY.md"
    dd_lines = [
        f"# RF Dataset Release {args.release_version} — Data Dictionary",
        "",
        "| Column | Unit | Description |",
        "|---|---|---|",
        *[f"| `{c}` | {u} | {d} |" for c, u, d in RELEASE_COLUMNS],
        "",
        "**Tiers:** `rf_dataset_all.*` is every joined observation (QA view). "
        "`rf_dataset_calibration_grade.csv` is the subset with "
        "`calibration_eligible == true` — the only rows valid for path-loss "
        "calibration. Use the latter for any modeling claim.",
    ]
    data_dict.write_text("\n".join(dd_lines))
    files[str(data_dict.relative_to(ROOT))] = {"sha256": sha256(data_dict)}

    prov = {}
    prov_path = ROOT / args.provenance if not Path(args.provenance).is_absolute() else Path(args.provenance)
    if prov_path.exists():
        prov = json.loads(prov_path.read_text())

    manifest = {
        "release_version": args.release_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "trial_id": args.trial_id,
        "source_predictions": str(pred_path.relative_to(ROOT)) if pred_path.is_relative_to(ROOT) else str(pred_path),
        "schema_version": 2,
        "row_counts": {
            "all_observations": int(len(rel)),
            "calibration_grade": int(len(elig)),
            "proposal_target_calibration_grade": 2500,
        },
        "pipeline_provenance": {
            k: prov.get(k) for k in (
                "model_name", "model_version", "model_hash", "calibration_version",
                "baseline_predictor", "feature_recipe_version", "git_commit",
            )
        },
        "files": files,
        "columns": [{"name": c, "unit": u, "description": d} for c, u, d in RELEASE_COLUMNS],
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))

    print(json.dumps({
        "release": str(out_dir.relative_to(ROOT)),
        "all_observations": len(rel),
        "calibration_grade": len(elig),
        "files": list(files),
    }, indent=2))

    if len(elig) < args.min_rows:
        raise SystemExit(
            f"calibration-grade rows {len(elig)} < required {args.min_rows} "
            "(Trial 1 has none; this is expected until Trial 2 controlled-link data)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

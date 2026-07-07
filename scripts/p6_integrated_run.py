#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> dict:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return {
        "cmd": cmd,
        "exit_code": p.returncode,
        "stdout": p.stdout[-12000:],
        "stderr": p.stderr[-12000:],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="P6 integrated dry-run/live-trial evidence runner")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--skip-schema-validation", action="store_true",
                    help="Skip schema validation gate (not recommended)")
    args = ap.parse_args()

    root = Path(args.root)
    out_dir = root / "artifacts/release"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Schema validation gate — hard-fail before running expensive pipeline steps.
    if not args.skip_schema_validation:
        ingest_root = Path(args.ingest_root)
        node_jsonls = {
            "meshradiohead2": ingest_root / "meshradiohead2" / "jsonl" / "telemetry_stream.jsonl",
        }
        validator = root / "scripts" / "validation" / "schema_validate.py"
        schema_ok = True
        for node_id, jsonl_path in node_jsonls.items():
            report_path = root / "artifacts" / "reports" / f"schema_validation_{node_id}.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            if not jsonl_path.exists():
                print(f"[schema_gate] WARN: {node_id} JSONL not found at {jsonl_path} — skipping")
                continue
            result = run(
                ["python3", str(validator), "--input", str(jsonl_path), "--output", str(report_path)],
                root,
            )
            if result["exit_code"] != 0:
                print(f"[schema_gate] FAIL: {node_id} has invalid records — aborting p6 run")
                schema_ok = False
        if not schema_ok:
            (out_dir / "p6_artifact_index.json").write_text(
                json.dumps({
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "trial_id": args.trial_id,
                    "gates": {"overall_ok": False, "schema_validation_ok": False},
                    "error": "schema_validation_failed",
                }, indent=2),
                encoding="utf-8",
            )
            return 1
        print("[schema_gate] PASS: all available JSONL files are schema-valid")

    steps = [
        ["python3", "scripts/airmap_dry_run.py"],
        [
            "python3",
            "scripts/airmap_live_trial.py",
            "--ingest-root",
            args.ingest_root,
            "--trial-id",
            args.trial_id,
            "--node-id",
            "meshradiohead2",
            "--head-id",
            "meshradiohead2",
            "--min-observed-samples",
            "200",
        ],
        ["python3", "scripts/dem_transformer.py", "--ingest-root", args.ingest_root, "--trial-id", args.trial_id],
        ["python3", "scripts/geology_loss.py"],
        [
            "python3",
            "scripts/dataset_sentinel.py",
            "--input",
            "artifacts/airmap/live_trial/predictions_postcalibration.parquet",
            "--out-dir",
            "artifacts/qa",
            "--min-accepted-pct",
            "70",
        ],
        [
            "python3",
            "scripts/error_quantifier.py",
            "--input",
            "artifacts/qa/sentinel_scored.parquet",
            "--out-dir",
            "artifacts/eval",
            "--min-samples",
            "200",
            # Falsifiable gate: a 60 dB RMSE threshold could be passed by predicting
            # the mean; 12 dB reflects a usable model (literature sigma 6-8 dB).
            "--max-rmse-db",
            "12",
        ],
        ["python3", "scripts/weather_guard.py", "--telemetry", "artifacts/qa/sentinel_scored.parquet", "--out-dir", "artifacts/weather"],
        [
            "python3",
            "scripts/coverage_overlay_mvp.py",
            "--ingest-root",
            args.ingest_root,
            "--node-id",
            "meshradiohead2",
            "--trial-id",
            args.trial_id,
            "--live-trial-dir",
            "artifacts/airmap/live_trial",
        ],
        ["python3", "scripts/build_evidence_index.py"],
    ]

    runlog = []
    for cmd in steps:
        runlog.append(run(cmd, root))

    (out_dir / "p6_runlog.json").write_text(json.dumps(runlog, indent=2), encoding="utf-8")

    # Build artifact index
    artifact_globs = [
        "artifacts/airmap/**/*",
        "artifacts/dem/**/*",
        "artifacts/itm/**/*",
        "artifacts/qa/**/*",
        "artifacts/eval/**/*",
        "artifacts/weather/**/*",
        "artifacts/overlay/**/*",
        "artifacts/reports/**/*",
        "artifacts/release/**/*",
    ]

    files = []
    for g in artifact_globs:
        for p in root.glob(g):
            if p.is_file():
                files.append(str(p.relative_to(root)))

    gates = {
        "schema_validation_ok": not args.skip_schema_validation,
        "dry_run_ok": any(r["cmd"][:2] == ["python3", "scripts/airmap_dry_run.py"] and r["exit_code"] == 0 for r in runlog),
        "live_trial_ok": any(r["cmd"][:2] == ["python3", "scripts/airmap_live_trial.py"] and r["exit_code"] == 0 for r in runlog),
        "dem_ok": any(r["cmd"][:2] == ["python3", "scripts/dem_transformer.py"] and r["exit_code"] == 0 for r in runlog),
        "geology_ok": any(r["cmd"][:2] == ["python3", "scripts/geology_loss.py"] and r["exit_code"] == 0 for r in runlog),
        "sentinel_ok": any(r["cmd"][:2] == ["python3", "scripts/dataset_sentinel.py"] and r["exit_code"] == 0 for r in runlog),
        "eval_ok": any(r["cmd"][:2] == ["python3", "scripts/error_quantifier.py"] and r["exit_code"] == 0 for r in runlog),
        "weather_ok": any(r["cmd"][:2] == ["python3", "scripts/weather_guard.py"] and r["exit_code"] == 0 for r in runlog),
        "overlay_ok": any(r["cmd"][:2] == ["python3", "scripts/coverage_overlay_mvp.py"] and r["exit_code"] == 0 for r in runlog),
        "evidence_index_ok": any(r["cmd"][:2] == ["python3", "scripts/build_evidence_index.py"] and r["exit_code"] == 0 for r in runlog),
    }
    gates["overall_ok"] = all(gates.values())

    index = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "trial_id": args.trial_id,
        "gates": gates,
        "runlog": "artifacts/release/p6_runlog.json",
        "artifact_count": len(files),
        "artifacts": sorted(files),
    }

    (out_dir / "p6_artifact_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(json.dumps(index, indent=2))
    return 0 if gates["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

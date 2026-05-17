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
    args = ap.parse_args()

    root = Path(args.root)
    out_dir = root / "artifacts/release"
    out_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        ["python3", "scripts/airmap_dry_run.py"],
        [
            "python3",
            "scripts/airmap_live_trial.py",
            "--ingest-root",
            args.ingest_root,
            "--trial-id",
            args.trial_id,
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
            "--max-rmse-db",
            "60",
        ],
        ["python3", "scripts/weather_guard.py", "--telemetry", "artifacts/qa/sentinel_scored.parquet", "--out-dir", "artifacts/weather"],
        [
            "python3",
            "scripts/coverage_overlay_mvp.py",
            "--ingest-root",
            args.ingest_root,
            "--trial-id",
            args.trial_id,
            "--live-trial-dir",
            "artifacts/airmap/live_trial",
        ],
    ]

    runlog = []
    for cmd in steps:
        runlog.append(run(cmd, root))

    (out_dir / "p6_runlog.json").write_text(json.dumps(runlog, indent=2), encoding="utf-8")

    # Build artifact index
    artifact_globs = [
        "artifacts/airmap/**/*",
        "artifacts/dem/**/*",
        "artifacts/qa/**/*",
        "artifacts/eval/**/*",
        "artifacts/weather/**/*",
        "artifacts/overlay/**/*",
        "artifacts/reports/**/*",
    ]

    files = []
    for g in artifact_globs:
        for p in root.glob(g):
            if p.is_file():
                files.append(str(p.relative_to(root)))

    gates = {
        "dry_run_ok": any(r["cmd"][:2] == ["python3", "scripts/airmap_dry_run.py"] and r["exit_code"] == 0 for r in runlog),
        "live_trial_ok": any(r["cmd"][:2] == ["python3", "scripts/airmap_live_trial.py"] and r["exit_code"] == 0 for r in runlog),
        "dem_ok": any(r["cmd"][:2] == ["python3", "scripts/dem_transformer.py"] and r["exit_code"] == 0 for r in runlog),
        "geology_ok": any(r["cmd"][:2] == ["python3", "scripts/geology_loss.py"] and r["exit_code"] == 0 for r in runlog),
        "sentinel_ok": any(r["cmd"][:2] == ["python3", "scripts/dataset_sentinel.py"] and r["exit_code"] == 0 for r in runlog),
        "eval_ok": any(r["cmd"][:2] == ["python3", "scripts/error_quantifier.py"] and r["exit_code"] == 0 for r in runlog),
        "weather_ok": any(r["cmd"][:2] == ["python3", "scripts/weather_guard.py"] and r["exit_code"] == 0 for r in runlog),
        "overlay_ok": any(r["cmd"][:2] == ["python3", "scripts/coverage_overlay_mvp.py"] and r["exit_code"] == 0 for r in runlog),
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

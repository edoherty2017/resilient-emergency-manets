#!/usr/bin/env python3
"""Build advisor-ready evidence index from current pipeline artifacts.

Reads from artifacts/ and emits:
  artifacts/release/evidence_index.json   — machine-readable full index
  artifacts/release/evidence_summary.md   — human-readable Markdown for advisor

Usage:
  python3 scripts/build_evidence_index.py
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root).decode().strip()
    except Exception:
        return "unknown"


def _file_entry(rel: str) -> dict:
    p = ROOT / rel
    return {"path": rel, "exists": p.exists(), "size_bytes": p.stat().st_size if p.exists() else 0}


def main() -> int:
    out_dir = ROOT / "artifacts/release"
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    git = _git_commit(ROOT)

    # ── Load gate summaries ──────────────────────────────────────────────────
    schema_rep  = _read_json(ROOT / "artifacts/reports/schema_validation_meshradiohead2.json")
    quality_g   = _read_json(ROOT / "artifacts/airmap/live_trial/quality_gates.json")
    metrics_g   = _read_json(ROOT / "artifacts/airmap/live_trial/metrics_global.json")
    cal         = _read_json(ROOT / "artifacts/airmap/live_trial/calibration_deltas.json")
    join_q      = _read_json(ROOT / "artifacts/airmap/live_trial/join_quality.json")
    provenance  = _read_json(ROOT / "artifacts/airmap/live_trial/provenance.json")
    sentinel_d  = _read_json(ROOT / "artifacts/qa/sentinel_decision.json")
    sentinel_s  = _read_json(ROOT / "artifacts/qa/sentinel_summary.json")
    eval_d      = _read_json(ROOT / "artifacts/eval/eval_decision.json")
    eval_m      = _read_json(ROOT / "artifacts/eval/metrics_global.json")
    weather_s   = _read_json(ROOT / "artifacts/weather/weather_guard_status.json")
    overlay_s   = _read_json(ROOT / "artifacts/overlay/overlay_summary.json")
    transition  = _read_json(ROOT / "artifacts/overlay/transition_window_summary.json")
    p6_idx      = _read_json(ROOT / "artifacts/release/p6_artifact_index.json")

    pipeline = [
        {
            "step": "schema_validation",
            "script": "scripts/validation/schema_validate.py",
            "inputs": ["(live JSONL from meshradiohead2 via rsync)"],
            "outputs": [_file_entry("artifacts/reports/schema_validation_meshradiohead2.json")],
            "gate": "PASS" if schema_rep.get("ok") else "FAIL",
            "key_metrics": {
                "total_records": schema_rep.get("total_records"),
                "data_invalid_records": schema_rep.get("data_invalid_records", schema_rep.get("invalid_records", 0)),
                "parse_error_records": schema_rep.get("parse_error_records", 0),
                "pass_rate": schema_rep.get("pass_rate"),
            },
        },
        {
            "step": "airmap_live_trial",
            "script": "scripts/airmap_live_trial.py",
            "inputs": [
                "/tmp/manet_ingest/meshradiohead2/jsonl/telemetry_stream.jsonl",
                "config/airmap/model-baseline.yaml",
                "config/airmap/calibration-and-eval.yaml",
            ],
            "outputs": [
                _file_entry("artifacts/airmap/live_trial/predictions_postcalibration.parquet"),
                _file_entry("artifacts/airmap/live_trial/predictions_precalibration.parquet"),
                _file_entry("artifacts/airmap/live_trial/metrics_global.json"),
                _file_entry("artifacts/airmap/live_trial/metrics_stratified.csv"),
                _file_entry("artifacts/airmap/live_trial/satellite_timebin_metrics.csv"),
                _file_entry("artifacts/airmap/live_trial/satellite_outage_events.csv"),
                _file_entry("artifacts/airmap/live_trial/provenance.json"),
            ],
            "gate": "PASS" if quality_g.get("passed") else "FAIL",
            "key_metrics": {
                "rows_total": metrics_g.get("n") and join_q.get("matched_count") and (
                    join_q["matched_count"] + join_q.get("missing_observation_metric_count", 0)
                ),
                "rows_with_rssi": metrics_g.get("n"),
                "metric_source": metrics_g.get("metric_target"),
                "mae_db": metrics_g.get("mae"),
                "rmse_db": metrics_g.get("rmse"),
                "residual_bias_db": cal.get("residual_bias_db"),
                "join_matched_pct": join_q.get("matched_pct"),
                "model_name": provenance.get("model_name"),
                "model_version": provenance.get("model_version"),
                "calibration_version": provenance.get("calibration_version"),
                "warnings": quality_g.get("warnings", []),
            },
        },
        {
            "step": "dataset_sentinel",
            "script": "scripts/dataset_sentinel.py",
            "inputs": ["artifacts/airmap/live_trial/predictions_postcalibration.parquet"],
            "outputs": [
                _file_entry("artifacts/qa/sentinel_scored.parquet"),
                _file_entry("artifacts/qa/sentinel_decision.json"),
                _file_entry("artifacts/qa/quarantine_reject_rows.csv"),
            ],
            "gate": sentinel_d.get("status", "UNKNOWN"),
            "key_metrics": {
                "rows_total": sentinel_s.get("rows_total"),
                "accepted_rows": sentinel_s.get("accepted_rows"),
                "accepted_pct": sentinel_s.get("accepted_pct"),
                "anomaly_rows": sentinel_s.get("anomaly_rows"),
                "quality_counts": sentinel_s.get("quality_counts"),
            },
        },
        {
            "step": "error_quantifier",
            "script": "scripts/error_quantifier.py",
            "inputs": ["artifacts/qa/sentinel_scored.parquet"],
            "outputs": [
                _file_entry("artifacts/eval/metrics_global.json"),
                _file_entry("artifacts/eval/metrics_stratified.csv"),
                _file_entry("artifacts/eval/eval_decision.json"),
                _file_entry("artifacts/eval/outlier_points.geojson"),
            ],
            "gate": eval_d.get("status", "UNKNOWN"),
            "key_metrics": {
                "n": eval_m.get("n"),
                "mae_db": eval_m.get("mae"),
                "rmse_db": eval_m.get("rmse"),
                "max_rmse_threshold_db": eval_d.get("rules", {}).get("max_rmse_db"),
            },
        },
        {
            "step": "weather_guard",
            "script": "scripts/weather_guard.py",
            "inputs": ["artifacts/qa/sentinel_scored.parquet"],
            "outputs": [
                _file_entry("artifacts/weather/weather_guard_status.json"),
                _file_entry("artifacts/weather/weather_guard_audit.json"),
            ],
            "gate": "PASS" if weather_s.get("risk_state") == "normal" else "HOLD",
            "key_metrics": {
                "risk_state": weather_s.get("risk_state"),
                "recommendation": weather_s.get("recommendation"),
            },
        },
        {
            "step": "coverage_overlay",
            "script": "scripts/coverage_overlay_mvp.py",
            "inputs": [
                "/tmp/manet_ingest/meshradiohead2/jsonl/telemetry_stream.jsonl",
                "/tmp/manet_ingest/meshradiohead2/connectivity_events.jsonl",
                "artifacts/airmap/live_trial/predictions_postcalibration.parquet",
            ],
            "outputs": [
                _file_entry("artifacts/overlay/coverage_overlay.html"),
                _file_entry("artifacts/overlay/coverage_timeline.csv"),
                _file_entry("artifacts/overlay/transition_window_summary.json"),
                _file_entry("artifacts/overlay/overlay_summary.json"),
            ],
            "gate": "PASS" if overlay_s.get("gps_gate_passed") and overlay_s.get("transition_window_pass") else "WARN",
            "key_metrics": {
                "rows_total": overlay_s.get("rows_total"),
                "rows_with_gps": overlay_s.get("rows_with_gps"),
                "coverage_mode_counts": overlay_s.get("coverage_mode_counts"),
                "control_plane_mode_counts": overlay_s.get("control_plane_mode_counts"),
                "transition_window_pass": overlay_s.get("transition_window_pass"),
                "mesh_only_coverage_pct": transition.get("MESH_ONLY", {}).get("coverage_pct"),
            },
        },
    ]

    known_limitations = [
        "rsrp_dbm is null for all records — pipeline runs on rssi_dbm fallback and labels it in all artifacts.",
        "GNSS fix rate is low (1143/64001 rows = 1.8%) — location-stratified analysis uses synthetic route interpolation.",
        "Starlink data covers only the last ~2.5h of a 4-day collection window (106 connected rows); density will grow with each session.",
        "meshnode1 (hiker node) is offline (SD card fault, being reflashed) — all data is single-node; multi-hop propagation analysis pending.",
        "Weather guard uses synthetic defaults (no live weather feed wired yet).",
    ]

    # Compute overall_gate from individual step results (p6_artifact_index.json is
    # not yet written when this script runs as the last p6 step — reading it would
    # see the previous run's state).
    step_gates = [s["gate"] for s in pipeline]
    overall_gate = "PASS" if all(g == "PASS" for g in step_gates) else "FAIL"

    index = {
        "generated_at_utc": now.isoformat(),
        "git_commit": git,
        "overall_gate": overall_gate,
        "trial_id": "trial-live",
        "node_id": "meshradiohead2",
        "pipeline": pipeline,
        "known_limitations": known_limitations,
        "artifact_count": p6_idx.get("artifact_count"),
        "p6_artifact_index": "artifacts/release/p6_artifact_index.json",
    }

    (out_dir / "evidence_index.json").write_text(json.dumps(index, indent=2))

    # ── Markdown summary ─────────────────────────────────────────────────────
    def gate_badge(g: str) -> str:
        return {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARN": "⚠️ WARN", "HOLD": "⚠️ HOLD"}.get(g, g)

    lines = [
        f"# MANET Evidence Index — trial-live",
        f"",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Git commit:** `{git}`  ",
        f"**Node:** `meshradiohead2`  ",
        f"**Overall gate:** {gate_badge(overall_gate)}",
        f"",
        f"---",
        f"",
        f"## Pipeline Steps",
        f"",
        f"| Step | Script | Gate | Key Metrics |",
        f"|---|---|---|---|",
    ]

    for s in pipeline:
        km = s["key_metrics"]
        if s["step"] == "schema_validation":
            kstr = (f"{km['total_records']} rows, {km['data_invalid_records']} data-invalid, "
                    f"{km['parse_error_records']} parse-errors, {km['pass_rate']:.1%} pass")
        elif s["step"] == "airmap_live_trial":
            kstr = f"n={km['rows_with_rssi']}, RMSE={km['rmse_db']:.1f} dB, MAE={km['mae_db']:.1f} dB ({km['metric_source']})"
        elif s["step"] == "dataset_sentinel":
            kstr = f"{km['accepted_pct']:.1f}% accepted, {km['anomaly_rows']} anomalies"
        elif s["step"] == "error_quantifier":
            kstr = f"n={km['n']}, RMSE={km['rmse_db']:.1f} dB (threshold {km['max_rmse_threshold_db']} dB)"
        elif s["step"] == "weather_guard":
            kstr = f"{km['risk_state']} → {km['recommendation']}"
        elif s["step"] == "coverage_overlay":
            m = km.get("coverage_mode_counts", {})
            kstr = f"GPS rows={km['rows_with_gps']}, MESH={m.get('MESH',0)}, SAT={m.get('SATELLITE',0)}, NONE={m.get('NONE',0)}"
        else:
            kstr = ""
        lines.append(f"| {s['step']} | `{s['script']}` | {gate_badge(s['gate'])} | {kstr} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## RF Model Performance",
        f"",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Samples (rssi_dbm) | {metrics_g.get('n', '?')} |",
        f"| MAE | {metrics_g.get('mae', 0):.2f} dB |",
        f"| RMSE | {metrics_g.get('rmse', 0):.2f} dB |",
        f"| Residual bias (post-calibration) | {cal.get('residual_bias_db', 0):.3f} dB |",
        f"| Sentinel accepted | {sentinel_s.get('accepted_pct', 0):.2f}% |",
        f"| Join match rate | {join_q.get('matched_pct', 0):.1f}% |",
        f"",
        f"**Metric:** FSPL baseline with residual calibration, rssi\\_dbm fallback (rsrp\\_dbm unavailable in current LoRa-first path).",
        f"",
        f"---",
        f"",
        f"## Connectivity Coverage (Transition Windows)",
        f"",
        f"| Control-Plane Mode | Rows | Covered | Coverage % | Pass |",
        f"|---|---|---|---|---|",
    ]

    for mode in ["IP_FULL", "IP_DEGRADED", "MESH_ONLY"]:
        t = transition.get(mode, {})
        n = t.get("n_rows", 0)
        cov = t.get("covered_rows", 0)
        pct = t.get("coverage_pct", 0.0)
        p = "✅" if t.get("pass", True) else "❌"
        lines.append(f"| {mode} | {n} | {cov} | {pct:.1f}% | {p} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Known Limitations",
        f"",
    ]
    for lim in known_limitations:
        lines.append(f"- {lim}")

    lines += [
        f"",
        f"---",
        f"",
        f"## Artifacts",
        f"",
        f"Full artifact index: `artifacts/release/p6_artifact_index.json` ({p6_idx.get('artifact_count', '?')} files)  ",
        f"Interactive coverage map: `artifacts/overlay/coverage_overlay.html`  ",
        f"Outlier GeoJSON: `artifacts/eval/outlier_points.geojson`  ",
        f"Provenance: `artifacts/airmap/live_trial/provenance.json`  ",
        f"",
    ]

    md = "\n".join(lines)
    (out_dir / "evidence_summary.md").write_text(md)

    print(f"evidence_index.json  → {out_dir/'evidence_index.json'}")
    print(f"evidence_summary.md  → {out_dir/'evidence_summary.md'}")
    print(f"overall_gate: {overall_gate}")
    return 0 if overall_gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

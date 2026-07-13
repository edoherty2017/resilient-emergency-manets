#!/usr/bin/env python3
"""Build advisor-ready evidence index from current pipeline artifacts.

Reads from artifacts/ and emits:
  artifacts/release/evidence_index.json   — machine-readable full index
  artifacts/release/evidence_summary.md   — human-readable Markdown for advisor

Usage:
  python3 scripts/build_evidence_index.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ_ERRORS: dict[str, str] = {}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
        if not isinstance(value, dict):
            raise ValueError("top-level JSON value is not an object")
        return value
    except Exception as exc:
        READ_ERRORS[str(path.relative_to(ROOT))] = f"{type(exc).__name__}: {exc}"
        return {}


def _git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    except Exception:
        return "unknown"


def _git_dirty(root: Path) -> bool | None:
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root).decode().strip())
    except Exception:
        return None


def _file_entry(rel: str) -> dict:
    p = ROOT / rel
    return {"path": rel, "exists": p.is_file(), "size_bytes": p.stat().st_size if p.is_file() else 0}


def _fmt(value, spec: str = "", default: str = "—") -> str:
    """None-safe number formatting for the markdown tables."""
    if value is None:
        return default
    try:
        return format(value, spec) if spec else str(value)
    except (ValueError, TypeError):
        return str(value)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    READ_ERRORS.clear()
    out_dir = ROOT / "artifacts/release"
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    git = _git_commit(ROOT)
    git_dirty = _git_dirty(ROOT)

    # ── Load gate summaries ──────────────────────────────────────────────────
    schema_rep  = _read_json(ROOT / "artifacts/reports/schema_validation_meshradiohead2.json")
    schema_rep_node = _read_json(ROOT / "artifacts/reports/schema_validation_meshnode1.json")
    schema_summary = _read_json(ROOT / "artifacts/reports/schema_validation_summary.json")
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
    itm_sum     = _read_json(ROOT / "artifacts/itm/itm_summary.json")
    airtime     = _read_json(ROOT / "artifacts/itm/lora_airtime.json")
    pdr_sum     = _read_json(ROOT / "artifacts/pdr/pdr_summary.json")

    # Calibration-eligible block is the only evidence-grade error number; the
    # top-level mae/rmse in metrics_global is the all-matched shakeout view.
    cal_elig = metrics_g.get("calibration_eligible", {}) if isinstance(metrics_g, dict) else {}
    held_out = (cal.get("blocked_cv") or {}).get("held_out_rmse_db", {}) if cal else {}
    fit = cal.get("floating_intercept") if cal else None
    validator_path = ROOT / "scripts/validation/schema_validate.py"
    validator_sha256 = hashlib.sha256(validator_path.read_bytes()).hexdigest() if validator_path.is_file() else None
    schema_gate_ok = (
        schema_rep.get("ok") is True
        and schema_rep_node.get("ok") is True
        and schema_summary.get("overall_ok") is True
        and schema_summary.get("canonical_validator_sha256") == validator_sha256
    )

    pipeline = [
        {
            "step": "schema_validation",
            "script": "scripts/validation/schema_validate.py",
            "inputs": ["(immutable/synchronized JSONL from meshradiohead2 and meshnode1)"],
            "outputs": [
                _file_entry("artifacts/reports/schema_validation_meshradiohead2.json"),
                _file_entry("artifacts/reports/schema_validation_meshnode1.json"),
                _file_entry("artifacts/reports/schema_validation_summary.json"),
            ],
            "gate": "PASS" if schema_gate_ok else "FAIL",
            "key_metrics": {
                "total_records": schema_rep.get("total_records"),
                "data_invalid_records": schema_rep.get("data_invalid_records", schema_rep.get("invalid_records", 0)),
                "parse_error_records": schema_rep.get("parse_error_records", 0),
                "pass_rate": schema_rep.get("pass_rate"),
                "head_ok": schema_rep.get("ok"),
                "node_ok": schema_rep_node.get("ok"),
                "validator_hash_matches": schema_summary.get("canonical_validator_sha256") == validator_sha256,
            },
        },
        {
            "step": "airmap_live_trial",
            "script": "scripts/airmap_live_trial.py",
            "inputs": [
                "<ingest-root>/meshradiohead2/jsonl/telemetry_stream.jsonl",
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
                "rows_with_metric": metrics_g.get("n"),
                "calibration_eligible_n": cal_elig.get("n"),
                "baseline_predictor": cal.get("baseline_predictor"),
                "calibration_method": cal.get("calibration_method"),
                "path_loss_exponent": (fit or {}).get("path_loss_exponent"),
                "shadowing_sigma_db": (fit or {}).get("sigma_db"),
                "held_out_rmse_db": held_out,
                "eligible_rmse_db": cal_elig.get("rmse"),
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
                "<ingest-root>/meshradiohead2/jsonl/telemetry_stream.jsonl",
                "<ingest-root>/meshradiohead2/connectivity_events.jsonl",
                "artifacts/airmap/live_trial/predictions_postcalibration.parquet",
            ],
            "outputs": [
                _file_entry("artifacts/overlay/coverage_overlay.html"),
                _file_entry("artifacts/overlay/coverage_timeline.csv"),
                _file_entry("artifacts/overlay/transition_window_summary.json"),
                _file_entry("artifacts/overlay/overlay_summary.json"),
            ],
            "gate": "PASS" if overlay_s.get("gps_gate_passed") and overlay_s.get("transition_window_pass") else "FAIL",
            "key_metrics": {
                "rows_total": overlay_s.get("rows_total"),
                "rows_with_gps": overlay_s.get("rows_with_gps"),
                "coverage_mode_counts": overlay_s.get("coverage_mode_counts"),
                "control_plane_mode_counts": overlay_s.get("control_plane_mode_counts"),
                "control_plane_evidence_pct": overlay_s.get("control_plane_evidence_pct"),
                "transition_window_pass": overlay_s.get("transition_window_pass"),
                "mesh_only_coverage_pct": transition.get("MESH_ONLY", {}).get("coverage_pct"),
            },
        },
    ]

    # A stale PASS document is not enough when the artifact it purports to
    # index is absent. Make completeness explicit and fail the affected step.
    for step in pipeline:
        missing_outputs = [entry["path"] for entry in step["outputs"] if not entry["exists"]]
        step["outputs_complete"] = not missing_outputs
        step["missing_outputs"] = missing_outputs
        if missing_outputs:
            step["gate"] = "FAIL"

    # ── Standalone analyses (not part of the per-row pipeline gate) ───────────
    itm_links = itm_sum.get("links", []) if isinstance(itm_sum, dict) else []
    itm_gap = itm_sum.get("gap_segment") if isinstance(itm_sum, dict) else None
    analyses = {
        "itm_terrain_link_analysis": {
            "script": "scripts/itm_relay_links.py (+ dem_3dep.py)",
            "model": itm_sum.get("model"),
            "n_links": len(itm_links),
            "gap_pct_meets_planning_threshold": (itm_gap or {}).get("pct_meets_planning_threshold"),
            "gap_pct_meets_sensitivity": (itm_gap or {}).get("pct_meets_sensitivity"),
            "outputs": [
                _file_entry("artifacts/itm/relay_links_itm.csv"),
                _file_entry("artifacts/itm/gap_segment_itm_coverage.csv"),
                _file_entry("artifacts/itm/itm_summary.json"),
            ],
        },
        "lora_airtime_capacity": {
            "script": "scripts/lora_airtime.py",
            "sos_text_airtime_ms": (airtime.get("airtime_ms") or {}).get("sos_text_~64B"),
            "sos_chain_serial_ms": (airtime.get("sos_chain") or {}).get("serial_airtime_ms"),
            "per_node_utilization_pct": (airtime.get("channel_utilization") or {}).get("per_node_utilization_pct"),
            "outputs": [_file_entry("artifacts/itm/lora_airtime.json")],
        },
        "pdr_controlled_beacon": {
            "script": "scripts/pdr_analysis.py",
            "available": bool(pdr_sum),
            "pdr_overall": pdr_sum.get("pdr_overall"),
            "pdr_overall_wilson95": pdr_sum.get("pdr_overall_wilson95"),
            "note": None if pdr_sum else "no controlled-beacon trial run yet (Trial 2 deliverable)",
            "outputs": [
                _file_entry("artifacts/pdr/pdr_summary.json"),
                _file_entry("artifacts/pdr/pdr_stratified.csv"),
            ],
        },
    }

    known_limitations = [
        "LoRa RSSI/ESP and cellular RSRP are different observables; any fallback or service-layer comparison must remain explicitly labeled.",
        "Historical Trial 1 artifacts reported no calibration-grade rows; regenerate current gates before making a statement about the present dataset.",
        "ITM predictions use a real USGS 3DEP DEM but model terrain diffraction only; vegetation/canopy excess loss is budgeted separately, not modeled.",
        "Cellular, weather, multi-node, GNSS, and controlled-link sufficiency must be established from the current source artifacts, not inherited from earlier snapshots.",
        "The fallback command path has no field-proven deployed remote responder that returns authenticated ACK records.",
        "Runtime storage has a capacity gate but no automatic evidence archival/rotation policy.",
    ]

    # Compute overall_gate from individual step results (p6_artifact_index.json is
    # not yet written when this script runs as the last p6 step — reading it would
    # see the previous run's state).
    step_gates = [s["gate"] for s in pipeline]
    overall_gate = "PASS" if (
        all(g == "PASS" for g in step_gates)
        and not READ_ERRORS
        and git_dirty is False
        and git != "unknown"
    ) else "FAIL"

    index = {
        "generated_at_utc": now.isoformat(),
        "git_commit": git,
        "source_tree_dirty": git_dirty,
        "overall_gate": overall_gate,
        "trial_id": "trial-live",
        "node_id": "meshradiohead2",
        "pipeline": pipeline,
        "standalone_analyses": analyses,
        "known_limitations": known_limitations,
        "input_read_errors": READ_ERRORS,
        "artifact_count": p6_idx.get("artifact_count"),
        "p6_artifact_index": "artifacts/release/p6_artifact_index.json",
    }

    _atomic_write_text(out_dir / "evidence_index.json", json.dumps(index, indent=2, allow_nan=False) + "\n")

    # ── Markdown summary ─────────────────────────────────────────────────────
    def gate_badge(g: str) -> str:
        return {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARN": "⚠️ WARN", "HOLD": "⚠️ HOLD"}.get(g, g)

    lines = [
        f"# MANET Evidence Index — trial-live",
        f"",
        f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Git commit:** `{git}`  ",
        f"**Source tree dirty:** `{git_dirty}`  ",
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
            kstr = (f"{_fmt(km.get('total_records'))} rows, {_fmt(km.get('data_invalid_records'))} data-invalid, "
                    f"{_fmt(km.get('parse_error_records'))} parse-errors, {_fmt(km.get('pass_rate'), '.1%')} pass")
        elif s["step"] == "airmap_live_trial":
            ho = km.get("held_out_rmse_db") or {}
            best = km.get("baseline_predictor") or "fspl"
            kstr = (f"eligible n={_fmt(km.get('calibration_eligible_n'))}, "
                    f"predictor={best}, n̂={_fmt(km.get('path_loss_exponent'), '.2f')}, "
                    f"held-out RMSE itm={_fmt(ho.get('itm'), '.1f')}/fi={_fmt(ho.get('floating_intercept'), '.1f')} dB")
        elif s["step"] == "dataset_sentinel":
            kstr = f"{_fmt(km.get('accepted_pct'), '.1f')}% accepted, {_fmt(km.get('anomaly_rows'))} anomalies"
        elif s["step"] == "error_quantifier":
            kstr = f"n={_fmt(km.get('n'))}, RMSE={_fmt(km.get('rmse_db'), '.1f')} dB (threshold {_fmt(km.get('max_rmse_threshold_db'))} dB)"
        elif s["step"] == "weather_guard":
            kstr = f"{_fmt(km.get('risk_state'))} → {_fmt(km.get('recommendation'))}"
        elif s["step"] == "coverage_overlay":
            m = km.get("coverage_mode_counts") or {}
            kstr = (f"GPS rows={_fmt(km.get('rows_with_gps'))}, MESH={m.get('MESH',0)}, "
                    f"SAT={m.get('SATELLITE',0)}, NONE={m.get('NONE',0)}, "
                    f"control-plane evidence={_fmt(km.get('control_plane_evidence_pct'), '.1f')}%")
        else:
            kstr = ""
        lines.append(f"| {s['step']} | `{s['script']}` | {gate_badge(s['gate'])} | {kstr} |")

    am = analyses["itm_terrain_link_analysis"]
    at = analyses["lora_airtime_capacity"]
    lines += [
        f"",
        f"---",
        f"",
        f"## RF Model Performance (calibration-eligible rows only)",
        f"",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Calibration-eligible samples | {_fmt(cal_elig.get('n'))} |",
        f"| Baseline predictor | {_fmt(cal.get('baseline_predictor'))} |",
        f"| Path-loss exponent n̂ | {_fmt((fit or {}).get('path_loss_exponent'), '.2f')} |",
        f"| Shadowing σ̂ | {_fmt((fit or {}).get('sigma_db'), '.2f')} dB |",
        f"| Held-out RMSE — ITM | {_fmt(held_out.get('itm'), '.2f')} dB |",
        f"| Held-out RMSE — floating-intercept | {_fmt(held_out.get('floating_intercept'), '.2f')} dB |",
        f"| Held-out RMSE — FSPL baseline | {_fmt(held_out.get('fspl'), '.2f')} dB |",
        f"| Join match rate | {_fmt(join_q.get('matched_pct'), '.1f')}% |",
        f"",
        f"**Metric:** ESP (RSSI+SNR) where available; floating-intercept log-distance fit and "
        f"ITM-over-real-DEM compared by contiguous-time blocked cross-validation. No "
        f"calibration-grade rows ⇒ values show as —.",
        f"",
        f"---",
        f"",
        f"## Terrain Link Analysis (ITM / Longley–Rice)",
        f"",
        f"Model: {_fmt(am.get('model'))}  ",
        f"Proposed links evaluated: {_fmt(am.get('n_links'))}  ",
        f"Collector-gap coverage: {_fmt(am.get('gap_pct_meets_planning_threshold'), '.0f')}% above planning "
        f"threshold, {_fmt(am.get('gap_pct_meets_sensitivity'), '.0f')}% above sensitivity  ",
        f"Airtime: SOS text {_fmt(at.get('sos_text_airtime_ms'), '.0f')} ms, 3-hop "
        f"{_fmt(at.get('sos_chain_serial_ms'), '.0f')} ms serial; {_fmt(at.get('per_node_utilization_pct'), '.2f')}% "
        f"channel per beaconing node  ",
        f"Artifacts: `artifacts/itm/relay_links_itm.csv`, `artifacts/itm/itm_summary.json`",
        f"",
        f"---",
        f"",
        f"## Connectivity-Mode Intervals (Receive-Side Indicator Presence)",
        f"",
        f"These rows describe recently observed control-plane intervals and per-record RF/satellite indicators; they are not independent delivery trials.",
        f"",
        f"| Control-Plane Mode | Rows | Covered | Coverage % | 95% Wilson CI | Pass |",
        f"|---|---|---|---|---|---|",
    ]

    for mode in ["IP_FULL", "IP_DEGRADED", "MESH_ONLY"]:
        t = transition.get(mode, {})
        n = t.get("n_rows")
        cov = t.get("covered_rows")
        pct = t.get("coverage_pct")
        ci = t.get("coverage_pct_wilson95")
        ci_str = f"[{ci[0]:.1f}, {ci[1]:.1f}]%" if ci else "—"
        p = "✅" if t.get("pass", False) else "❌"
        lines.append(f"| {mode} | {_fmt(n)} | {_fmt(cov)} | {_fmt(pct, '.1f')}% | {ci_str} | {p} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## Known Limitations",
        f"",
    ]
    for lim in known_limitations:
        lines.append(f"- {lim}")

    if READ_ERRORS:
        lines += [f"", f"## Corrupt JSON Inputs", f""]
        for path, error in sorted(READ_ERRORS.items()):
            lines.append(f"- `{path}`: {error}")

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

    md = "\n".join(lines) + "\n"
    _atomic_write_text(out_dir / "evidence_summary.md", md)

    print(f"evidence_index.json  → {out_dir/'evidence_index.json'}")
    print(f"evidence_summary.md  → {out_dir/'evidence_summary.md'}")
    print(f"overall_gate: {overall_gate}")
    return 0 if overall_gate == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

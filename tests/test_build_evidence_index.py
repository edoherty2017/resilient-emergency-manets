from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_evidence_index.py"
_spec = importlib.util.spec_from_file_location("build_evidence_index", MODULE_PATH)
assert _spec and _spec.loader
build_evidence_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_evidence_index)


def write_json(root: Path, relative: str, value: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def create_passing_fixture(root: Path) -> None:
    validator = root / "scripts/validation/schema_validate.py"
    validator.parent.mkdir(parents=True, exist_ok=True)
    validator.write_text("# canonical validator fixture\n", encoding="utf-8")
    validator_hash = hashlib.sha256(validator.read_bytes()).hexdigest()

    write_json(root, "artifacts/reports/schema_validation_meshradiohead2.json", {"ok": True})
    write_json(root, "artifacts/reports/schema_validation_meshnode1.json", {"ok": True})
    write_json(
        root,
        "artifacts/reports/schema_validation_summary.json",
        {"overall_ok": True, "canonical_validator_sha256": validator_hash},
    )
    write_json(root, "artifacts/airmap/live_trial/quality_gates.json", {"passed": True})
    write_json(root, "artifacts/airmap/live_trial/metrics_global.json", {})
    write_json(root, "artifacts/airmap/live_trial/calibration_deltas.json", {})
    write_json(root, "artifacts/airmap/live_trial/join_quality.json", {})
    write_json(root, "artifacts/airmap/live_trial/provenance.json", {})
    write_json(root, "artifacts/qa/sentinel_decision.json", {"status": "PASS"})
    write_json(root, "artifacts/qa/sentinel_summary.json", {})
    write_json(root, "artifacts/eval/eval_decision.json", {"status": "PASS"})
    write_json(root, "artifacts/eval/metrics_global.json", {})
    write_json(root, "artifacts/weather/weather_guard_status.json", {"risk_state": "normal"})
    write_json(
        root,
        "artifacts/overlay/overlay_summary.json",
        {
            "gps_gate_passed": True,
            "transition_window_pass": True,
            "control_plane_evidence_pct": 100.0,
        },
    )
    write_json(root, "artifacts/overlay/transition_window_summary.json", {})

    required_non_json = [
        "artifacts/airmap/live_trial/predictions_postcalibration.parquet",
        "artifacts/airmap/live_trial/predictions_precalibration.parquet",
        "artifacts/airmap/live_trial/metrics_stratified.csv",
        "artifacts/airmap/live_trial/satellite_timebin_metrics.csv",
        "artifacts/airmap/live_trial/satellite_outage_events.csv",
        "artifacts/qa/sentinel_scored.parquet",
        "artifacts/qa/quarantine_reject_rows.csv",
        "artifacts/eval/metrics_stratified.csv",
        "artifacts/eval/outlier_points.geojson",
        "artifacts/weather/weather_guard_audit.json",
        "artifacts/overlay/coverage_overlay.html",
        "artifacts/overlay/coverage_timeline.csv",
    ]
    for relative in required_non_json:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")


def configure_clean_source(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(build_evidence_index, "ROOT", root)
    monkeypatch.setattr(build_evidence_index, "_git_commit", lambda _root: "a" * 40)
    monkeypatch.setattr(build_evidence_index, "_git_dirty", lambda _root: False)


def test_clean_complete_evidence_pack_can_pass(tmp_path, monkeypatch):
    create_passing_fixture(tmp_path)
    configure_clean_source(monkeypatch, tmp_path)

    assert build_evidence_index.main() == 0
    index = json.loads((tmp_path / "artifacts/release/evidence_index.json").read_text())
    assert index["overall_gate"] == "PASS"
    assert all(step["outputs_complete"] for step in index["pipeline"])


def test_stale_pass_document_cannot_hide_missing_artifact(tmp_path, monkeypatch):
    create_passing_fixture(tmp_path)
    configure_clean_source(monkeypatch, tmp_path)
    missing = tmp_path / "artifacts/overlay/coverage_timeline.csv"
    missing.unlink()

    assert build_evidence_index.main() == 1
    index = json.loads((tmp_path / "artifacts/release/evidence_index.json").read_text())
    overlay = next(step for step in index["pipeline"] if step["step"] == "coverage_overlay")
    assert index["overall_gate"] == "FAIL"
    assert overlay["gate"] == "FAIL"
    assert "artifacts/overlay/coverage_timeline.csv" in overlay["missing_outputs"]


def test_dirty_source_tree_cannot_pass(tmp_path, monkeypatch):
    create_passing_fixture(tmp_path)
    configure_clean_source(monkeypatch, tmp_path)
    monkeypatch.setattr(build_evidence_index, "_git_dirty", lambda _root: True)

    assert build_evidence_index.main() == 1
    index = json.loads((tmp_path / "artifacts/release/evidence_index.json").read_text())
    assert index["source_tree_dirty"] is True
    assert index["overall_gate"] == "FAIL"

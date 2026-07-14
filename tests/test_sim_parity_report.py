from __future__ import annotations

import json
from pathlib import Path

from scripts import sim_parity_report as spr


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _rust_summary(**over) -> dict:
    d = {
        "mode": "flood", "seed": 42,
        "pdr_overall": 0.912,
        "aggregate_offered_airtime_ratio": 0.623,
        "channel_utilization": 0.623,
        "duty_misses_total": 0,
        "fleet_energy": {"deaths_total": 29223},
        "sos": {"sent": 186, "delivered": 186},
    }
    d.update(over)
    return d


def _py_summary(**over) -> dict:
    # Python arm: same shape, but no top-level duty_misses_total (known asymmetry).
    d = {
        "mode": "flood", "seed": 42,
        "pdr_overall": 0.9080,   # abs diff 0.004 -> within pdr band
        "aggregate_offered_airtime_ratio": 0.6300,
        "channel_utilization": 0.6300,
        "fleet_energy": {"deaths_total": 30000},  # rel ~0.026 -> within 0.15
        "sos": {"sent": 186, "delivered": 185},   # abs 1 -> within band
    }
    d.update(over)
    return d


def test_dotted_get_and_rel_diff():
    assert spr.dotted_get({"a": {"b": 3}}, "a.b") == 3
    assert spr.dotted_get({"a": {"b": 3}}, "a.c") is None
    assert spr.dotted_get({"a": 1}, "a.b") is None
    assert spr.rel_diff(0.0, 0.0) == 0.0          # no divide-by-zero
    assert spr.rel_diff(100.0, 110.0) == 10.0 / 110.0


def test_compare_pair_passes_within_band_and_marks_python_absent_duty():
    recs = {r["label"]: r for r in spr.compare_pair(_py_summary(), _rust_summary())}
    assert recs["pdr_overall"]["status"] == "pass"
    assert recs["aggregate_offered_airtime_ratio"]["status"] == "pass"
    assert recs["fleet_energy.deaths_total"]["status"] == "pass"
    assert recs["sos.delivered"]["status"] == "pass"
    # Python summary has no top-level duty_misses_total -> absent_py, not a flag.
    assert recs["duty_misses_total"]["status"] == "absent_py"
    assert recs["duty_misses_total"]["rust"] == 0


def test_compare_pair_flags_out_of_band_metric():
    # Push PDR far apart: 0.912 vs 0.50 -> abs 0.412, rel ~0.45, both exceed band.
    recs = {r["label"]: r
            for r in spr.compare_pair(_py_summary(pdr_overall=0.50), _rust_summary())}
    r = recs["pdr_overall"]
    assert r["status"] == "flag"
    assert abs(r["abs_diff"] - 0.412) < 1e-9


def test_build_report_python_arm_absent(tmp_path: Path):
    corrected = tmp_path / "corrected"
    _write(corrected / "corrected_flood.json", _rust_summary())
    _write(corrected / "sweep" / "fs_flood_s42.json", _rust_summary())
    # No corrected_py_* files at all -> python arm absent, graceful Rust inventory.
    report = spr.build_report(corrected, corrected, ["flood"], [42])
    assert report["python_arm_present"] is False
    assert report["totals"]["flag"] == 0
    assert any(inv["mode"] == "flood" and inv["seed"] == 42
               for inv in report["rust_inventory"])
    # inventory carries the shared scalar values
    inv = report["rust_inventory"][0]
    assert inv["pdr_overall"] == 0.912
    assert inv["rust_source"] == "sweep"


def test_build_report_prefers_sweep_then_falls_back_to_aggregate(tmp_path: Path):
    corrected = tmp_path / "corrected"
    py_dir = tmp_path / "py"
    # sweep exists only for seed 42; seed 43 must fall back to the aggregate.
    _write(corrected / "sweep" / "fs_flood_s42.json", _rust_summary(seed=42))
    _write(corrected / "corrected_flood.json", _rust_summary(seed=42))
    _write(py_dir / "corrected_py_flood_seed42.json", _py_summary())
    _write(py_dir / "corrected_py_flood_seed43.json", _py_summary())

    report = spr.build_report(corrected, py_dir, ["flood"], [42, 43])
    by_seed = {p["seed"]: p for p in report["pairs"]}
    assert by_seed[42]["rust_source"] == "sweep"
    assert by_seed[43]["rust_source"] == "aggregate"
    # seed 43 paired against the seed-42 aggregate -> mismatch is surfaced.
    assert by_seed[43]["seed_mismatch"]["aggregate_seed"] == 42
    assert report["python_arm_present"] is True
    assert report["totals"]["flag"] == 0


def test_build_report_reports_missing_rust(tmp_path: Path):
    corrected = tmp_path / "corrected"   # empty: no Rust files
    py_dir = tmp_path / "py"
    _write(py_dir / "corrected_py_flood_seed42.json", _py_summary())
    report = spr.build_report(corrected, py_dir, ["flood"], [42])
    assert report["pairs"][0]["status"] == "rust_missing"


def test_main_runs_on_synthetic_dir(tmp_path: Path, capsys):
    corrected = tmp_path / "corrected"
    _write(corrected / "sweep" / "fs_flood_s42.json", _rust_summary())
    rc = spr.main(["--corrected-dir", str(corrected), "--py-dir", str(corrected),
                   "--modes", "flood", "--seeds", "42"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "python arm absent" in out
    assert "MODEL-ONLY" in out

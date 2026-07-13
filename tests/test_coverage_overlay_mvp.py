import importlib.util
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "coverage_overlay_mvp.py"
_spec = importlib.util.spec_from_file_location("coverage_overlay_mvp", MODULE_PATH)
assert _spec and _spec.loader
coverage_overlay_mvp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coverage_overlay_mvp)


def test_load_residuals_preserves_timebin_and_topography(tmp_path):
    trial_dir = tmp_path
    pred = pd.DataFrame(
        {
            "timestamp_utc": ["2026-05-16T14:44:15Z"],
            "node_id": ["meshhikernode1"],
            "trial_id": ["trial-live"],
            "obs_metric_dbm": [-101.0],
            "pred_rssi_dbm": [-95.0],
            "time_bin": ["day"],
            "topography_class": ["valley"],
            "segment_id": ["king-ravine-001"],
        }
    )
    pred.to_parquet(trial_dir / "predictions_postcalibration.parquet", index=False)

    out = coverage_overlay_mvp.load_residuals(trial_dir)

    for col in ["time_bin", "topography_class", "segment_id"]:
        assert col in out.columns


def test_render_leaflet_html_has_time_bin_and_ravine_notch_controls(tmp_path):
    df = pd.DataFrame(
        {
            "lat": [44.3412668, 44.2613341],
            "lon": [-71.3001011, -71.2915966],
            "elev_m": [1012.0, 1202.0],
            "timestamp_utc": pd.to_datetime(["2026-05-16T09:00:00Z", "2026-05-16T19:30:00Z"], utc=True),
            "node_id": ["meshhikernode1", "meshhikernode1"],
            "trial_id": ["trial-live", "trial-live"],
            "coverage_mode": ["MESH", "SATELLITE"],
            "mesh_metric_dbm": [-102.0, -110.0],
            "cell_rsrp_dbm": [None, None],
            "satellite_link_status": ["offline", "connected"],
            "abs_error_db": [4.0, 13.0],
            "error_band": ["low", "high"],
            "time_bin": ["dawn", "evening_peak"],
            "topography_class": ["valley", "alpine_ridge"],
            "segment_id": ["king-ravine-001", "summit-approach-001"],
            "ravine_notch_segment": [True, False],
        }
    )

    out_html = tmp_path / "overlay.html"
    coverage_overlay_mvp.render_leaflet_html(df, out_html, "test")
    html = out_html.read_text()

    assert "Time-bin layers" in html
    assert "toggle-ravine-notch" in html
    assert "timeBinOrder" in html
    assert "ravine_notch_segment" in html


def test_missing_events_are_unknown_not_ip_full():
    telemetry = pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(["2026-05-16T09:00:00Z"], utc=True)}
    )

    out = coverage_overlay_mvp.assign_control_plane_mode(telemetry, pd.DataFrame())

    assert out["control_plane_mode"].tolist() == ["UNKNOWN"]


def test_rows_before_first_transition_remain_unknown():
    telemetry = pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(["2026-05-16T09:00:00Z", "2026-05-16T09:02:00Z"], utc=True)}
    )
    events = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(["2026-05-16T09:01:00Z"], utc=True),
            "connectivity_mode": ["MESH_ONLY"],
        }
    )

    out = coverage_overlay_mvp.assign_control_plane_mode(telemetry, events)

    assert out["control_plane_mode"].tolist() == ["UNKNOWN", "MESH_ONLY"]


def test_stale_connectivity_event_is_not_carried_forward_forever():
    telemetry = pd.DataFrame(
        {"timestamp_utc": pd.to_datetime(["2026-05-16T09:10:01Z"], utc=True)}
    )
    events = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(["2026-05-16T09:00:00Z"], utc=True),
            "connectivity_mode": ["IP_FULL"],
        }
    )

    out = coverage_overlay_mvp.assign_control_plane_mode(telemetry, events)

    assert out["control_plane_mode"].tolist() == ["UNKNOWN"]


def test_transition_summary_fails_modes_with_no_observations():
    timeline = pd.DataFrame(
        {"control_plane_mode": ["IP_FULL"] * 4, "coverage_mode": ["MESH"] * 4}
    )

    summary = coverage_overlay_mvp.transition_window_summary(timeline)

    assert summary["IP_FULL"]["pass"] is True
    assert summary["IP_DEGRADED"]["pass"] is False
    assert summary["MESH_ONLY"]["pass"] is False


def test_connectivity_loader_rejects_corrupt_json(tmp_path):
    path = tmp_path / "connectivity_events.jsonl"
    path.write_text('{"timestamp_utc":"2026-05-16T09:00:00Z"}\nnot-json\n')

    with pytest.raises(ValueError, match="line 2"):
        coverage_overlay_mvp.load_connectivity_events(path)


def test_transition_gate_rejects_token_single_observation():
    timeline = pd.DataFrame(
        {"control_plane_mode": ["MESH_ONLY"], "coverage_mode": ["MESH"]}
    )

    summary = coverage_overlay_mvp.transition_window_summary(timeline)

    assert summary["MESH_ONLY"]["coverage_pct"] == 100.0
    assert summary["MESH_ONLY"]["pass"] is False


def test_render_escapes_telemetry_strings_from_html(tmp_path):
    df = pd.DataFrame(
        {
            "lat": [44.3],
            "lon": [-71.3],
            "timestamp_utc": pd.to_datetime(["2026-05-16T09:00:00Z"], utc=True),
            "node_id": ["</script><script>alert(1)</script>"],
            "coverage_mode": ["MESH"],
            "control_plane_mode": ["MESH_ONLY"],
            "time_bin": ["day"],
            "topography_class": ["valley"],
            "segment_id": ["segment"],
            "ravine_notch_segment": [False],
        }
    )
    output = tmp_path / "overlay.html"

    coverage_overlay_mvp.render_leaflet_html(df, output, "test")
    rendered = output.read_text()

    assert "</script><script>alert(1)</script>" not in rendered
    assert "&lt;/script&gt;" in rendered


def test_inferred_daypart_uses_local_not_utc_hour():
    timestamp = pd.Timestamp("2026-07-13T10:00:00Z")

    assert coverage_overlay_mvp.infer_time_bin_from_timestamp(timestamp) == "dawn"


def test_legacy_satellite_alias_cannot_create_positive_coverage():
    telemetry = pd.DataFrame({"satellite_link_status": ["online"]})

    with pytest.raises(ValueError, match="satellite_link_status"):
        coverage_overlay_mvp.build_coverage(telemetry)

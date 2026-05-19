import importlib.util
from pathlib import Path

import pandas as pd


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

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts import build_gateway_coverage, render_sim_viewer


class FakeDem:
    def __init__(self, value: float = 0.0):
        self.lat = np.array([0.0, 1.0])
        self.lon = np.array([0.0, 1.0])
        self.z = np.full((2, 2), value)

    def profile(self, *_args):
        return 100.0, np.array([0.0, 0.0])


def test_coverage_cache_binds_dem_site_model_and_reports_failures(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def failing_itm(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(render_sim_viewer, "ROOT", tmp_path)
    monkeypatch.setattr(render_sim_viewer, "itm_p2p_loss", failing_itm)
    first = render_sim_viewer.coverage_layer(
        FakeDem(), "../unsafe gateway", 0.5, 0.5, 3.0, grid=2, pad=(0.5, 0.5)
    )
    assert first["claim_status"] == "MODELED_Q50_NOT_FIELD_VALIDATED"
    assert first["itm_error_cells"] == 4
    assert first["itm_error_types"] == {"RuntimeError": 4}
    assert len(calls) == 4
    cache_path = tmp_path / first["cache"]["path"]
    assert cache_path.is_file()
    assert cache_path.parent == tmp_path / "artifacts/sim"

    # Identical inputs reuse the validated cache without rerunning ITM.
    second = render_sim_viewer.coverage_layer(
        FakeDem(), "../unsafe gateway", 0.5, 0.5, 3.0, grid=2, pad=(0.5, 0.5)
    )
    assert second["cache"] == first["cache"]
    assert len(calls) == 4

    # A mounting-height change must not reuse the first raster.
    changed = render_sim_viewer.coverage_layer(
        FakeDem(), "../unsafe gateway", 0.5, 0.5, 4.0, grid=2, pad=(0.5, 0.5)
    )
    assert changed["cache"]["identity_sha256"] != first["cache"]["identity_sha256"]
    assert len(calls) == 8
    assert not list(tmp_path.rglob("_cov_*.png"))


def test_gateway_bundle_is_structured_provenance_not_bare_layer_list(
    tmp_path: Path, monkeypatch
) -> None:
    topology = tmp_path / "topology.json"
    dem = tmp_path / "dem.npz"
    topology.write_text(
        json.dumps(
            {
                "sites": {
                    "gateway": {
                        "lat": 0.5,
                        "lon": 0.5,
                        "hg_m": 3.0,
                        "mqtt_uplink": True,
                    }
                }
            }
        )
    )
    dem.write_bytes(b"fixture")
    layer = {
        "name": "gateway",
        "claim_status": "MODELED_Q50_NOT_FIELD_VALIDATED",
        "itm_error_cells": 0,
    }
    monkeypatch.setattr(build_gateway_coverage, "ROOT", tmp_path)
    monkeypatch.setattr(build_gateway_coverage, "Dem", lambda _path: object())
    monkeypatch.setattr(
        build_gateway_coverage, "coverage_layer", lambda *_args, **_kwargs: layer
    )
    monkeypatch.setattr(
        build_gateway_coverage,
        "source_entry",
        lambda path: {"path": str(path), "bytes": 1, "sha256": "0" * 64},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_gateway_coverage.py",
            "--topology",
            "topology.json",
            "--dem-npz",
            "dem.npz",
            "--out",
            "bundle.json",
        ],
    )

    assert build_gateway_coverage.main() == 0
    report = json.loads((tmp_path / "bundle.json").read_text())
    assert report["artifact_kind"].endswith("visualization_bundle")
    assert report["claim_status"] == "MODELED_Q50_NOT_FIELD_VALIDATED"
    assert report["layers"] == [layer]
    assert report["total_itm_error_cells"] == 0


def test_gateway_bundle_fails_closed_on_itm_errors(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "topology.json").write_text(
        json.dumps(
            {
                "sites": {
                    "gateway": {
                        "lat": 0.5,
                        "lon": 0.5,
                        "hg_m": 3.0,
                        "mqtt_uplink": True,
                    }
                }
            }
        )
    )
    (tmp_path / "dem.npz").write_bytes(b"fixture")
    monkeypatch.setattr(build_gateway_coverage, "ROOT", tmp_path)
    monkeypatch.setattr(build_gateway_coverage, "Dem", lambda _path: object())
    monkeypatch.setattr(
        build_gateway_coverage,
        "coverage_layer",
        lambda *_args, **_kwargs: {"name": "gateway", "itm_error_cells": 1},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_gateway_coverage.py",
            "--topology",
            "topology.json",
            "--dem-npz",
            "dem.npz",
            "--out",
            "bundle.json",
        ],
    )

    with pytest.raises(RuntimeError, match="refusing to write"):
        build_gateway_coverage.main()
    assert not (tmp_path / "bundle.json").exists()

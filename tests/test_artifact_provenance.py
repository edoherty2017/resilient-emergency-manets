from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.build_hiker_routes import ROUTES


ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "artifacts/sim"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(entry: dict[str, Any]) -> Path:
    path = Path(entry["path"])
    return path if path.is_absolute() else ROOT / path


def _verify_entry(entry: dict[str, Any]) -> Path:
    path = _path(entry)
    assert path.is_file(), entry["path"]
    assert _sha256(path) == entry["sha256"], entry["path"]
    if "bytes" in entry:
        assert path.stat().st_size == entry["bytes"], entry["path"]
    return path


@pytest.mark.parametrize("suffix", ["", "_statewide"])
def test_route_sources_and_legacy_topology_chain_are_verifiable(suffix: str) -> None:
    topology_path = SIM / f"topology{suffix}.json"
    routes_path = SIM / f"routes{suffix}.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    routes = json.loads(routes_path.read_text(encoding="utf-8"))

    assert routes["source_inputs"]["topology"]["path"] == str(
        topology_path.relative_to(ROOT)
    )
    assert routes["source_inputs"]["topology"]["sha256"] == _sha256(topology_path)
    for entry in routes["generators"].values():
        _verify_entry(entry)

    expected_definitions = hashlib.sha256(
        json.dumps(ROUTES, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert routes["route_definitions_sha256"] == expected_definitions
    for route in routes["routes"].values():
        provenance = route["geometry_provenance"]
        _verify_entry(
            {"path": provenance["cache_path"], "sha256": provenance["cache_sha256"]}
        )

    retrospective = topology["retrospective_provenance"]
    _verify_entry(retrospective["attachment_tool"])
    referenced = retrospective["referenced_files_at_audit"]
    _verify_entry(referenced["dem_manifest"])
    _verify_entry(referenced["current_sim_config"])
    dem_entry = referenced["dem"]
    assert dem_entry["path"] == topology["dem"]
    assert routes["source_inputs"]["dem"] == {
        "path": dem_entry["path"],
        "sha256": dem_entry["sha256"],
    }

    # Large DEM arrays intentionally stay out of Git. Their small source
    # manifest must nevertheless bind the exact omitted bytes used here.
    dem_manifest = json.loads(_path(referenced["dem_manifest"]).read_text())
    assert dem_manifest["checksums_sha256"][dem_entry["path"]] == dem_entry["sha256"]


def test_published_map_coverage_and_report_manifests_match_current_files() -> None:
    statewide_topology = json.loads((SIM / "topology_statewide.json").read_text())
    statewide_dem = statewide_topology["retrospective_provenance"][
        "referenced_files_at_audit"
    ]["dem"]

    audit = json.loads((SIM / "coverage_audit_statewide.json").read_text())
    for entry in audit["inputs"].values():
        _verify_entry(entry)

    field = json.loads((SIM / "coverage_field_stats.json").read_text())
    for name, entry in field["input_provenance"].items():
        if name == "dem":
            assert entry["path"] == statewide_dem["path"]
            assert entry["sha256"] == statewide_dem["sha256"]
        else:
            _verify_entry(entry)

    map_manifest = json.loads((SIM / "statewide_proposal_map_manifest.json").read_text())
    for name, entry in map_manifest["inputs"].items():
        if name == "dem":
            assert entry["path"] == statewide_dem["path"]
            assert entry["sha256"] == statewide_dem["sha256"]
        else:
            _verify_entry(entry)
    _verify_entry(map_manifest["output"])
    assert map_manifest["inputs"]["service_areas.json"]["path"] == (
        "artifacts/sim/service_areas.json"
    )

    # These names are intentionally retained compatibility aliases.
    assert (SIM / "coverage_field_stats.json").read_bytes() == (
        SIM / "trail_coverage.json"
    ).read_bytes()

    report_manifest = json.loads(
        (ROOT / "artifacts/coverage_prediction/trial1_report_manifest.json").read_text()
    )
    for name in ("generator", "source", "output"):
        _verify_entry(report_manifest[name])

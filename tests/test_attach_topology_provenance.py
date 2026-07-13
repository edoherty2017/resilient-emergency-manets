from __future__ import annotations

import json
from pathlib import Path

from scripts.attach_topology_provenance import attach


def test_retrospective_attachment_does_not_claim_original_generator(tmp_path: Path) -> None:
    (tmp_path / "artifacts/dem/cache").mkdir(parents=True)
    (tmp_path / "config/sim").mkdir(parents=True)
    dem = tmp_path / "artifacts/dem/cache/dem.npz"
    manifest = tmp_path / "artifacts/dem/cache/dem_manifest.json"
    config = tmp_path / "config/sim/wmnf_sim.yaml"
    tool = tmp_path / "attach.py"
    topology = tmp_path / "topology.json"
    dem.write_bytes(b"dem")
    manifest.write_text("{}")
    config.write_text("radio: {}")
    tool.write_text("# tool")
    topology.write_text(json.dumps({"dem": "artifacts/dem/cache/dem.npz"}))

    result = attach(
        topology,
        root=tmp_path,
        config_path=config,
        tool_path=tool,
    )
    provenance = result["retrospective_provenance"]

    assert provenance["original_generator_sha256"] is None
    assert provenance["status"].startswith("PARTIAL_RETROSPECTIVE")
    assert len(provenance["referenced_files_at_audit"]["dem"]["sha256"]) == 64

#!/usr/bin/env python3
"""Attach honest retrospective source hashes to legacy topology inputs.

Legacy topology JSON predates generator/source hashing. This tool does not
pretend that current files were the exact originals: it labels the attachment
as retrospective and leaves the original generator hash unknown. Future
topologies written by ``build_sim_topology.py`` carry generation-time hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    resolved = path.resolve()
    try:
        label = str(resolved.relative_to(root.resolve()))
    except ValueError:
        label = str(resolved)
    return {
        "path": label,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def attach(
    topology_path: Path,
    *,
    root: Path = ROOT,
    config_path: Path | None = None,
    tool_path: Path | None = None,
) -> dict[str, Any]:
    topology = json.loads(topology_path.read_text())
    dem_path = root / topology["dem"]
    dem_manifest_path = dem_path.with_name(f"{dem_path.stem}_manifest.json")
    config_path = config_path or root / "config/sim/wmnf_sim.yaml"
    tool_path = tool_path or Path(__file__)
    topology.setdefault("artifact_kind", "candidate_network_model_input")
    topology["claim_status"] = "MODELED_UNVERIFIED_SITE_AND_BACKHAUL_ASSUMPTIONS"
    topology.setdefault(
        "limitations",
        [
            "Fixed sites and mqtt_uplink flags are design assumptions, not proof of permission, power, mounting, backhaul, or legal feasibility.",
            "Modeled q50/q90 links do not establish packet-delivery probability or field coverage.",
        ],
    )
    topology["retrospective_provenance"] = {
        "status": "PARTIAL_RETROSPECTIVE_NOT_GENERATION_TIME_PROVENANCE",
        "attached_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_generator_sha256": None,
        "warning": (
            "These hashes identify source files present during the 2026-07-13 "
            "audit. They cannot prove those exact bytes produced this legacy topology."
        ),
        "attachment_tool": entry(tool_path, root),
        "referenced_files_at_audit": {
            "dem": entry(dem_path, root),
            "dem_manifest": entry(dem_manifest_path, root),
            "current_sim_config": entry(config_path, root),
        },
    }
    return topology


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value))
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "topologies",
        nargs="*",
        default=[
            "artifacts/sim/topology.json",
            "artifacts/sim/topology_statewide.json",
        ],
    )
    args = parser.parse_args(argv)
    for raw_path in args.topologies:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        atomic_write(path, attach(path))
        print(f"attached retrospective provenance: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

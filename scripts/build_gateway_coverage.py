#!/usr/bin/env python3
"""Statewide ITM coverage rasters for every MQTT gateway.

Reuses render_sim_viewer.coverage_layer (60x60 ITM grid per gateway, cached
as artifacts/sim/coverage_<name>.npz) over the statewide DEM, and writes one
index — artifacts/sim/coverage_overlays.json — that render_year_arena.py
embeds as a toggleable heatmap layer group. Pad is sized to the 12 km
max-link radius of the statewide build (vs the pilot's 5 km).

Run: .venv/bin/python scripts/build_gateway_coverage.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem  # noqa: E402
from render_sim_viewer import coverage_layer  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_entry(path: Path) -> dict:
    resolved = path.resolve()
    try:
        label = str(resolved.relative_to(ROOT))
    except ValueError:
        label = str(resolved)
    return {
        "path": label,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topology", default="artifacts/sim/topology_statewide.json")
    ap.add_argument("--dem-npz",
                    default="artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    ap.add_argument("--out", default="artifacts/sim/coverage_overlays.json")
    ap.add_argument("--pad-lat", type=float, default=0.11)   # ~12 km
    ap.add_argument("--pad-lon", type=float, default=0.15)
    ap.add_argument("--only", default=None, help="single gateway (timing test)")
    ap.add_argument(
        "--allow-itm-errors",
        action="store_true",
        help="write an explicitly incomplete visualization when ITM cells fail",
    )
    args = ap.parse_args()

    topology_path = ROOT / args.topology
    dem_path = ROOT / args.dem_npz
    topo = json.loads(topology_path.read_text())
    dem = Dem(dem_path)
    gws = {n: s for n, s in topo["sites"].items() if s.get("mqtt_uplink")}
    if args.only:
        gws = {args.only: gws[args.only]}
    layers = []
    t0 = time.time()
    for i, (n, s) in enumerate(sorted(gws.items())):
        t1 = time.time()
        layers.append(coverage_layer(dem, n, s["lat"], s["lon"], s["hg_m"],
                                     pad=(args.pad_lat, args.pad_lon)))
        print(f"[{i+1}/{len(gws)}] {n}  {time.time()-t1:.1f}s", flush=True)
    total_itm_errors = sum(layer["itm_error_cells"] for layer in layers)
    if total_itm_errors and not args.allow_itm_errors:
        raise RuntimeError(
            f"refusing to write coverage index after {total_itm_errors} ITM cell "
            "errors; inspect the inputs or explicitly pass --allow-itm-errors"
        )
    report = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_kind": "uncalibrated_itm_q50_signal_visualization_bundle",
        "claim_status": "MODELED_Q50_NOT_FIELD_VALIDATED",
        "input_provenance": {
            "generator": source_entry(Path(__file__)),
            "raster_generator": source_entry(ROOT / "scripts/render_sim_viewer.py"),
            "itm_model": source_entry(ROOT / "scripts/itm_relay_links.py"),
            "radio_budget": source_entry(ROOT / "scripts/radio_link_budget.py"),
            "topology": source_entry(topology_path),
            "dem": source_entry(dem_path),
            "dependency_lock": source_entry(ROOT / "requirements.lock"),
        },
        "parameters": {
            "pad_lat": args.pad_lat,
            "pad_lon": args.pad_lon,
            "gateway_filter": args.only,
            "allow_itm_errors": args.allow_itm_errors,
        },
        "total_itm_error_cells": total_itm_errors,
        "limitations": [
            "The rasters are uncalibrated Longley-Rice q50 model output, not AIRMap predictions or field-observed coverage.",
            "A q50 received-power estimate is not a packet-delivery probability or reliability bound.",
            "Site coordinates, mounting heights, radio parameters, and DEM values remain modeled inputs.",
        ],
        "layers": layers,
    }
    atomic_write_json(ROOT / args.out, report)
    print(f"wrote {args.out}: {len(layers)} gateway rasters "
          f"in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

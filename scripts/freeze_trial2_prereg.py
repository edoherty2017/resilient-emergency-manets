#!/usr/bin/env python3
"""Freeze the Trial 2 preregistration by hashing its inputs into a manifest.

A preregistration only has evidential value if the exact bytes it commits to are
pinned before field collection begins. Generating ``docs/trial2-preregistration.md``
and ``artifacts/trial2/predictions.csv`` does NOT freeze them — this script does,
by recording a SHA-256 + byte count for every frozen input and output alongside a
caller-supplied UTC build timestamp, the Git HEAD, and the worktree-dirty state.

What is bound (see ``DECLARED_INPUTS`` below):
  * the corrected prospective prediction table (``artifacts/trial2/predictions.csv``)
  * its generator (``scripts/trial2_predictions.py``)
  * the canonical radio metadata (``config/sim/wmnf_sim.yaml``)
  * statewide topology and routes (``artifacts/sim/{topology,routes}_statewide.json``)
  * the DEM source manifest for the Presidentials-wide raster used by the generator
  * the field eligibility gate (``scripts/airmap_live_trial.py``) and PDR / scoring
    analysis code (``scripts/pdr_analysis.py``)
  * the generator's actual runtime inputs — the non-statewide topology/routes it
    reads and its library dependencies — so the prediction is byte-reproducible.

The build timestamp is NEVER read from the wall clock implicitly: it must be passed
via ``--stamp`` (ISO-8601, UTC) so the freeze instant is an auditable input, not a
side effect of when the script happened to run. The output manifest is treated as
immutable: an existing manifest is not overwritten unless ``--force`` is given.

Usage:
    .venv/bin/python scripts/freeze_trial2_prereg.py --stamp 2026-07-13T18:30:00+00:00
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "trial2-prereg/1.0"
DEFAULT_MANIFEST = "artifacts/trial2/prereg_manifest.json"

# role -> (repo-relative path, human description). Ordered so the manifest reads
# top-down from the frozen prediction to the code that will score it in the field.
DECLARED_INPUTS: dict[str, tuple[str, str]] = {
    "prediction_csv": (
        "artifacts/trial2/predictions.csv",
        "Corrected prospective per-stratum RSSI / threshold-exceedance predictions.",
    ),
    "generator": (
        "scripts/trial2_predictions.py",
        "Generator that produced the prediction table and the prereg document.",
    ),
    "radio_metadata": (
        "config/sim/wmnf_sim.yaml",
        "Canonical radio / link-budget configuration for the deployment.",
    ),
    "topology_statewide": (
        "artifacts/sim/topology_statewide.json",
        "Statewide topology (beacon site coordinates and metadata).",
    ),
    "routes_statewide": (
        "artifacts/sim/routes_statewide.json",
        "Statewide route geometry pack.",
    ),
    "dem_manifest": (
        "artifacts/dem/cache/usgs_3dep_presidentials_wide_manifest.json",
        "USGS 3DEP Presidentials-wide DEM source manifest (binds the omitted raster).",
    ),
    "eligibility_rules": (
        "scripts/airmap_live_trial.py",
        "Calibration-eligibility gate (hops_away==0, exclusions) applied to field data.",
    ),
    "analysis_code": (
        "scripts/pdr_analysis.py",
        "PDR / opportunity-accounting analysis used to score the frozen predictions.",
    ),
    # The generator actually reads the non-statewide topology/routes and these
    # library modules; binding them makes predictions.csv byte-reproducible.
    "generator_topology": (
        "artifacts/sim/topology.json",
        "Topology JSON the generator reads for beacon site coordinates.",
    ),
    "generator_routes": (
        "artifacts/sim/routes.json",
        "Routes JSON the generator reads for the Ammo-Jewell walk geometry.",
    ),
    "generator_lib_radio": (
        "scripts/radio_link_budget.py",
        "Link-budget library the generator imports (RX power reference).",
    ),
    "generator_lib_itm": (
        "scripts/itm_relay_links.py",
        "ITM DEM sampling / haversine library the generator imports.",
    ),
}

DEFAULT_MANIFEST_FIELDDAY = "artifacts/trial2/prereg_manifest_fieldday.json"

# Bindings for the per-route field-day pack (Moosilauke / Kearsarge / Monadnock).
# Kept separate from DECLARED_INPUTS so the original 2026-07-19 ammo/jewell freeze
# stays byte-identical and auditable; ordering mirrors it: prediction first, then
# generator, then the code that scores it.
DECLARED_INPUTS_FIELDDAY: dict[str, tuple[str, str]] = {
    "prediction_csv": (
        "artifacts/trial2/predictions_fieldday.csv",
        "Per-route field-day RSSI / threshold-exceedance predictions (frozen bands).",
    ),
    "generation_manifest": (
        "artifacts/trial2/predictions_fieldday_manifest.json",
        "Generation-time manifest (beacon rule, heights, DEM hashes) for the pack.",
    ),
    "generator": (
        "scripts/trial2_predictions_field.py",
        "Generator that produced the field-day prediction table.",
    ),
    "radio_metadata": (
        "config/sim/wmnf_sim.yaml",
        "Canonical radio / link-budget configuration for the deployment.",
    ),
    "dem_manifest_moosilauke": (
        "artifacts/dem/cache/usgs_3dep_moosilauke_manifest.json",
        "USGS 3DEP Moosilauke DEM source manifest (binds the omitted raster).",
    ),
    "dem_manifest_kearsarge": (
        "artifacts/dem/cache/usgs_3dep_kearsarge_manifest.json",
        "USGS 3DEP Kearsarge DEM source manifest (binds the omitted raster).",
    ),
    "dem_manifest_monadnock": (
        "artifacts/dem/cache/usgs_3dep_monadnock_manifest.json",
        "USGS 3DEP Monadnock DEM source manifest (binds the omitted raster).",
    ),
    "eligibility_rules": (
        "scripts/airmap_live_trial.py",
        "Calibration-eligibility gate (hops_away==0, exclusions) applied to field data.",
    ),
    "analysis_code": (
        "scripts/pdr_analysis.py",
        "PDR / opportunity-accounting analysis used to score the frozen predictions.",
    ),
    "generator_lib_radio": (
        "scripts/radio_link_budget.py",
        "Link-budget library the generator imports (RX power reference).",
    ),
    "generator_lib_itm": (
        "scripts/itm_relay_links.py",
        "ITM DEM sampling / haversine library the generator imports.",
    ),
}


def sha256_and_size(path: Path) -> tuple[str, int]:
    """Return (hex sha256, byte count) for ``path``, streaming to bound memory."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def parse_stamp(raw: str) -> str:
    """Validate a caller-supplied UTC ISO-8601 timestamp; return canonical form.

    We refuse anything without an explicit UTC offset so the freeze instant can
    never be silently reinterpreted in another timezone.
    """
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - message is exercised in tests
        raise ValueError(f"--stamp is not ISO-8601: {raw!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"--stamp must be an explicit UTC time (offset +00:00): {raw!r}")
    return parsed.astimezone(timezone.utc).isoformat()


def git_state(root: Path) -> tuple[str, bool]:
    """Return (HEAD sha, worktree_dirty). HEAD is 'unknown' outside a Git repo."""
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout

    try:
        head = run("rev-parse", "HEAD").strip()
        dirty = bool(
            run("status", "--porcelain=v1", "--untracked-files=normal").strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown", False
    return head, dirty


def build_manifest(
    stamp: str, root: Path = ROOT, declared: dict[str, tuple[str, str]] = DECLARED_INPUTS
) -> dict:
    """Hash every declared input and assemble the immutable manifest dict.

    Raises ``FileNotFoundError`` if any declared input is missing, so a freeze can
    never silently omit a binding.
    """
    inputs: dict[str, dict] = {}
    missing: list[str] = []
    for role, (rel_path, description) in declared.items():
        path = root / rel_path
        if not path.is_file():
            missing.append(rel_path)
            continue
        sha, size = sha256_and_size(path)
        inputs[role] = {
            "path": rel_path,
            "sha256": sha,
            "bytes": size,
            "description": description,
        }
    if missing:
        raise FileNotFoundError(
            "cannot freeze; declared input(s) missing: " + ", ".join(sorted(missing))
        )

    head, dirty = git_state(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "build_timestamp_utc": parse_stamp(stamp),
        "git_head": head,
        "git_worktree_dirty": dirty,
        "generated_by": "scripts/freeze_trial2_prereg.py",
        "input_count": len(inputs),
        "inputs": inputs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp",
        required=True,
        help="UTC ISO-8601 build timestamp, e.g. 2026-07-13T18:30:00+00:00 "
        "(never taken from the wall clock implicitly).",
    )
    ap.add_argument(
        "--pack",
        choices=("prereg", "fieldday"),
        default="prereg",
        help="Which frozen pack to bind: the ammo/jewell preregistration (default) "
        "or the per-route field-day pack.",
    )
    ap.add_argument(
        "--out",
        default=None,
        help=f"Manifest output path (default {DEFAULT_MANIFEST} or "
        f"{DEFAULT_MANIFEST_FIELDDAY} per --pack).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing manifest. Omit to keep the freeze immutable.",
    )
    args = ap.parse_args()

    declared = DECLARED_INPUTS if args.pack == "prereg" else DECLARED_INPUTS_FIELDDAY
    default_out = DEFAULT_MANIFEST if args.pack == "prereg" else DEFAULT_MANIFEST_FIELDDAY
    out = Path(args.out) if args.out else Path(default_out)
    if not out.is_absolute():
        out = ROOT / out
    if out.exists() and not args.force:
        raise SystemExit(
            f"refusing to overwrite frozen manifest {out} (pass --force to replace)"
        )

    manifest = build_manifest(args.stamp, ROOT, declared)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"froze {manifest['input_count']} inputs -> {out}")
    print(f"  build_timestamp_utc: {manifest['build_timestamp_utc']}")
    print(f"  git_head: {manifest['git_head']} (dirty={manifest['git_worktree_dirty']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

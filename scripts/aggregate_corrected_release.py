#!/usr/bin/env python3
"""Aggregate a corrected replacement-run release + write its provenance manifest.

Reads fs_<mode>_s<seed>.json summaries from a release dir, computes per-mode
means and t-based 95% confidence intervals (df = n-1) for the primary/secondary
metrics, writes corrected_stats.json, and binds git state + input/output SHA-256
into release_manifest.json. MODEL-ONLY, single-engine (fastsim/Rust).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ["flood", "min_hop", "etx", "energy_aware", "lb_energy",
         "duty_sync", "duty_adaptive", "rotate_lb", "selective_duty"]
# two-sided t(0.975) by df; extendable
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ci95(v: list[float]) -> tuple[float, float]:
    n = len(v)
    mu = statistics.mean(v)
    if n < 2:
        return round(mu, 6), 0.0
    sd = statistics.stdev(v)
    t = T975.get(n - 1, 1.96)
    return round(mu, 6), round(t * sd / math.sqrt(n), 6)


def aggregate(release: Path) -> dict:
    rows: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    seeds: set[int] = set()
    for f in sorted(release.glob("fs_*.json")):
        stem = f.stem[len("fs_"):]
        mode, _, seed = stem.rpartition("_s")
        seeds.add(int(seed))
        d = json.loads(f.read_text())
        fe = d.get("fleet_energy", {}) or {}
        s = d.get("sos", {}) or {}
        rows[mode]["pdr"].append(d["pdr_overall"])
        rows[mode]["util"].append(d.get("aggregate_offered_airtime_ratio",
                                        d.get("channel_utilization")))
        rows[mode]["deaths"].append(fe["deaths_total"])
        rows[mode]["dmiss"].append(d.get("duty_misses_total",
                                         fe.get("duty_misses_total", 0)))
        rows[mode]["sosd"].append(s.get("delivered", 0))
        rows[mode]["soss"].append(s.get("sent", 0))
    stats = {"engine": "fastsim (rust)", "seeds": sorted(seeds),
             "ci": "t-based 95% (df = n-1)", "days": 365,
             "claim_status": "MODEL_ONLY_uncalibrated", "modes": {}}
    for m in MODES:
        if m not in rows:
            continue
        r = rows[m]
        pm, pe = ci95(r["pdr"])
        dm, de = ci95([float(x) for x in r["deaths"]])
        um, ue = ci95(r["util"])
        dmm, _ = ci95([float(x) for x in r["dmiss"]])
        stats["modes"][m] = {
            "pdr": pm, "pdr_ci95": pe, "deaths": dm, "deaths_ci95": de,
            "offered_airtime": um, "offered_airtime_ci95": ue,
            "sos_delivered": round(statistics.mean(r["sosd"]), 1),
            "sos_sent": round(statistics.mean(r["soss"]), 1),
            "duty_misses": round(dmm, 0),
        }
    return stats


def git_head() -> tuple[str, bool]:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    return head, dirty


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", default="artifacts/sim/corrected/release_v1")
    a = ap.parse_args(argv)
    rel = ROOT / a.release if not Path(a.release).is_absolute() else Path(a.release)
    stats = aggregate(rel)
    (rel / "corrected_stats.json").write_text(json.dumps(stats, indent=2) + "\n")

    head, dirty = git_head()
    inputs = {p.name: sha256(p) for p in rel.glob("*.json")
              if not p.name.startswith("fs_")
              and p.name not in ("release_manifest.json", "corrected_stats.json")}
    inputs.update({p.name: sha256(p) for p in rel.glob("*.yaml")})
    binary = ROOT / "fastsim/target/release/fastsim"
    manifest = {
        "schema_version": "1.0", "artifact_kind": "corrected_replacement_release",
        "claim_status": "MODEL_ONLY_uncalibrated_single_engine_microparity_checked",
        "git_head": head, "git_worktree_dirty": dirty,
        "engine": "fastsim (rust)",
        "engine_binary_sha256": sha256(binary) if binary.exists() else None,
        "modes": list(stats["modes"].keys()), "seeds": stats["seeds"], "days": 365,
        "locked_inputs_sha256": inputs,
        "n_run_files": len(list(rel.glob("fs_*.json"))),
        "aggregate": "corrected_stats.json",
        "aggregate_sha256": sha256(rel / "corrected_stats.json"),
        "reproduce": "scripts/run_corrected_release.sh",
        "note": ("Rust-only; Python arm not run at statewide scale. Micro-parity "
                 "within tolerance except duty-mode offered_airtime. No algorithm "
                 "winner declared."),
    }
    (rel / "release_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"aggregated {len(stats['modes'])} modes, {len(stats['seeds'])} seeds; "
          f"manifest bound to {head[:8]} (dirty={dirty})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

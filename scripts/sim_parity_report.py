#!/usr/bin/env python3
"""Python <-> Rust parity accounting for the corrected replacement runs.

Pairs the corrected Python summaries (``corrected_py_<mode>_seed<S>.json``) with
the corrected Rust summaries (preferring the per-seed sweep file
``corrected/sweep/fs_<mode>_s<S>.json`` and falling back to the single-seed
aggregate ``corrected/corrected_<mode>.json``) for the nine shared modes, and
reports the absolute and relative difference on each shared scalar metric.

This implements the parity section of
``docs/sim-replacement-analysis-plan.md``. Exact numeric equality is **not**
expected: the two engines use independent, keyed per-phenomenon RNG streams, so
seed-matched runs are not trace-identical. Parity here is bounded-difference
accounting -- report the two values, their absolute/relative difference, and flag
anything outside the pre-registered tolerance band.

The report runs even when the Python arm is entirely missing: it prints
"python arm absent" and falls back to a Rust-side inventory so the run is still
informative.

Run: .venv/bin/python scripts/sim_parity_report.py
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]

# The nine modes shared by both engines (Rust set = 11 Python modes minus the
# two learned-policy modes q_routing / rl_duty, which are Python-only).
SHARED_MODES = [
    "flood", "min_hop", "etx", "energy_aware", "lb_energy",
    "duty_sync", "duty_adaptive", "rotate_lb", "selective_duty",
]

DEFAULT_SEEDS = [42, 43, 44, 45, 46]

EPS = 1e-9

# Pre-registered tolerance bands (docs/sim-replacement-analysis-plan.md sec 4.3).
# A metric passes a pair if abs_diff <= tol_abs OR rel_diff <= tol_rel.
# tol_abs = None means "no absolute pass path; use relative only".
#
# Each spec: (label, dotted-path getter, tol_abs, tol_rel).
KEY_SPECS: list[tuple[str, str, Optional[float], float]] = [
    ("pdr_overall", "pdr_overall", 0.03, 0.05),
    ("aggregate_offered_airtime_ratio", "aggregate_offered_airtime_ratio", 0.03, 0.10),
    ("channel_utilization", "channel_utilization", 0.03, 0.10),
    ("sos.sent", "sos.sent", 3.0, 0.10),
    ("sos.delivered", "sos.delivered", 3.0, 0.10),
    ("fleet_energy.deaths_total", "fleet_energy.deaths_total", None, 0.15),
    ("duty_misses_total", "duty_misses_total", None, 0.15),
]


# ── data access ────────────────────────────────────────────────────────────
def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def dotted_get(d: Any, path: str) -> Any:
    """Return d["a"]["b"] for path "a.b", or None if any level is missing."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def py_path(py_dir: Path, mode: str, seed: int) -> Path:
    return py_dir / f"corrected_py_{mode}_seed{seed}.json"


def rust_path(corrected_dir: Path, mode: str, seed: int) -> tuple[Optional[Path], str]:
    """Resolve the Rust summary for (mode, seed).

    Prefer the per-seed sweep file; fall back to the single-seed aggregate.
    Returns (path_or_None, source_tag).
    """
    sweep = corrected_dir / "sweep" / f"fs_{mode}_s{seed}.json"
    if sweep.is_file():
        return sweep, "sweep"
    agg = corrected_dir / f"corrected_{mode}.json"
    if agg.is_file():
        return agg, "aggregate"
    return None, "missing"


# ── comparison ─────────────────────────────────────────────────────────────
def rel_diff(p: float, r: float) -> float:
    return abs(p - r) / max(abs(p), abs(r), EPS)


def compare_pair(py_summary: dict, rust_summary: dict,
                 specs: list[tuple[str, str, Optional[float], float]] = KEY_SPECS
                 ) -> list[dict]:
    """Per-key parity records for one paired (py, rust) summary.

    Each record: label, py, rust, abs_diff, rel_diff, tol_abs, tol_rel, status.
    status is one of: "pass", "flag", "absent_py", "absent_rust", "absent_both".
    Absent keys carry no numeric diff and do not count toward pass/flag tallies.
    """
    records: list[dict] = []
    for label, path, tol_abs, tol_rel in specs:
        pv = dotted_get(py_summary, path)
        rv = dotted_get(rust_summary, path)
        rec: dict[str, Any] = {
            "label": label, "py": pv, "rust": rv,
            "tol_abs": tol_abs, "tol_rel": tol_rel,
            "abs_diff": None, "rel_diff": None,
        }
        p_ok = isinstance(pv, (int, float)) and not isinstance(pv, bool)
        r_ok = isinstance(rv, (int, float)) and not isinstance(rv, bool)
        if p_ok and r_ok:
            ad = abs(float(pv) - float(rv))
            rd = rel_diff(float(pv), float(rv))
            rec["abs_diff"] = ad
            rec["rel_diff"] = rd
            passed = (tol_abs is not None and ad <= tol_abs) or rd <= tol_rel
            rec["status"] = "pass" if passed else "flag"
        elif not p_ok and not r_ok:
            rec["status"] = "absent_both"
        elif not p_ok:
            rec["status"] = "absent_py"
        else:
            rec["status"] = "absent_rust"
        records.append(rec)
    return records


# ── report assembly ────────────────────────────────────────────────────────
def build_report(corrected_dir: Path, py_dir: Path,
                 modes: list[str], seeds: list[int]) -> dict:
    pairs: list[dict] = []
    rust_inventory: list[dict] = []
    py_present = False

    for mode in modes:
        for seed in seeds:
            pp = py_path(py_dir, mode, seed)
            rp, rsrc = rust_path(corrected_dir, mode, seed)
            rust_summary = load_json(rp) if rp is not None else None
            if rust_summary is not None:
                inv = {"mode": mode, "seed": seed, "rust_source": rsrc,
                       "rust_file": str(rp.relative_to(ROOT)) if _under(rp, ROOT) else str(rp)}
                # note a seed mismatch when we fell back to the seed-42 aggregate
                if rsrc == "aggregate":
                    agg_seed = rust_summary.get("seed")
                    if agg_seed is not None and agg_seed != seed:
                        inv["seed_mismatch"] = {"requested": seed, "aggregate_seed": agg_seed}
                for label, path, _a, _r in KEY_SPECS:
                    inv[label] = dotted_get(rust_summary, path)
                rust_inventory.append(inv)

            if not pp.is_file():
                if rust_summary is not None:
                    pairs.append({"mode": mode, "seed": seed, "rust_source": rsrc,
                                  "status": "python_missing", "records": []})
                continue
            py_present = True
            py_summary = load_json(pp)
            if rust_summary is None:
                pairs.append({"mode": mode, "seed": seed, "rust_source": "missing",
                              "status": "rust_missing", "records": []})
                continue
            records = compare_pair(py_summary, rust_summary)
            entry = {"mode": mode, "seed": seed, "rust_source": rsrc,
                     "status": "compared", "records": records}
            if rsrc == "aggregate":
                agg_seed = rust_summary.get("seed")
                if agg_seed is not None and agg_seed != seed:
                    entry["seed_mismatch"] = {"requested": seed, "aggregate_seed": agg_seed}
            pairs.append(entry)

    flags = sum(1 for pr in pairs for rec in pr["records"] if rec["status"] == "flag")
    passes = sum(1 for pr in pairs for rec in pr["records"] if rec["status"] == "pass")
    return {
        "python_arm_present": py_present,
        "modes": modes,
        "seeds": seeds,
        "pairs": pairs,
        "rust_inventory": rust_inventory,
        "totals": {"pass": passes, "flag": flags},
        "note": ("Exact equality is NOT expected: the engines use independent keyed "
                 "per-phenomenon RNG streams, so parity is bounded-difference "
                 "accounting, not identity. All outputs are MODEL-ONLY."),
    }


def _under(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        if v != 0 and (abs(v) >= 1e6 or abs(v) < 1e-4):
            return f"{v:.3e}"
        return f"{v:.5g}"
    return str(v)


def print_report(report: dict) -> None:
    print("=" * 78)
    print("Python <-> Rust parity report (corrected replacement runs) -- MODEL-ONLY")
    print("=" * 78)
    print(report["note"])
    print(f"modes={report['modes']}")
    print(f"seeds={report['seeds']}")
    print()

    if not report["python_arm_present"]:
        print("python arm absent -- no corrected_py_<mode>_seed<S>.json summaries found.")
        print("Falling back to Rust-side inventory of the shared-metric scalars:\n")
        inv = report["rust_inventory"]
        if not inv:
            print("  (no Rust summaries found either)")
            return
        cols = ["mode", "seed", "rust_source"] + [s[0] for s in KEY_SPECS]
        _print_table(cols, inv)
        # surface any seed mismatches from aggregate fallback
        mism = [i for i in inv if "seed_mismatch" in i]
        if mism:
            print("\n  seed mismatches (aggregate fallback):")
            for i in mism:
                print(f"    {i['mode']} requested seed {i['seed_mismatch']['requested']} "
                      f"-> aggregate seed {i['seed_mismatch']['aggregate_seed']}")
        return

    for pr in report["pairs"]:
        head = f"[{pr['mode']} seed{pr['seed']}] rust_source={pr['rust_source']} status={pr['status']}"
        if "seed_mismatch" in pr:
            head += (f"  (seed mismatch: aggregate is seed "
                     f"{pr['seed_mismatch']['aggregate_seed']})")
        print(head)
        if pr["status"] != "compared":
            print("    (no comparison)")
            continue
        for rec in pr["records"]:
            mark = {"pass": "ok  ", "flag": "FLAG", "absent_py": "py? ",
                    "absent_rust": "rs? ", "absent_both": "--  "}[rec["status"]]
            print(f"    {mark} {rec['label']:<34} "
                  f"py={_fmt(rec['py']):>12} rust={_fmt(rec['rust']):>12} "
                  f"abs={_fmt(rec['abs_diff']):>10} rel={_fmt(rec['rel_diff']):>9}")
        print()

    t = report["totals"]
    print("-" * 78)
    print(f"totals: {t['pass']} within-tolerance, {t['flag']} FLAGGED beyond tolerance")
    if t["flag"]:
        print("FLAGGED metrics exceed the plan tolerance band and warrant investigation")
        print("(a flag is a divergence signal between two uncalibrated models, not proof")
        print(" of a defect). See docs/sim-replacement-analysis-plan.md sec 4.")
    else:
        print("all compared metrics are within the pre-registered tolerance bands")


def _print_table(cols: list[str], rows: list[dict]) -> None:
    widths = {c: max(len(c), *(len(_fmt(r.get(c))) for r in rows)) for c in cols}
    print("  " + "  ".join(c.ljust(widths[c]) for c in cols))
    print("  " + "  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  " + "  ".join(_fmt(r.get(c)).ljust(widths[c]) for c in cols))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corrected-dir", default="artifacts/sim/corrected",
                    help="dir holding corrected_<mode>.json and sweep/fs_<mode>_s<S>.json")
    ap.add_argument("--py-dir", default="artifacts/sim/corrected",
                    help="dir holding corrected_py_<mode>_seed<S>.json (Python arm)")
    ap.add_argument("--modes", nargs="*", default=SHARED_MODES)
    ap.add_argument("--seeds", nargs="*", type=int, default=DEFAULT_SEEDS)
    ap.add_argument("--json-out", default=None,
                    help="optional path to write the machine-readable report")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any metric is flagged beyond tolerance")
    args = ap.parse_args(argv)

    corrected_dir = _resolve(args.corrected_dir)
    py_dir = _resolve(args.py_dir)

    report = build_report(corrected_dir, py_dir, list(args.modes), list(args.seeds))
    print_report(report)

    if args.json_out:
        out = _resolve(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nwrote machine-readable report to {out}")

    if args.strict and report["totals"]["flag"]:
        return 2
    return 0


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path)


if __name__ == "__main__":
    raise SystemExit(main())

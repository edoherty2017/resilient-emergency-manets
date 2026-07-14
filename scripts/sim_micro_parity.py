#!/usr/bin/env python3
"""Micro-scenario Python<->Rust parity harness.

Runs BOTH engines (scripts/mesh_sim.py and fastsim) on the same small
scenario with identical inputs/seed via explicit subprocess arg-lists (no
shell word-splitting), then compares the shared summary scalars.

Because the two engines use independent keyed RNG streams, exact bit-equality
is NOT expected; parity here is bounded-difference accounting. Divergences
beyond the per-metric tolerance are flagged so bucket-3 reconciliation can
target the largest ones first.

Run: .venv/bin/python scripts/sim_micro_parity.py \
       --topology artifacts/sim/topology.json \
       --routes artifacts/sim/routes.json \
       --weather artifacts/sim/weather_year.json --days 3 --seed 42 \
       --modes flood duty_sync selective_duty
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv/bin/python"
RUST = ROOT / "fastsim/target/release/fastsim"
CFG = ROOT / "config/sim/wmnf_sim.yaml"

# per-metric (absolute, relative) tolerances — mirror the analysis plan
TOL = {
    "pdr_overall": (0.03, 0.05),
    "offered_airtime": (0.03, 0.10),
    "deaths_total": (None, 0.15),
    "duty_misses_total": (None, 0.15),
    "sos_sent": (3, 0.10),
    "sos_delivered": (3, 0.10),
}


def common_args(a: argparse.Namespace) -> list[str]:
    return [
        "--topology", a.topology, "--routes", a.routes,
        "--weather", a.weather, "--days", str(a.days), "--seed", str(a.seed),
        "--sos-retry", "--renters-per-route", str(a.renters),
        "--telemetry-interval-s", "3600", "--beacon-interval-s", "900",
        "--energy-step-s", "600", "--route-refresh-s", "3600",
    ]


def run_python(mode: str, a: argparse.Namespace, out: Path) -> None:
    subprocess.run(
        [str(PY), str(ROOT / "scripts/mesh_sim.py"), *common_args(a),
         "--kiosk-pool", "--mode", mode, "--trace", "", "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True)


def run_rust(mode: str, a: argparse.Namespace, out: Path) -> None:
    subprocess.run(
        [str(RUST), *common_args(a), "--config", str(CFG),
         "--mode", mode, "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True)


def scalars(path: Path) -> dict:
    d = json.loads(path.read_text())
    fe = d.get("fleet_energy", {}) or {}
    s = d.get("sos", {}) or {}
    return {
        "pdr_overall": d.get("pdr_overall"),
        # both engines expose an offered-airtime-like ratio under one of these
        "offered_airtime": d.get("aggregate_offered_airtime_ratio",
                                 d.get("channel_utilization")),
        "deaths_total": fe.get("deaths_total"),
        "duty_misses_total": d.get("duty_misses_total",
                                   fe.get("duty_misses_total")),
        "sos_sent": s.get("sent"),
        "sos_delivered": s.get("delivered"),
    }


def flag(metric: str, py, rs) -> tuple[str, bool]:
    if py is None or rs is None:
        return ("absent", py is None and rs is None)
    try:
        py, rs = float(py), float(rs)
    except (TypeError, ValueError):
        return ("?", py == rs)
    abs_d = abs(py - rs)
    rel_d = abs_d / max(abs(rs), 1e-9)
    atol, rtol = TOL.get(metric, (None, 0.10))
    ok = True
    if atol is not None and abs_d > atol:
        ok = rel_d <= (rtol or 0)
    if rtol is not None and rel_d > rtol:
        ok = ok and (atol is not None and abs_d <= atol)
    return (f"abs {abs_d:.4g} / rel {rel_d:.1%}", ok)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--routes", default="artifacts/sim/routes.json")
    ap.add_argument("--weather", default="artifacts/sim/weather_year.json")
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--renters", type=int, default=2)
    ap.add_argument("--modes", nargs="+",
                    default=["flood", "duty_sync", "selective_duty"])
    ap.add_argument("--out", default=None,
                    help="write the full comparison JSON here")
    a = ap.parse_args(argv)

    results = {}
    any_fail = False
    tmp = Path(tempfile.mkdtemp(prefix="parity-"))
    print(f"{'mode':<15}{'metric':<18}{'python':>12}{'rust':>12}"
          f"{'divergence':>20}  flag")
    for mode in a.modes:
        pj, rj = tmp / f"py_{mode}.json", tmp / f"rs_{mode}.json"
        try:
            run_python(mode, a, pj)
            run_rust(mode, a, rj)
        except subprocess.CalledProcessError as e:
            print(f"{mode:<15} RUN FAILED: {e.stderr.strip().splitlines()[-1:]}")
            any_fail = True
            continue
        py, rs = scalars(pj), scalars(rj)
        results[mode] = {"python": py, "rust": rs, "checks": {}}
        for m in TOL:
            div, ok = flag(m, py[m], rs[m])
            results[mode]["checks"][m] = {"python": py[m], "rust": rs[m],
                                          "divergence": div, "within_tol": ok}
            if not ok:
                any_fail = True
            print(f"{mode:<15}{m:<18}{str(py[m]):>12}{str(rs[m]):>12}"
                  f"{div:>20}  {'ok' if ok else 'FLAG'}")
        print()
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"scenario": vars(a), "results": results,
             "all_within_tolerance": not any_fail}, indent=2) + "\n")
    print("PARITY:", "all within tolerance" if not any_fail
          else "DIVERGENCES beyond tolerance (see FLAG rows)")
    return 0 if not any_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())

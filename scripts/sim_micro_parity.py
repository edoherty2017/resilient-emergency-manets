#!/usr/bin/env python3
"""Micro-scenario Python<->Rust parity harness.

Runs BOTH engines (scripts/mesh_sim.py and fastsim) on the same small
scenario with identical inputs/seed via explicit subprocess arg-lists (no
shell word-splitting), then compares the shared summary scalars.

Because the two engines use independent keyed RNG streams, exact bit-equality
is NOT expected; parity here is bounded-difference accounting. Divergences
beyond the per-metric tolerance are flagged so bucket-3 reconciliation can
target the largest ones first.

wur rows (docs/wur-design-2026-07-31.md §5, pre-registered): listing "wur"
in --modes runs it once per value of --wur-delta-db (default 0 and 55, so
the wake-budget mechanism is differentially exercised) and compares the six
shared scalars PLUS the strengthened wur metrics: wake_attempts_total,
wake_misses_total, wake_budget_fail_total, fleet consumed Wh, and overall
delivery p50. Re-run the incumbent three modes first as the baseline parity
check before trusting any wur row.

Run: .venv/bin/python scripts/sim_micro_parity.py \
       --topology artifacts/sim/topology.json \
       --routes artifacts/sim/routes.json \
       --weather artifacts/sim/weather_year.json --days 3 --seed 42 \
       --modes flood duty_sync selective_duty wur
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

# wur-row additions, pre-registered in docs/wur-design-2026-07-31.md §5:
# the six-metric gate alone is toothless for wur (deaths structurally 0/0
# and sos counts auto-pass at micro scale), so wur rows also compare wake
# accounting, fleet consumed energy, and one latency-bearing scalar.
# Expected summary keys (either engine may emit them top-level or inside
# fleet_energy): wake_attempts_total, wake_misses_total,
# wake_budget_fail_total, consumed_wh_total|fleet_consumed_wh,
# overall_delivery_latency_p50_s. duty_misses ≡ 0 in wur mode is pinned by
# runtime assertions/tests inside BOTH engines, not here.
WUR_TOL = {
    "wake_attempts_total": (None, 0.10),
    "wake_misses_total": (5, None),
    "wake_budget_fail_total": (None, 0.10),
    "fleet_consumed_wh": (None, 0.10),
    "overall_delivery_p50_s": (0.5, None),
}
ALL_TOL = {**TOL, **WUR_TOL}


def common_args(a: argparse.Namespace) -> list[str]:
    return [
        "--topology", a.topology, "--routes", a.routes,
        "--weather", a.weather, "--days", str(a.days), "--seed", str(a.seed),
        "--sos-retry", "--renters-per-route", str(a.renters),
        "--telemetry-interval-s", "3600", "--beacon-interval-s", "900",
        "--energy-step-s", "600", "--route-refresh-s", "3600",
    ]


def run_python(mode: str, a: argparse.Namespace, out: Path,
               extra: tuple[str, ...] = ()) -> None:
    subprocess.run(
        [str(PY), str(ROOT / "scripts/mesh_sim.py"), *common_args(a),
         "--kiosk-pool", "--mode", mode, *extra,
         "--trace", "", "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True)


def run_rust(mode: str, a: argparse.Namespace, out: Path,
             extra: tuple[str, ...] = ()) -> None:
    subprocess.run(
        [str(RUST), *common_args(a), "--config", str(CFG),
         "--mode", mode, *extra, "--out", str(out)],
        cwd=ROOT, check=True, capture_output=True, text=True)


def scalars(path: Path, wur: bool = False) -> dict:
    d = json.loads(path.read_text())
    fe = d.get("fleet_energy", {}) or {}
    s = d.get("sos", {}) or {}
    out = {
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
    if wur:
        def either(*keys):
            """First non-None among top-level then fleet_energy keys —
            tolerant of where each engine chose to emit the wur scalars."""
            for k in keys:
                for src in (d, fe):
                    if src.get(k) is not None:
                        return src[k]
            return None
        out.update({
            "wake_attempts_total": either("wake_attempts_total"),
            "wake_misses_total": either("wake_misses_total"),
            "wake_budget_fail_total": either("wake_budget_fail_total"),
            "fleet_consumed_wh": either("fleet_consumed_wh",
                                        "consumed_wh_total"),
            "overall_delivery_p50_s": either("overall_delivery_latency_p50_s",
                                             "overall_delivery_p50_s"),
        })
    return out


def flag(metric: str, py, rs) -> tuple[str, bool]:
    if py is None or rs is None:
        return ("absent", py is None and rs is None)
    try:
        py, rs = float(py), float(rs)
    except (TypeError, ValueError):
        return ("?", py == rs)
    abs_d = abs(py - rs)
    # symmetric denominator per plan §4.2 (docs/sim-replacement-analysis-plan.md
    # — the registered authority; conformed from the old max(|rust|, 1e-9)).
    rel_d = abs_d / max(abs(py), abs(rs), 1e-9)
    atol, rtol = ALL_TOL.get(metric, (None, 0.10))
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
    ap.add_argument("--wur-delta-db", nargs="+", type=float,
                    default=[0.0, 55.0], metavar="DB",
                    help="run each 'wur' entry of --modes once per delta, "
                         "passing --wur-delta-db through to BOTH engines "
                         "(spec §5: 0 and 55 exercise the wake budget "
                         "differentially)")
    ap.add_argument("--out", default=None,
                    help="write the full comparison JSON here")
    a = ap.parse_args(argv)

    # expand mode list into runs: wur is parameterized over the delta sweep
    runs: list[tuple[str, str, tuple[str, ...]]] = []
    for mode in a.modes:
        if mode == "wur":
            for dd in a.wur_delta_db:
                runs.append((f"wur[delta={dd:g}]", mode,
                             ("--wur-delta-db", str(dd))))
        else:
            runs.append((mode, mode, ()))

    results = {}
    any_fail = False
    tmp = Path(tempfile.mkdtemp(prefix="parity-"))
    print(f"{'mode':<16}{'metric':<24}{'python':>12}{'rust':>12}"
          f"{'divergence':>20}  flag")
    for label, mode, extra in runs:
        slug = label.replace("[delta=", "_d").replace("]", "")
        pj, rj = tmp / f"py_{slug}.json", tmp / f"rs_{slug}.json"
        try:
            run_python(mode, a, pj, extra)
            run_rust(mode, a, rj, extra)
        except subprocess.CalledProcessError as e:
            print(f"{label:<16} RUN FAILED: {e.stderr.strip().splitlines()[-1:]}")
            any_fail = True
            continue
        is_wur = mode == "wur"
        py, rs = scalars(pj, is_wur), scalars(rj, is_wur)
        results[label] = {"python": py, "rust": rs, "checks": {}}
        metrics = list(TOL) + (list(WUR_TOL) if is_wur else [])
        for m in metrics:
            div, ok = flag(m, py[m], rs[m])
            results[label]["checks"][m] = {"python": py[m], "rust": rs[m],
                                           "divergence": div, "within_tol": ok}
            if not ok:
                any_fail = True
            print(f"{label:<16}{m:<24}{str(py[m]):>12}{str(rs[m]):>12}"
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

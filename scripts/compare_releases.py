#!/usr/bin/env python3
"""Diff two corrected releases mode-by-mode.

Shows what an engine change did to the headline metrics, with the v1 CI as the
yardstick: a delta far outside the seed-level CI is an engine-behavior change,
not noise. MODEL-ONLY numbers on both sides.

Run: .venv/bin/python scripts/compare_releases.py \
       --a artifacts/sim/corrected/release_v1 --b artifacts/sim/corrected/release_v2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> dict:
    p = ROOT / rel / "corrected_stats.json"
    return json.loads(p.read_text())["modes"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", default="artifacts/sim/corrected/release_v1")
    ap.add_argument("--b", default="artifacts/sim/corrected/release_v2")
    args = ap.parse_args(argv)
    A, B = load(args.a), load(args.b)
    print(f"{'mode':<15}{'PDR a→b':<22}{'Δ':>9}{'deaths a→b':<22}{'Δ':>8}"
          f"{'SOS a→b':<16}")
    for m in A:
        if m not in B:
            print(f"{m:<15} (missing in b)")
            continue
        a, b = A[m], B[m]
        dp = b["pdr"] - a["pdr"]
        dd = b["deaths"] - a["deaths"]
        sig = "*" if abs(dp) > 3 * max(a.get("pdr_ci95", 0), 1e-6) else " "
        print(f"{m:<15}{a['pdr']:.4f} → {b['pdr']:.4f}      {dp:>+8.4f}{sig}"
              f"{a['deaths']:>9.0f} → {b['deaths']:<9.0f}{dd:>+8.0f}"
              f"  {a['sos_delivered']:.0f}/{a['sos_sent']:.0f} → "
              f"{b['sos_delivered']:.0f}/{b['sos_sent']:.0f}")
    print("\n* = |ΔPDR| exceeds 3× the v1 seed-level CI (engine change, not noise)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

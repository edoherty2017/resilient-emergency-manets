#!/usr/bin/env python3
"""Merge cellular service-layer telemetry into the RF telemetry stream.

Joins cellular_telemetry.jsonl (from cellular_ping_collector.py) onto the
GPS-bearing telemetry by timestamp (merge_asof, 35 s tolerance), fills cellular
positions from the telemetry GPS, and emits an enriched stream plus a quality
gate that flags sessions with no coverage gradient (cell_available always true or
always false → not useful for the cross-technology comparison).

Usage:
  python3 scripts/merge_cellular_into_telemetry.py \
      --telemetry /tmp/manet_ingest/meshradiohead2/jsonl/telemetry_stream.jsonl \
      --cellular  /tmp/manet_ingest/meshradiohead2/cellular_telemetry.jsonl \
      --out /tmp/manet_ingest/meshradiohead2/jsonl/telemetry_stream_cell.jsonl
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc")
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge cellular availability into telemetry")
    ap.add_argument("--telemetry", required=True)
    ap.add_argument("--cellular", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tolerance-s", type=int, default=35)
    ap.add_argument("--summary", default="artifacts/cellular/cellular_merge_summary.json")
    args = ap.parse_args()

    tele = load_jsonl(Path(args.telemetry))
    cell = load_jsonl(Path(args.cellular))
    if tele.empty:
        raise SystemExit("empty telemetry")
    if cell.empty:
        raise SystemExit("empty cellular telemetry")

    cell_cols = ["timestamp_utc", "cell_ping_rtt_ms", "cell_available", "cell_carrier", "cell_tech"]
    cell = cell[[c for c in cell_cols if c in cell.columns]].copy()

    merged = pd.merge_asof(
        tele.sort_values("timestamp_utc"),
        cell.sort_values("timestamp_utc"),
        on="timestamp_utc", direction="nearest",
        tolerance=pd.Timedelta(seconds=args.tolerance_s),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for rec in merged.to_dict(orient="records"):
            rec["timestamp_utc"] = pd.Timestamp(rec["timestamp_utc"]).isoformat()
            f.write(json.dumps(rec, default=str) + "\n")

    matched = merged["cell_available"].notna()
    n_matched = int(matched.sum())
    avail = merged.loc[matched, "cell_available"].astype(bool)
    gradient_ok = bool(avail.nunique() > 1) if n_matched else False
    rtt = pd.to_numeric(merged.get("cell_ping_rtt_ms"), errors="coerce")

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "telemetry_rows": int(len(tele)),
        "cellular_rows": int(len(cell)),
        "matched_rows": n_matched,
        "tolerance_s": args.tolerance_s,
        "cell_available_pct": float(100.0 * avail.mean()) if n_matched else None,
        "rtt_ms_p50": float(rtt.median()) if rtt.notna().any() else None,
        "rtt_ms_p95": float(rtt.quantile(0.95)) if rtt.notna().any() else None,
        "coverage_gradient_observed": gradient_ok,
        "gate": {
            "status": "PASS" if gradient_ok else "WARN",
            "rule": "cell_available must vary (both reachable and unreachable seen) for a useful comparison",
        },
        "output": str(out_path),
    }
    sp = Path(args.summary)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

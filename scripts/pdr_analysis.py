#!/usr/bin/env python3
"""Packet Delivery Ratio (PDR) analysis for controlled beacon links.

Why this exists (docs/academic-rigor-review-2026-06-12.md, P1 item 10):
RSSI-vs-distance fits on received packets are left-censored — packets below the
demodulation floor vanish, so received-only analysis is biased optimistic. With a
beacon transmitting at a KNOWN cadence, every missing packet is an observed delivery
failure, making PDR the primary, censoring-free link-quality endpoint (and a proposal
KPI: "PDR in deep ravines").

Usage (Trial 2):
    python3 scripts/pdr_analysis.py \
        --input /tmp/manet_ingest/meshradiohead2/jsonl/telemetry_stream.jsonl \
        --beacon-node-id '!abcd1234' \
        --beacon-interval-s 30 \
        --trial-id trial2 \
        --head-gpx artifacts/gpx/trial2_head.gpx

The beacon node MUST be configured with a fixed broadcast interval and its true
cadence recorded in the field log; --beacon-interval-s is ground truth, not an
estimate. Expected-count windows start at the first received beacon packet.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for a binomial proportion (returned as fractions)."""
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(center - half, 0.0), min(center + half, 1.0))


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)


def load_garmin_gpx(path: Path) -> pd.DataFrame:
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    rows = []
    for p in root.findall(f".//{prefix}trkpt"):
        time_el = p.find(f"{prefix}time")
        if time_el is None:
            continue
        ele_el = p.find(f"{prefix}ele")
        rows.append({
            "timestamp_utc": pd.Timestamp(time_el.text).tz_convert("UTC"),
            "rx_lat": float(p.get("lat")),
            "rx_lon": float(p.get("lon")),
            "rx_elev_m": float(ele_el.text) if ele_el is not None else np.nan,
        })
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="PDR vs distance/terrain for a fixed-cadence beacon link")
    ap.add_argument("--input", required=True, help="Receiver-side telemetry JSONL")
    ap.add_argument("--beacon-node-id", required=True, help="from_mesh_id of the beacon transmitter")
    ap.add_argument("--beacon-interval-s", type=float, required=True,
                    help="Ground-truth beacon cadence (from field log), seconds")
    ap.add_argument("--beacon-lat", type=float, default=None, help="Surveyed beacon latitude (static node)")
    ap.add_argument("--beacon-lon", type=float, default=None, help="Surveyed beacon longitude (static node)")
    ap.add_argument("--beacon-elev-m", type=float, default=None, help="Surveyed beacon elevation (m)")
    ap.add_argument("--head-gpx", default=None, help="Receiver GPX track for distance computation")
    ap.add_argument("--trial-id", default=None)
    ap.add_argument("--window-s", type=float, default=300.0, help="Aggregation window (seconds)")
    ap.add_argument("--direct-only", action="store_true", default=True,
                    help="Count only hops_away==0 packets as delivered (default true)")
    ap.add_argument("--out-dir", default="artifacts/pdr")
    args = ap.parse_args()

    df = load_jsonl(Path(args.input))
    if df.empty:
        raise SystemExit("no telemetry rows")
    if args.trial_id and "trial_id" in df.columns:
        df = df[df["trial_id"] == args.trial_id].copy()

    if "from_mesh_id" not in df.columns:
        raise SystemExit("telemetry lacks from_mesh_id; cannot attribute beacon packets")
    bx = df[df["from_mesh_id"].astype(str) == str(args.beacon_node_id)].copy()
    if bx.empty:
        raise SystemExit(f"no packets from beacon {args.beacon_node_id}")

    # Direct-link filter: a relayed beacon packet is not a delivery on the
    # measured link. Requires collector hop fields (hop_start/hop_limit).
    hop_limit = pd.to_numeric(bx.get("hop_limit"), errors="coerce")
    hop_start = pd.to_numeric(bx.get("hop_start"), errors="coerce")
    bx["hops_away"] = hop_start - hop_limit
    hop_data_available = bool(bx["hops_away"].notna().any())
    if args.direct_only and hop_data_available:
        bx = bx[bx["hops_away"] == 0].copy()
    if bx.empty:
        raise SystemExit("no direct-link beacon packets after hop filter")

    # De-duplicate retransmissions/mesh duplicates: packets closer together than
    # half the beacon interval count once.
    bx = bx.sort_values("timestamp_utc")
    gap = bx["timestamp_utc"].diff().dt.total_seconds()
    bx = bx[(gap.isna()) | (gap > args.beacon_interval_s / 2.0)].copy()

    # Receiver position for distance stratification.
    if args.head_gpx:
        gpx = load_garmin_gpx(Path(args.head_gpx))
        bx = pd.merge_asof(
            bx.sort_values("timestamp_utc"),
            gpx,
            on="timestamp_utc",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=60),
        )
    else:
        bx["rx_lat"] = pd.to_numeric(bx.get("lat"), errors="coerce")
        bx["rx_lon"] = pd.to_numeric(bx.get("lon"), errors="coerce")
        bx["rx_elev_m"] = pd.to_numeric(bx.get("elev_m"), errors="coerce")

    if args.beacon_lat is not None and args.beacon_lon is not None:
        def link_dist(r):
            if pd.isna(r.get("rx_lat")) or pd.isna(r.get("rx_lon")):
                return np.nan
            d2 = haversine_m(args.beacon_lat, args.beacon_lon, r["rx_lat"], r["rx_lon"])
            if args.beacon_elev_m is not None and pd.notna(r.get("rx_elev_m")):
                return math.sqrt(d2 ** 2 + (args.beacon_elev_m - r["rx_elev_m"]) ** 2)
            return d2
        bx["distance_m"] = bx.apply(link_dist, axis=1)
    else:
        bx["distance_m"] = np.nan

    bx["topography_class"] = pd.cut(
        pd.to_numeric(bx.get("rx_elev_m"), errors="coerce"),
        bins=[-np.inf, 1200, 1500, np.inf],
        labels=["valley_forest", "sub_alpine", "alpine_ridge"],
    ).astype(str)
    bx["distance_bin"] = pd.cut(
        bx["distance_m"],
        bins=[0, 500, 1000, 2000, 5000, np.inf],
        labels=["0-0.5km", "0.5-1km", "1-2km", "2-5km", "5km+"],
    ).astype(str)

    # Windowed PDR: expected = window_s / beacon_interval_s (continuous-operation
    # assumption — the observation span is anchored to received packets, so windows
    # before the first / after the last reception are NOT counted as losses; that
    # is conservative for coverage claims and stated in the output).
    t0, t1 = bx["timestamp_utc"].min(), bx["timestamp_utc"].max()
    span_s = (t1 - t0).total_seconds()
    expected_per_window = args.window_s / args.beacon_interval_s
    bx["window_idx"] = ((bx["timestamp_utc"] - t0).dt.total_seconds() // args.window_s).astype(int)

    win_rows = []
    n_windows = int(span_s // args.window_s) + 1
    by_win = bx.groupby("window_idx")
    for w in range(n_windows):
        grp = by_win.get_group(w) if w in by_win.groups else bx.iloc[0:0]
        expected = max(int(round(expected_per_window)), 1)
        received = min(int(len(grp)), expected)
        lo, hi = wilson_ci(received, expected)
        win_rows.append({
            "window_idx": w,
            "window_start_utc": (t0 + pd.Timedelta(seconds=w * args.window_s)).isoformat(),
            "expected": expected,
            "received": received,
            "pdr": received / expected,
            "pdr_wilson95_lo": lo,
            "pdr_wilson95_hi": hi,
            "median_distance_m": float(grp["distance_m"].median()) if grp["distance_m"].notna().any() else None,
            "topography_class": grp["topography_class"].mode().iat[0] if len(grp) else "unknown",
            "distance_bin": grp["distance_bin"].mode().iat[0] if len(grp) else "unknown",
            "median_rssi_dbm": float(pd.to_numeric(grp.get("rssi_dbm"), errors="coerce").median()) if len(grp) else None,
            "median_snr_db": float(pd.to_numeric(grp.get("snr_db"), errors="coerce").median()) if len(grp) else None,
        })
    windows = pd.DataFrame(win_rows)

    # Stratified PDR: per distance_bin x topography_class over received-window strata.
    strat_rows = []
    for (dbin, topo), grp in windows[windows["received"] > 0].groupby(["distance_bin", "topography_class"]):
        exp_total = int(grp["expected"].sum())
        rec_total = int(grp["received"].sum())
        lo, hi = wilson_ci(rec_total, exp_total)
        strat_rows.append({
            "distance_bin": dbin,
            "topography_class": topo,
            "n_windows": int(len(grp)),
            "expected": exp_total,
            "received": rec_total,
            "pdr": rec_total / exp_total if exp_total else None,
            "pdr_wilson95_lo": lo,
            "pdr_wilson95_hi": hi,
            "meets_min_n": exp_total >= 30,
        })
    strat = pd.DataFrame(strat_rows)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    windows.to_csv(out_dir / "pdr_windows.csv", index=False)
    strat.to_csv(out_dir / "pdr_stratified.csv", index=False)

    exp_total = int(windows["expected"].sum())
    rec_total = int(windows["received"].sum())
    lo, hi = wilson_ci(rec_total, exp_total)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "beacon_node_id": args.beacon_node_id,
        "beacon_interval_s": args.beacon_interval_s,
        "window_s": args.window_s,
        "hop_data_available": hop_data_available,
        "direct_only_applied": bool(args.direct_only and hop_data_available),
        "observation_span_s": span_s,
        "n_windows": n_windows,
        "expected_total": exp_total,
        "received_total": rec_total,
        "pdr_overall": rec_total / exp_total if exp_total else None,
        "pdr_overall_wilson95": [lo, hi],
        "caveats": [
            "expected counts assume continuous beacon operation between first and last reception",
            "windows are temporally autocorrelated; stratified CIs are per-stratum descriptive",
            "without hop telemetry, relayed packets inflate PDR" if not hop_data_available else None,
        ],
    }
    summary["caveats"] = [c for c in summary["caveats"] if c]
    (out_dir / "pdr_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

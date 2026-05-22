#!/usr/bin/env python3
"""Mesh neighbor catalog — multi-source RF propagation observation builder.

Reads JSONL from all nodes in the ingest root. For every received packet that
has both RSSI/SNR and resolvable GPS for source AND receiver, emits a complete
propagation observation: (from_pos, to_pos, distance_m, rssi_dbm, snr_db).

Source position: backward merge_asof against that node's POSITION_APP history.
Receiver position: backward merge_asof against the recording node's own
  POSITION_APP history (is_own_node=True rows).

Outputs:
  artifacts/mesh_catalog/observations.parquet   — full join table
  artifacts/mesh_catalog/node_summary.json      — per-node stats
  artifacts/mesh_catalog/catalog_summary.json   — run-level stats
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fspl_db(distance_m: float, freq_mhz: float) -> float:
    d_km = max(distance_m / 1000.0, 1e-6)
    return 32.44 + 20 * math.log10(d_km) + 20 * math.log10(freq_mhz)


def git_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    except Exception:
        return "unknown"


def load_jsonl(path: Path, recorder_node_id: str) -> pd.DataFrame:
    rows = []
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                r = json.loads(line)
                r["_recorder"] = recorder_node_id
                rows.append(r)
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)


def asof_join_positions(obs: pd.DataFrame, pos: pd.DataFrame,
                        obs_key: str, pos_key: str,
                        suffix: str, tolerance_s: int) -> pd.DataFrame:
    """For each row in obs, find the last row in pos where pos[pos_key] == obs[obs_key]
    and pos.timestamp_utc <= obs.timestamp_utc within tolerance."""
    tol = pd.Timedelta(seconds=tolerance_s)
    result_parts = []

    pos_cols = ["timestamp_utc", pos_key, "lat", "lon", "elev_m"]
    pos_clean = pos[[c for c in pos_cols if c in pos.columns]].dropna(subset=["lat", "lon"]).copy()
    pos_clean = pos_clean.rename(columns={
        "lat": f"lat_{suffix}",
        "lon": f"lon_{suffix}",
        "elev_m": f"elev_m_{suffix}",
        "timestamp_utc": f"ts_pos_{suffix}",
    })

    for key_val, grp_obs in obs.groupby(obs_key, sort=False):
        grp_pos = pos_clean[pos_clean[pos_key] == key_val].sort_values(f"ts_pos_{suffix}")
        if grp_pos.empty:
            result_parts.append(grp_obs)
            continue
        merged = pd.merge_asof(
            grp_obs.sort_values("timestamp_utc"),
            grp_pos.drop(columns=[pos_key]),
            left_on="timestamp_utc",
            right_on=f"ts_pos_{suffix}",
            direction="backward",
            tolerance=tol,
        )
        result_parts.append(merged)

    if not result_parts:
        return obs
    return pd.concat(result_parts, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root",         default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--ingest-root",  default="/home/doher/manet_ingest")
    ap.add_argument("--trial-id",     default=None, help="Filter to specific trial_id (default: all)")
    ap.add_argument("--freq-mhz",     type=float, default=915.0)
    ap.add_argument("--tolerance-s",  type=int,   default=30,
                    help="Max age of position fix to pair with an RF observation (seconds)")
    ap.add_argument("--min-obs",      type=int,   default=5,
                    help="Minimum observations per source node to include in catalog")
    args = ap.parse_args()

    root       = Path(args.root)
    ingest     = Path(args.ingest_root)
    out_dir    = root / "artifacts/mesh_catalog"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Discover all node JSONL files
    all_frames: list[pd.DataFrame] = []
    for node_dir in sorted(ingest.iterdir()):
        jsonl = node_dir / "jsonl" / "telemetry_stream.jsonl"
        if jsonl.exists():
            df = load_jsonl(jsonl, recorder_node_id=node_dir.name)
            if not df.empty:
                all_frames.append(df)
                print(f"  loaded {len(df):,} rows from {node_dir.name}")

    if not all_frames:
        raise SystemExit(f"no JSONL files found under {ingest}")

    all_df = pd.concat(all_frames, ignore_index=True)

    if args.trial_id:
        all_df = all_df[all_df.get("trial_id", pd.Series()) == args.trial_id]
        if all_df.empty:
            raise SystemExit(f"no rows for trial_id={args.trial_id}")

    # Coerce key columns
    for col in ("rssi_dbm", "snr_db", "lat", "lon", "elev_m"):
        if col in all_df.columns:
            all_df[col] = pd.to_numeric(all_df[col], errors="coerce")

    if "from_mesh_id" not in all_df.columns:
        raise SystemExit("from_mesh_id column missing — collector may be outdated")

    # --- Build position timeline (all POSITION_APP packets from any node) ---
    pos_df = all_df[
        all_df["portnum"].str.contains("POSITION", na=False) &
        all_df["lat"].notna() & all_df["lon"].notna()
    ][["timestamp_utc", "from_mesh_id", "lat", "lon", "elev_m"]].copy()

    # --- Build own-node position timeline (receiver positions) ---
    own_pos_df = all_df[
        all_df.get("is_own_node", pd.Series(dtype=bool)) == True
    ][["timestamp_utc", "_recorder", "lat", "lon", "elev_m"]].dropna(subset=["lat", "lon"]).copy() \
        if "is_own_node" in all_df.columns else pd.DataFrame()

    # --- RF observations: packets with RSSI (excludes own POSITION_APP retransmits) ---
    obs_df = all_df[all_df["rssi_dbm"].notna()].copy()
    obs_df = obs_df[obs_df["from_mesh_id"].notna()].copy()

    print(f"\n  {len(pos_df):,} position packets from {pos_df['from_mesh_id'].nunique()} unique nodes")
    print(f"  {len(obs_df):,} RF observations (with RSSI)")
    print(f"  {obs_df['from_mesh_id'].nunique()} unique source nodes observed")

    # --- Join source positions ---
    print("\n  joining source positions...")
    obs_with_src = asof_join_positions(
        obs_df, pos_df,
        obs_key="from_mesh_id", pos_key="from_mesh_id",
        suffix="src", tolerance_s=args.tolerance_s,
    )

    # --- Join receiver positions ---
    if not own_pos_df.empty:
        print("  joining receiver positions...")
        obs_joined = asof_join_positions(
            obs_with_src, own_pos_df,
            obs_key="_recorder", pos_key="_recorder",
            suffix="rx", tolerance_s=args.tolerance_s,
        )
    else:
        obs_joined = obs_with_src.copy()
        for col in ("lat_rx", "lon_rx", "elev_m_rx"):
            obs_joined[col] = np.nan
        print("  WARNING: no own-node positions found — rx position column will be null")
        print("  (pair phones with nodes before trial to populate rx positions)")

    # --- Compute distance and FSPL for complete observations ---
    complete = obs_joined.dropna(subset=["lat_src", "lon_src", "lat_rx", "lon_rx"]).copy()
    if complete.empty:
        print("\n  WARNING: no complete observations (source + receiver GPS both resolved)")
        print("  Partial catalog written — run again after collecting position data.")
    else:
        complete["distance_m"] = complete.apply(
            lambda r: haversine_m(r["lat_src"], r["lon_src"], r["lat_rx"], r["lon_rx"]), axis=1
        )
        complete["fspl_db"] = complete["distance_m"].apply(lambda d: fspl_db(d, args.freq_mhz))
        complete["pred_rssi_dbm"] = 20.0 - complete["fspl_db"]
        complete["residual_db"] = complete["rssi_dbm"] - complete["pred_rssi_dbm"]

    # --- Per-node summary ---
    node_summary: dict[str, dict] = {}
    all_source_ids = obs_df["from_mesh_id"].dropna().unique()
    for node_id in sorted(all_source_ids):
        node_obs = obs_df[obs_df["from_mesh_id"] == node_id]
        node_complete = complete[complete["from_mesh_id"] == node_id] if not complete.empty else pd.DataFrame()
        node_pos = pos_df[pos_df["from_mesh_id"] == node_id]

        last_pos = node_pos.sort_values("timestamp_utc").iloc[-1] if not node_pos.empty else None
        node_summary[node_id] = {
            "total_rf_observations":    int(len(node_obs)),
            "complete_observations":    int(len(node_complete)),
            "position_packets":         int(len(node_pos)),
            "last_known_lat":           float(last_pos["lat"])   if last_pos is not None else None,
            "last_known_lon":           float(last_pos["lon"])   if last_pos is not None else None,
            "last_known_elev_m":        float(last_pos["elev_m"]) if last_pos is not None and pd.notna(last_pos.get("elev_m")) else None,
            "rssi_dbm_mean":            float(node_obs["rssi_dbm"].mean()) if node_obs["rssi_dbm"].notna().any() else None,
            "rssi_dbm_min":             float(node_obs["rssi_dbm"].min())  if node_obs["rssi_dbm"].notna().any() else None,
            "distance_m_mean":          float(node_complete["distance_m"].mean()) if not node_complete.empty else None,
            "residual_db_mean":         float(node_complete["residual_db"].mean()) if not node_complete.empty else None,
        }

    # --- Save outputs ---
    if not complete.empty:
        keep_cols = [c for c in [
            "timestamp_utc", "from_mesh_id", "_recorder", "trial_id",
            "lat_src", "lon_src", "elev_m_src",
            "lat_rx",  "lon_rx",  "elev_m_rx",
            "distance_m", "rssi_dbm", "snr_db",
            "fspl_db", "pred_rssi_dbm", "residual_db",
            "portnum", "is_own_node",
        ] if c in complete.columns]
        complete[keep_cols].to_parquet(out_dir / "observations.parquet", index=False)
        print(f"\n  wrote {len(complete):,} complete observations → {out_dir}/observations.parquet")

    node_summary_path = out_dir / "node_summary.json"
    node_summary_path.write_text(json.dumps(node_summary, indent=2, default=str))

    catalog_summary = {
        "generated_at_utc":       datetime.now(timezone.utc).isoformat(),
        "git_commit":             git_commit(root),
        "ingest_root":            str(ingest),
        "trial_id_filter":        args.trial_id,
        "tolerance_seconds":      args.tolerance_s,
        "freq_mhz":               args.freq_mhz,
        "total_rf_observations":  int(len(obs_df)),
        "unique_source_nodes":    int(obs_df["from_mesh_id"].nunique()),
        "nodes_with_gps":         int(sum(1 for n in node_summary.values() if n["last_known_lat"] is not None)),
        "complete_observations":  int(len(complete)) if not complete.empty else 0,
        "distance_m_min":         float(complete["distance_m"].min()) if not complete.empty else None,
        "distance_m_max":         float(complete["distance_m"].max()) if not complete.empty else None,
        "rssi_dbm_mean":          float(complete["rssi_dbm"].mean())  if not complete.empty else None,
        "rssi_dbm_std":           float(complete["rssi_dbm"].std())   if not complete.empty else None,
        "residual_db_rmse":       float(np.sqrt((complete["residual_db"] ** 2).mean())) if not complete.empty else None,
    }
    (out_dir / "catalog_summary.json").write_text(json.dumps(catalog_summary, indent=2, default=str))

    # Human-readable summary
    print(f"\n{'='*60}")
    print(f"  Mesh Neighbor Catalog")
    print(f"{'='*60}")
    print(f"  Source nodes observed:    {catalog_summary['unique_source_nodes']}")
    print(f"  Nodes with GPS:           {catalog_summary['nodes_with_gps']}")
    print(f"  Complete observations:     {catalog_summary['complete_observations']}")
    if not complete.empty:
        print(f"  Distance range:           {catalog_summary['distance_m_min']:.0f}m – {catalog_summary['distance_m_max']:.0f}m")
        print(f"  Mean RSSI:                {catalog_summary['rssi_dbm_mean']:.1f} dBm")
        print(f"  FSPL residual RMSE:       {catalog_summary['residual_db_rmse']:.2f} dB")
    print(f"\n  Per-node breakdown ({len(node_summary)} nodes):")
    for nid, s in sorted(node_summary.items(), key=lambda x: -x[1]["total_rf_observations"]):
        pos_str = f"({s['last_known_lat']:.4f}, {s['last_known_lon']:.4f})" if s["last_known_lat"] else "no GPS"
        rssi_str = f"{s['rssi_dbm_mean']:.1f} dBm" if s["rssi_dbm_mean"] else "—"
        print(f"    {nid:<16}  {s['total_rf_observations']:4d} obs  {s['complete_observations']:4d} complete  "
              f"rssi={rssi_str}  pos={pos_str}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

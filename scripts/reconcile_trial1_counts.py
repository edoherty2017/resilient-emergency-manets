#!/usr/bin/env python3
"""Reconcile the two Trial 1 populations (686/50 hike-map vs 764/41 mesh catalog).

Audit ledger 2026-07-13 §3 (Medium): "Trial 1 populations still disagree
(686 vs 764 records; 50 vs 41 IDs)."

Root cause (verified by this script): the two numbers were never one population.
  * 686 / 50  = hike_data_map.py over the 2026-05-23 Mt Washington AFTERNOON hike
                window (>=16:24 UTC), counting ALL packet types (rssi optional).
  * 764 / 41  = mesh_neighbor_catalog.py snapshot generated 2026-05-23 02:34 UTC
                (BEFORE the hike) over the pre-hike soak / 05-20..21 range test,
                unioning two recorders and requiring rssi_dbm + from_mesh_id.

The single canonical decoded receiver log reproduces BOTH the 686/50 hike numbers
and the 41-node catalog set exactly. The exact 764 union additionally needs the
DECODED head recorder stream, which is not present locally (see MISSING below).

Run:
  python3 scripts/reconcile_trial1_counts.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
# Canonical decoded receiver export (has from_mesh_id); reproduces the hike map.
RX = REPO / "data/raw-telemetry-export/20260524T112222Z/remote_meshhikernode1/telemetry_stream.jsonl"
NODE_SUMMARY = REPO / "artifacts/mesh_catalog/node_summary.json"

HIKE_DATE = "2026-05-23"
ACTIVE_START_UTC = "2026-05-23T16:24"   # collector reconnected 12:24 EDT
CATALOG_GEN_UTC = "2026-05-23T02:34"    # catalog_summary.generated_at_utc


def load(path: Path) -> pd.DataFrame:
    rows = []
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return pd.DataFrame(rows)


def main() -> int:
    df = load(RX)
    ts = df["timestamp_utc"].astype(str)

    # --- HIKE MAP population (hike_data_map.load_hike_records) ---
    hike = df[ts.str.startswith(HIKE_DATE) & (ts >= ACTIVE_START_UTC)]
    hike_records = len(hike)
    hike_ids = set(hike["from_mesh_id"].dropna())
    hike_rssi_rows = int(hike["rssi_dbm"].notna().sum())

    # --- CATALOG population reproduced on this single recorder ---
    pre = df[ts < CATALOG_GEN_UTC]
    pre_obs = pre[pre["rssi_dbm"].notna() & pre["from_mesh_id"].notna()]
    cat_ids_repro = set(pre_obs["from_mesh_id"])

    cat_ids = set(json.loads(NODE_SUMMARY.read_text()).keys())

    print(f"HIKE MAP  : records={hike_records} (expect 686)  unique_ids={len(hike_ids)} (expect 50)")
    print(f"            rows carrying rssi_dbm = {hike_rssi_rows}")
    print(f"CATALOG   : node_summary ids={len(cat_ids)} (expect 41)  "
          f"sum_obs={sum(v['total_rf_observations'] for v in json.loads(NODE_SUMMARY.read_text()).values())} (expect 764)")
    print(f"REPRO     : hikernode pre-hike rssi rows={len(pre_obs)}  ids={len(cat_ids_repro)}")
    print(f"            reproduced catalog id set == node_summary id set: {cat_ids_repro == cat_ids}")

    print("\nID reconciliation:")
    print(f"  in BOTH hike & catalog     : {len(hike_ids & cat_ids)}")
    print(f"  hike-only (afternoon nodes): {len(hike_ids - cat_ids)}")
    print(f"  catalog-only (pre-hike)    : {len(cat_ids - hike_ids)}")

    ok = (hike_records == 686 and len(hike_ids) == 50 and cat_ids_repro == cat_ids)
    print(f"\nRECONCILED: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

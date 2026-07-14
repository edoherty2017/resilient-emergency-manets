"""Regression test for the Trial 1 population reconciliation.

Locks the two disagreeing Trial 1 populations and their overlap so the
686/50 vs 764/41 discrepancy (audit ledger 2026-07-13 §3) stays reconciled:

  * 686 records / 50 unique IDs  -- hike-map afternoon window
  * 764 RF observations / 41 IDs -- pre-hike mesh catalog
  * 18 IDs in both, 32 hike-only, 23 catalog-only

It also verifies the canonical input checksums recorded in the provenance
file still match the live inputs, and that reconcile_trial1_counts.main()
exits 0 (reconciled).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile_trial1_counts as rc  # noqa: E402

PROVENANCE = ROOT / "artifacts/coverage_prediction/reconcile_trial1_provenance.json"


def _populations():
    """Re-derive both populations using the reconcile script's own loader/constants."""
    df = rc.load(rc.RX)
    ts = df["timestamp_utc"].astype(str)

    hike = df[ts.str.startswith(rc.HIKE_DATE) & (ts >= rc.ACTIVE_START_UTC)]
    hike_records = len(hike)
    hike_ids = set(hike["from_mesh_id"].dropna())

    node_summary = json.loads(rc.NODE_SUMMARY.read_text())
    cat_ids = set(node_summary.keys())
    cat_obs = sum(v["total_rf_observations"] for v in node_summary.values())

    return hike_records, hike_ids, cat_ids, cat_obs


def test_hike_map_population_is_686_over_50_ids():
    hike_records, hike_ids, _, _ = _populations()
    assert hike_records == 686
    assert len(hike_ids) == 50


def test_catalog_population_is_764_observations_over_41_ids():
    _, _, cat_ids, cat_obs = _populations()
    assert cat_obs == 764
    assert len(cat_ids) == 41


def test_id_split_is_18_both_32_hike_only_23_catalog_only():
    _, hike_ids, cat_ids, _ = _populations()
    assert len(hike_ids & cat_ids) == 18
    assert len(hike_ids - cat_ids) == 32
    assert len(cat_ids - hike_ids) == 23


def test_reconcile_main_exits_zero():
    assert rc.main() == 0


def test_provenance_checksums_match_live_inputs():
    prov = json.loads(PROVENANCE.read_text())
    for rel, recorded in prov["inputs_sha256"].items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == recorded, f"checksum drift for {rel}"

    expected = prov["expected_counts"]
    hike_records, hike_ids, cat_ids, cat_obs = _populations()
    assert expected["hike_map_records"] == hike_records == 686
    assert expected["hike_map_unique_ids"] == len(hike_ids) == 50
    assert expected["catalog_rf_observations"] == cat_obs == 764
    assert expected["catalog_unique_ids"] == len(cat_ids) == 41
    assert expected["ids_in_both"] == len(hike_ids & cat_ids) == 18
    assert expected["hike_only"] == len(hike_ids - cat_ids) == 32
    assert expected["catalog_only"] == len(cat_ids - hike_ids) == 23

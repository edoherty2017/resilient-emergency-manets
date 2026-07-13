#!/usr/bin/env python3
"""Exclude optimistic short-link-policy edges from legacy sim inputs.

The legacy topology replaced certain sub-1.35 km ITM losses with FSPL+26 dB
only when the replacement was less lossy. That is an optimistic model-selection
rule with no independent calibration. This migration preserves the former
active value and a freshly computed diagnostic ITM value, while setting the
active simulator loss to 300 dB until field calibration supports another rule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, itm_p2p_loss  # noqa: E402


EXCLUDED_LINK_DB = 300.0


def migrate_topology(
    topology: dict[str, Any],
    diagnostic_loss: Callable[[str, str], dict[str, float]],
) -> tuple[dict[str, Any], dict[frozenset[str], dict[str, float]]]:
    migrated: dict[frozenset[str], dict[str, float]] = {}
    for key, link in topology["links"].items():
        if link.get("model") not in {
            "short_link_fspl",
            "short_link_fspl_unvalidated_opt_in",
        }:
            continue
        left, right = key.split("|")
        diagnostic = diagnostic_loss(left, right)
        superseded = {
            "loss_db_q50": float(link["loss_db_q50"]),
            "loss_db_q90": float(link["loss_db_q90"]),
            "model": link["model"],
            "status": "UNVALIDATED_OPTIMISTIC_POLICY_EXCLUDED",
        }
        link["superseded_short_link_policy"] = superseded
        link["short_link_diagnostic"] = {
            "itm_loss_db_q50": float(diagnostic["loss_db_q50"]),
            "itm_loss_db_q90": float(diagnostic["loss_db_q90"]),
            "field_calibrated": False,
        }
        link["loss_db_q50"] = EXCLUDED_LINK_DB
        link["loss_db_q90"] = EXCLUDED_LINK_DB
        link["model"] = "excluded_unvalidated_short_link"
        link["simulation_eligible"] = False
        migrated[frozenset((left, right))] = {
            "policy_rssi_dbm_q50": (
                float(topology["radio"]["rx_power_reference_dbm"])
                - superseded["loss_db_q50"]
            ),
            "policy_rssi_dbm_q90": (
                float(topology["radio"]["rx_power_reference_dbm"])
                - superseded["loss_db_q90"]
            ),
            "diagnostic_itm_rssi_dbm_q50": (
                float(topology["radio"]["rx_power_reference_dbm"])
                - float(diagnostic["loss_db_q50"])
            ),
            "diagnostic_itm_rssi_dbm_q90": (
                float(topology["radio"]["rx_power_reference_dbm"])
                - float(diagnostic["loss_db_q90"])
            ),
        }
    topology["short_link_policy_correction"] = {
        "corrected_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_excluded_links": len(migrated),
        "active_excluded_loss_db": EXCLUDED_LINK_DB,
        "reason": (
            "The FSPL+26 dB replacement was selected only when less lossy than "
            "ITM and had no independent field calibration. Values are preserved "
            "per link but excluded from simulation until calibrated."
        ),
    }
    return topology, migrated


def migrate_matrix(
    matrix: pd.DataFrame,
    migrated: dict[frozenset[str], dict[str, float]],
    receiver_reference_dbm: float,
) -> pd.DataFrame:
    result = matrix.copy()
    if "planning_evidence_eligible" not in result:
        result["planning_evidence_eligible"] = True
    for index, row in result.iterrows():
        endpoints = frozenset(str(row["link"]).split("<->"))
        if endpoints not in migrated:
            continue
        details = migrated[endpoints]
        result.at[index, "path_type"] = "excluded_unvalidated_short_link"
        result.at[index, "pred_rssi_dbm_q50"] = receiver_reference_dbm - EXCLUDED_LINK_DB
        result.at[index, "pred_rssi_dbm_q90"] = receiver_reference_dbm - EXCLUDED_LINK_DB
        result.at[index, "usable_q90"] = False
        result.at[index, "planning_ok_q90"] = False
        result.at[index, "planning_evidence_eligible"] = False
        for name, value in details.items():
            result.at[index, name] = round(value, 3)
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value))
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", action="append", default=None)
    args = parser.parse_args(argv)
    suffixes = args.suffix or ["", "_statewide"]

    for suffix in suffixes:
        topology_path = ROOT / f"artifacts/sim/topology{suffix}.json"
        matrix_path = ROOT / f"artifacts/sim/link_matrix{suffix}.csv"
        topology = json.loads(topology_path.read_text())
        dem = Dem(ROOT / topology["dem"])
        sites = topology["sites"]

        def diagnostic(left: str, right: str) -> dict[str, float]:
            a, b = sites[left], sites[right]
            distance, profile = dem.profile(a["lat"], a["lon"], b["lat"], b["lon"])
            result = itm_p2p_loss(
                distance / 1000.0,
                profile,
                (float(a["hg_m"]), float(b["hg_m"])),
            )
            return {
                "loss_db_q50": float(result["loss_db_q50"]),
                "loss_db_q90": float(result["loss_db_q90"]),
            }

        topology, migrated = migrate_topology(topology, diagnostic)
        matrix = migrate_matrix(
            pd.read_csv(matrix_path),
            migrated,
            float(topology["radio"]["rx_power_reference_dbm"]),
        )
        atomic_json(topology_path, topology)
        matrix.to_csv(matrix_path, index=False)
        print(f"{suffix or '(base)'}: excluded {len(migrated)} short links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

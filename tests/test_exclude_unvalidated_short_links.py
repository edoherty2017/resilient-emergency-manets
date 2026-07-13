from __future__ import annotations

import pandas as pd

from scripts.exclude_unvalidated_short_links import migrate_matrix, migrate_topology


def test_optimistic_short_link_is_preserved_but_excluded() -> None:
    topology = {
        "radio": {"rx_power_reference_dbm": 26.3},
        "links": {
            "a|b": {
                "loss_db_q50": 80.0,
                "loss_db_q90": 80.0,
                "model": "short_link_fspl",
            },
            "b|c": {"loss_db_q50": 90.0, "loss_db_q90": 95.0, "model": "itm"},
        },
    }
    migrated_topology, migrated = migrate_topology(
        topology,
        lambda _a, _b: {"loss_db_q50": 140.0, "loss_db_q90": 150.0},
    )
    link = migrated_topology["links"]["a|b"]

    assert link["model"] == "excluded_unvalidated_short_link"
    assert link["loss_db_q50"] == 300.0
    assert link["superseded_short_link_policy"]["loss_db_q50"] == 80.0
    assert link["short_link_diagnostic"]["itm_loss_db_q90"] == 150.0
    assert migrated_topology["links"]["b|c"]["loss_db_q50"] == 90.0

    matrix = pd.DataFrame(
        [
            {
                "link": "b<->a",
                "path_type": "short_link_policy",
                "pred_rssi_dbm_q50": -53.7,
                "pred_rssi_dbm_q90": -53.7,
                "usable_q90": True,
                "planning_ok_q90": True,
            }
        ]
    )
    corrected = migrate_matrix(matrix, migrated, 26.3)
    assert corrected.loc[0, "planning_evidence_eligible"] == False  # noqa: E712
    assert corrected.loc[0, "pred_rssi_dbm_q90"] == -273.7
    assert corrected.loc[0, "policy_rssi_dbm_q90"] == -53.7

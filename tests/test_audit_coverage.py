from __future__ import annotations

import pandas as pd
import pytest

from scripts.audit_coverage import audit_tier, connectivity, trail_coverage


SITES = {
    "gateway": {"mqtt_uplink": True},
    "relay": {"mqtt_uplink": False},
}


def test_sensitivity_can_pass_while_planning_gate_fails() -> None:
    links = pd.DataFrame(
        [{"link": "gateway<->relay", "pred_rssi_dbm_q90": -110.0}]
    )
    routes = {
        "route": {
            "loss_t_s": [0, 1],
            "loss_db_q50": {"relay": [135.0, 135.0]},
        }
    }

    sensitivity = audit_tier(SITES, links, routes, -131.0, 0.85)
    planning = audit_tier(SITES, links, routes, -100.0, 0.85)

    assert sensitivity["verdict"] == "PASS"
    assert planning["verdict"] == "FAIL"
    assert planning["stranded_sites"] == ["relay"]
    assert planning["trail_coverage"][0]["estimate_quantile"] == "loss_db_q50"


def test_trail_gate_uses_only_gateway_reachable_sites() -> None:
    routes = {
        "route": {
            "loss_t_s": [0, 1],
            "loss_db_q50": {
                "gateway": [120.0, 140.0],
                "stranded_nearby": [20.0, 20.0],
            },
        }
    }
    rows = trail_coverage(routes, {"gateway"}, -100.0, 0.75)

    assert rows[0]["coverage"] == 0.5
    assert rows[0]["reachable_candidate_sites"] == 1
    assert rows[0]["ok"] is False


def test_connectivity_rejects_unknown_link_endpoint() -> None:
    links = pd.DataFrame(
        [{"link": "gateway<->invented", "pred_rssi_dbm_q90": -50.0}]
    )
    with pytest.raises(ValueError, match="unknown sites"):
        connectivity(SITES, links, -100.0)


def test_controlling_gate_can_exclude_unvalidated_short_link_policy() -> None:
    links = pd.DataFrame(
        [
            {
                "link": "gateway<->relay",
                "pred_rssi_dbm_q90": -50.0,
                "path_type": "short_link_policy",
            }
        ]
    )

    assumed = connectivity(SITES, links, -100.0, allow_short_link_policy=True)
    strict = connectivity(SITES, links, -100.0, allow_short_link_policy=False)

    assert assumed["stranded_sites"] == []
    assert strict["stranded_sites"] == ["relay"]
    assert strict["n_excluded_short_link_policy"] == 1


def test_counterfactual_uses_preserved_policy_value_after_input_migration() -> None:
    links = pd.DataFrame(
        [
            {
                "link": "gateway<->relay",
                "pred_rssi_dbm_q90": -273.7,
                "policy_rssi_dbm_q90": -60.0,
                "path_type": "excluded_unvalidated_short_link",
                "planning_evidence_eligible": False,
            }
        ]
    )
    result = connectivity(SITES, links, -100.0, allow_short_link_policy=True)
    assert result["stranded_sites"] == []
    assert result["n_assumed_short_link_policy"] == 1

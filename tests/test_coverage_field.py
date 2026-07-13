from __future__ import annotations

import numpy as np

from scripts.coverage_field import (
    _reachable_sites_from_audit,
    _state_mask,
    contiguous_range_m,
)


def test_service_polygon_does_not_fill_interior_radio_shadow() -> None:
    distances = np.array([100.0, 200.0, 300.0, 400.0])
    # The ray recovers at 400 m, but a simple radial polygon cannot represent
    # the 300 m hole and must stop conservatively at 200 m.
    rssi = np.array([-80.0, -95.0, -105.0, -90.0])
    assert contiguous_range_m(distances, rssi, -100.0) == 200.0


def test_reachable_sites_come_from_controlling_planning_tier() -> None:
    audit = {
        "planning_screen": {
            "components": [
                {
                    "reaches_backhaul": True,
                    "members": ["gateway", "relay_a"],
                },
                {"reaches_backhaul": False, "members": ["relay_b"]},
            ]
        }
    }
    assert _reachable_sites_from_audit(audit) == {"gateway", "relay_a"}


def test_state_mask_excludes_polygon_exterior() -> None:
    boundary = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
        ],
    }
    mask = _state_mask(np.array([1.0, 3.0]), np.array([1.0]), boundary)
    assert mask[:, 0].tolist() == [True, False]

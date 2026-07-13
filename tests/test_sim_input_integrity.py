from __future__ import annotations

import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "artifacts/sim"


@pytest.mark.parametrize("suffix", ["", "_statewide"])
def test_topology_and_route_inputs_are_internally_consistent(suffix: str):
    topology = json.loads((SIM / f"topology{suffix}.json").read_text())
    route_document = json.loads((SIM / f"routes{suffix}.json").read_text())
    routes = route_document["routes"]
    sites = topology["sites"]

    assert topology["claim_status"].startswith("MODELED_UNVERIFIED")
    assert topology["retrospective_provenance"]["original_generator_sha256"] is None
    assert route_document["claim_status"] == "MODELED_NOT_FIELD_OBSERVED"
    assert route_document["total_itm_error_substitutions"] == 0
    assert re.fullmatch(
        r"[0-9a-f]{64}", route_document["source_inputs"]["dem"]["sha256"]
    )

    radio = topology["radio"]
    assert "eirp_dbm" not in radio
    assert radio["tx_eirp_dbm"] == pytest.approx(24.15)
    assert radio["rx_power_reference_dbm"] == pytest.approx(26.3)

    for key, link in topology["links"].items():
        left, right = key.split("|")
        assert left in sites and right in sites and left != right
        assert math.isfinite(float(link["loss_db_q50"]))
        assert link.get("model") not in {
            "short_link_fspl",
            "short_link_fspl_unvalidated_opt_in",
        }
        if link.get("model") == "excluded_unvalidated_short_link":
            assert link["simulation_eligible"] is False
            assert link["loss_db_q50"] == 300.0
            assert link["superseded_short_link_policy"]["status"].endswith(
                "POLICY_EXCLUDED"
            )

    assert routes
    for name, route in routes.items():
        assert route["kiosk"] in sites, name
        assert route["return_kiosk"] in sites, name
        assert route["geometry"] in {"osm", "mixed_osm_chord", "chord"}
        provenance = route["geometry_provenance"]
        assert provenance["routed_legs"] + provenance["chord_fallback_legs"] >= 1
        if route["geometry"] == "osm":
            assert provenance["chord_fallback_legs"] == 0
        assert route["itm_error_substitutions"] == 0
        assert len(route["t_s"]) == len(route["lat"]) == len(route["lon"])
        assert len(route["t_s"]) >= 2
        assert all(b > a for a, b in zip(route["t_s"], route["t_s"][1:]))
        assert all(b > a for a, b in zip(route["loss_t_s"], route["loss_t_s"][1:]))
        assert set(route["loss_db_q50"]) == set(sites)
        for losses in route["loss_db_q50"].values():
            assert len(losses) == len(route["loss_t_s"])
            assert all(math.isfinite(float(value)) for value in losses)


def test_weather_input_is_complete_pinned_reanalysis():
    weather = json.loads((SIM / "weather_year.json").read_text())
    assert weather["source"] == "Open-Meteo Historical Weather API"
    assert weather["source_kind"] == "reanalysis"
    assert weather["model_requested"] == "era5"
    assert weather["not_station_measurements"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", weather["api_response_sha256"])
    assert weather["n_days"] == len(weather["days"]) == 365

    dates = [date.fromisoformat(day["date"]) for day in weather["days"]]
    assert dates == [dates[0] + timedelta(days=i) for i in range(len(dates))]
    assert weather["start_date"] == dates[0].isoformat()
    assert weather["end_date"] == dates[-1].isoformat()
    for day in weather["days"]:
        assert 0.0 < float(day["kt"]) <= 0.95
        assert float(day["snowfall_cm"]) >= 0.0
        assert day["cloud_pct"] is not None
        assert day["temp_c"] is not None

"""Sanity tests for the simulation layer (solar model + mesh sim + routing)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import solar_model  # noqa: E402

TOPO = ROOT / "artifacts/sim/topology.json"
CFG = ROOT / "config/sim/wmnf_sim.yaml"

needs_topo = pytest.mark.skipif(not TOPO.exists(), reason="run build_sim_topology.py first")


def _cfg():
    import yaml
    return yaml.safe_load(CFG.read_text())


def test_solar_position_noon_summer():
    # Local solar noon ≈ 16:45 UTC at lon −71.3; sun high in late June
    elev, az = solar_model.solar_position(44.27, -71.3,
                                          datetime(2026, 6, 21, 16, 45, tzinfo=timezone.utc))
    assert 65 < elev < 72
    assert 150 < az < 210


def test_solar_zero_at_night():
    elev, _ = solar_model.solar_position(44.27, -71.3,
                                         datetime(2026, 6, 21, 6, 0, tzinfo=timezone.utc))
    assert solar_model.clear_sky_ghi(elev) == 0.0 or elev < 5


def test_daily_wh_seasonal_ordering():
    cfg = _cfg()["solar"]
    hz = np.zeros(48)
    june = solar_model.daily_solar_wh(44.27, -71.3,
                                      datetime(2026, 6, 21, tzinfo=timezone.utc), 0.5, hz, cfg)
    dec = solar_model.daily_solar_wh(44.27, -71.3,
                                     datetime(2026, 12, 21, tzinfo=timezone.utc), 0.5, hz, cfg)
    assert june > 2 * dec > 0


def test_horizon_shading_reduces_energy():
    cfg = _cfg()["solar"]
    when = datetime(2026, 7, 10, tzinfo=timezone.utc)
    open_sky = solar_model.daily_solar_wh(44.27, -71.3, when, 0.5, np.zeros(48), cfg)
    # July midday sun is ~66° here, so a 35° wall only clips mornings/evenings;
    # a 70° canyon blocks direct beam all day, leaving only sky diffuse — which
    # for flat geometry is exactly the Erbs-style diffuse fraction of GHI.
    ravine = solar_model.daily_solar_wh(44.27, -71.3, when, 0.5, np.full(48, 35.0), cfg)
    canyon = solar_model.daily_solar_wh(44.27, -71.3, when, 0.5, np.full(48, 70.0), cfg)
    assert canyon < ravine < open_sky
    assert canyon == pytest.approx(solar_model.diffuse_fraction(0.5) * open_sky, rel=0.02)


@needs_topo
def test_mesh_sim_one_day_invariants():
    from mesh_sim import run_sim
    s = run_sim(days=1, seed=123)
    assert 0.0 <= s["pdr_overall"] <= 1.0
    assert s["channel_utilization"] < 0.5
    # grid nodes never die; every packet delivered has non-negative latency
    for n, st in s["per_node"].items():
        if st["power"] == "grid":
            assert st["deaths"] == 0 and st["final_soc"] == 1.0
    for o in s["per_origin"].values():
        if o["latency_p50_s"] is not None:
            assert o["latency_p50_s"] >= 0.0


@needs_topo
def test_energy_aware_uses_less_airtime():
    from mesh_sim import run_sim
    f = run_sim(days=1, seed=123, mode="flood")
    e = run_sim(days=1, seed=123, mode="energy_aware")
    assert e["channel_utilization"] < f["channel_utilization"]


@needs_topo
def test_route_enumeration_reaches_gateways():
    from train_energy_router import enumerate_routes
    cfg = _cfg()
    topo = json.loads(TOPO.read_text())
    routes, _ = enumerate_routes(topo, cfg["radio"], cfg["shadowing"]["sigma_db"])
    origins = {r[0] for r in routes}
    assert {"ammo_relay", "jewell_relay", "lakes_hut"} <= origins
    gateways = {n for n, s in topo["sites"].items() if s.get("mqtt_uplink")}
    assert all(r[-1] in gateways for r in routes)

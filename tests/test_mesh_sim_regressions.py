"""Regression tests for simulator mechanics that can bias conclusions."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mesh_sim  # noqa: E402


def _cfg() -> dict:
    import yaml

    cfg = copy.deepcopy(yaml.safe_load(
        (ROOT / "config/sim/wmnf_sim.yaml").read_text()))
    cfg["shadowing"].update(sigma_db=0.0, fast_fading_db=0.0)
    return cfg


def _topo(*, solar: set[str] | None = None) -> dict:
    solar = solar or set()
    sites = {}
    for i, name in enumerate(("a", "b", "c")):
        sites[name] = {
            "lat": 44.0 + i * 0.001,
            "lon": -71.0,
            "elev_m": 1200.0,
            "power": "solar" if name in solar else "grid",
            "mqtt_uplink": False,
            "horizon_deg": [0.0] * 48,
        }
    links = {
        "a|b": {"loss_db_q50": 100.0},
        "a|c": {"loss_db_q50": 100.0},
        "b|c": {"loss_db_q50": 100.0},
    }
    return {"sites": sites, "links": links, "hiker": None}


def _pkt(origin: str, packet_id: int) -> dict:
    return {"id": packet_id, "origin": origin, "kind": "tel", "bytes": 40,
            "hop_limit": 0, "dest": "nobody"}


def test_radio_reference_supports_canonical_and_legacy_config():
    canonical = {"tx_eirp_dbm": 24.15, "rx_antenna_gain_dbi": 2.15,
                 "rx_feed_loss_db": 0.0}
    legacy = {"eirp_dbm": 26.3}
    assert mesh_sim.radio_rx_reference_dbm(canonical) == pytest.approx(26.3)
    assert mesh_sim.radio_rx_reference_dbm(legacy) == pytest.approx(26.3)


def _collision_run(order: tuple[str, str]):
    sim = mesh_sim.MeshSim(_topo(), _cfg(), mode="flood", days=0.001, seed=7)
    for packet_id, sender in enumerate(order, 1):
        sim.env.process(sim.transmit(sim.nodes[sender], _pkt(sender, packet_id)))
    sim.env.run()
    sim.days = sim.env.now / 86400.0
    return sim, sim.summary()


def test_equal_simultaneous_packets_collide_independent_of_insertion_order():
    ab, summary_ab = _collision_run(("a", "b"))
    ba, summary_ba = _collision_run(("b", "a"))

    assert ab.nodes["c"].stats["rx_ok"] == ba.nodes["c"].stats["rx_ok"] == 0
    assert ab.nodes["c"].stats["collisions"] == 2
    assert ba.nodes["c"].stats["collisions"] == 2
    assert summary_ab["per_node"]["c"] == summary_ba["per_node"]["c"]


def test_offered_airtime_is_distinct_from_union_local_occupancy():
    _, summary = _collision_run(("a", "b"))

    # Two exactly overlapping transmissions offer 2x airtime while every
    # receiver observes only one interval's worth of physical busy time.
    assert summary["aggregate_offered_airtime_ratio"] == pytest.approx(2.0)
    assert summary["channel_utilization"] == pytest.approx(2.0)
    assert summary["channel_occupancy"]["receiver_busy_ratio_max"] == pytest.approx(1.0)


def test_local_busy_union_clips_an_open_interval_to_run_horizon():
    sim = mesh_sim.MeshSim(_topo(), _cfg(), seed=9)
    sim.record_channel_busy("a", 0.0, 2.0)
    sim.record_channel_busy("a", 0.5, 1.0)
    sim.record_channel_busy("a", 5.0, 10.0)
    assert sim.channel_busy_through("a", 7.0) == pytest.approx(4.0)


def _one_duty_tx(start: float):
    sim = mesh_sim.MeshSim(_topo(), _cfg(), mode="duty_sync", days=0.001, seed=11)
    sim.nodes["c"].duty = 0.05
    sim.nodes["c"].wake_phase_s = 0.0

    def delayed():
        yield sim.env.timeout(start)
        yield from sim.transmit(sim.nodes["a"], _pkt("a", 1))

    sim.env.process(delayed())
    sim.env.run()
    return sim


def test_duty_cad_has_deterministic_hits_and_misses():
    missed = _one_duty_tx(0.20)
    detected = _one_duty_tx(0.95)

    assert missed.nodes["c"].stats["rx_ok"] == 0
    assert missed.nodes["c"].stats["duty_misses"] == 1
    assert detected.nodes["c"].stats["rx_ok"] == 1
    assert detected.nodes["c"].stats["duty_misses"] == 0


def test_trace_sampling_cannot_change_model_results(tmp_path: Path):
    def run(rate: float, path: Path) -> dict:
        sim = mesh_sim.MeshSim(_topo(), _cfg(), mode="flood", days=0.001,
                               seed=19, trace_path=path,
                               rx_trace_sample=rate)

        def traffic():
            for packet_id in range(1, 8):
                yield from sim.transmit(sim.nodes["a"], _pkt("a", packet_id))
                yield sim.env.timeout(0.25)

        sim.env.process(traffic())
        sim.env.run()
        sim.trace_fh.close()
        sim.trace_fh = None
        sim.days = sim.env.now / 86400.0
        return sim.summary()

    sparse = run(0.0, tmp_path / "sparse.jsonl")
    full = run(1.0, tmp_path / "full.jsonl")
    assert sparse == full


def test_algorithm_rng_consumption_cannot_shift_traffic_or_incidents():
    flood = mesh_sim.MeshSim(_topo(), _cfg(), mode="flood", seed=21)
    learned = mesh_sim.MeshSim(_topo(), _cfg(), mode="q_routing", seed=21)

    # Model an algorithm consuming arbitrarily more MAC/policy randomness.
    flood.rng_for("mac", "a").random(500)
    flood.rng_for("policy", "q_routing").random(500)
    flood.rng_for("incidents", "day:0").random(5)  # e.g. skipped/extra selector draws

    assert np.array_equal(
        flood.rng_for("traffic", "telemetry:a").random(20),
        learned.rng_for("traffic", "telemetry:a").random(20),
    )
    assert np.array_equal(
        flood.rng_for("incidents", "day:1").random(20),
        learned.rng_for("incidents", "day:1").random(20),
    )


def test_exogenous_traffic_clock_does_not_wait_for_mac_service():
    def origin_times(mac_delay: float) -> list[float]:
        sim = mesh_sim.MeshSim(_topo(), _cfg(), mode="flood", seed=22,
                               telemetry_interval_s=10.0)
        times: list[float] = []
        real_new_pkt = sim.new_pkt

        def recording_new_pkt(*args, **kwargs):
            times.append(sim.env.now)
            return real_new_pkt(*args, **kwargs)

        def delayed_send(_node, _pkt):
            yield sim.env.timeout(mac_delay)

        sim.new_pkt = recording_new_pkt
        sim.csma_send = delayed_send
        sim.env.process(sim.gen_fixed_telemetry(sim.nodes["a"]))
        sim.env.run(until=100.0)
        return times

    assert origin_times(0.0) == origin_times(25.0)


def test_latency_reservoir_samples_the_whole_run():
    sim = mesh_sim.MeshSim(_topo(), _cfg(), seed=23)
    for latency in range(10_000):
        sim.aggregate_packet({"origin": "a", "kind": "tel", "delivered": True,
                              "latency_s": float(latency)})

    agg = sim.agg["a"]
    assert agg["latency_observations"] == 10_000
    assert len(agg["lat"]) == mesh_sim.LATENCY_RESERVOIR_SIZE
    assert max(agg["lat"]) > 9_000
    assert np.median(agg["lat"]) == pytest.approx(5_000, abs=350)


def test_death_events_are_separate_from_dead_time_and_availability():
    sim = mesh_sim.MeshSim(_topo(solar={"a"}), _cfg(), days=100 / 86400.0,
                           seed=29)
    node = sim.nodes["a"]

    def transitions():
        yield sim.env.timeout(10.0)
        sim.mark_dead(node)
        yield sim.env.timeout(20.0)
        node.soc_wh = 0.1 * node.cap_wh
        sim.mark_alive(node)
        yield sim.env.timeout(30.0)
        sim.mark_dead(node)

    sim.env.process(transitions())
    sim.env.run(until=100.0)
    summary = sim.summary()

    assert summary["fleet_energy"]["death_events_total"] == 2
    assert summary["fleet_energy"]["unique_nodes_died"] == 1
    assert summary["fleet_energy"]["dead_time_s_total"] == pytest.approx(60.0)
    assert summary["fleet_energy"]["availability"] == pytest.approx(0.4)
    assert summary["per_node"]["a"]["dead_time_s"] == pytest.approx(60.0)


def test_kiosk_charge_does_not_debit_bank_when_radio_is_full():
    sim = mesh_sim.MeshSim(_topo(), _cfg(), energy_step_s=60.0, seed=31)
    radio = sim.nodes["a"]
    radio.power = "battery"
    radio.docked = True
    radio.kiosk = "box"
    sim.kiosk_banks = {"box": {"soc_wh": 10.0, "cap_wh": 10.0}}

    sim.env.process(sim.energy_process())
    sim.env.run(until=60.1)
    assert sim.kiosk_banks["box"]["soc_wh"] == pytest.approx(10.0)

    radio.soc_wh = radio.cap_wh - 0.05
    sim.env.run(until=120.1)
    assert radio.soc_wh == pytest.approx(radio.cap_wh)
    assert sim.kiosk_banks["box"]["soc_wh"] == pytest.approx(9.95)


def test_kiosk_checkout_rejects_undercharged_radio():
    sim = mesh_sim.MeshSim(_topo(), _cfg(), kiosk_pool=True, seed=37)
    radio = sim.nodes["a"]
    radio.power = "battery"
    radio.docked = True
    radio.kiosk = "box"
    radio.soc_wh = 0.1 * radio.cap_wh
    dead_radio = sim.nodes["b"]
    dead_radio.power = "battery"
    dead_radio.docked = True
    dead_radio.kiosk = "box"
    dead_radio.alive = False
    route = {"duration_s": 60.0, "lat": [44.0], "lon": [-71.0],
             "t_s": [0.0], "loss_t_s": [0.0], "loss_db_q50": {}}
    walker = {"name": "w", "route": route, "start_s": 0.0,
              "kiosk": "box", "return_kiosk": "box"}

    sim.env.process(sim.kiosk_dispatch(walker))
    sim.env.run(until=0.1)
    assert sim.rental_stats["walker_days"] == 1
    assert sim.rental_stats["served"] == 0
    assert sim.rental_stats["starved"] == 1
    assert sim.rental_stats["unusable_at_checkout"] == 2
    assert sim.rental_stats["starved_unserviceable"] == 1


def test_routing_solar_forecast_does_not_use_realized_full_day_weather():
    weather_dark = {"start_date": "2026-07-10",
                    "days": [{"kt": 0.01, "snow_factor": 0.1}]}
    weather_bright = {"start_date": "2026-07-10",
                      "days": [{"kt": 0.99, "snow_factor": 1.0}]}
    sim_dark = mesh_sim.MeshSim(_topo(solar={"a"}), _cfg(), weather=weather_dark,
                                seed=41)
    sim_bright = mesh_sim.MeshSim(_topo(solar={"a"}), _cfg(), weather=weather_bright,
                                  seed=41)

    assert sim_dark._kt_for_day(0) != sim_bright._kt_for_day(0)
    assert sim_dark.solar_remaining_wh(sim_dark.nodes["a"], 12 * 3600) == pytest.approx(
        sim_bright.solar_remaining_wh(sim_bright.nodes["a"], 12 * 3600))


def test_sos_burst_ids_and_absolute_retry_schedule():
    sim = mesh_sim.MeshSim(_topo(), _cfg(), sos_retry=True, seed=43)
    node = sim.nodes["a"]
    sent: list[tuple[float, int, int]] = []

    def fake_send(_node, pkt):
        sent.append((sim.env.now, pkt["id"], pkt["sos_id"]))
        yield sim.env.timeout(0.0)

    sim.csma_send = fake_send
    sim.env.process(sim.send_sos_incident(node, node.name))
    sim.env.run(until=601.0)

    assert [t for t, _, _ in sent[:5]] == [0.0, 30.0, 60.0, 300.0, 600.0]
    assert len({packet_id for _, packet_id, _ in sent[:3]}) == 1
    assert sent[3][1] != sent[0][1] and sent[4][1] != sent[3][1]
    assert len({sos_id for _, _, sos_id in sent}) == 1
    assert next(iter(sim.sos_incidents.values()))["tries"] == 3


def test_cli_accepts_fractional_days_for_smoke_runs(tmp_path, monkeypatch):
    captured = {}

    def fake_run_sim(**kwargs):
        captured.update(kwargs)
        return {"pdr_overall": 1.0, "link_health": [], "per_node": {}}

    monkeypatch.setattr(mesh_sim, "ROOT", tmp_path)
    monkeypatch.setattr(mesh_sim, "run_sim", fake_run_sim)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mesh_sim.py", "--days", "0.02", "--trace", "", "--out", "summary.json"],
    )

    assert mesh_sim.main() == 0
    assert captured["days"] == pytest.approx(0.02)
    assert (tmp_path / "summary.json").is_file()

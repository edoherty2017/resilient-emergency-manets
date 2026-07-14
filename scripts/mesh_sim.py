#!/usr/bin/env python3
"""Discrete-event simulation of the WMNF LoRa mesh (SimPy).

Layers:
  PHY   — per-packet RSSI = EIRP − ITM q50 loss (topology.json) + slow lognormal
          shadowing (Gauss-Markov) + fast fading. Reception requires
          RSSI ≥ sensitivity AND SNR ≥ SF11 demod threshold; overlapping
          transmissions at a receiver collide unless the strongest wins by the
          capture threshold; half-duplex.
  MAC   — CSMA: carrier-sense + slotted random backoff. Rebroadcasts use the
          Meshtastic managed-flood contention window (better SNR → longer
          wait, so the farthest node relays first) and are CANCELLED if the
          same packet is overheard again while waiting (duplicate suppression).
  NET   — two pluggable modes:
            flood         Meshtastic managed flooding with hop_limit
            energy_aware  source routing (Dijkstra) with energy-cost edges:
                          airtime energy × battery-scarcity × solar-poverty —
                          the analytic baseline the ML router learns to beat
  ENERGY— continuous RX-listen drain + per-TX energy at 3.7 V; solar charging
          from solar_model (real DEM horizon shading, daily clearness index);
          grid-powered sites never die; battery nodes die at 0% and revive at
          5% on solar.

Traffic: fixed nodes send telemetry; the hiker replays the real Trial 1 GPX
daily (position beacons + one SOS per day). Destination for everything is any
MQTT-uplinked gateway (summit Sherman Adams / Cog Marshfield).

Run: .venv/bin/python scripts/mesh_sim.py --mode flood --days 3
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import simpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lora_airtime import airtime_ms  # noqa: E402
import solar_model  # noqa: E402

SLOT_S = 0.040          # CSMA slot ≈ 5 symbol times at SF11/BW250
CARRIER_SENSE_DBM = -124.0
BAT_TRACE_S = 300.0
REVIVE_FRACTION = 0.05
KIOSK_CHARGE_W = 10.0   # trailhead charging-box output per docked node
T_SNIFF_S = 1.0         # CAD/preamble-sampling period for duty-cycled modes
CAD_MIN_SYMBOLS = 2.0    # receiver must observe this much preamble to lock
KIOSK_MIN_CHECKOUT_SOC = 0.20  # operational reserve; configurable per run config
LATENCY_RESERVOIR_SIZE = 2000
ROUTED_MODES = ("min_hop", "etx", "energy_aware", "lb_energy",
                "duty_sync", "duty_adaptive", "rotate_lb",
                "q_routing", "rl_duty", "selective_duty")
DUTY_MODES = ("duty_sync", "duty_adaptive", "rotate_lb", "rl_duty",
              "selective_duty")
LEARNED_MODES = ("q_routing", "rl_duty")


# ── Support models ───────────────────────────────────────────────────────────
def radio_rx_reference_dbm(radio: dict) -> float:
    """Terminal-gain reference used in ``Pr = reference - basic loss``.

    Canonical configs separate true transmit EIRP from receive antenna/feed
    terms. ``eirp_dbm`` remains a backward-compatible fallback for older files
    where it actually contained the combined TX+RX link-budget reference.
    """
    if "tx_eirp_dbm" in radio:
        return (float(radio["tx_eirp_dbm"])
                + float(radio.get("rx_antenna_gain_dbi", 0.0))
                - float(radio.get("rx_feed_loss_db", 0.0)))
    return float(radio["eirp_dbm"])


class Shadowing:
    """Slow lognormal shadowing per node pair (Gauss-Markov), plus fast fading."""

    def __init__(self, sigma_db, fast_db, coherence_s, rng):
        self.sigma, self.fast, self.tau, self.rng = sigma_db, fast_db, coherence_s, rng
        self.state: dict[frozenset, tuple[float, float]] = {}

    def sample(self, a: str, b: str, t: float) -> float:
        return self.batch(a, [b], t)[0]

    def batch(self, a: str, names: list, t: float) -> list:
        """One vectorized RNG draw for all receivers of a transmission."""
        n = len(names)
        z = self.rng.standard_normal(2 * n)
        out = []
        for i, b in enumerate(names):
            key = (a, b) if a < b else (b, a)
            st = self.state.get(key)
            if st is None:
                val = z[i] * self.sigma
            else:
                val0, t0 = st
                rho = math.exp(-max(t - t0, 0.0) / self.tau)
                val = rho * val0 + math.sqrt(1.0 - rho * rho) * self.sigma * z[i]
            self.state[key] = (val, t)
            out.append(val + self.fast * z[n + i])
        return out


class LinkModel:
    """Median ITM loss between any two nodes at time t (fixed sites + movers)."""

    def __init__(self, topo: dict):
        self.links = topo["links"]
        self.hiker = topo["hiker"]

    def fixed_loss(self, a: str, b: str) -> float | None:
        e = self.links.get(f"{a}|{b}") or self.links.get(f"{b}|{a}")
        return e["loss_db_q50"] if e else None

    def hiker_loss(self, site: str, track_t: float) -> float:
        h = self.hiker
        return float(np.interp(track_t, h["t_s"], h["loss_db_q50"][site]))


# ── Node ─────────────────────────────────────────────────────────────────────
class Node:
    def __init__(self, name, site, cfg, horizon):
        self.name = name
        self.lat, self.lon = site["lat"], site["lon"]
        self.power = site.get("power", "battery")
        self.mqtt = bool(site.get("mqtt_uplink"))
        self.horizon = horizon
        # mounting model: forest sites get canopy-filtered pyramid panels
        elev = site.get("elev_m", 2000.0)
        if self.power == "solar":
            solar_cfg = cfg["solar"]
            self.site_solar = {
                "geometry": "pyramid", "tilt_deg": solar_cfg["pyramid_tilt_deg"],
                "canopy_tau": (solar_cfg["canopy_tau_16ft"] if elev < 1100.0 else 1.0),
            }
        else:
            self.site_solar = None
        self.route = None          # rental nodes: route dict from routes.json
        self.start_s = None        # daily checkout time (sim s past midnight)
        self.docked = False        # in the charging box (radio off, charging)
        bat = cfg["battery"]
        self.cap_wh = bat["capacity_wh"] * bat["usable_fraction"]
        self.soc_wh = self.cap_wh * bat["start_soc"]
        self.alive = True
        self.seen: set = set()
        self.pending_rebroadcast: dict = {}
        self.tx_until = -1.0
        self.fwd_ewma = 0.0        # relay-burden tracker (lb_energy)
        self.death_score = 0.0     # decaying death memory (lb_energy)
        self.duty = 1.0            # listen duty cycle (duty-cycled modes)
        self.wake_phase_s = 0.0    # deterministic CAD phase within T_SNIFF_S
        self.dead_since_s: float | None = None
        self.dead_time_s = 0.0
        self.ever_died = False
        self.stats = {"tx": 0, "rx_ok": 0, "collisions": 0, "dup_suppressed": 0,
                      "tx_airtime_s": 0.0, "energy_tx_wh": 0.0, "deaths": 0,
                      "solar_wh": 0.0, "duty_misses": 0}


# ── Simulation ───────────────────────────────────────────────────────────────
class MeshSim:
    def __init__(self, topo, cfg, mode="flood", days=None, seed=None,
                 extra_hikers=0, beacon_interval_s=None, hop_limit=None,
                 trace_path: Path | None = None, always_beacon=False,
                 routes: dict | None = None, renters_per_route: int = 3,
                 rx_trace_sample: float = 1.0, bat_trace_s: float = BAT_TRACE_S,
                 pos_trace_s: float | None = None, energy_step_s: float | None = None,
                 weather: dict | None = None, telemetry_interval_s: float | None = None,
                 route_refresh_s: float = 900.0, sos_retry: bool = False,
                 kiosk_pool: bool = False, kiosk_spares: int = 2,
                 kiosk_demand_scale: float | None = None,
                 hiker_trace_sample: float = 1.0):
        self.always_beacon = always_beacon
        self.telemetry_interval_s = telemetry_interval_s
        self.routes = routes
        self.rx_trace_sample = rx_trace_sample
        self.bat_trace_s = bat_trace_s
        self.pos_trace_s = pos_trace_s if pos_trace_s is not None else bat_trace_s
        self.energy_step_s = energy_step_s
        self.topo, self.cfg, self.mode = topo, cfg, mode
        self.days = float(days or cfg["sim"]["duration_days"])  # fractions OK
        self.seed = int(seed if seed is not None else cfg["sim"]["seed"])
        # Independent, name-keyed streams keep observation/trace choices from
        # perturbing the modeled system and keep each phenomenon stable when a
        # different routing algorithm consumes a different number of draws.
        self._rngs: dict[tuple[str, str], np.random.Generator] = {}
        self.rng = self.rng_for("legacy")  # compatibility for external experiments
        self.env = simpy.Environment()
        self.radio = cfg["radio"]
        self.rx_power_reference_dbm = radio_rx_reference_dbm(self.radio)
        self.hop_limit = hop_limit if hop_limit is not None else self.radio["hop_limit"]
        self.noise_dbm = -174.0 + 10 * math.log10(self.radio["bw_hz"]) + self.radio["noise_figure_db"]
        self.shadow = Shadowing(cfg["shadowing"]["sigma_db"], cfg["shadowing"]["fast_fading_db"],
                                cfg["shadowing"]["coherence_s"],
                                self.rng_for("rf_shadow"))
        self.linkmodel = LinkModel(topo)
        self.start_utc = datetime.fromisoformat(cfg["sim"]["start_date"]).replace(tzinfo=timezone.utc)
        self.beacon_interval_s = beacon_interval_s or cfg["traffic"]["position_interval_s"]
        self.kiosk_pool = kiosk_pool
        self.kiosk_spares = kiosk_spares
        self.hiker_trace_sample = hiker_trace_sample
        self.walkers: list = []            # kiosk-pool walker definitions
        self.walker_radio: dict = {}       # walker name -> radio name (today)
        self.rental_stats = {"walker_days": 0, "served": 0, "starved": 0,
                             "starved_no_stock": 0,
                             "starved_unserviceable": 0,
                             "unusable_at_checkout": 0, "checkout_socs": []}

        self.nodes: dict[str, Node] = {}
        for name, s in topo["sites"].items():
            self.nodes[name] = Node(name, s, cfg, np.array(s["horizon_deg"]))
        # Hiker(s): node 0 replays the real GPX; extras are static walkers pinned
        # to random track waypoints (storm-sweep load generators).
        h = topo.get("hiker")
        self.hiker_names = []
        proxy = topo["sites"].get("ammo_relay") or next(iter(topo["sites"].values()))
        hz_valley = np.array(proxy["horizon_deg"])  # proxy horizon for movers
        if h:
            for k in range(1 + extra_hikers):
                name = "hiker_alpha" if k == 0 else f"hiker_{k:02d}"
                site = {"lat": h["lat"][0], "lon": h["lon"][0], "power": "battery"}
                self.nodes[name] = Node(name, site, cfg, hz_valley)
                self.nodes[name].track_offset = (0.0 if k == 0 else float(
                    self.rng_for("mobility", name).uniform(0, h["t_s"][-1])))
                self.hiker_names.append(name)
        # rental fleet: renters_per_route staggered checkouts per route per day
        if routes and not kiosk_pool:
            for rname, r in routes["routes"].items():
                for k in range(renters_per_route):
                    name = f"rent_{rname}_{k}"
                    site = {"lat": r["lat"][0], "lon": r["lon"][0], "power": "battery"}
                    nd = Node(name, site, cfg, hz_valley)
                    nd.route = r
                    nd.start_s = (11.5 + 1.5 * k) * 3600.0   # 07:30/09:00/10:30 ET
                    nd.docked = True
                    self.nodes[name] = nd
                    self.hiker_names.append(name)
        elif routes and kiosk_pool:
            # kiosk inventories: demand tiers from real AMC usage data,
            # capped at kiosk capacity; walkers draw best-charge radio
            kc = cfg.get("kiosk", {})
            cap = kc.get("capacity", 20)
            TIER_A = {"franconia_ridge_loop", "tuckerman_loop",
                      "monadnock_white_dot", "ammo_jewell_loop"}
            TIER_B = {"lonesome_lake_family", "carter_wildcat",
                      "crawford_traverse", "valley_way_madison",
                      "pack_monadnock_loop", "kearsarge_winslow",
                      "cardigan_west_ridge", "chocorua_piper"}
            # real-scale AMC demand by default; --kiosk-demand-scale pins the
            # fleet explicitly (0.25 ≈ the 50-walker fleet of the mega8 runs,
            # for arena comparability with traces from before 2026-07-08)
            scale = (kiosk_demand_scale if kiosk_demand_scale is not None
                     else renters_per_route / 2.0)
            kiosk_load: dict = {}
            for rname, r in sorted(routes["routes"].items()):
                tier = (kc.get("demand_tier_a", 20) if rname in TIER_A else
                        kc.get("demand_tier_b", 10) if rname in TIER_B else
                        kc.get("demand_tier_c", 4))
                n_walk = max(1, round(tier * scale))
                for k in range(n_walk):
                    self.walkers.append({
                        "name": f"walker_{rname}_{k}", "route": r,
                        "route_name": rname,
                        "start_s": (11.0 + 6.0 * k / max(n_walk, 1)) * 3600.0,
                        "kiosk": r["kiosk"], "return_kiosk": r["return_kiosk"]})
                    kiosk_load[r["kiosk"]] = kiosk_load.get(r["kiosk"], 0) + 1
            self.kiosk_banks = {}
            for kiosk, n_walkers in kiosk_load.items():
                self.kiosk_banks[kiosk] = {
                    "soc_wh": kc.get("battery_wh", 1000.0),
                    "cap_wh": kc.get("battery_wh", 1000.0)}
                ks = topo["sites"].get(kiosk)
                base = ({"lat": ks["lat"], "lon": ks["lon"]} if ks
                        else {"lat": 44.0, "lon": -71.5})
                for i in range(min(n_walkers + kiosk_spares, cap)):
                    name = f"radio_{kiosk}_{i}"
                    nd = Node(name, {**base, "power": "battery"}, cfg, hz_valley)
                    nd.docked = True
                    nd.kiosk = kiosk
                    self.nodes[name] = nd
                    self.hiker_names.append(name)

        self.active_tx: list[dict] = []   # in-flight transmissions
        self.channel_busy_closed_s: dict[str, float] = {}
        self.channel_busy_open: dict[str, tuple[float, float]] = {}
        self.pkt_seq = 0
        self.pkt_meta: dict = {}
        self.delivered: set = set()
        self.trace_fh = open(trace_path, "w") if trace_path else None
        self.summary_rows = []
        self.total_airtime_s = 0.0
        self.daily_kt: list[float] = []
        self.route_next: dict = {}
        self.route_cost: dict = {}
        self.route_tree_t = -1e9
        self.route_refresh_s = route_refresh_s
        self._fwd_median = 0.0
        self.fleet_soc_series: list = []
        # learned-control state (q_routing / rl_duty)
        self.qrt: dict[str, dict[str, float]] | None = None   # Q[u][v] cost-to-gw
        self.qduty: dict = {}                                  # Q[(state, duty)]
        self.rl_updates = 0
        # static fixed-site adjacency (margin dB) for the routed modes
        self.fixed_adj: dict[str, list] = {}
        eirp, sens = self.rx_power_reference_dbm, self.radio["rx_sensitivity_dbm"]
        for key, l in topo["links"].items():
            a, b = key.split("|")
            margin = eirp - l["loss_db_q50"] - sens
            if margin < 3.0:
                continue
            self.fixed_adj.setdefault(a, []).append((b, margin))
            self.fixed_adj.setdefault(b, []).append((a, margin))
        # link-health ledger between fixed sites: attempts/successes/margins
        self.link_health: dict[tuple, dict] = {}
        self.agg: dict = {}          # pruned per-origin stats (year-scale runs)
        self.sos_log: list = []
        self.sos_retry = sos_retry
        self.sos_acked: set = set()  # sos pkt ids ACKed back to the originator
        self.sos_incidents: dict = {}  # sos_id -> {t0, tries, delivered, first_latency}
        # historical reanalysis weather (fetch_weather_year.py): per-day kt + snow
        self.weather = weather["days"] if weather else None
        if weather:
            self.start_utc = datetime.fromisoformat(
                weather["start_date"]).replace(tzinfo=timezone.utc)

        # A receiver's wake clock is deterministic and independent of event
        # order. duty_sync shares phase zero; other duty modes are per-node.
        for name, node in self.nodes.items():
            node.wake_phase_s = (0.0 if mode in ("duty_sync", "selective_duty")
                                 else float(self.rng_for("duty_phase", name).random())
                                 * T_SNIFF_S)

    def rng_for(self, phenomenon: str, entity: str = "") -> np.random.Generator:
        """Return a deterministic RNG stream keyed by phenomenon and entity.

        Python's randomized ``hash()`` is deliberately avoided so streams are
        reproducible across processes and remain independent of lookup order.
        """
        key = (phenomenon, entity)
        rng = self._rngs.get(key)
        if rng is None:
            material = f"mesh-sim-v2|{self.seed}|{phenomenon}|{entity}".encode()
            child_seed = int.from_bytes(
                hashlib.blake2b(material, digest_size=16).digest(), "little")
            rng = self._rngs[key] = np.random.default_rng(child_seed)
        return rng

    # ── time / trace helpers ────────────────────────────────────────────────
    def now_utc(self):
        return self.start_utc + timedelta(seconds=self.env.now)

    def emit(self, **kv):
        if self.trace_fh:
            kv["t"] = round(self.env.now, 2)
            self.trace_fh.write(json.dumps(kv) + "\n")

    def emit_sampled(self, **kv):
        if self.trace_fh and (self.rx_trace_sample >= 1.0
                              or self.rng_for("trace").random() < self.rx_trace_sample):
            self.emit(**kv)

    def trace_selected(self, rate: float) -> bool:
        """Observation-only sampling; never consumes a model RNG stream."""
        return bool(self.trace_fh and
                    (rate >= 1.0 or self.rng_for("trace").random() < rate))

    def record_channel_busy(self, name: str, start: float, end: float):
        """Accumulate the union of RF-busy intervals at one receiver.

        Calls arrive in nondecreasing start-time order, so the union needs only
        the previous right edge rather than retaining a year of intervals.
        """
        current = self.channel_busy_open.get(name)
        if current is None:
            self.channel_busy_open[name] = (start, end)
        elif start <= current[1]:
            self.channel_busy_open[name] = (current[0], max(current[1], end))
        else:
            self.channel_busy_closed_s[name] = (
                self.channel_busy_closed_s.get(name, 0.0)
                + current[1] - current[0])
            self.channel_busy_open[name] = (start, end)

    def channel_busy_through(self, name: str, end: float) -> float:
        """Exact union-busy seconds clipped to the simulation horizon."""
        total = self.channel_busy_closed_s.get(name, 0.0)
        current = self.channel_busy_open.get(name)
        if current is not None and end > current[0]:
            total += max(min(current[1], end) - current[0], 0.0)
        return min(total, max(end, 0.0))

    def receiver_cad_detects(self, node: Node, start: float,
                             preamble_s: float) -> bool:
        """Whether a duty-cycled receiver observes enough packet preamble.

        Awake windows repeat every ``T_SNIFF_S``. Once CAD locks, the receiver
        stays awake for the packet; a packet whose preamble misses the window
        is lost. This is deterministic, explicit, and charges the same listen
        duty used by the energy model.
        """
        if self.mode not in DUTY_MODES or node.duty >= 1.0:
            return True
        awake_s = max(0.0, min(float(node.duty), 1.0)) * T_SNIFF_S
        cad_s = CAD_MIN_SYMBOLS * (2 ** self.radio["sf"]) / self.radio["bw_hz"]
        if awake_s + 1e-12 < cad_s:
            return False
        phase = node.wake_phase_s
        preamble_end = start + preamble_s
        k0 = math.floor((start - phase) / T_SNIFF_S) - 1
        for k in range(k0, k0 + 4):
            wake_start = phase + k * T_SNIFF_S
            wake_end = wake_start + awake_s
            overlap = min(preamble_end, wake_end) - max(start, wake_start)
            if overlap + 1e-12 >= cad_s:
                return True
        return False

    # ── geometry: where is a hiker at sim time t? ───────────────────────────
    def hiker_track_t(self, node: Node, t: float) -> float:
        """Track time: replay starts 12:00 UTC (08:00 ET) daily; parked at the
        trailhead waypoint otherwise."""
        h = self.topo["hiker"]
        if not h:
            return 0.0
        day_s = t % 86400.0
        walk = day_s - 12 * 3600.0
        if walk < 0 or walk > h["t_s"][-1]:
            return 0.0
        return (walk + getattr(node, "track_offset", 0.0)) % h["t_s"][-1]

    def route_track_t(self, node: Node, t: float) -> float | None:
        """Renter track time; None when not walking (docked/parked)."""
        tt = (t % 86400.0) - node.start_s
        return tt if 0.0 <= tt <= node.route["duration_s"] else None

    def hiker_pos(self, node: Node, t: float):
        if node.route is not None:
            r = node.route
            tt = self.route_track_t(node, t)
            if tt is None:
                tt = 0.0 if (t % 86400.0) < node.start_s else r["duration_s"]
            return (float(np.interp(tt, r["t_s"], r["lat"])),
                    float(np.interp(tt, r["t_s"], r["lon"])))
        h = self.topo["hiker"]
        if not h:
            return (node.lat, node.lon)      # kiosk radio, docked at the box
        tt = self.hiker_track_t(node, t)
        return (float(np.interp(tt, h["t_s"], h["lat"])),
                float(np.interp(tt, h["t_s"], h["lon"])))

    def loss_db(self, a: str, b: str, t: float) -> float:
        a_h, b_h = a in self.hiker_names, b in self.hiker_names
        if not a_h and not b_h:
            v = self.linkmodel.fixed_loss(a, b)
            return v if v is not None else 300.0
        if a_h and b_h:
            # hiker↔hiker: both antennas ~1.5 m over ground — FSPL + 20 dB
            # clutter + 12 dB/km terrain excess beyond 1.5 km (ground-level
            # links die by ~4-5 km; the old flat model reached across the state)
            la1, lo1 = self.hiker_pos(self.nodes[a], t)
            la2, lo2 = self.hiker_pos(self.nodes[b], t)
            d = max(great_circle_m(la1, lo1, la2, lo2), 10.0)
            if d > 8000.0:
                return 300.0
            fspl = 20 * math.log10(d) + 20 * math.log10(self.radio["freq_mhz"]) - 27.55
            return fspl + 20.0 + 12.0 * max(0.0, d / 1000.0 - 1.5)
        hiker, site = (a, b) if a_h else (b, a)
        hn = self.nodes[hiker]
        if hn.route is None and not self.topo.get("hiker"):
            return 300.0                     # docked kiosk radio: radio is off
        if hn.route is not None:
            r = hn.route
            if site not in r["loss_db_q50"]:
                return 300.0        # site outside the route's precomputed range
            tt = self.route_track_t(hn, t)
            if tt is None:
                tt = 0.0 if (t % 86400.0) < hn.start_s else r["duration_s"]
            return float(np.interp(tt, r["loss_t_s"], r["loss_db_q50"][site]))
        return self.linkmodel.hiker_loss(site, self.hiker_track_t(hn, t))

    def rssi_dbm(self, a: str, b: str, t: float) -> float:
        return (self.rx_power_reference_dbm - self.loss_db(a, b, t)
                + self.shadow.sample(a, b, t))

    # ── PHY: broadcast one packet on the shared channel ─────────────────────
    def transmit(self, sender: Node, pkt: dict):
        air_s = airtime_ms(pkt["bytes"], self.radio["sf"], self.radio["bw_hz"],
                           self.radio["cr"], self.radio["preamble_syms"]) / 1000.0
        symbol_s = (2 ** self.radio["sf"]) / self.radio["bw_hz"]
        preamble_s = (self.radio["preamble_syms"] + 4.25) * symbol_s
        t0 = self.env.now
        tx = {"sender": sender.name, "start": t0, "end": t0 + air_s, "pkt": pkt,
              "preamble_s": preamble_s, "rssi_at": {}, "cad_at": {},
              "overlaps": []}
        cand = []
        for name, node in self.nodes.items():
            if name == sender.name or not node.alive or node.docked:
                continue
            loss = self.loss_db(sender.name, name, t0)
            if loss > 220.0:      # >80 dB below sensitivity: shadowing can't save it
                continue
            cand.append((name, loss))
        if cand:
            shades = self.shadow.batch(sender.name, [c[0] for c in cand], t0)
            for (name, loss), sh in zip(cand, shades):
                tx["rssi_at"][name] = self.rx_power_reference_dbm - loss + sh
                tx["cad_at"][name] = self.receiver_cad_detects(
                    self.nodes[name], t0, preamble_s)
        # Record immutable snapshots on both sides of every overlap while both
        # transmissions are known. The snapshot remains after the earlier TX
        # leaves active_tx, so reception cannot depend on equal-time event order;
        # avoiding object references also prevents cyclic garbage in long runs.
        for other in self.active_tx:
            if other["end"] > t0 and other["start"] < tx["end"]:
                tx["overlaps"].append({"sender": other["sender"],
                                       "rssi_at": other["rssi_at"]})
                other["overlaps"].append({"sender": tx["sender"],
                                          "rssi_at": tx["rssi_at"]})
        self.active_tx.append(tx)
        self.record_channel_busy(sender.name, t0, t0 + air_s)
        for name, rssi in tx["rssi_at"].items():
            if rssi >= CARRIER_SENSE_DBM:
                self.record_channel_busy(name, t0, t0 + air_s)
        sender.tx_until = t0 + air_s
        sender.stats["tx"] += 1
        if pkt["kind"] == "fwd":
            sender.fwd_ewma = 0.995 * sender.fwd_ewma + 1.0
        sender.stats["tx_airtime_s"] += air_s
        horizon = self.days * 86400.0
        self.total_airtime_s += max(min(t0 + air_s, horizon) - t0, 0.0)
        e = self.cfg["energy"]
        etx = (e["tx_current_ma"] - e["rx_listen_ma"]) / 1000.0 * e["battery_v"] * air_s / 3600.0
        sender.stats["energy_tx_wh"] += etx
        if sender.power != "grid":
            sender.soc_wh -= etx
        if sender.name in self.hiker_names and self.trace_selected(
                1.0 if pkt.get("okind", pkt["kind"]) == "sos"
                else self.hiker_trace_sample):
            self.emit(ev="tx", n=sender.name, pkt=pkt["id"], kind=pkt["kind"],
                      orig=pkt["origin"], hl=pkt["hop_limit"], air=round(air_s, 3))
        else:
            self.emit_sampled(ev="tx", n=sender.name, pkt=pkt["id"], kind=pkt["kind"],
                              orig=pkt["origin"], hl=pkt["hop_limit"], air=round(air_s, 3))
        yield self.env.timeout(air_s)
        self.active_tx.remove(tx)
        self.deliver(tx)

    def track_link_health(self, a: str, b: str, rssi: float, got_it: bool):
        if a in self.hiker_names or b in self.hiker_names:
            return
        key = (a, b) if a < b else (b, a)
        lh = self.link_health.setdefault(key, {"try": 0, "ok": 0, "margin_sum": 0.0})
        lh["try"] += 1
        lh["ok"] += int(got_it)
        lh["margin_sum"] += rssi - self.radio["rx_sensitivity_dbm"]

    def deliver(self, tx):
        """Decide reception at each node at end of airtime (collision window)."""
        # q_routing learns from the fate of its own routed hops: find this
        # packet's intended next hop so each branch below can report the
        # outcome as a TD sample (fails pruned before rssi_at go unobserved,
        # exactly as they would on real hardware).
        qr_next = None
        if self.mode == "q_routing" and not tx["pkt"].get("flood"):
            route = tx["pkt"].get("route") or []
            if tx["sender"] in route:
                i = route.index(tx["sender"])
                if i + 1 < len(route):
                    qr_next = route[i + 1]
        for name, rssi in tx["rssi_at"].items():
            node = self.nodes[name]
            if not node.alive or node.docked:
                if name == qr_next:
                    self._qr_update(tx["sender"], name, False, tx["start"])
                continue
            # Any local transmission overlapping this reception makes the
            # half-duplex radio unavailable, regardless of which TX ended first.
            if any(o["sender"] == name for o in tx["overlaps"]):
                if name == qr_next:
                    self._qr_update(tx["sender"], name, False, tx["start"])
                continue
            interferers = [o for o in tx["overlaps"] if o["sender"] != name]
            worst_i = max((o["rssi_at"].get(name, -999.0) for o in interferers),
                          default=-999.0)
            snr = rssi - self.noise_dbm
            ok = (rssi >= self.radio["rx_sensitivity_dbm"]
                  and snr >= self.radio["snr_demod_threshold_db"])
            if ok and not tx["cad_at"].get(name, False):
                node.stats["duty_misses"] += 1
                if name == qr_next:
                    self._qr_update(tx["sender"], name, False, tx["start"])
                continue
            if ok and worst_i > rssi - self.radio["capture_threshold_db"]:
                node.stats["collisions"] += 1
                self.track_link_health(tx["sender"], name, rssi, False)
                if name == qr_next:
                    self._qr_update(tx["sender"], name, False, tx["start"])
                self.emit_sampled(ev="col", n=name, pkt=tx["pkt"]["id"], **{"from": tx["sender"]})
                continue
            if not ok:
                self.track_link_health(tx["sender"], name, rssi, False)
                if name == qr_next:
                    self._qr_update(tx["sender"], name, False, tx["start"])
                continue
            self.track_link_health(tx["sender"], name, rssi, True)
            if name == qr_next:
                self._qr_update(tx["sender"], name, True, tx["start"])
            node.stats["rx_ok"] += 1
            if tx["sender"] in self.hiker_names and self.trace_selected(
                    1.0 if tx["pkt"].get("okind", tx["pkt"]["kind"]) == "sos"
                    else self.hiker_trace_sample):
                self.emit(ev="rx", n=name, pkt=tx["pkt"]["id"], rssi=round(rssi, 1),
                          **{"from": tx["sender"]})
            else:
                self.emit_sampled(ev="rx", n=name, pkt=tx["pkt"]["id"], rssi=round(rssi, 1),
                                  **{"from": tx["sender"]})
            self.on_receive(node, dict(tx["pkt"]), rssi, snr)

    # ── NET: reception handling ──────────────────────────────────────────────
    def on_receive(self, node: Node, pkt: dict, rssi: float, snr: float):
        key = (pkt["origin"], pkt["id"])
        if key in node.seen:
            if key in node.pending_rebroadcast:      # duplicate suppression
                node.pending_rebroadcast.pop(key).interrupt()
                node.stats["dup_suppressed"] += 1
            return
        node.seen.add(key)
        dest = pkt.get("dest", "mqtt")
        k0 = pkt.get("okind", pkt["kind"])   # original kind survives forwarding
        arrived = (node.name == dest) if dest != "mqtt" else node.mqtt
        if k0 == "ack" and node.name == pkt.get("dest"):
            self.sos_acked.add(pkt.get("ack_for"))
        if arrived and key not in self.delivered:
            self.delivered.add(key)
            meta = self.pkt_meta[key]
            meta["delivered"], meta["latency_s"] = True, self.env.now - meta["t0"]
            meta["via"] = node.name
            self.emit_sampled(ev="deliver", pkt=pkt["id"], orig=pkt["origin"],
                              via=node.name, kind=k0,
                              lat_s=round(meta["latency_s"], 2))
            if k0 == "sos":
                inc = self.sos_incidents.get(pkt.get("sos_id", pkt["id"]))
                if inc is not None and not inc["delivered"]:
                    inc["delivered"] = True
                    inc["first_latency"] = self.env.now - inc["t0"]
            if self.sos_retry and k0 == "sos" and node.mqtt:
                ack = self.new_pkt(node.name, "ack", 16, dest=pkt["origin"],
                                   flood=True)
                ack["hop_limit"] = 6
                ack["ack_for"] = pkt.get("sos_id", pkt["id"])
                self.env.process(self.csma_send(node, ack))
        if self.mode == "flood" or pkt.get("flood"):
            if pkt["hop_limit"] > 0 and node.name not in self.hiker_names:
                pkt2 = {**pkt, "hop_limit": pkt["hop_limit"] - 1, "kind": "fwd",
                        "okind": pkt.get("okind", pkt["kind"])}
                proc = self.env.process(self.rebroadcast_after_cw(node, pkt2, snr, key))
                node.pending_rebroadcast[key] = proc
        else:  # routed modes: source-routed unicast along the tree
            route = pkt.get("route", [])
            if node.name in route:
                idx = route.index(node.name)
                if idx + 1 <= len(route) - 1 and pkt["hop_limit"] > 0:
                    pkt2 = {**pkt, "hop_limit": pkt["hop_limit"] - 1, "kind": "fwd",
                            "okind": pkt.get("okind", pkt["kind"])}
                    self.env.process(self.csma_send(node, pkt2))

    def rebroadcast_after_cw(self, node: Node, pkt: dict, snr: float, key):
        """Meshtastic managed flood: contention window scaled by SNR —
        strong SNR (near) waits longer, weak SNR (far) relays first."""
        if pkt.get("okind", pkt["kind"]) == "sos":
            slots = 1.2                           # SOS relays first, always
        else:
            snr_norm = min(max((snr + 20.0) / 30.0, 0.0), 1.0)
            slots = 2 + snr_norm * 6
        try:
            rng = self.rng_for("rebroadcast", node.name)
            yield self.env.timeout(float(rng.uniform(1, slots)) * SLOT_S * 8)
            node.pending_rebroadcast.pop(key, None)
            yield from self.csma_send(node, pkt)
        except simpy.Interrupt:
            pass

    # ── MAC: carrier sense + slotted backoff ─────────────────────────────────
    def channel_busy_at(self, node: Node) -> bool:
        t = self.env.now
        for o in self.active_tx:
            if o["start"] <= t < o["end"] and o["rssi_at"].get(node.name, -999) >= CARRIER_SENSE_DBM:
                return True
        return False

    def csma_send(self, node: Node, pkt: dict):
        prio = pkt.get("okind", pkt["kind"]) == "sos"   # SOS preempts, fwds too
        attempts = 200 if prio else 30
        rng = self.rng_for("mac", node.name)
        for _ in range(attempts):
            if not node.alive:
                return
            if node.tx_until > self.env.now or self.channel_busy_at(node):
                yield self.env.timeout(
                    float(rng.uniform(1, 2 if prio else 8)) * SLOT_S)
                continue
            yield self.env.timeout(
                float(rng.uniform(0, 1 if prio else 3)) * SLOT_S)
            # A radio is a single half-duplex resource. A second local process
            # may have begun transmitting while this process backed off.
            if node.tx_until > self.env.now or self.channel_busy_at(node):
                continue
            yield from self.transmit(node, pkt)
            return

    # ── energy-aware routing ─────────────────────────────────────────────────
    def _kt_for_day(self, day: int) -> float:
        if self.weather:
            return self.weather[min(day, len(self.weather) - 1)]["kt"]
        while len(self.daily_kt) <= day:
            month = (self.start_utc + timedelta(days=len(self.daily_kt))).month
            self.daily_kt.append(solar_model.sample_daily_kt(month,
                                                             self.rng_for("weather"),
                                                             self.cfg["solar"]))
        return self.daily_kt[day]

    def _snow_factor_for_day(self, day: int) -> float:
        """Panel derate from real snowfall: fresh snow blankets the pyramid
        (sheds within ~a day thanks to the steep faces)."""
        if not self.weather:
            return 1.0
        w = self.weather[min(day, len(self.weather) - 1)]
        return w.get("snow_factor", 1.0)

    def solar_remaining_wh(self, node: Node, t: float) -> float:
        """Forecast panel Wh from now to midnight using monthly climatology.

        The physical energy process still uses the realized weather day. Route
        decisions deliberately do not: using that full-day value before sunset
        would leak future weather into the controller.
        """
        day = int(t // 86400)
        key = (node.name, day)
        prof = getattr(self, "_solar_profiles", None)
        if prof is None:
            prof = self._solar_profiles = {}
        if key not in prof:
            day0 = self.start_utc + timedelta(days=day)
            kt = float(self.cfg["solar"]["monthly_kt_mean"][day0.month - 1])
            prof[key] = [solar_model.solar_power_w(node.lat, node.lon,
                                                   day0 + timedelta(hours=h), kt,
                                                   node.horizon, self.cfg["solar"],
                                                   node.site_solar)
                         for h in range(24)]
        hour = int((t % 86400) // 3600)
        return float(sum(prof[key][hour:]))  # W-hours: 1 h per sample

    def node_scarcity(self, node: Node, t: float) -> float:
        """Energy-scarcity multiplier: 1 (rich) → ~60 (nearly dead, no sun coming)."""
        if node.power == "grid":
            return 1.0
        runway = node.soc_wh
        if node.power == "solar":
            runway += self.solar_remaining_wh(node, t)
        rf = min(runway / node.cap_wh, 1.0)
        return 1.0 + 3.0 * (1.0 - rf) / max(rf, 0.05)

    # ── routed modes: gateway-rooted shortest-path tree (RPL/DV-style) ───────
    # One multi-source Dijkstra from all live gateways per refresh window gives
    # every fixed node its next hop toward backhaul — O(E log V) per window
    # instead of per-packet, which is what makes statewide year runs feasible
    # (and matches how tree/distance-vector protocols actually converge).

    def link_p_success(self, margin_db: float) -> float:
        sigma = self.cfg["shadowing"]["sigma_db"]
        return 0.5 * (1.0 + math.erf(margin_db / (sigma * math.sqrt(2.0))))

    def edge_weight(self, u: str, v: str, margin: float, t: float) -> float:
        """Cost of node v relaying one packet received from u, per self.mode."""
        mode = "lb_energy" if self.mode in DUTY_MODES else self.mode
        if mode == "min_hop":
            return 1.0
        p = max(self.link_p_success(margin), 0.02)
        if mode == "etx":
            return 1.0 / p                      # expected transmissions
        e = self.cfg["energy"]
        etx_j = e["tx_current_ma"] / 1000.0 * e["battery_v"] * 0.5
        nv = self.nodes[v]
        w = (etx_j / p) * self.node_scarcity(nv, t)
        if mode == "lb_energy":
            # self-monitoring: nodes carrying more than their share of relay
            # traffic (EWMA vs fleet median) or dying faster than the fleet
            # get progressively expensive, so load rotates across parallel
            # paths and drain equalizes.
            med = max(self._fwd_median, 1e-6)
            overuse = max(0.0, nv.fwd_ewma / med - 1.0)
            w *= (1.0 + 2.0 * overuse) * (1.0 + 1.5 * nv.death_score)
        return w

    # ── learned control: Q-routing + RL duty cycling ─────────────────────────
    # q_routing: distributed Q-learning next-hop selection (Boyan & Littman
    # 1994) with an energy-aware reward. Q[u][v] = learned expected
    # scarcity-weighted transmissions from u to a gateway when relaying via v.
    # Updates come from actual per-hop outcomes in deliver() — link quality is
    # EXPERIENCED, not computed from the propagation model, so the policy
    # adapts online to shadowing, collisions, and relay deaths.
    # rl_duty: tabular Q-learning over each node's listen duty cycle; one
    # shared table pools experience across the (homogeneous) fixed fleet.
    QR_ALPHA = 0.2
    RL_ACTIONS = (0.02, 0.05, 0.10, 0.25)
    RL_ALPHA, RL_GAMMA = 0.15, 0.9

    def _rl_eps(self) -> float:
        """ε-greedy exploration, exponential decay (20-day half-life), 2% floor."""
        return 0.02 + 0.13 * math.exp(-self.env.now / (86400.0 * 20.0))

    def _qr_init(self):
        """Warm-start Q from an ETX shortest-path pass (standard practice:
        optimistic-zero init wastes weeks routing packets into dead ends;
        scarcity/collision structure is still learned entirely online)."""
        dist: dict[str, float] = {}
        pq = []
        for n, nd in self.nodes.items():
            if nd.mqtt:
                dist[n] = 0.0
                heapq.heappush(pq, (0.0, n))
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, math.inf):
                continue
            for v, margin in self.fixed_adj.get(u, ()):
                p = max(self.link_p_success(margin), 0.02)
                if d + 1.0 / p < dist.get(v, math.inf):
                    dist[v] = d + 1.0 / p
                    heapq.heappush(pq, (d + 1.0 / p, v))
        self.qrt = {}
        for u, nbrs in self.fixed_adj.items():
            if self.nodes[u].mqtt:
                continue
            self.qrt[u] = {}
            for v, margin in nbrs:
                p = max(self.link_p_success(margin), 0.02)
                self.qrt[u][v] = 1.0 / p + dist.get(v, 200.0)

    def _qr_value(self, n: str) -> float:
        """V(n) = min_v Q[n][v]; gateways are absorbing (V=0)."""
        if self.nodes[n].mqtt:
            return 0.0
        q = self.qrt.get(n) if self.qrt else None
        return min(q.values()) if q else math.inf

    def _qr_update(self, u: str, v: str, got_it: bool, t: float):
        """TD update on an observed hop u→v. Success bootstraps from V(v);
        failure is a no-progress sample (pay the hop, still at Q[u][v])."""
        qs = self.qrt.get(u) if self.qrt else None
        if qs is None or v not in qs:
            return
        c = self.node_scarcity(self.nodes[v], t)
        sample = c + (min(self._qr_value(v), 1e6) if got_it else qs[v])
        qs[v] += self.QR_ALPHA * (sample - qs[v])
        self.rl_updates += 1

    def _build_q_routes(self):
        """Derive next hops ε-greedily from the learned Q, with a downhill
        constraint (V must strictly decrease toward the gateway) so learned
        routes are loop-free by construction."""
        t = self.env.now
        if self.qrt is None:
            self._qr_init()
        eps = self._rl_eps()
        nxt: dict[str, str | None] = {}
        cost: dict[str, float] = {}
        vals = {n: self._qr_value(n) for n in self.qrt}
        for n, nd in self.nodes.items():
            if nd.mqtt and nd.alive:
                nxt[n], cost[n] = None, 0.0
        for u, qs in self.qrt.items():
            nd = self.nodes[u]
            if not nd.alive or nd.docked:
                continue
            vu = vals.get(u, math.inf)
            cand = [(q, v) for v, q in qs.items()
                    if self.nodes[v].alive and not self.nodes[v].docked
                    and (self.nodes[v].mqtt or vals.get(v, math.inf) < vu)]
            if not cand:
                continue
            policy_rng = self.rng_for("policy", "q_routing")
            if len(cand) > 1 and float(policy_rng.random()) < eps:
                q, v = cand[int(policy_rng.integers(len(cand)))]
            else:
                q, v = min(cand)
            nxt[u] = v
            cost[u] = vu if vu < math.inf else q
        self.route_next, self.route_cost = nxt, cost
        self.route_tree_t = t

    def _rl_state(self, nd: Node, t: float) -> tuple:
        """Compact node state: SOC quartile, solar runway, time block, load."""
        soc_b = min(int(nd.soc_wh / nd.cap_wh * 4), 3)
        sun = (self.solar_remaining_wh(nd, t) / max(nd.cap_wh, 1e-6)
               if nd.power == "solar" else 0.0)
        sun_b = 0 if sun < 0.05 else (1 if sun < 0.3 else 2)
        hour_b = int((t % 86400.0) / 21600.0)
        busy_b = int(nd.fwd_ewma > max(self._fwd_median, 1e-6))
        return (soc_b, sun_b, hour_b, busy_b)

    def _rl_duty_step(self, nd: Node, t: float):
        """One Q-learning step per node per route-refresh window: credit the
        previous action (traffic served − listen energy − death penalty),
        then pick the next duty ε-greedily."""
        e = self.cfg["energy"]
        rx_w = e["rx_listen_ma"] / 1000.0 * e["battery_v"]
        s2 = self._rl_state(nd, t)
        prev = getattr(nd, "_rl", None)
        if prev is not None:
            dt_h = max((t - prev["t"]) / 3600.0, 1e-6)
            served = nd.stats["rx_ok"] - prev["rx_ok"]
            died = nd.stats["deaths"] - prev["deaths"]
            listen_wh = prev["a"] * rx_w * dt_h
            r = 0.01 * served - 4.0 * listen_wh - 50.0 * died
            key = (prev["s"], prev["a"])
            q0 = self.qduty.get(key, 0.0)
            best2 = max(self.qduty.get((s2, a), 0.0) for a in self.RL_ACTIONS)
            self.qduty[key] = q0 + self.RL_ALPHA * (r + self.RL_GAMMA * best2 - q0)
            self.rl_updates += 1
        policy_rng = self.rng_for("policy", f"rl_duty:{nd.name}")
        if float(policy_rng.random()) < self._rl_eps():
            a = self.RL_ACTIONS[int(policy_rng.integers(len(self.RL_ACTIONS)))]
        else:
            a = max(self.RL_ACTIONS, key=lambda x: self.qduty.get((s2, x), 0.0))
        nd.duty = a
        nd._rl = {"s": s2, "a": a, "t": t,
                  "rx_ok": nd.stats["rx_ok"], "deaths": nd.stats["deaths"]}

    def build_route_tree(self):
        """Multi-source Dijkstra from live gateways over the fixed-site graph."""
        if self.mode == "q_routing":
            self._build_q_routes()
            return
        t = self.env.now
        if self.mode in DUTY_MODES or self.mode == "lb_energy":
            fwds = sorted(nd.fwd_ewma for nd in self.nodes.values()
                          if not nd.mqtt and nd.name not in self.hiker_names)
            self._fwd_median = fwds[len(fwds) // 2] if fwds else 0.0
        dist: dict[str, float] = {}
        nxt: dict[str, str | None] = {}
        pq = []
        for n, nd in self.nodes.items():
            if nd.mqtt and nd.alive:
                dist[n] = 0.0
                nxt[n] = None
                heapq.heappush(pq, (0.0, n))
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, math.inf):
                continue
            for v, margin in self.fixed_adj.get(u, ()):
                nd = self.nodes[v]
                if not nd.alive or nd.docked:
                    continue
                w = self.edge_weight(v, u, margin, t)   # v relays toward u
                if d + w < dist.get(v, math.inf):
                    dist[v] = d + w
                    nxt[v] = u
                    heapq.heappush(pq, (d + w, v))
        self.route_next, self.route_cost = nxt, dist
        self.route_tree_t = t
        if self.mode in DUTY_MODES:
            on_tree = set(v for v in nxt.values() if v) | \
                      {n for n, nd in self.nodes.items() if nd.mqtt}
            crit = (self._critical_relays() if self.mode == "selective_duty"
                    else set())
            for n, nd in self.nodes.items():
                if nd.mqtt or nd.power == "grid" or n in self.hiker_names:
                    continue
                if self.mode == "duty_sync":
                    nd.duty = 0.05
                elif self.mode == "selective_duty":
                    # connectivity-critical relays (cut-vertices to a gateway)
                    # stay fully awake so delivery holds; everyone else sleeps
                    # at the duty_sync rate to conserve. Recomputed each rebuild
                    # so the awake backbone tracks the live graph as nodes die.
                    nd.duty = 1.0 if n in crit else 0.05
                elif self.mode == "duty_adaptive":
                    runway = nd.soc_wh + (self.solar_remaining_wh(nd, t)
                                          if nd.power == "solar" else 0.0)
                    rf = min(runway / nd.cap_wh, 1.0)
                    nd.duty = float(np.clip(0.02 + 0.23 * rf, 0.02, 0.25))
                elif self.mode == "rl_duty":
                    self._rl_duty_step(nd, t)
                else:  # rotate_lb: tree relays always-on, everyone else sniffs
                    nd.duty = 1.0 if n in on_tree else 0.02

    def _critical_relays(self) -> set:
        """Relays whose sleep would strand another node from every gateway —
        the cut-vertices of the live connectivity graph. Iterative Tarjan
        articulation-point search on the alive fixed sites plus a virtual
        super-source joined to all live gateways; O(V+E) per rebuild."""
        adj: dict[str, list] = {}
        gws = []
        for n, nd in self.nodes.items():
            if n in self.hiker_names or not nd.alive or nd.docked:
                continue
            adj.setdefault(n, [])
            if nd.mqtt:
                gws.append(n)
        for u in list(adj.keys()):
            for v, _margin in self.fixed_adj.get(u, ()):
                if v in adj:
                    adj[u].append(v)
        S = "\x00super"
        adj[S] = list(gws)
        for g in gws:
            adj[g].append(S)
        disc: dict[str, int] = {}
        low: dict[str, int] = {}
        parent: dict[str, str] = {}
        ap: set = set()
        timer = 0
        disc[S] = low[S] = timer
        timer += 1
        stack = [(S, iter(adj[S]))]
        while stack:
            u, it = stack[-1]
            pushed = False
            for v in it:
                if v not in disc:
                    parent[v] = u
                    disc[v] = low[v] = timer
                    timer += 1
                    stack.append((v, iter(adj[v])))
                    pushed = True
                    break
                elif v != parent.get(u):
                    low[u] = min(low[u], disc[v])
            if not pushed:
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    low[p] = min(low[p], low[u])
                    if parent.get(p) is not None and low[u] >= disc[p]:
                        ap.add(p)
        return {n for n in ap if n != S and not self.nodes[n].mqtt}

    def tree_path(self, start: str) -> list[str] | None:
        path, cur = [start], start
        for _ in range(24):
            nh = self.route_next.get(cur)
            if nh is None:
                return path if self.nodes[cur].mqtt else None
            path.append(nh)
            cur = nh
        return None

    def route_to_mqtt(self, origin: str) -> list[str] | None:
        if self.env.now - self.route_tree_t > self.route_refresh_s:
            self.build_route_tree()
        if origin not in self.hiker_names:
            return self.tree_path(origin)
        # mobile origin: attach to the best-reachable fixed site right now
        t = self.env.now
        best, best_cost, best_margin = None, math.inf, None
        for s, nd in self.nodes.items():
            if s in self.hiker_names or not nd.alive or nd.docked:
                continue
            c = self.route_cost.get(s)
            if c is None:
                continue
            loss = self.loss_db(origin, s, t)
            margin = self.rx_power_reference_dbm - loss - self.radio["rx_sensitivity_dbm"]
            if margin < 3.0:
                continue
            total = c + self.edge_weight(origin, s, margin, t)
            if total < best_cost:
                best, best_cost = s, total
        if best is None:
            return None
        sub = self.tree_path(best)
        return [origin] + sub if sub else None

    # ── traffic generators ───────────────────────────────────────────────────
    def new_pkt(self, origin: str, kind: str, nbytes: int,
                dest: str = "mqtt", flood: bool = False) -> dict:
        self.pkt_seq += 1
        pkt = {"id": self.pkt_seq, "origin": origin, "kind": kind, "bytes": nbytes,
               "hop_limit": self.hop_limit, "dest": dest}
        if flood:
            pkt["flood"] = True
        key = (origin, self.pkt_seq)
        self.pkt_meta[key] = {"t0": self.env.now, "kind": kind, "origin": origin,
                              "delivered": False, "latency_s": None, "via": None}
        if (self.mode in ROUTED_MODES
                and not flood and dest == "mqtt"):
            route = self.route_to_mqtt(origin)
            self.pkt_meta[key]["route"] = route
            if route:
                pkt["route"] = route
        node = self.nodes[origin]
        node.seen.add(key)
        if node.mqtt and dest == "mqtt":
            self.pkt_meta[key].update(delivered=True, latency_s=0.0, via=origin)
            self.delivered.add(key)
        return pkt

    def gen_fixed_telemetry(self, node: Node):
        tr = self.cfg["traffic"]
        iv = self.telemetry_interval_s or tr["telemetry_interval_s"]
        rng = self.rng_for("traffic", f"telemetry:{node.name}")
        yield self.env.timeout(float(rng.uniform(0, iv)))
        while True:
            if node.alive:
                pkt = self.new_pkt(node.name, "tel", tr["telemetry_payload_b"])
                self.env.process(self.csma_send(node, pkt))
            yield self.env.timeout(iv * float(rng.uniform(0.9, 1.1)))

    def gen_hiker(self, node: Node, interval_s: float):
        tr = self.cfg["traffic"]
        rng = self.rng_for("traffic", f"position:{node.name}")
        yield self.env.timeout(float(rng.uniform(0, interval_s)))
        while True:
            if node.alive and not node.docked:
                if node.route is not None:
                    walking = self.route_track_t(node, self.env.now) is not None
                else:
                    walking = 0.0 < self.hiker_track_t(node, self.env.now)
                if walking or self.always_beacon or (node.name != "hiker_alpha"
                                                     and node.route is None):
                    pkt = self.new_pkt(node.name, "pos", tr["position_payload_b"])
                    self.env.process(self.csma_send(node, pkt))
            yield self.env.timeout(interval_s * float(rng.uniform(0.9, 1.1)))

    def kiosk_dispatch(self, w: dict):
        """Daily: draw the highest-charge docked radio from the walker's kiosk;
        walk the route; dock the radio at the return kiosk."""
        r = w["route"]
        while True:
            day = int(self.env.now // 86400)
            t_out = day * 86400 + w["start_s"]
            if self.env.now > t_out:
                t_out += 86400
            yield self.env.timeout(t_out - self.env.now)
            self.rental_stats["walker_days"] += 1
            docked = [nd for nd in self.nodes.values()
                      if getattr(nd, "kiosk", None) == w["kiosk"] and nd.docked]
            min_soc = float(self.cfg.get("kiosk", {}).get(
                "min_checkout_soc", KIOSK_MIN_CHECKOUT_SOC))
            pool = [nd for nd in docked if nd.alive
                    and nd.soc_wh / nd.cap_wh >= min_soc]
            if not pool:
                self.rental_stats["starved"] += 1
                self.rental_stats[
                    "starved_unserviceable" if docked else "starved_no_stock"] += 1
                self.rental_stats["unusable_at_checkout"] += len(docked)
                self.emit(ev="starved", walker=w["name"], kiosk=w["kiosk"])
                yield self.env.timeout(86400.0)   # walker goes home; retry tomorrow
                continue
            radio = max(pool, key=lambda nd: nd.soc_wh)
            self.rental_stats["served"] += 1
            self.rental_stats["checkout_socs"].append(
                round(radio.soc_wh / radio.cap_wh, 3))
            radio.docked = False
            radio.route = r
            radio.start_s = w["start_s"]
            self.walker_radio[w["name"]] = radio.name
            self.emit(ev="assign", walker=w["name"], radio=radio.name,
                      kiosk=w["kiosk"], soc=round(radio.soc_wh / radio.cap_wh, 3))
            yield self.env.timeout(r["duration_s"])
            radio.docked = True
            radio.kiosk = w["return_kiosk"]
            radio.route = None
            self.walker_radio.pop(w["name"], None)
            self.emit(ev="return", n=radio.name, kiosk=w["return_kiosk"],
                      soc=round(radio.soc_wh / radio.cap_wh, 3))

    def kiosk_shuttle_process(self):
        """Nightly van run (03:00): redistribute docked radios so every kiosk
        opens with enough for its walkers — the drift fix real fleets use."""
        demand: dict = {}
        for w in self.walkers:
            demand[w["kiosk"]] = demand.get(w["kiosk"], 0) + 1
        while True:
            nxt = (int(self.env.now // 86400) + 1) * 86400 + 3 * 3600
            yield self.env.timeout(nxt - self.env.now)
            docked: dict = {}
            for nd in self.nodes.values():
                if getattr(nd, "kiosk", None) and nd.docked:
                    docked.setdefault(nd.kiosk, []).append(nd)
            moves = 0
            for kiosk, need in demand.items():
                have = docked.get(kiosk, [])
                while len(have) < need:
                    surplus = [(k, v) for k, v in docked.items()
                               if k != kiosk and len(v) > demand.get(k, 0)]
                    if not surplus:
                        break
                    surplus.sort(key=lambda kv: -(len(kv[1]) - demand.get(kv[0], 0)))
                    src_k, pool = surplus[0]
                    radio = min(pool, key=lambda nd: nd.soc_wh)  # move the worst
                    pool.remove(radio)
                    radio.kiosk = kiosk
                    have.append(radio)
                    docked[kiosk] = have
                    moves += 1
            if moves:
                self.emit(ev="shuttle", moved=moves)

    def kiosk_inventory_process(self):
        while True:
            yield self.env.timeout(1800.0)
            inv: dict = {}
            for nd in self.nodes.values():
                k = getattr(nd, "kiosk", None)
                if k and nd.docked:
                    inv.setdefault(k, []).append(round(nd.soc_wh / nd.cap_wh, 2))
            banks = {k: round(b["soc_wh"] / b["cap_wh"], 3)
                     for k, b in getattr(self, "kiosk_banks", {}).items()}
            self.emit(ev="kiosk", inv={k: sorted(v, reverse=True)
                                       for k, v in inv.items()}, banks=banks)

    def rental_process(self, node: Node):
        """Daily checkout/return lifecycle for a rented node.

        Docked = inside the trailhead charging box: radio off, recharging.
        Checked out at start_s, carried along the route, returned at the
        route's end kiosk (may differ for traverses), redistributed to the
        start kiosk overnight."""
        r = node.route
        while True:
            day = int(self.env.now // 86400)
            t_out = day * 86400 + node.start_s
            if self.env.now > t_out:
                t_out += 86400
            yield self.env.timeout(t_out - self.env.now)
            node.docked = False
            self.emit(ev="rent", n=node.name, kiosk=r["kiosk"],
                      soc=round(node.soc_wh / node.cap_wh, 3))
            yield self.env.timeout(r["duration_s"])
            node.docked = True
            self.emit(ev="return", n=node.name, kiosk=r["return_kiosk"],
                      soc=round(node.soc_wh / node.cap_wh, 3))

    def gen_hiker_msgs(self, a: Node, b: Node):
        """Two hikers on the same route texting each other (Meshtastic-style
        flooded DMs, delivered when the partner hears them)."""
        tr = self.cfg["traffic"]
        rng = self.rng_for("traffic", f"dm:{a.name}:{b.name}")
        yield self.env.timeout(float(rng.uniform(600, 1800)))
        turn = 0
        while True:
            if (a.alive and b.alive and not a.docked and not b.docked
                    and self.route_track_t(a, self.env.now) is not None
                    and self.route_track_t(b, self.env.now) is not None):
                src_n, dst_n = (a, b) if turn % 2 == 0 else (b, a)
                pkt = self.new_pkt(src_n.name, "msg", tr["sos_payload_b"],
                                   dest=dst_n.name, flood=True)
                self.env.process(self.csma_send(src_n, pkt))
                turn += 1
            yield self.env.timeout(float(rng.uniform(1800, 3600)))

    def gen_hiker_family(self, node: Node):
        """Occasional 'tell the family' message: hiker → any MQTT gateway →
        the outside world."""
        tr = self.cfg["traffic"]
        rng = self.rng_for("traffic", f"family:{node.name}")
        yield self.env.timeout(float(rng.uniform(1200, 2400)))
        while True:
            if (node.alive and not node.docked
                    and self.route_track_t(node, self.env.now) is not None):
                pkt = self.new_pkt(node.name, "fam", tr["sos_payload_b"])
                self.env.process(self.csma_send(node, pkt))
            yield self.env.timeout(float(rng.uniform(2700, 5400)))

    def gen_walker_msgs(self, wa: dict, wb: dict):
        tr = self.cfg["traffic"]
        rng = self.rng_for("traffic", f"walker-dm:{wa['name']}:{wb['name']}")
        yield self.env.timeout(float(rng.uniform(600, 1800)))
        turn = 0
        while True:
            ra = self.walker_radio.get(wa["name"])
            rb = self.walker_radio.get(wb["name"])
            if ra and rb:
                a, b = self.nodes[ra], self.nodes[rb]
                if a.alive and b.alive and not a.docked and not b.docked:
                    src_n, dst = (a, b.name) if turn % 2 == 0 else (b, a.name)
                    pkt = self.new_pkt(src_n.name, "msg", tr["sos_payload_b"],
                                       dest=dst, flood=True)
                    self.env.process(self.csma_send(src_n, pkt))
                    turn += 1
            yield self.env.timeout(float(rng.uniform(1800, 3600)))

    def send_sos_incident(self, node: Node, name: str):
        """Send one incident's duplicate burst and optional fresh-ID retries."""
        tr = self.cfg["traffic"]
        incident_t0 = self.env.now
        pkt = self.new_pkt(name, "sos", tr["sos_payload_b"], flood=True)
        sos_id = pkt["id"]
        pkt["sos_id"] = sos_id
        self.sos_incidents[sos_id] = {"t0": incident_t0, "tries": 1,
                                      "delivered": False,
                                      "first_latency": None}
        self.env.process(self.csma_send(node, pkt))
        # Burst copies preserve the logical packet ID and are anchored to the
        # incident clock, so engine/MAC runtime cannot turn the intended
        # +30/+60 schedule into +30/+90.
        for offset in (30.0, 60.0):
            yield self.env.timeout(max(incident_t0 + offset - self.env.now, 0.0))
            if node.alive:
                self.env.process(self.csma_send(node, dict(pkt)))
        if self.sos_retry:
            # Five-minute logical retries use fresh packet IDs so upstream
            # dedupe cannot suppress recovery, but retain the incident sos_id
            # for ACK and incident-level accounting.
            for retry in range(1, 25):
                yield self.env.timeout(max(
                    incident_t0 + retry * 300.0 - self.env.now, 0.0))
                if sos_id in self.sos_acked or not node.alive or node.docked:
                    break
                rp = self.new_pkt(name, "sos", tr["sos_payload_b"], flood=True)
                rp["sos_id"] = sos_id
                self.sos_incidents[sos_id]["tries"] += 1
                self.env.process(self.csma_send(node, rp))

    def gen_daily_sos(self):
        """One SOS per day from a random mid-route walker (renter if present)."""
        h = self.topo["hiker"]
        for day in range(max(int(math.ceil(self.days)), 1)):
            # Per-day stream: an unavailable sender (and therefore a skipped
            # selector draw) cannot shift any later day's incident schedule.
            rng = self.rng_for("incidents", f"day:{day}")
            if rng.random() > 0.5:          # ~180 incidents/yr statewide
                yield self.env.timeout(max((day + 1) * 86400 - self.env.now, 0.0))
                continue
            # pick the sender AT INCIDENT TIME: whoever is actually out hiking
            # (kiosk-pool radios have routes only while checked out)
            t_sos = day * 86400 + float(rng.uniform(13.0, 19.0)) * 3600.0
            yield self.env.timeout(max(t_sos - self.env.now, 0.0))
            out_now = [nd for nd in self.nodes.values()
                       if nd.route is not None and not nd.docked and nd.alive]
            if out_now:
                node = out_now[int(rng.integers(len(out_now)))]
                name = node.name
            elif h:
                name, node = "hiker_alpha", self.nodes["hiker_alpha"]
                t_sos = day * 86400 + 12 * 3600 + float(rng.uniform(0.2, 0.8)) * h["t_s"][-1]
            else:
                continue
            if node.alive and not node.docked:
                yield from self.send_sos_incident(node, name)

    # ── energy / solar / bookkeeping processes ───────────────────────────────
    def mark_dead(self, node: Node):
        """Transition a node to dead and begin availability accounting."""
        if not node.alive:
            return
        node.soc_wh = 0.0
        node.alive = False
        node.dead_since_s = self.env.now
        node.ever_died = True
        node.stats["deaths"] += 1
        node.death_score = 0.7 * node.death_score + 1.0
        self.route_tree_t = -1e9
        self.emit(ev="dead", n=node.name)

    def mark_alive(self, node: Node):
        """Transition a node to alive and close its current outage interval."""
        if node.alive:
            return
        if node.dead_since_s is not None:
            node.dead_time_s += max(self.env.now - node.dead_since_s, 0.0)
        node.dead_since_s = None
        node.alive = True
        self.route_tree_t = -1e9
        self.emit(ev="alive", n=node.name)

    def node_dead_time_s(self, node: Node, end_s: float | None = None) -> float:
        """Closed outage time plus any outage still open at ``end_s``."""
        end = self.env.now if end_s is None else end_s
        open_time = (max(end - node.dead_since_s, 0.0)
                     if node.dead_since_s is not None else 0.0)
        return node.dead_time_s + open_time

    def energy_process(self):
        e = self.cfg["energy"]
        step = float(self.energy_step_s or self.cfg["sim"]["solar_step_s"])
        v = e["battery_v"]
        rx_w = e["rx_listen_ma"] / 1000.0 * v
        sleep_w = e["light_sleep_ma"] / 1000.0 * v   # [BENCH-CALIBRATE] floor
        gps_wh_per_s = e["gps_active_ma"] / 1000.0 * v / 3600.0
        while True:
            yield self.env.timeout(step)
            t_utc = self.now_utc()
            day = int(self.env.now // 86400)
            kt = self._kt_for_day(day)
            snow = self._snow_factor_for_day(day)
            # kiosk solar arrays (flat mount) harvest into their banks
            kc = self.cfg.get("kiosk", {})
            for kname, bank in getattr(self, "kiosk_banks", {}).items():
                ks = self.topo["sites"].get(kname)
                if ks is None:
                    continue
                flat = {"geometry": "flat", "canopy_tau": 1.0}
                w = snow * solar_model.solar_power_w(
                    ks["lat"], ks["lon"], t_utc, kt,
                    np.array(ks["horizon_deg"]),
                    {**self.cfg["solar"],
                     "panel_w_nominal": kc.get("panel_w", 200.0)}, flat)
                bank["soc_wh"] = min(bank["soc_wh"] + w * step / 3600.0,
                                     bank["cap_wh"])
            for node in self.nodes.values():
                if node.power == "grid":
                    continue
                if node.docked:                      # in the charging box
                    charge_w = float(kc.get("charge_w_per_bay", KIOSK_CHARGE_W))
                    headroom = max(node.cap_wh - node.soc_wh, 0.0)
                    want = min(charge_w * step / 3600.0, headroom)
                    bank = getattr(self, "kiosk_banks", {}).get(
                        getattr(node, "kiosk", None))
                    if bank is not None:
                        got = min(want, max(bank["soc_wh"], 0.0))
                        bank["soc_wh"] -= got
                    else:
                        got = want
                    node.soc_wh += got
                    if not node.alive and node.soc_wh >= REVIVE_FRACTION * node.cap_wh:
                        self.mark_alive(node)
                    node._last_solar_w = 0.0
                    continue
                d = node.duty
                drain = (d * rx_w + (1.0 - d) * sleep_w) / 3600.0 * step
                if node.name in self.hiker_names:
                    drain += gps_wh_per_s * step
                sol_w = 0.0
                if node.power == "solar" and node.alive is not None:
                    sol_w = snow * solar_model.solar_power_w(
                        node.lat, node.lon, t_utc, kt,
                        node.horizon, self.cfg["solar"], node.site_solar)
                    gain = sol_w * step / 3600.0
                    node.soc_wh = min(node.soc_wh + gain, node.cap_wh)
                    node.stats["solar_wh"] += gain
                if node.alive:
                    node.soc_wh -= drain
                    if node.soc_wh <= 0.0:
                        self.mark_dead(node)
                elif node.soc_wh >= REVIVE_FRACTION * node.cap_wh:
                    self.mark_alive(node)
                node._last_solar_w = sol_w

    def trace_process(self):
        while True:
            for name, node in self.nodes.items():
                self.emit(ev="bat", n=name,
                          soc=round(node.soc_wh / node.cap_wh, 4),
                          sw=round(getattr(node, "_last_solar_w", 0.0), 2),
                          alive=node.alive)
            yield self.env.timeout(self.bat_trace_s)

    def pos_trace_process(self):
        last_dk: dict = {}
        while True:
            for name in self.hiker_names:
                node = self.nodes[name]
                if name != "hiker_alpha" and node.route is None:
                    continue
                dk = 1 if node.docked else 0
                # emit while walking, plus one fix on each dock/undock edge —
                # keeps year-long traces small without losing motion
                if dk == 0 or last_dk.get(name) != dk:
                    la, lo = self.hiker_pos(node, self.env.now)
                    self.emit(ev="pos", n=name, lat=round(la, 5), lon=round(lo, 5),
                              dk=dk)
                last_dk[name] = dk
            yield self.env.timeout(self.pos_trace_s)

    def fleet_soc_process(self):
        while True:
            yield self.env.timeout(21600.0)
            socs = np.array([nd.soc_wh / nd.cap_wh for nd in self.nodes.values()
                             if nd.power == "solar"])
            if len(socs):
                self.fleet_soc_series.append(
                    [round(self.env.now / 86400.0, 2),
                     round(float(np.quantile(socs, 0.10)), 3),
                     round(float(np.median(socs)), 3),
                     round(float(np.quantile(socs, 0.90)), 3),
                     round(float(np.std(socs)), 4)])

    def aggregate_packet(self, m: dict):
        """Fold packet metadata into bounded, unbiased summary state.

        Algorithm-R reservoir sampling gives every delivered latency over the
        full run equal inclusion probability; the former first-2000 cap
        silently represented only the beginning of a year-long simulation.
        """
        agg = self.agg.setdefault(m["origin"], {
            "sent": 0, "delivered": 0, "lat": [], "latency_observations": 0})
        agg.setdefault("latency_observations", len(agg.get("lat", [])))
        agg["sent"] += 1
        if m["delivered"]:
            agg["delivered"] += 1
            if m["latency_s"] is not None:
                agg["latency_observations"] += 1
                n = agg["latency_observations"]
                if len(agg["lat"]) < LATENCY_RESERVOIR_SIZE:
                    agg["lat"].append(m["latency_s"])
                else:
                    j = int(self.rng_for(
                        "latency_reservoir", m["origin"]).integers(n))
                    if j < LATENCY_RESERVOIR_SIZE:
                        agg["lat"][j] = m["latency_s"]
        if m["kind"] == "sos":
            self.sos_log.append({"delivered": m["delivered"],
                                 "latency_s": m["latency_s"]})

    def prune_process(self):
        """Hourly memory pruning so year-long runs stay bounded: aggregate and
        drop settled packet metadata; cap dedupe sets."""
        while True:
            yield self.env.timeout(3600.0)
            cutoff = self.env.now - 600.0
            for key, m in list(self.pkt_meta.items()):
                if m["t0"] < cutoff:
                    self.aggregate_packet(m)
                    del self.pkt_meta[key]
                    self.delivered.discard(key)
            for node in self.nodes.values():
                if len(node.seen) > 20000:
                    node.seen.clear()   # dedupe window reset; dups are minutes-old

    # ── run + summary ────────────────────────────────────────────────────────
    def run(self) -> dict:
        route_groups: dict = {}
        for name, node in self.nodes.items():
            if name in self.hiker_names:
                self.env.process(self.gen_hiker(node, self.beacon_interval_s))
                if not self.kiosk_pool and node.route is not None:
                    self.env.process(self.rental_process(node))
                    self.env.process(self.gen_hiker_family(node))
                    route_groups.setdefault(id(node.route), []).append(node)
                elif self.kiosk_pool:
                    self.env.process(self.gen_hiker_family(node))
            elif not node.mqtt:
                self.env.process(self.gen_fixed_telemetry(node))
        for group in route_groups.values():
            for a, b in zip(group, group[1:]):    # partner pairs per route
                self.env.process(self.gen_hiker_msgs(a, b))
        if self.kiosk_pool:
            for w in self.walkers:
                self.env.process(self.kiosk_dispatch(w))
            self.env.process(self.kiosk_shuttle_process())
            if self.trace_fh:
                self.env.process(self.kiosk_inventory_process())
            # DMs: pair the waves of each route via today's assigned radios
            byroute: dict = {}
            for w in self.walkers:
                byroute.setdefault(w["route_name"], []).append(w)
            for grp in byroute.values():
                for a, b in zip(grp, grp[1:]):
                    self.env.process(self.gen_walker_msgs(a, b))
        self.env.process(self.gen_daily_sos())
        self.env.process(self.energy_process())
        self.env.process(self.prune_process())
        self.env.process(self.fleet_soc_process())
        if self.trace_fh:
            self.env.process(self.trace_process())
            self.env.process(self.pos_trace_process())
        self.env.run(until=self.days * 86400)
        if self.trace_fh:
            self.trace_fh.close()
        return self.summary()

    def summary(self) -> dict:
        # flush every remaining packet into the pruned aggregates, then report
        # from the aggregates (identical result for short runs, bounded memory
        # for year runs)
        for key, m in list(self.pkt_meta.items()):
            self.aggregate_packet(m)
            del self.pkt_meta[key]
        origin_stats = {}
        for origin, a in self.agg.items():
            lat = a["lat"]
            origin_stats[origin] = {
                "sent": a["sent"], "delivered": a["delivered"],
                "pdr": round(a["delivered"] / a["sent"], 4) if a["sent"] else None,
                "latency_p50_s": round(float(np.median(lat)), 2) if lat else None,
                "latency_p95_s": round(float(np.quantile(lat, 0.95)), 2) if lat else None,
                "latency_observations": a.get("latency_observations", len(lat)),
                "latency_sample_size": len(lat),
                "latency_delivered_count": a.get("latency_observations", len(lat)),
                "latency_sample_count": len(lat),
                "latency_sample_method": "algorithm_r_uniform_reservoir",
            }
        sos = self.sos_log
        dur = self.days * 86400
        node_stats = {}
        for n, nd in self.nodes.items():
            dead_s = self.node_dead_time_s(nd, dur)
            busy_s = self.channel_busy_through(n, dur)
            node_stats[n] = {
                **nd.stats,
                "death_events": nd.stats["deaths"],
                "ever_died": nd.ever_died,
                "dead_time_s": round(dead_s, 2),
                "availability": round(max(0.0, 1.0 - dead_s / max(dur, 1e-9)), 6),
                "channel_busy_s": round(busy_s, 2),
                "channel_busy_ratio": round(busy_s / max(dur, 1e-9), 6),
                "tx_airtime_s": round(nd.stats["tx_airtime_s"], 1),
                "energy_tx_wh": round(nd.stats["energy_tx_wh"], 3),
                "solar_wh": round(nd.stats["solar_wh"], 2),
                "final_soc": round(nd.soc_wh / nd.cap_wh, 3),
                "power": nd.power,
            }
        # struggling links: fixed-fixed pairs that carried traffic with thin
        # margin or heavy loss — the "where does the network hurt" table
        link_rows = []
        for (a, b), lh in self.link_health.items():
            if lh["try"] < 20:
                continue
            prr = lh["ok"] / lh["try"]
            mean_margin = lh["margin_sum"] / lh["try"]
            if prr < 0.05 and mean_margin < 0.0:
                continue                     # dead pair, just flood spillover
            status = ("healthy" if (prr >= 0.8 and mean_margin >= 10.0)
                      else "struggling")
            link_rows.append({"a": a, "b": b, "tries": lh["try"],
                              "prr": round(prr, 4),
                              "mean_margin_db": round(mean_margin, 1),
                              "status": status,
                              "struggling": status == "struggling"})
        link_rows.sort(key=lambda r: (r["prr"], r["mean_margin_db"]))
        renters = [n for n in self.hiker_names if self.nodes[n].route is not None]
        n_renters = len(self.walkers) if self.kiosk_pool else len(renters)
        solar = [nd for nd in self.nodes.values() if nd.power == "solar"]
        relay_e = np.array(sorted(nd.stats["energy_tx_wh"] for nd in solar))
        gini = (float(np.sum((2 * np.arange(1, len(relay_e) + 1)
                              - len(relay_e) - 1) * relay_e)
                      / max(len(relay_e) * relay_e.sum(), 1e-9))
                if len(relay_e) and relay_e.sum() > 0 else None)
        solar_dead_s = sum(self.node_dead_time_s(nd, dur) for nd in solar)
        death_events = int(sum(nd.stats["deaths"] for nd in solar))
        fleet = {
            "mean_duty": (round(float(np.mean([nd.duty for nd in solar])), 4)
                          if solar else None),
            "final_soc_std": (round(float(np.std(
                [nd.soc_wh / nd.cap_wh for nd in solar])), 4) if solar else None),
            "final_soc_min": (round(float(min(
                nd.soc_wh / nd.cap_wh for nd in solar)), 4) if solar else None),
            "deaths_total": death_events,  # compatibility alias: event count
            "death_events_total": death_events,
            "unique_nodes_died": sum(nd.ever_died for nd in solar),
            "dead_time_s_total": round(solar_dead_s, 2),
            "availability": (round(max(0.0, 1.0 - solar_dead_s /
                                  max(dur * len(solar), 1e-9)), 6)
                             if solar else None),
            "relay_energy_gini": round(gini, 4) if gini is not None else None,
            "soc_series_6h": self.fleet_soc_series,
        }
        fixed_names = [n for n in self.nodes if n not in self.hiker_names]
        busy_ratios = np.array([
            self.channel_busy_through(n, dur) / max(dur, 1e-9)
            for n in fixed_names
        ])
        occupancy = {
            "definition": ("union of intervals with local received power at or above "
                           f"{CARRIER_SENSE_DBM:g} dBm, including own transmissions"),
            "n_receivers": len(fixed_names),
            "receiver_busy_ratio_p50": (round(float(np.quantile(busy_ratios, 0.50)), 6)
                                        if len(busy_ratios) else None),
            "receiver_busy_ratio_p95": (round(float(np.quantile(busy_ratios, 0.95)), 6)
                                        if len(busy_ratios) else None),
            "receiver_busy_ratio_max": (round(float(np.max(busy_ratios)), 6)
                                        if len(busy_ratios) else None),
        }
        offered = self.total_airtime_s / max(dur, 1e-9)
        return {
            "mode": self.mode, "days": self.days, "seed": self.seed,
            "hop_limit": self.hop_limit,
            "n_renters": n_renters,
            "rental": ({"walker_days": self.rental_stats["walker_days"],
                        "served": self.rental_stats["served"],
                        "starved": self.rental_stats["starved"],
                        "starved_no_stock": self.rental_stats["starved_no_stock"],
                        "starved_unserviceable": self.rental_stats[
                            "starved_unserviceable"],
                        "unusable_at_checkout": self.rental_stats[
                            "unusable_at_checkout"],
                        "min_checkout_soc": float(self.cfg.get("kiosk", {}).get(
                            "min_checkout_soc", KIOSK_MIN_CHECKOUT_SOC)),
                        "availability": round(self.rental_stats["served"] /
                                              max(self.rental_stats["walker_days"], 1), 4),
                        "mean_checkout_soc": (round(float(np.mean(
                            self.rental_stats["checkout_socs"])), 3)
                            if self.rental_stats["checkout_socs"] else None)}
                       if self.kiosk_pool else None),
            "fleet_energy": fleet,
            "link_health": link_rows,
            "beacon_interval_s": self.beacon_interval_s,
            "n_nodes": len(self.nodes),
            "daily_kt": [round(k, 3) for k in self.daily_kt],
            # The legacy key is retained so existing artifact readers do not
            # break, but it is explicitly an offered-airtime ratio, not a
            # bounded measurement of local channel occupancy.
            "channel_utilization": round(offered, 5),
            "channel_utilization_definition": "deprecated alias of aggregate offered airtime",
            "aggregate_offered_airtime_ratio": round(offered, 5),
            "channel_occupancy": occupancy,
            "start_date": self.start_utc.date().isoformat(),
            "weather_driven": bool(self.weather),
            "rng_stream_model": "blake2_keyed_per_phenomenon_and_entity_v2",
            "traffic_clock_model": "exogenous_arrivals_independent_of_mac_service",
            "routing_solar_forecast": "monthly_climatology_no_future_weather",
            "duty_wake_model": ({
                "model": "deterministic_periodic_cad",
                "sniff_period_s": T_SNIFF_S,
                "cad_min_symbols": CAD_MIN_SYMBOLS,
                "phase": ("shared_zero" if self.mode == "duty_sync"
                          else "stable_per_node"),
                "missed_reception_possible": True,
            } if self.mode in DUTY_MODES else None),
            "packets_originated": sum(a["sent"] for a in self.agg.values()),
            "pdr_overall": (round(sum(a["delivered"] for a in self.agg.values())
                                  / max(sum(a["sent"] for a in self.agg.values()), 1), 4)
                            if self.agg else None),
            "sos": ({"sent": len(self.sos_incidents),
                     "delivered": sum(1 for i in self.sos_incidents.values()
                                      if i["delivered"]),
                     "latencies_s": [round(i["first_latency"], 2)
                                     for i in self.sos_incidents.values()
                                     if i["first_latency"] is not None],
                     "mean_tries": (round(float(np.mean([i["tries"] for i in
                                    self.sos_incidents.values()])), 2)
                                    if self.sos_incidents else None),
                     "level": "incident"}
                    if self.sos_incidents else
                    {"sent": len(sos), "delivered": sum(m["delivered"] for m in sos),
                     "latencies_s": [round(m["latency_s"], 2) for m in sos
                                     if m["latency_s"] is not None]}),
            "per_origin": origin_stats,
            "per_node": node_stats,
            "rl": self.rl_summary(),
        }

    def rl_summary(self) -> dict | None:
        """Learned-policy snapshot for q_routing / rl_duty (None otherwise)."""
        if self.mode == "q_routing" and self.qrt is not None:
            return {"updates": self.rl_updates,
                    "epsilon_final": round(self._rl_eps(), 4),
                    "q_entries": sum(len(v) for v in self.qrt.values()),
                    "policy": {u: {v: round(q, 3) for v, q in qs.items()}
                               for u, qs in self.qrt.items()}}
        if self.mode == "rl_duty":
            return {"updates": self.rl_updates,
                    "epsilon_final": round(self._rl_eps(), 4),
                    "q_entries": len(self.qduty),
                    "policy": {f"{s}|{a}": round(q, 3)
                               for (s, a), q in self.qduty.items()}}
        return None


def great_circle_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def run_sim(mode="flood", days=None, seed=None, extra_hikers=0,
            beacon_interval_s=None, hop_limit=None, trace_path=None,
            always_beacon=False, routes_path=None, renters_per_route=3,
            rx_trace_sample=1.0, bat_trace_s=BAT_TRACE_S, pos_trace_s=None,
            energy_step_s=None, weather_path=None, telemetry_interval_s=None,
            route_refresh_s=900.0, sos_retry=False, kiosk_pool=False,
            kiosk_demand_scale=None, hiker_trace_sample=1.0,
            config="config/sim/wmnf_sim.yaml",
            topology="artifacts/sim/topology.json") -> dict:
    import yaml
    cfg = yaml.safe_load((ROOT / config).read_text())
    topo = json.loads((ROOT / topology).read_text())
    routes = None
    if routes_path:
        rp = ROOT / routes_path if not Path(routes_path).is_absolute() else Path(routes_path)
        if rp.exists():
            routes = json.loads(rp.read_text())
    weather = None
    if weather_path:
        wp = ROOT / weather_path if not Path(weather_path).is_absolute() else Path(weather_path)
        if wp.exists():
            weather = json.loads(wp.read_text())
    sim = MeshSim(topo, cfg, mode=mode, days=days, seed=seed,
                  extra_hikers=extra_hikers, beacon_interval_s=beacon_interval_s,
                  hop_limit=hop_limit, always_beacon=always_beacon,
                  routes=routes, renters_per_route=renters_per_route,
                  rx_trace_sample=rx_trace_sample, bat_trace_s=bat_trace_s,
                  pos_trace_s=pos_trace_s, energy_step_s=energy_step_s,
                  weather=weather, telemetry_interval_s=telemetry_interval_s,
                  route_refresh_s=route_refresh_s, sos_retry=sos_retry,
                  kiosk_pool=kiosk_pool, kiosk_demand_scale=kiosk_demand_scale,
                  hiker_trace_sample=hiker_trace_sample,
                  trace_path=Path(trace_path) if trace_path else None)
    return sim.run()


def main() -> int:
    ap = argparse.ArgumentParser(description="WMNF mesh discrete-event simulation")
    ap.add_argument("--mode", choices=["flood", "min_hop", "etx", "energy_aware",
                    "lb_energy", "duty_sync", "duty_adaptive", "rotate_lb",
                    "q_routing", "rl_duty", "selective_duty"],
                    default="flood")
    ap.add_argument(
        "--days",
        type=float,
        default=None,
        help="Simulation duration in days; fractional days are supported for smoke runs",
    )
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--extra-hikers", type=int, default=0)
    ap.add_argument("--beacon-interval-s", type=float, default=None)
    ap.add_argument("--hop-limit", type=int, default=None)
    ap.add_argument("--trace", default="artifacts/sim/trace.jsonl")
    ap.add_argument("--out", default="artifacts/sim/summary.json")
    ap.add_argument("--routes", default="artifacts/sim/routes.json",
                    help="Rental-fleet routes ('' to disable)")
    ap.add_argument("--renters-per-route", type=int, default=3)
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--weather", default=None,
                    help="Historical reanalysis file from fetch_weather_year.py")
    ap.add_argument("--bat-trace-s", type=float, default=BAT_TRACE_S)
    ap.add_argument("--pos-trace-s", type=float, default=None)
    ap.add_argument("--energy-step-s", type=float, default=None)
    ap.add_argument("--telemetry-interval-s", type=float, default=None)
    ap.add_argument("--route-refresh-s", type=float, default=900.0)
    ap.add_argument("--rx-trace-sample", type=float, default=0.25)
    ap.add_argument("--sos-retry", action="store_true",
                    help="Gateway ACK + originator retry every 5 min until heard")
    ap.add_argument("--kiosk-pool", action="store_true",
                    help="Kiosk inventory model: shared radio pools, "
                         "best-charge checkout, +2 spares per kiosk")
    ap.add_argument("--kiosk-demand-scale", type=float, default=None,
                    help="Scale AMC-tier walker demand (1.0 = real ~212/day; "
                         "0.25 ≈ the 50-walker mega8 fleet)")
    ap.add_argument("--hiker-trace-sample", type=float, default=1.0,
                    help="Sample rate for hiker-origin tx/rx trace events "
                         "(SOS always traced)")
    args = ap.parse_args()

    (ROOT / "artifacts/sim").mkdir(parents=True, exist_ok=True)
    s = run_sim(mode=args.mode, days=args.days, seed=args.seed,
                extra_hikers=args.extra_hikers,
                beacon_interval_s=args.beacon_interval_s,
                hop_limit=args.hop_limit,
                routes_path=args.routes or None,
                renters_per_route=args.renters_per_route,
                rx_trace_sample=args.rx_trace_sample, topology=args.topology,
                weather_path=args.weather, bat_trace_s=args.bat_trace_s,
                pos_trace_s=args.pos_trace_s, energy_step_s=args.energy_step_s,
                telemetry_interval_s=args.telemetry_interval_s,
                route_refresh_s=args.route_refresh_s, sos_retry=args.sos_retry,
                kiosk_pool=args.kiosk_pool,
                kiosk_demand_scale=args.kiosk_demand_scale,
                hiker_trace_sample=args.hiker_trace_sample,
                trace_path=ROOT / args.trace if args.trace else None)
    out = ROOT / args.out
    out.write_text(json.dumps(s, indent=2))
    if s.get("rl"):
        pol = ROOT / f"artifacts/sim/ml/policy_{args.mode}.json"
        pol.parent.mkdir(parents=True, exist_ok=True)
        pol.write_text(json.dumps(s["rl"], indent=2))
        print(f"learned policy ({s['rl']['q_entries']} Q entries, "
              f"{s['rl']['updates']} updates, eps {s['rl']['epsilon_final']}) "
              f"-> {pol.relative_to(ROOT)}")
    print(json.dumps({k: v for k, v in s.items()
                      if k not in ("per_node", "per_origin", "link_health", "rl")},
                     indent=2))
    struggling = [r for r in s["link_health"] if r["struggling"]]
    print(f"struggling links ({len(struggling)} of {len(s['link_health'])} active):")
    for r in struggling[:12]:
        print(f"  {r['a']:>20s} <-> {r['b']:20s} PRR {r['prr']:.2f}  "
              f"margin {r['mean_margin_db']:+6.1f} dB  ({r['tries']} tries)")
    print("per-node:")
    for n, st in s["per_node"].items():
        print(f"  {n:22s} tx {st['tx']:5d}  rx {st['rx_ok']:6d}  col {st['collisions']:4d} "
              f" dup- {st['dup_suppressed']:4d}  E_tx {st['energy_tx_wh']:7.3f} Wh "
              f" solar {st['solar_wh']:7.2f} Wh  SOC {st['final_soc']:5.1%} "
              f" deaths {st['deaths']}  [{st['power']}]")
    written_outputs = [args.out]
    if args.trace:
        written_outputs.insert(0, args.trace)
    print("wrote " + ", ".join(written_outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
ROUTED_MODES = ("min_hop", "etx", "energy_aware", "lb_energy",
                "duty_sync", "duty_adaptive", "rotate_lb")
DUTY_MODES = ("duty_sync", "duty_adaptive", "rotate_lb")


# ── Support models ───────────────────────────────────────────────────────────
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
        self.stats = {"tx": 0, "rx_ok": 0, "collisions": 0, "dup_suppressed": 0,
                      "tx_airtime_s": 0.0, "energy_tx_wh": 0.0, "deaths": 0,
                      "solar_wh": 0.0}


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
                 kiosk_pool: bool = False, kiosk_spares: int = 2):
        self.always_beacon = always_beacon
        self.telemetry_interval_s = telemetry_interval_s
        self.routes = routes
        self.rx_trace_sample = rx_trace_sample
        self.bat_trace_s = bat_trace_s
        self.pos_trace_s = pos_trace_s if pos_trace_s is not None else bat_trace_s
        self.energy_step_s = energy_step_s
        self.topo, self.cfg, self.mode = topo, cfg, mode
        self.days = float(days or cfg["sim"]["duration_days"])  # fractions OK
        self.rng = np.random.default_rng(seed if seed is not None else cfg["sim"]["seed"])
        self.env = simpy.Environment()
        self.radio = cfg["radio"]
        self.hop_limit = hop_limit if hop_limit is not None else self.radio["hop_limit"]
        self.noise_dbm = -174.0 + 10 * math.log10(self.radio["bw_hz"]) + self.radio["noise_figure_db"]
        self.shadow = Shadowing(cfg["shadowing"]["sigma_db"], cfg["shadowing"]["fast_fading_db"],
                                cfg["shadowing"]["coherence_s"], self.rng)
        self.linkmodel = LinkModel(topo)
        self.start_utc = datetime.fromisoformat(cfg["sim"]["start_date"]).replace(tzinfo=timezone.utc)
        self.beacon_interval_s = beacon_interval_s or cfg["traffic"]["position_interval_s"]
        self.kiosk_pool = kiosk_pool
        self.kiosk_spares = kiosk_spares
        self.walkers: list = []            # kiosk-pool walker definitions
        self.walker_radio: dict = {}       # walker name -> radio name (today)
        self.rental_stats = {"walker_days": 0, "served": 0, "starved": 0,
                             "checkout_socs": []}

        self.nodes: dict[str, Node] = {}
        for name, s in topo["sites"].items():
            self.nodes[name] = Node(name, s, cfg, np.array(s["horizon_deg"]))
        # Hiker(s): node 0 replays the real GPX; extras are static walkers pinned
        # to random track waypoints (storm-sweep load generators).
        h = topo.get("hiker")
        self.hiker_names = []
        hz_valley = np.array(topo["sites"]["ammo_relay"]["horizon_deg"])  # proxy horizon
        if h:
            for k in range(1 + extra_hikers):
                name = "hiker_alpha" if k == 0 else f"hiker_{k:02d}"
                site = {"lat": h["lat"][0], "lon": h["lon"][0], "power": "battery"}
                self.nodes[name] = Node(name, site, cfg, hz_valley)
                self.nodes[name].track_offset = (0.0 if k == 0 else
                                                 float(self.rng.uniform(0, h["t_s"][-1])))
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
            # kiosk inventories: one radio per daily walker-wave + spares;
            # walkers draw the highest-charge docked radio each morning
            kiosk_load: dict = {}
            for rname, r in routes["routes"].items():
                for k in range(renters_per_route):
                    self.walkers.append({
                        "name": f"walker_{rname}_{k}", "route": r,
                        "route_name": rname,
                        "start_s": (11.5 + 1.5 * k) * 3600.0,
                        "kiosk": r["kiosk"], "return_kiosk": r["return_kiosk"]})
                    kiosk_load[r["kiosk"]] = kiosk_load.get(r["kiosk"], 0) + 1
            for kiosk, n_walkers in kiosk_load.items():
                ks = topo["sites"].get(kiosk)
                base = ({"lat": ks["lat"], "lon": ks["lon"]} if ks
                        else {"lat": 44.0, "lon": -71.5})
                for i in range(n_walkers + kiosk_spares):
                    name = f"radio_{kiosk}_{i}"
                    nd = Node(name, {**base, "power": "battery"}, cfg, hz_valley)
                    nd.docked = True
                    nd.kiosk = kiosk
                    self.nodes[name] = nd
                    self.hiker_names.append(name)

        self.active_tx: list[dict] = []   # in-flight transmissions
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
        # static fixed-site adjacency (margin dB) for the routed modes
        self.fixed_adj: dict[str, list] = {}
        eirp, sens = self.radio["eirp_dbm"], self.radio["rx_sensitivity_dbm"]
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
        # real historical weather (fetch_weather_year.py): per-day kt + snow
        self.weather = weather["days"] if weather else None
        if weather:
            self.start_utc = datetime.fromisoformat(
                weather["start_date"]).replace(tzinfo=timezone.utc)

    # ── time / trace helpers ────────────────────────────────────────────────
    def now_utc(self):
        return self.start_utc + timedelta(seconds=self.env.now)

    def emit(self, **kv):
        if self.trace_fh:
            kv["t"] = round(self.env.now, 2)
            self.trace_fh.write(json.dumps(kv) + "\n")

    def emit_sampled(self, **kv):
        if self.trace_fh and (self.rx_trace_sample >= 1.0
                              or self.rng.random() < self.rx_trace_sample):
            self.emit(**kv)

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
        return (self.radio["eirp_dbm"] - self.loss_db(a, b, t)
                + self.shadow.sample(a, b, t))

    # ── PHY: broadcast one packet on the shared channel ─────────────────────
    def transmit(self, sender: Node, pkt: dict):
        air_s = airtime_ms(pkt["bytes"], self.radio["sf"], self.radio["bw_hz"],
                           self.radio["cr"], self.radio["preamble_syms"]) / 1000.0
        if self.mode in DUTY_MODES:
            # X-MAC strobed preamble until the receiver's next CAD sniff
            air_s += float(self.rng.uniform(0.0, T_SNIFF_S))
        t0 = self.env.now
        tx = {"sender": sender.name, "start": t0, "end": t0 + air_s, "pkt": pkt,
              "rssi_at": {}}
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
                tx["rssi_at"][name] = self.radio["eirp_dbm"] - loss + sh
        self.active_tx.append(tx)
        sender.tx_until = t0 + air_s
        sender.stats["tx"] += 1
        if pkt["kind"] == "fwd":
            sender.fwd_ewma = 0.995 * sender.fwd_ewma + 1.0
        sender.stats["tx_airtime_s"] += air_s
        self.total_airtime_s += air_s
        e = self.cfg["energy"]
        etx = (e["tx_current_ma"] - e["rx_listen_ma"]) / 1000.0 * e["battery_v"] * air_s / 3600.0
        sender.stats["energy_tx_wh"] += etx
        if sender.power != "grid":
            sender.soc_wh -= etx
        if sender.name in self.hiker_names:
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
        for name, rssi in tx["rssi_at"].items():
            node = self.nodes[name]
            if not node.alive:
                continue
            if node.tx_until > tx["start"]:      # half-duplex: was transmitting
                continue
            interferers = [o for o in self.active_tx + [tx]
                           if o is not tx and o["sender"] != name
                           and o["start"] < tx["end"] and o["end"] > tx["start"]]
            worst_i = max((o["rssi_at"].get(name, -999.0) for o in interferers),
                          default=-999.0)
            snr = rssi - self.noise_dbm
            ok = (rssi >= self.radio["rx_sensitivity_dbm"]
                  and snr >= self.radio["snr_demod_threshold_db"])
            if ok and worst_i > rssi - self.radio["capture_threshold_db"]:
                node.stats["collisions"] += 1
                self.track_link_health(tx["sender"], name, rssi, False)
                self.emit_sampled(ev="col", n=name, pkt=tx["pkt"]["id"], **{"from": tx["sender"]})
                continue
            if not ok:
                self.track_link_health(tx["sender"], name, rssi, False)
                continue
            self.track_link_health(tx["sender"], name, rssi, True)
            node.stats["rx_ok"] += 1
            if tx["sender"] in self.hiker_names:
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
            yield self.env.timeout(float(self.rng.uniform(1, slots)) * SLOT_S * 8)
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
        for _ in range(attempts):
            if not node.alive:
                return
            if self.channel_busy_at(node):
                yield self.env.timeout(
                    float(self.rng.uniform(1, 2 if prio else 8)) * SLOT_S)
                continue
            yield self.env.timeout(
                float(self.rng.uniform(0, 1 if prio else 3)) * SLOT_S)
            if self.channel_busy_at(node):
                continue
            yield from self.transmit(node, pkt)
            return

    # ── energy-aware routing ─────────────────────────────────────────────────
    def _kt_for_day(self, day: int) -> float:
        if self.weather:
            return self.weather[min(day, len(self.weather) - 1)]["kt"]
        while len(self.daily_kt) <= day:
            month = (self.start_utc + timedelta(days=len(self.daily_kt))).month
            self.daily_kt.append(solar_model.sample_daily_kt(month, self.rng,
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
        """Expected panel Wh from now to midnight (today's kt, node's horizon).
        This is the 'estimated solar gain' term of the routing cost — a relay
        that will recharge this afternoon is cheaper to spend than one that
        won't see sun again until tomorrow."""
        day = int(t // 86400)
        key = (node.name, day)
        prof = getattr(self, "_solar_profiles", None)
        if prof is None:
            prof = self._solar_profiles = {}
        if key not in prof:
            kt = self._kt_for_day(day)
            day0 = self.start_utc + timedelta(days=day)
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

    def build_route_tree(self):
        """Multi-source Dijkstra from live gateways over the fixed-site graph."""
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
            for n, nd in self.nodes.items():
                if nd.mqtt or nd.power == "grid" or n in self.hiker_names:
                    continue
                if self.mode == "duty_sync":
                    nd.duty = 0.05
                elif self.mode == "duty_adaptive":
                    runway = nd.soc_wh + (self.solar_remaining_wh(nd, t)
                                          if nd.power == "solar" else 0.0)
                    rf = min(runway / nd.cap_wh, 1.0)
                    nd.duty = float(np.clip(0.02 + 0.23 * rf, 0.02, 0.25))
                else:  # rotate_lb: tree relays always-on, everyone else sniffs
                    nd.duty = 1.0 if n in on_tree else 0.02

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
            margin = self.radio["eirp_dbm"] - loss - self.radio["rx_sensitivity_dbm"]
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
        yield self.env.timeout(float(self.rng.uniform(0, iv)))
        while True:
            if node.alive:
                pkt = self.new_pkt(node.name, "tel", tr["telemetry_payload_b"])
                yield from self.csma_send(node, pkt)
            yield self.env.timeout(iv * float(self.rng.uniform(0.9, 1.1)))

    def gen_hiker(self, node: Node, interval_s: float):
        tr = self.cfg["traffic"]
        yield self.env.timeout(float(self.rng.uniform(0, interval_s)))
        while True:
            if node.alive and not node.docked:
                if node.route is not None:
                    walking = self.route_track_t(node, self.env.now) is not None
                else:
                    walking = 0.0 < self.hiker_track_t(node, self.env.now)
                if walking or self.always_beacon or (node.name != "hiker_alpha"
                                                     and node.route is None):
                    pkt = self.new_pkt(node.name, "pos", tr["position_payload_b"])
                    yield from self.csma_send(node, pkt)
            yield self.env.timeout(interval_s * float(self.rng.uniform(0.9, 1.1)))

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
            pool = [nd for nd in self.nodes.values()
                    if getattr(nd, "kiosk", None) == w["kiosk"] and nd.docked]
            if not pool:
                self.rental_stats["starved"] += 1
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
            self.emit(ev="kiosk", inv={k: sorted(v, reverse=True)
                                       for k, v in inv.items()})

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
        yield self.env.timeout(float(self.rng.uniform(600, 1800)))
        turn = 0
        while True:
            if (a.alive and b.alive and not a.docked and not b.docked
                    and self.route_track_t(a, self.env.now) is not None
                    and self.route_track_t(b, self.env.now) is not None):
                src_n, dst_n = (a, b) if turn % 2 == 0 else (b, a)
                pkt = self.new_pkt(src_n.name, "msg", tr["sos_payload_b"],
                                   dest=dst_n.name, flood=True)
                yield from self.csma_send(src_n, pkt)
                turn += 1
            yield self.env.timeout(float(self.rng.uniform(1800, 3600)))

    def gen_hiker_family(self, node: Node):
        """Occasional 'tell the family' message: hiker → any MQTT gateway →
        the outside world."""
        tr = self.cfg["traffic"]
        yield self.env.timeout(float(self.rng.uniform(1200, 2400)))
        while True:
            if (node.alive and not node.docked
                    and self.route_track_t(node, self.env.now) is not None):
                pkt = self.new_pkt(node.name, "fam", tr["sos_payload_b"])
                yield from self.csma_send(node, pkt)
            yield self.env.timeout(float(self.rng.uniform(2700, 5400)))

    def gen_walker_msgs(self, wa: dict, wb: dict):
        tr = self.cfg["traffic"]
        yield self.env.timeout(float(self.rng.uniform(600, 1800)))
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
                    yield from self.csma_send(src_n, pkt)
                    turn += 1
            yield self.env.timeout(float(self.rng.uniform(1800, 3600)))

    def gen_daily_sos(self):
        """One SOS per day from a random mid-route walker (renter if present)."""
        tr = self.cfg["traffic"]
        h = self.topo["hiker"]
        for day in range(max(int(math.ceil(self.days)), 1)):
            if self.rng.random() > 0.5:          # ~180 incidents/yr statewide
                yield self.env.timeout(max((day + 1) * 86400 - self.env.now, 0.0))
                continue
            # pick the sender AT INCIDENT TIME: whoever is actually out hiking
            # (kiosk-pool radios have routes only while checked out)
            t_sos = day * 86400 + float(self.rng.uniform(13.0, 19.0)) * 3600.0
            yield self.env.timeout(max(t_sos - self.env.now, 0.0))
            out_now = [nd for nd in self.nodes.values()
                       if nd.route is not None and not nd.docked and nd.alive]
            if out_now:
                node = out_now[int(self.rng.integers(len(out_now)))]
                name = node.name
            elif h:
                name, node = "hiker_alpha", self.nodes["hiker_alpha"]
                t_sos = day * 86400 + 12 * 3600 + float(self.rng.uniform(0.2, 0.8)) * h["t_s"][-1]
            else:
                continue
            if node.alive and not node.docked:
                pkt = self.new_pkt(name, "sos", tr["sos_payload_b"], flood=True)
                sos_id = pkt["id"]
                pkt["sos_id"] = sos_id
                self.sos_incidents[sos_id] = {"t0": self.env.now, "tries": 1,
                                              "delivered": False,
                                              "first_latency": None}
                yield from self.csma_send(node, pkt)
                for gap in (30.0, 60.0):          # beacon repeats; dedupe upstream
                    yield self.env.timeout(gap)
                    if node.alive:
                        yield from self.csma_send(node, dict(pkt))
                if self.sos_retry:
                    # retry as fresh packets every 5 min until the gateway ACK
                    # arrives — the hiker keeps signaling until heard
                    for _ in range(24):
                        yield self.env.timeout(300.0)
                        if (sos_id in self.sos_acked or not node.alive
                                or node.docked):
                            break
                        rp = self.new_pkt(name, "sos", tr["sos_payload_b"],
                                          flood=True)
                        rp["sos_id"] = sos_id
                        self.sos_incidents[sos_id]["tries"] += 1
                        yield from self.csma_send(node, rp)

    # ── energy / solar / bookkeeping processes ───────────────────────────────
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
            for node in self.nodes.values():
                if node.power == "grid":
                    continue
                if node.docked:                      # in the charging box
                    node.soc_wh = min(node.soc_wh + KIOSK_CHARGE_W * step / 3600.0,
                                      node.cap_wh)
                    if not node.alive and node.soc_wh >= REVIVE_FRACTION * node.cap_wh:
                        node.alive = True
                        self.emit(ev="alive", n=node.name)
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
                        node.soc_wh, node.alive = 0.0, False
                        node.stats["deaths"] += 1
                        node.death_score = 0.7 * node.death_score + 1.0
                        self.route_tree_t = -1e9      # force tree rebuild
                        self.emit(ev="dead", n=node.name)
                elif node.soc_wh >= REVIVE_FRACTION * node.cap_wh:
                    node.alive = True
                    self.route_tree_t = -1e9
                    self.emit(ev="alive", n=node.name)
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

    def prune_process(self):
        """Hourly memory pruning so year-long runs stay bounded: aggregate and
        drop settled packet metadata; cap dedupe sets."""
        while True:
            yield self.env.timeout(3600.0)
            cutoff = self.env.now - 600.0
            for key, m in list(self.pkt_meta.items()):
                if m["t0"] < cutoff:
                    agg = self.agg.setdefault(m["origin"], {
                        "sent": 0, "delivered": 0, "lat": []})
                    agg["sent"] += 1
                    if m["delivered"]:
                        agg["delivered"] += 1
                        if m["latency_s"] is not None and len(agg["lat"]) < 2000:
                            agg["lat"].append(m["latency_s"])
                    if m["kind"] == "sos":
                        self.sos_log.append({"delivered": m["delivered"],
                                             "latency_s": m["latency_s"]})
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
            agg = self.agg.setdefault(m["origin"], {"sent": 0, "delivered": 0, "lat": []})
            agg["sent"] += 1
            if m["delivered"]:
                agg["delivered"] += 1
                if m["latency_s"] is not None and len(agg["lat"]) < 2000:
                    agg["lat"].append(m["latency_s"])
            if m["kind"] == "sos":
                self.sos_log.append({"delivered": m["delivered"],
                                     "latency_s": m["latency_s"]})
            del self.pkt_meta[key]
        origin_stats = {}
        for origin, a in self.agg.items():
            lat = a["lat"]
            origin_stats[origin] = {
                "sent": a["sent"], "delivered": a["delivered"],
                "pdr": round(a["delivered"] / a["sent"], 4) if a["sent"] else None,
                "latency_p50_s": round(float(np.median(lat)), 2) if lat else None,
                "latency_p95_s": round(float(np.quantile(lat, 0.95)), 2) if lat else None,
            }
        sos = self.sos_log
        node_stats = {n: {**nd.stats,
                          "tx_airtime_s": round(nd.stats["tx_airtime_s"], 1),
                          "energy_tx_wh": round(nd.stats["energy_tx_wh"], 3),
                          "solar_wh": round(nd.stats["solar_wh"], 2),
                          "final_soc": round(nd.soc_wh / nd.cap_wh, 3),
                          "power": nd.power}
                      for n, nd in self.nodes.items()}
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
        solar = [nd for nd in self.nodes.values() if nd.power == "solar"]
        relay_e = np.array(sorted(nd.stats["energy_tx_wh"] for nd in solar))
        gini = (float(np.sum((2 * np.arange(1, len(relay_e) + 1)
                              - len(relay_e) - 1) * relay_e)
                      / max(len(relay_e) * relay_e.sum(), 1e-9))
                if len(relay_e) and relay_e.sum() > 0 else None)
        fleet = {
            "mean_duty": round(float(np.mean([nd.duty for nd in solar])), 4),
            "final_soc_std": round(float(np.std([nd.soc_wh / nd.cap_wh for nd in solar])), 4),
            "final_soc_min": round(float(min(nd.soc_wh / nd.cap_wh for nd in solar)), 4),
            "deaths_total": int(sum(nd.stats["deaths"] for nd in solar)),
            "relay_energy_gini": round(gini, 4) if gini is not None else None,
            "soc_series_6h": self.fleet_soc_series,
        }
        dur = self.days * 86400
        return {
            "mode": self.mode, "days": self.days, "hop_limit": self.hop_limit,
            "n_renters": len(renters),
            "rental": ({"walker_days": self.rental_stats["walker_days"],
                        "served": self.rental_stats["served"],
                        "starved": self.rental_stats["starved"],
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
            "channel_utilization": round(self.total_airtime_s / dur, 5),
            "start_date": self.start_utc.date().isoformat(),
            "weather_driven": bool(self.weather),
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
        }


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
                  kiosk_pool=kiosk_pool,
                  trace_path=Path(trace_path) if trace_path else None)
    return sim.run()


def main() -> int:
    ap = argparse.ArgumentParser(description="WMNF mesh discrete-event simulation")
    ap.add_argument("--mode", choices=["flood", "min_hop", "etx", "energy_aware",
                    "lb_energy", "duty_sync", "duty_adaptive", "rotate_lb"],
                    default="flood")
    ap.add_argument("--days", type=int, default=None)
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
                    help="Real-weather file from fetch_weather_year.py")
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
                trace_path=ROOT / args.trace if args.trace else None)
    out = ROOT / args.out
    out.write_text(json.dumps(s, indent=2))
    print(json.dumps({k: v for k, v in s.items()
                      if k not in ("per_node", "per_origin", "link_health")}, indent=2))
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
    print(f"wrote {args.trace}, {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

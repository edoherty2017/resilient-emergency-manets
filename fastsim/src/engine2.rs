//! Event handlers + run loop.

use crate::inputs::*;
use crate::rng::Rng;
use crate::sim::*;
use crate::solar::solar_power_w;
use std::cmp::Reverse;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

const RX_GATE_DB: f64 = 220.0;

impl Sim {
    fn sched(&mut self, dt: f64, ev: Ev) -> u64 {
        self.seq += 1;
        let seq = self.seq;
        self.heap.push(Reverse(Sched {
            t: self.now + dt,
            seq,
            ev,
        }));
        seq
    }

    pub fn run(&mut self) {
        let end = self.p.days * 86400.0;
        while let Some(Reverse(s)) = self.heap.pop() {
            // The modeled interval is [0, end).  Processing a checkout exactly
            // at `end` would count a served rental with zero in-horizon time.
            if s.t >= end {
                break;
            }
            self.now = s.t;
            self.handle(s.ev, s.seq);
        }
        self.now = end;
        if self.now > self.energy_last_t {
            self.handle_energy();
        }
        if self.p.mode.is_duty() && self.route_tree_t < -1.0e17 {
            self.build_route_tree();
        }
        self.final_prune();
    }

    fn handle(&mut self, ev: Ev, seq: u64) {
        match ev {
            Ev::Telemetry { node } => {
                if self.nodes[node as usize].alive {
                    let b = self.cfg.traffic.telemetry_payload_b;
                    let f = self.new_flight2(node, Kind::Tel, b, Dest::Mqtt, false);
                    self.csma2(node, f);
                }
                let jitter = self.event_uniform(RNG_TRAFFIC_TELEMETRY, node as u64, 0.9, 1.1);
                let iv = self.p.telemetry_iv * jitter;
                self.sched(iv, Ev::Telemetry { node });
            }
            Ev::Beacon { node } => {
                let n = &self.nodes[node as usize];
                if n.alive && !n.docked && self.walking(node) {
                    let b = self.cfg.traffic.position_payload_b;
                    let f = self.new_flight2(node, Kind::Pos, b, Dest::Mqtt, false);
                    self.csma2(node, f);
                }
                let jitter = self.event_uniform(RNG_TRAFFIC_BEACON, node as u64, 0.9, 1.1);
                let iv = self.p.beacon_iv * jitter;
                self.sched(iv, Ev::Beacon { node });
            }
            Ev::Family { node } => {
                let n = &self.nodes[node as usize];
                if n.alive && !n.docked && self.walking(node) {
                    let b = self.cfg.traffic.sos_payload_b;
                    let f = self.new_flight2(node, Kind::Fam, b, Dest::Mqtt, false);
                    self.csma2(node, f);
                }
                let iv = self.event_uniform(RNG_TRAFFIC_FAMILY, node as u64, 2700.0, 5400.0);
                self.sched(iv, Ev::Family { node });
            }
            Ev::MsgPair {
                route,
                wa,
                wb,
                turn,
            } => {
                let ra = self.walkers[wa as usize].radio;
                let rb = self.walkers[wb as usize].radio;
                let mut next_turn = turn;
                if let (Some(ra), Some(rb)) = (ra, rb) {
                    let (a, b) = (&self.nodes[ra as usize], &self.nodes[rb as usize]);
                    if a.alive
                        && b.alive
                        && !a.docked
                        && !b.docked
                        && self.walking(ra)
                        && self.walking(rb)
                    {
                        let (src, dst) = if turn % 2 == 0 { (ra, rb) } else { (rb, ra) };
                        let bytes = self.cfg.traffic.sos_payload_b;
                        let f = self.new_flight2(src, Kind::Msg, bytes, Dest::Node(dst), true);
                        self.csma2(src, f);
                        next_turn += 1;
                    }
                }
                let entity = ((wa as u64) << 32) | wb as u64;
                let iv = self.event_uniform(RNG_TRAFFIC_MESSAGE, entity, 1800.0, 3600.0);
                self.sched(
                    iv,
                    Ev::MsgPair {
                        route,
                        wa,
                        wb,
                        turn: next_turn,
                    },
                );
            }
            Ev::SosDay { day } => {
                let next_day_t = (day as f64 + 1.0) * 86400.0;
                if Rng::keyed_f64(self.p.seed, RNG_INCIDENT_OCCURRENCE, day as u64) <= 0.5 {
                    let hour =
                        13.0 + 6.0 * Rng::keyed_f64(self.p.seed, RNG_INCIDENT_TIME, day as u64);
                    let t_sos = day as f64 * 86400.0 + hour * 3600.0;
                    let dt = (t_sos - self.now).max(0.0);
                    self.sched(
                        dt,
                        Ev::SosSend {
                            node: u32::MAX,
                            // For stage zero this field carries the immutable
                            // day key; later stages carry the incident ID.
                            sos_id: day as u64,
                            stage: 0,
                        },
                    );
                }
                if ((day + 1) as f64) < self.p.days.ceil() {
                    self.sched(
                        (next_day_t - self.now).max(0.0),
                        Ev::SosDay { day: day + 1 },
                    );
                }
            }
            Ev::SosSend {
                node,
                sos_id,
                stage,
            } => {
                self.handle_sos(node, sos_id, stage);
            }
            Ev::SosBurst { node, flight } => {
                let n = &self.nodes[node as usize];
                if n.alive
                    && !n.docked
                    && self.now <= flight.expires_at
                    && self.pkt_meta.contains_key(&flight.id)
                {
                    self.csma2(node, flight);
                }
            }
            Ev::TxAttempt {
                node,
                flight,
                tries,
                post_difs,
            } => {
                self.handle_tx_attempt(node, flight, tries, post_difs);
            }
            Ev::TxEnd { idx } => {
                self.handle_tx_end(idx);
            }
            Ev::RebroadcastFire { node, key, flight } => {
                let n = &mut self.nodes[node as usize];
                if n.pending.get(&key) == Some(&seq) {
                    n.pending.remove(&key);
                    if self.now <= flight.expires_at && self.pkt_meta.contains_key(&flight.id) {
                        self.csma2(node, flight);
                    }
                }
            }
            Ev::EnergyStep => {
                self.handle_energy();
                self.sched(self.p.energy_step_s, Ev::EnergyStep);
            }
            Ev::SocSample => {
                let mut socs: Vec<f64> = self
                    .nodes
                    .iter()
                    .filter(|n| n.solar)
                    .map(|n| n.soc_wh / n.cap_wh)
                    .collect();
                socs.sort_by(f64::total_cmp);
                if !socs.is_empty() {
                    let mean = socs.iter().sum::<f64>() / socs.len() as f64;
                    let var =
                        socs.iter().map(|x| (x - mean).powi(2)).sum::<f64>() / socs.len() as f64;
                    self.soc_series.push((
                        self.now / 86400.0,
                        linear_quantile_sorted(&socs, 0.10).expect("non-empty SOC sample"),
                        linear_quantile_sorted(&socs, 0.50).expect("non-empty SOC sample"),
                        linear_quantile_sorted(&socs, 0.90).expect("non-empty SOC sample"),
                        var.sqrt(),
                    ));
                }
                self.sched(21600.0, Ev::SocSample);
            }
            Ev::Prune => {
                let cutoff = self.now - 600.0;
                let settled: Vec<u64> = self
                    .pkt_meta
                    .iter()
                    .filter(|(_, m)| m.t0 < cutoff)
                    .map(|(k, _)| *k)
                    .collect();
                for id in settled {
                    let m = self.pkt_meta.remove(&id).unwrap();
                    self.settle_packet(id, m);
                }
                for n in &mut self.nodes {
                    if n.seen.len() > 20000 {
                        n.seen.clear();
                    }
                }
                self.sched(3600.0, Ev::Prune);
            }
            Ev::Dispatch { walker } => {
                self.handle_dispatch(walker);
            }
            Ev::WalkEnd { walker } => {
                let (radio, ret) = {
                    let w = &mut self.walkers[walker as usize];
                    (w.radio.take(), w.return_kiosk)
                };
                if let Some(radio) = radio {
                    self.set_docked(radio, true);
                    let n = &mut self.nodes[radio as usize];
                    n.kiosk = Some(ret);
                    n.route = None;
                }
            }
            Ev::Shuttle => {
                self.handle_shuttle();
                self.sched(86400.0, Ev::Shuttle);
            }
            Ev::OutageStart { node } => {
                self.nodes[node as usize].forced_outage = true;
                self.refresh_node_availability(node);
            }
            Ev::OutageEnd { node } => {
                self.nodes[node as usize].forced_outage = false;
                self.refresh_node_availability(node);
            }
        }
        if self.p.mode.is_duty() && self.route_tree_t < -1.0e17 {
            self.build_route_tree();
        }
    }

    fn walking(&self, node: u32) -> bool {
        self.track_t2(node).is_some()
    }

    fn track_t2(&self, node: u32) -> Option<f64> {
        let n = &self.nodes[node as usize];
        let ri = n.route? as usize;
        let route = self.routes.get(ri)?;
        let tt = self.now - n.start_s;
        if tt >= 0.0 && tt < route.duration_s {
            Some(tt)
        } else {
            None
        }
    }

    fn handle_sos(&mut self, node: u32, sos_id: u64, stage: u32) {
        if stage == 0 {
            // pick whoever is actually out hiking right now
            let out: Vec<u32> = (self.n_fixed..self.nodes.len())
                .map(|i| i as u32)
                .filter(|&i| {
                    let n = &self.nodes[i as usize];
                    n.alive && !n.docked && n.route.is_some() && self.walking(i)
                })
                .collect();
            if out.is_empty() {
                return;
            }
            let sender_u = Rng::keyed_f64(self.p.seed, RNG_INCIDENT_SENDER, sos_id);
            let origin = out[((sender_u * out.len() as f64) as usize).min(out.len() - 1)];
            let bytes = self.cfg.traffic.sos_payload_b;
            let mut f = self.new_flight2(origin, Kind::Sos, bytes, Dest::Mqtt, true);
            let sid = f.id;
            f.sos_id = sid;
            self.sos_incidents.insert(sid, (self.now, 1, false, 0.0));
            self.csma2(origin, f.clone());
            // Three physical copies form one logical initial attempt.  Copies
            // retain the packet ID so normal duplicate suppression applies.
            self.sched(
                30.0,
                Ev::SosBurst {
                    node: origin,
                    flight: f.clone(),
                },
            );
            self.sched(
                60.0,
                Ev::SosBurst {
                    node: origin,
                    flight: f,
                },
            );
            if self.p.sos_retry {
                self.sched(
                    300.0,
                    Ev::SosSend {
                        node: origin,
                        sos_id: sid,
                        stage: 1,
                    },
                );
            }
            return;
        }
        let n = &self.nodes[node as usize];
        if !n.alive || n.docked || !self.walking(node) {
            return;
        }
        // 5-minute retries until ACK, up to 24
        if self.sos_acked.contains(&sos_id) || stage > 24 {
            return;
        }
        if let Some(inc) = self.sos_incidents.get_mut(&sos_id) {
            inc.1 += 1;
        }
        let bytes = self.cfg.traffic.sos_payload_b;
        let mut f = self.new_flight2(node, Kind::Sos, bytes, Dest::Mqtt, true);
        f.sos_id = sos_id;
        self.csma2(node, f);
        self.sched(
            300.0,
            Ev::SosSend {
                node,
                sos_id,
                stage: stage + 1,
            },
        );
    }

    fn handle_tx_attempt(&mut self, node: u32, flight: Flight, tries: u32, post_difs: bool) {
        if !self.nodes[node as usize].alive
            || self.nodes[node as usize].docked
            || self.now > flight.expires_at
            || !self.pkt_meta.contains_key(&flight.id)
        {
            return;
        }
        // A radio cannot originate/forward two frames concurrently.  This is
        // a local resource wait, not a failed CSMA attempt.
        let own_tx_until = self.nodes[node as usize].tx_until;
        if own_tx_until > self.now {
            self.sched(
                own_tx_until - self.now,
                Ev::TxAttempt {
                    node,
                    flight,
                    tries,
                    // The prior DIFS is no longer valid after waiting through
                    // our own transmission; sense the channel and perform a
                    // fresh DIFS before sending.
                    post_difs: false,
                },
            );
            return;
        }
        let prio = flight.okind == Kind::Sos;
        let max_tries = if prio { 200 } else { 30 };
        if tries >= max_tries {
            return;
        }
        let busy = self.channel_busy_at2(node);
        if !post_difs {
            if busy {
                let d = self.event_uniform(
                    RNG_MAC_BUSY_BACKOFF,
                    node as u64,
                    1.0,
                    if prio { 2.0 } else { 8.0 },
                ) * SLOT_S;
                self.sched(
                    d,
                    Ev::TxAttempt {
                        node,
                        flight,
                        tries: tries + 1,
                        post_difs: false,
                    },
                );
            } else {
                let d = self.event_uniform(
                    RNG_MAC_DIFS,
                    node as u64,
                    0.0,
                    if prio { 1.0 } else { 3.0 },
                ) * SLOT_S;
                self.sched(
                    d,
                    Ev::TxAttempt {
                        node,
                        flight,
                        tries,
                        post_difs: true,
                    },
                );
            }
            return;
        }
        if busy {
            self.sched(
                0.0,
                Ev::TxAttempt {
                    node,
                    flight,
                    tries: tries + 1,
                    post_difs: false,
                },
            );
            return;
        }
        self.transmit(node, flight);
    }

    fn transmit(&mut self, sender: u32, flight: Flight) {
        // Pay all baseline/GPS energy accrued through this instant before
        // deciding whether the sender can start another frame.
        self.accrue_node_energy_state(sender);
        self.settle_node_energy_segments(sender);
        if !self.nodes[sender as usize].alive || self.nodes[sender as usize].docked {
            return;
        }
        // Duty cycling affects deterministic receiver acquisition, not packet
        // airtime.  The old random 0..1 s extension was a perfect-wakeup
        // abstraction and also consumed an algorithm-dependent RNG draw.
        let air = self.airtime_s2(flight.bytes);
        let horizon = self.p.days * 86400.0;
        let accounted_air = ((self.now + air).min(horizon) - self.now).max(0.0);
        let etx = {
            let e = &self.cfg.energy;
            let sender_node = &self.nodes[sender as usize];
            let listen_ma = if sender_node.is_radio && self.p.hiker_rx_ma > 0.0 {
                self.p.hiker_rx_ma
            } else if !sender_node.is_radio && self.p.relay_rx_ma > 0.0 {
                self.p.relay_rx_ma
            } else {
                e.rx_listen_ma
            };
            let baseline_ma =
                sender_node.duty * listen_ma + (1.0 - sender_node.duty) * e.light_sleep_ma;
            let incremental_tx_ma = (e.tx_current_ma - baseline_ma).max(0.0);
            incremental_tx_ma / 1000.0 * e.battery_v * accounted_air / 3600.0
        };
        if !self.nodes[sender as usize].grid && self.nodes[sender as usize].soc_wh < etx {
            let n = &mut self.nodes[sender as usize];
            n.soc_wh = 0.0;
            n.energy_alive = false;
            n.stats.deaths += 1;
            n.death_score = 0.7 * n.death_score + 1.0;
            self.refresh_node_availability(sender);
            return;
        }
        let mut rssi_at = Vec::new();
        for j in 0..self.nodes.len() as u32 {
            if j == sender {
                continue;
            }
            let (receiver_docked, receiver_channel, receiver_epoch) = {
                let receiver = &self.nodes[j as usize];
                (
                    receiver.docked,
                    receiver.channel,
                    receiver.availability_epoch,
                )
            };
            if receiver_docked {
                continue;
            }
            if self.p.regional_channels && receiver_channel != self.nodes[sender as usize].channel {
                continue;
            }
            let loss = self.loss_db(sender, j);
            if loss > RX_GATE_DB {
                continue;
            }
            let sh = self.shadow_sample2(sender, j);
            rssi_at.push((
                j,
                self.cfg.radio.received_power_reference_dbm() - loss + sh,
                receiver_epoch,
            ));
        }
        let end = self.now + air;
        let cad_acquired: HashSet<u32> = rssi_at
            .iter()
            .map(|(rx, _, _)| *rx)
            .filter(|&rx| self.receiver_acquires_preamble_at(rx, self.now, end))
            .collect();
        self.local_busy[sender as usize].add(self.now, end);
        for &(rx, rssi, _) in &rssi_at {
            if rssi >= CARRIER_SENSE_DBM {
                self.local_busy[rx as usize].add(self.now, end);
            }
        }
        let idx = self.next_tx_idx;
        self.next_tx_idx += 1;
        self.active.insert(
            idx,
            ActiveTx {
                start: self.now,
                end,
                sender,
                rssi_at,
                sender_availability_epoch: self.nodes[sender as usize].availability_epoch,
                cad_acquired,
                flight: flight.clone(),
            },
        );
        {
            let n = &mut self.nodes[sender as usize];
            n.tx_until = end;
            n.stats.tx += 1;
            n.stats.tx_airtime_s += accounted_air;
            n.stats.energy_tx_wh += etx;
            if !n.grid {
                n.soc_wh = (n.soc_wh - etx).max(0.0);
                if n.energy_alive && n.soc_wh <= 0.0 {
                    n.soc_wh = 0.0;
                    n.energy_alive = false;
                    n.stats.deaths += 1;
                    n.death_score = 0.7 * n.death_score + 1.0;
                }
            }
        }
        if flight.is_fwd {
            self.record_forward(sender);
        }
        self.refresh_node_availability(sender);
        self.total_offered_airtime_s += accounted_air;
        self.sched(air, Ev::TxEnd { idx });
    }

    fn handle_tx_end(&mut self, idx: u64) {
        let Some(tx) = self.active.remove(&idx) else {
            return;
        };
        let noise = self.noise_dbm2();
        let r = &self.cfg.radio;
        let (sens, demod, capture) = (
            r.rx_sensitivity_dbm,
            r.snr_demod_threshold_db,
            r.capture_threshold_db,
        );
        let sender_fixed = !self.nodes[tx.sender as usize].is_radio;
        let sender_continuously_available = self.nodes[tx.sender as usize].alive
            && !self.nodes[tx.sender as usize].docked
            && self.nodes[tx.sender as usize].availability_epoch == tx.sender_availability_epoch;
        for &(rx, rssi, receiver_epoch) in &tx.rssi_at {
            if !sender_continuously_available
                || !self.nodes[rx as usize].alive
                || self.nodes[rx as usize].docked
                || self.nodes[rx as usize].availability_epoch != receiver_epoch
            {
                continue;
            }
            let receiver_was_transmitting = self
                .active
                .values()
                .chain(self.completed_overlap.values())
                .any(|other| other.sender == rx && other.start < tx.end && other.end > tx.start);
            if receiver_was_transmitting {
                // Exact interval overlap; a TX starting exactly at tx.end does
                // not retroactively make this reception half-duplex.
                continue;
            }
            let snr = rssi - noise;
            let phy_ok = rssi >= sens && snr >= demod;
            let cad_acquired = tx.cad_acquired.contains(&rx);
            if phy_ok && !cad_acquired {
                self.nodes[rx as usize].stats.duty_misses += 1;
            }
            let mut worst_i = f64::NEG_INFINITY;
            if cad_acquired {
                for other in self.active.values().chain(self.completed_overlap.values()) {
                    if other.sender != rx && other.start < tx.end && other.end > tx.start {
                        if let Some(&(_, ri, _)) = other.rssi_at.iter().find(|(n, _, _)| *n == rx) {
                            worst_i = worst_i.max(ri);
                        }
                    }
                }
            }
            // Link health measures PHY opportunities, not a duty-cycle CAD
            // sleep that deliberately prevented an attempted reception.
            if sender_fixed && !self.nodes[rx as usize].is_radio && cad_acquired {
                let key = if tx.sender < rx {
                    (tx.sender, rx)
                } else {
                    (rx, tx.sender)
                };
                let lh = self.link_health.entry(key).or_insert(LinkHealth {
                    tries: 0,
                    ok: 0,
                    margin_sum: 0.0,
                });
                lh.tries += 1;
                lh.margin_sum += rssi - sens;
                if phy_ok && cad_acquired && worst_i <= rssi - capture {
                    lh.ok += 1;
                }
            }
            if !phy_ok || !cad_acquired {
                continue;
            }
            if worst_i > rssi - capture {
                self.nodes[rx as usize].stats.collisions += 1;
                continue;
            }
            self.nodes[rx as usize].stats.rx_ok += 1;
            self.on_receive(rx, &tx.flight, snr);
        }

        // Keep the completed frame while any currently active frame overlaps
        // it.  A later TxEnd can therefore see earlier-ending interferers.
        self.completed_overlap.insert(idx, tx);
        let active = &self.active;
        self.completed_overlap.retain(|_, old| {
            active
                .values()
                .any(|a| a.start < old.end && a.end > old.start)
        });
    }

    fn on_receive(&mut self, rx: u32, flight: &Flight, snr: f64) {
        let key = (flight.origin, flight.id);
        {
            let node = &mut self.nodes[rx as usize];
            if node.seen.contains(&key) {
                if node.pending.remove(&key).is_some() {
                    node.stats.dup_suppressed += 1;
                }
                return;
            }
            node.seen.insert(key);
        }
        let k0 = flight.okind;
        let node_mqtt = self.nodes[rx as usize].mqtt;
        if self.now > flight.expires_at || !self.pkt_meta.contains_key(&flight.id) {
            return;
        }
        let arrived = match flight.dest {
            Dest::Mqtt => node_mqtt,
            Dest::Node(d) => rx == d,
        };
        if k0 == Kind::Ack && matches!(flight.dest, Dest::Node(d) if d == rx) {
            self.sos_acked.insert(flight.ack_for);
        }
        if arrived {
            let mut first_delivery = false;
            if let Some(m) = self.pkt_meta.get_mut(&flight.id) {
                if !m.delivered {
                    m.delivered = true;
                    m.latency = self.now - m.t0;
                    first_delivery = true;
                }
            }
            if first_delivery && k0 == Kind::Sos {
                if let Some(inc) = self.sos_incidents.get_mut(&flight.sos_id) {
                    if !inc.2 {
                        inc.2 = true;
                        inc.3 = self.now - inc.0;
                    }
                }
            }
            if first_delivery && self.p.sos_retry && k0 == Kind::Sos && node_mqtt {
                let mut ack = self.new_flight2(rx, Kind::Ack, 16, Dest::Node(flight.origin), true);
                ack.hop_limit = 6;
                ack.ack_for = flight.sos_id;
                self.csma2(rx, ack);
            }
        }
        if self.p.mode == Mode::Flood || flight.flood {
            let is_radio = self.nodes[rx as usize].is_radio;
            if flight.hop_limit > 0 && !is_radio {
                let mut fwd = flight.clone();
                fwd.hop_limit -= 1;
                fwd.is_fwd = true;
                let slots = if k0 == Kind::Sos {
                    1.2
                } else {
                    2.0 + 6.0 * ((snr + 20.0) / 30.0).clamp(0.0, 1.0)
                };
                let delay =
                    self.event_uniform(RNG_MAC_REBROADCAST, rx as u64, 1.0, slots.max(1.0001))
                        * SLOT_S
                        * 8.0;
                let reg = self.sched(
                    delay,
                    Ev::RebroadcastFire {
                        node: rx,
                        key,
                        flight: fwd,
                    },
                );
                self.nodes[rx as usize].pending.insert(key, reg);
            }
        } else if let Some(route) = &flight.route {
            if let Some(pos) = route.iter().position(|&n| n == rx) {
                if pos + 1 < route.len() && flight.hop_limit > 0 {
                    let mut fwd = flight.clone();
                    fwd.hop_limit -= 1;
                    fwd.is_fwd = true;
                    self.csma2(rx, fwd);
                }
            }
        }
    }

    fn settle_node_energy_segments(&mut self, node: u32) {
        let i = node as usize;
        let segments = std::mem::take(&mut self.nodes[i].energy_segments);
        if self.nodes[i].grid {
            return;
        }
        let battery_v = self.cfg.energy.battery_v;
        let listen_ma = if self.nodes[i].is_radio {
            if self.p.hiker_rx_ma > 0.0 {
                self.p.hiker_rx_ma
            } else {
                self.cfg.energy.rx_listen_ma
            }
        } else if self.p.relay_rx_ma > 0.0 {
            self.p.relay_rx_ma
        } else {
            self.cfg.energy.rx_listen_ma
        };
        let sleep_w = self.cfg.energy.light_sleep_ma / 1000.0 * battery_v;
        let gps_w = self.cfg.energy.gps_active_ma / 1000.0 * battery_v;

        for segment in segments {
            match segment {
                EnergySegment::Docked { seconds, kiosk } => {
                    let headroom_wh = (self.nodes[i].cap_wh - self.nodes[i].soc_wh).max(0.0);
                    let want_wh =
                        (self.cfg.kiosk.charge_w_per_bay * seconds / 3600.0).min(headroom_wh);
                    let got_wh = if let Some(k) = kiosk {
                        if let Some(bank) = self.kiosk_banks.get_mut(&k) {
                            let got = want_wh.min(bank.soc_wh.max(0.0));
                            bank.soc_wh -= got;
                            got
                        } else {
                            want_wh
                        } // grid-site kiosk fallback
                    } else {
                        want_wh
                    };
                    let n = &mut self.nodes[i];
                    n.soc_wh = (n.soc_wh + got_wh).min(n.cap_wh);
                    if !n.energy_alive && n.soc_wh >= REVIVE_FRACTION * n.cap_wh {
                        n.energy_alive = true;
                    }
                }
                EnergySegment::Active {
                    listen_s,
                    sleep_s,
                    gps_s,
                } => {
                    let drain = (listen_s * listen_ma / 1000.0 * battery_v
                        + sleep_s * sleep_w
                        + gps_s * gps_w)
                        / 3600.0;
                    let n = &mut self.nodes[i];
                    n.soc_wh = (n.soc_wh - drain).max(0.0);
                    if n.energy_alive && n.soc_wh <= 0.0 {
                        n.energy_alive = false;
                        n.stats.deaths += 1;
                        n.death_score = 0.7 * n.death_score + 1.0;
                    }
                }
            }
        }
        let n = &mut self.nodes[i];
        if n.soc_wh <= 0.0 {
            n.soc_wh = 0.0;
            if n.energy_alive {
                n.energy_alive = false;
                n.stats.deaths += 1;
                n.death_score = 0.7 * n.death_score + 1.0;
            }
        }
        self.refresh_node_availability(node);
    }

    fn handle_energy(&mut self) {
        let step = (self.now - self.energy_last_t).max(0.0);
        if step <= 0.0 {
            return;
        }
        self.energy_last_t = self.now;
        for i in 0..self.nodes.len() {
            self.accrue_node_energy_state(i as u32);
        }
        let day = self.day2();
        let (kt, snow) = self.kt_snow2(day);
        let calendar_index = day.min(self.weather_calendar.len().saturating_sub(1));
        let doy = self.weather_calendar[calendar_index].0;
        let sec_of_day = self.now % 86400.0;
        // kiosk solar arrays: flat-mount panel using the site's horizon mask
        let mut kiosk_sites: Vec<u32> = self.kiosk_banks.keys().copied().collect();
        kiosk_sites.sort_unstable();
        for ks in kiosk_sites {
            let (lat, lon, hz) = {
                let n = &self.nodes[ks as usize];
                (n.lat, n.lon, n.horizon.clone())
            };
            let flat = crate::solar::SiteSolar {
                pyramid: false,
                tilt_deg: 0.0,
                canopy_tau: 1.0,
            };
            let gain =
                snow * solar_power_w(
                    lat,
                    lon,
                    doy,
                    sec_of_day,
                    kt,
                    &hz,
                    &flat,
                    self.cfg.kiosk.panel_w,
                    self.cfg.solar.system_efficiency,
                ) * step
                    / 3600.0;
            if let Some(bank) = self.kiosk_banks.get_mut(&ks) {
                bank.soc_wh = (bank.soc_wh + gain).min(bank.cap_wh);
            }
        }
        for i in 0..self.nodes.len() {
            let (is_grid, is_solar, lat, lon) = {
                let n = &self.nodes[i];
                (n.grid, n.solar, n.lat, n.lon)
            };
            if is_grid {
                continue;
            }
            if is_solar {
                let gain = {
                    let n = &self.nodes[i];
                    n.site_solar.as_ref().map_or(0.0, |ss| {
                        snow * solar_power_w(
                            lat,
                            lon,
                            doy,
                            sec_of_day,
                            kt,
                            &n.horizon,
                            ss,
                            self.cfg.solar.panel_w_nominal,
                            self.cfg.solar.system_efficiency,
                        )
                    }) * step
                        / 3600.0
                };
                let n = &mut self.nodes[i];
                n.soc_wh = (n.soc_wh + gain).min(n.cap_wh);
                n.stats.solar_wh += gain;
            }
            if !self.nodes[i].energy_alive
                && self.nodes[i].soc_wh >= REVIVE_FRACTION * self.nodes[i].cap_wh
            {
                self.nodes[i].energy_alive = true;
            }
            self.settle_node_energy_segments(i as u32);
        }
    }

    fn handle_dispatch(&mut self, walker: u32) {
        let w = &self.walkers[walker as usize];
        let (kiosk, route) = (w.kiosk, w.route);
        self.rental.walker_days += 1;
        let stock: Vec<u32> = (self.n_fixed..self.nodes.len())
            .map(|i| i as u32)
            .filter(|&i| {
                let n = &self.nodes[i as usize];
                n.docked && n.kiosk == Some(kiosk)
            })
            .collect();
        let pool: Vec<u32> = stock
            .iter()
            .copied()
            .filter(|&i| {
                let n = &self.nodes[i as usize];
                n.alive && n.cap_wh > 0.0 && n.soc_wh / n.cap_wh >= self.cfg.kiosk.min_checkout_soc
            })
            .collect();
        if pool.is_empty() {
            self.rental.starved += 1;
            if stock.is_empty() {
                self.rental.starved_no_stock += 1;
            } else {
                self.rental.starved_unserviceable += 1;
                self.rental.unusable_at_checkout += stock.len() as u64;
            }
            self.sched(86400.0, Ev::Dispatch { walker });
            return;
        }
        let best = *pool
            .iter()
            .max_by(|&&a, &&b| {
                self.nodes[a as usize]
                    .soc_wh
                    .total_cmp(&self.nodes[b as usize].soc_wh)
            })
            .unwrap();
        self.rental.served += 1;
        self.rental.checkout_soc_sum +=
            self.nodes[best as usize].soc_wh / self.nodes[best as usize].cap_wh;
        {
            let ch = self.nodes[kiosk as usize].channel;
            let dispatch_t = self.now;
            self.set_docked(best, false);
            let n = &mut self.nodes[best as usize];
            n.route = Some(route);
            n.start_s = dispatch_t;
            n.channel = ch;
        }
        self.walkers[walker as usize].radio = Some(best);
        let dur = self.routes[route as usize].duration_s;
        self.sched(dur, Ev::WalkEnd { walker });
        self.sched(86400.0, Ev::Dispatch { walker });
    }

    fn handle_shuttle(&mut self) {
        let mut demand: HashMap<u32, i64> = HashMap::new();
        for w in &self.walkers {
            *demand.entry(w.kiosk).or_insert(0) += 1;
        }
        let mut docked: HashMap<u32, Vec<u32>> = HashMap::new();
        for i in self.n_fixed..self.nodes.len() {
            let n = &self.nodes[i];
            if n.docked {
                if let Some(k) = n.kiosk {
                    docked.entry(k).or_default().push(i as u32);
                }
            }
        }
        let mut kiosks: Vec<u32> = demand.keys().copied().collect();
        kiosks.sort();
        for kiosk in kiosks {
            let need = demand[&kiosk];
            loop {
                let have = docked.get(&kiosk).map_or(0, |v| v.len() as i64);
                if have >= need {
                    break;
                }
                // donor: kiosk with the largest surplus
                let donor = docked
                    .iter()
                    .filter(|(k, v)| {
                        **k != kiosk && (v.len() as i64) > *demand.get(k).unwrap_or(&0)
                    })
                    // HashMap iteration order must not decide equal-surplus
                    // shuttle moves. Prefer the lowest stable kiosk index on
                    // ties after maximizing available surplus.
                    .max_by_key(|(k, v)| {
                        (v.len() as i64 - *demand.get(k).unwrap_or(&0), Reverse(**k))
                    })
                    .map(|(k, _)| *k);
                let Some(src) = donor else { break };
                // move the worst-charged surplus radio
                let radio = {
                    let pool = docked.get_mut(&src).unwrap();
                    let (pos, _) = pool
                        .iter()
                        .enumerate()
                        .min_by(|(_, &a), (_, &b)| {
                            self.nodes[a as usize]
                                .soc_wh
                                .total_cmp(&self.nodes[b as usize].soc_wh)
                        })
                        .unwrap();
                    pool.swap_remove(pos)
                };
                // Settle the elapsed dock interval against its source bank
                // before changing the radio's kiosk assignment.
                self.accrue_node_energy_state(radio);
                self.nodes[radio as usize].kiosk = Some(kiosk);
                docked.entry(kiosk).or_default().push(radio);
            }
        }
    }

    pub fn final_prune(&mut self) {
        let ids: Vec<u64> = self.pkt_meta.keys().copied().collect();
        for id in ids {
            let m = self.pkt_meta.remove(&id).unwrap();
            self.settle_packet(id, m);
        }
    }

    fn settle_packet(&mut self, id: u64, m: PktMeta) {
        self.agg
            .entry(m.origin)
            .or_default()
            .record(self.p.seed, id, m.delivered, m.latency);
    }

    // thin aliases so sim.rs fields stay private-ish to this module pair
    fn day2(&self) -> usize {
        (self.now / 86400.0) as usize
    }
    fn kt_snow2(&self, day: usize) -> (f64, f64) {
        let i = day.min(self.weather.len().saturating_sub(1));
        self.weather[i]
    }
    fn channel_busy_at2(&self, node: u32) -> bool {
        for tx in self.active.values() {
            if tx.start <= self.now
                && self.now < tx.end
                && tx
                    .rssi_at
                    .iter()
                    .any(|(n, r, _)| *n == node && *r >= CARRIER_SENSE_DBM)
            {
                return true;
            }
        }
        false
    }
    fn receiver_acquires_preamble_at(&self, rx: u32, tx_start: f64, tx_end: f64) -> bool {
        if !self.p.mode.is_duty() {
            return true;
        }
        let duty = self.nodes[rx as usize].duty.clamp(0.0, 1.0);
        if duty >= 1.0 {
            return true;
        }
        let symbol_s = (1u64 << self.cfg.radio.sf) as f64 / self.cfg.radio.bw_hz;
        let preamble_end =
            (tx_start + (self.cfg.radio.preamble_syms + 4.25) * symbol_s).min(tx_end);
        let needed = CAD_MIN_SYMBOLS * symbol_s;
        let awake_len = duty * CAD_PERIOD_S;
        if awake_len + f64::EPSILON < needed {
            return false;
        }
        let phase = if matches!(self.p.mode, Mode::DutySync | Mode::SelectiveDuty) {
            0.0
        } else {
            Rng::keyed_f64(self.p.seed, RNG_CAD_PHASE, rx as u64) * CAD_PERIOD_S
        };
        let first = ((tx_start - phase) / CAD_PERIOD_S).floor() as i64 - 1;
        let last = ((preamble_end - phase) / CAD_PERIOD_S).ceil() as i64 + 1;
        (first..=last).any(|k| {
            let wake_start = phase + k as f64 * CAD_PERIOD_S;
            let wake_end = wake_start + awake_len;
            let overlap = preamble_end.min(wake_end) - tx_start.max(wake_start);
            overlap + f64::EPSILON >= needed
        })
    }
    fn refresh_node_availability(&mut self, i: u32) {
        let n = &mut self.nodes[i as usize];
        let should_be_alive = n.energy_alive && !n.forced_outage;
        if should_be_alive == n.alive {
            return;
        }
        n.availability_epoch = n.availability_epoch.wrapping_add(1);
        if should_be_alive {
            if let Some(start) = n.unavailable_since.take() {
                n.stats.unavailable_s += (self.now - start).max(0.0);
            }
        } else if n.unavailable_since.is_none() {
            n.unavailable_since = Some(self.now);
        }
        n.alive = should_be_alive;
        self.route_tree_t = -1e18;
    }
    fn set_docked(&mut self, i: u32, docked: bool) {
        self.accrue_node_energy_state(i);
        let node = &mut self.nodes[i as usize];
        if node.docked != docked {
            node.docked = docked;
            node.availability_epoch = node.availability_epoch.wrapping_add(1);
        }
    }
    fn airtime_s2(&mut self, bytes: u32) -> f64 {
        let r = &self.cfg.radio;
        if let Some(&v) = self.airtime_lut.get(&bytes) {
            return v;
        }
        let v = airtime_ms(bytes, r.sf, r.bw_hz, r.cr, r.preamble_syms) / 1000.0;
        self.airtime_lut.insert(bytes, v);
        v
    }
    fn noise_dbm2(&self) -> f64 {
        -174.0 + 10.0 * self.cfg.radio.bw_hz.log10() + self.cfg.radio.noise_figure_db
    }
    fn shadow_sample2(&mut self, a: u32, b: u32) -> f64 {
        let key = if a < b { (a, b) } else { (b, a) };
        let sh_sigma = self.cfg.shadowing.sigma_db;
        let sh_fast = self.cfg.shadowing.fast_fading_db;
        let sh_tau = self.cfg.shadowing.coherence_s;
        let entity = ((key.0 as u64) << 32) | key.1 as u64;
        let seed = self.p.seed;
        let link_rng = self
            .link_rng
            .entry(key)
            .or_insert_with(|| Rng::stream(seed, RNG_PHY ^ Rng::mix64(entity)));
        let z1 = link_rng.normal();
        let z2 = link_rng.normal();
        let val = match self.shadow.get(&key) {
            None => z1 * sh_sigma,
            Some(&(v0, t0)) => {
                let rho = (-(self.now - t0).max(0.0) / sh_tau).exp();
                rho * v0 + (1.0 - rho * rho).sqrt() * sh_sigma * z1
            }
        };
        self.shadow.insert(key, (val, self.now));
        val + sh_fast * z2
    }
    fn new_flight2(
        &mut self,
        origin: u32,
        kind: Kind,
        bytes: u32,
        dest: Dest,
        flood: bool,
    ) -> Flight {
        self.pkt_seq += 1;
        let id = self.pkt_seq;
        self.pkt_meta.insert(
            id,
            PktMeta {
                origin,
                t0: self.now,
                delivered: false,
                latency: 0.0,
            },
        );
        let mut route = None;
        if self.p.mode.is_routed() && !flood && matches!(dest, Dest::Mqtt) {
            route = self.route_to_mqtt2(origin).map(Arc::new);
        }
        {
            let node = &mut self.nodes[origin as usize];
            node.seen.insert((origin, id));
        }
        if self.nodes[origin as usize].mqtt && matches!(dest, Dest::Mqtt) {
            if let Some(m) = self.pkt_meta.get_mut(&id) {
                m.delivered = true;
            }
        }
        Flight {
            id,
            origin,
            okind: kind,
            bytes,
            hop_limit: self.cfg.radio.hop_limit,
            dest,
            flood,
            route,
            sos_id: 0,
            ack_for: 0,
            is_fwd: false,
            expires_at: self.now + PACKET_TTL_S,
        }
    }
    fn csma2(&mut self, node: u32, flight: Flight) {
        self.sched(
            0.0,
            Ev::TxAttempt {
                node,
                flight,
                tries: 0,
                post_difs: false,
            },
        );
    }
    fn route_to_mqtt2(&mut self, origin: u32) -> Option<Vec<u32>> {
        self.route_to_mqtt_public(origin)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::inputs::{
        BatteryCfg, Config, EnergyCfg, KioskCfg, Link, RadioCfg, Route, RoutesFile, ShadowCfg,
        Site, SolarCfg, Topology, TrafficCfg, WeatherDay, WeatherFile,
    };
    use std::collections::HashMap;

    fn site(mqtt: bool) -> Site {
        Site {
            lat: 44.0,
            lon: -71.0,
            hg_m: 5.0,
            power: "grid".to_string(),
            mqtt_uplink: mqtt,
            elev_m: 500.0,
            horizon_deg: vec![0.0; 48],
        }
    }

    fn test_config() -> Config {
        Config {
            radio: RadioCfg {
                freq_mhz: 915.0,
                sf: 7,
                bw_hz: 125_000.0,
                cr: 1,
                preamble_syms: 8.0,
                tx_eirp_dbm: Some(0.0),
                rx_antenna_gain_dbi: 0.0,
                rx_feed_loss_db: 0.0,
                legacy_link_budget_dbm: None,
                rx_sensitivity_dbm: -130.0,
                noise_figure_db: 6.0,
                snr_demod_threshold_db: -10.0,
                capture_threshold_db: 6.0,
                hop_limit: 3,
            },
            shadowing: ShadowCfg {
                sigma_db: 0.0,
                fast_fading_db: 0.0,
                coherence_s: 30.0,
            },
            energy: EnergyCfg {
                battery_v: 3.7,
                tx_current_ma: 100.0,
                rx_listen_ma: 10.0,
                light_sleep_ma: 1.0,
                gps_active_ma: 1.0,
            },
            battery: BatteryCfg {
                capacity_wh: 10.0,
                usable_fraction: 1.0,
                start_soc: 1.0,
            },
            solar: SolarCfg {
                panel_w_nominal: 1.0,
                system_efficiency: 1.0,
                canopy_tau_16ft: 1.0,
                pyramid_tilt_deg: 30.0,
                monthly_kt_mean: vec![0.4; 12],
            },
            traffic: TrafficCfg {
                telemetry_interval_s: 900.0,
                position_interval_s: 300.0,
                telemetry_payload_b: 40,
                position_payload_b: 40,
                sos_payload_b: 64,
            },
            sim: SimCfg::default(),
            kiosk: KioskCfg {
                capacity: 20,
                panel_w: 100.0,
                battery_wh: 100.0,
                charge_w_per_bay: 10.0,
                min_checkout_soc: 0.20,
                demand_tier_a: 1,
                demand_tier_b: 1,
                demand_tier_c: 1,
            },
        }
    }

    fn test_sim(mode: Mode) -> Sim {
        let mut sites = HashMap::new();
        sites.insert("a".to_string(), site(false));
        sites.insert("b".to_string(), site(false));
        sites.insert("c".to_string(), site(true));
        let mut links = HashMap::new();
        links.insert(
            "a|c".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        );
        links.insert(
            "b|c".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        );
        let topology = Topology { sites, links };
        let routes = RoutesFile {
            routes: HashMap::<String, Route>::new(),
        };
        let weather = WeatherFile {
            start_date: "2026-01-01".to_string(),
            days: vec![WeatherDay {
                date: "2026-01-01".to_string(),
                kt: 0.4,
                snow_factor: 1.0,
            }],
        };
        Sim::new(test_config(), topology, routes, weather, test_params(mode))
    }

    fn test_params(mode: Mode) -> Params {
        Params {
            mode,
            days: 1.0,
            seed: 42,
            renters_per_route: 2,
            kiosk_spares: 0,
            sos_retry: false,
            telemetry_iv: 3600.0,
            beacon_iv: 900.0,
            route_refresh_s: 3600.0,
            energy_step_s: 600.0,
            relay_rx_ma: 0.0,
            hiker_rx_ma: 0.0,
            regional_channels: false,
            outages: Vec::new(),
        }
    }

    fn rental_test_sim(duration_s: f64, days: f64) -> Sim {
        let sites = HashMap::from([("kiosk".to_string(), site(true))]);
        let route = Route {
            kiosk: "kiosk".to_string(),
            return_kiosk: "kiosk".to_string(),
            duration_s,
            t_s: vec![0.0, duration_s],
            lat: vec![44.0, 44.1],
            lon: vec![-71.0, -71.0],
            loss_t_s: vec![0.0, duration_s],
            loss_db_q50: HashMap::from([("kiosk".to_string(), vec![100.0, 120.0])]),
        };
        let mut params = test_params(Mode::MinHop);
        params.days = days;
        Sim::new(
            test_config(),
            Topology {
                sites,
                links: HashMap::new(),
            },
            RoutesFile {
                routes: HashMap::from([("overnight".to_string(), route)]),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            params,
        )
    }

    fn simultaneous_collision(sender_order: [&str; 2]) -> (u64, u64, bool, bool) {
        let mut sim = test_sim(Mode::Flood);
        let receiver = sim.name_to_idx["c"];
        let mut packet_ids = Vec::new();
        for sender_name in sender_order {
            let sender = sim.name_to_idx[sender_name];
            let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
            packet_ids.push(flight.id);
            sim.transmit(sender, flight);
        }
        sim.handle_tx_end(0);
        assert_eq!(
            sim.completed_overlap.len(),
            1,
            "earlier-ending result must remain for its overlap peer"
        );
        sim.handle_tx_end(1);
        assert!(sim.completed_overlap.is_empty());
        (
            sim.nodes[receiver as usize].stats.collisions,
            sim.nodes[receiver as usize].stats.rx_ok,
            sim.pkt_meta[&packet_ids[0]].delivered,
            sim.pkt_meta[&packet_ids[1]].delivered,
        )
    }

    #[test]
    fn simultaneous_equal_power_collision_is_symmetric_under_sender_order() {
        let ab = simultaneous_collision(["a", "b"]);
        let ba = simultaneous_collision(["b", "a"]);
        assert_eq!(ab, (2, 0, false, false));
        assert_eq!(ba, ab);
    }

    #[test]
    fn duty_receiver_requires_deterministic_preamble_cad_overlap() {
        let mut sim = test_sim(Mode::DutySync);
        let sender = sim.name_to_idx["a"];
        let receiver = sim.name_to_idx["c"];
        sim.nodes[receiver as usize].duty = 0.05;

        sim.now = 0.020;
        let in_window = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, in_window);
        assert!(sim.active[&0].cad_acquired.contains(&receiver));
        sim.nodes[receiver as usize].duty = 0.0;
        assert!(
            sim.active[&0].cad_acquired.contains(&receiver),
            "TxStart CAD decision must not change during the frame"
        );

        sim.now = 0.200;
        sim.nodes[receiver as usize].duty = 0.05;
        let outside_window = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, outside_window);
        assert!(!sim.active[&1].cad_acquired.contains(&receiver));
        sim.handle_tx_end(0);
        sim.handle_tx_end(1);
        assert_eq!(sim.nodes[receiver as usize].stats.duty_misses, 1);
    }

    #[test]
    fn one_radio_cannot_start_two_overlapping_transmissions() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let first = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, first);
        let second = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.handle_tx_attempt(sender, second, 0, true);
        assert_eq!(sim.active.len(), 1);
        assert!(sim.heap.iter().any(|Reverse(s)| {
            matches!(
                &s.ev,
                Ev::TxAttempt {
                    node,
                    post_difs: false,
                    ..
                } if *node == sender
            ) && s.t >= sim.nodes[sender as usize].tx_until
        }));
    }

    #[test]
    fn docked_radio_cannot_transmit_a_queued_frame() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.nodes[sender as usize].docked = true;
        sim.handle_tx_attempt(sender, flight, 0, false);
        assert!(sim.active.is_empty());
        assert_eq!(sim.nodes[sender as usize].stats.tx, 0);
    }

    #[test]
    fn duty_mode_is_initialized_before_the_first_event() {
        let mut sites = HashMap::new();
        let mut relay = site(false);
        relay.power = "solar".to_string();
        sites.insert("relay".to_string(), relay);
        sites.insert("gateway".to_string(), site(true));
        let mut links = HashMap::new();
        links.insert(
            "relay|gateway".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        );
        let sim = Sim::new(
            test_config(),
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            test_params(Mode::DutySync),
        );
        let relay = sim.name_to_idx["relay"] as usize;
        assert_eq!(sim.now, 0.0);
        assert_eq!(sim.nodes[relay].duty, 0.05);
        assert_eq!(sim.route_tree_t, 0.0);
    }

    #[test]
    fn energy_aware_cost_is_charged_to_the_gatewayward_relay() {
        let mut sites = HashMap::new();
        sites.insert("gateway".to_string(), site(true));
        for name in ["relay_a", "relay_b", "source"] {
            let mut relay = site(false);
            relay.power = "battery".to_string();
            sites.insert(name.to_string(), relay);
        }
        let mut links = HashMap::new();
        for (key, loss_db_q50) in [
            ("gateway|relay_a", 127.0),
            ("gateway|relay_b", 90.0),
            ("relay_a|source", 90.0),
            ("relay_b|source", 127.0),
        ] {
            links.insert(
                key.to_string(),
                Link {
                    loss_db_q50,
                    loss_db_q90: loss_db_q50,
                },
            );
        }
        let mut cfg = test_config();
        cfg.shadowing.sigma_db = 8.0;
        let mut sim = Sim::new(
            cfg,
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            test_params(Mode::EnergyAware),
        );

        let relay_a = sim.name_to_idx["relay_a"];
        let relay_b = sim.name_to_idx["relay_b"];
        let source = sim.name_to_idx["source"];
        // scarcity = 1 + 3(1-rf)/rf, so these are 2.5 and 3.0.
        sim.nodes[relay_a as usize].soc_wh = sim.nodes[relay_a as usize].cap_wh * (2.0 / 3.0);
        sim.nodes[relay_b as usize].soc_wh = sim.nodes[relay_b as usize].cap_wh * 0.6;
        sim.build_route_tree();

        assert_eq!(
            sim.route_next[source as usize],
            Some(relay_a),
            "the weak inbound link through relay_b must multiply relay_b's scarcity"
        );
    }

    #[test]
    fn energy_accounting_splits_at_checkout_state_transition() {
        let mut sim = rental_test_sim(3600.0, 1.0);
        sim.now = 11.0 * 3600.0;
        sim.handle_dispatch(0);
        let radio = sim.walkers[0].radio.expect("radio checked out");
        sim.now += 300.0;
        sim.handle_energy();

        let cap = sim.nodes[radio as usize].cap_wh;
        let expected_drain_wh = (10.0 + 1.0) / 1000.0 * 3.7 * 300.0 / 3600.0;
        assert!((sim.nodes[radio as usize].soc_wh - (cap - expected_drain_wh)).abs() < 1e-12);
    }

    #[test]
    fn energy_segments_preserve_active_then_docked_chronology() {
        let mut sim = rental_test_sim(3600.0, 1.0);
        sim.now = 11.0 * 3600.0;
        sim.handle_dispatch(0);
        let radio = sim.walkers[0].radio.expect("radio checked out");
        let cap = sim.nodes[radio as usize].cap_wh;

        sim.now += 300.0;
        sim.handle(Ev::WalkEnd { walker: 0 }, 1);
        sim.now += 300.0;
        sim.handle_energy();

        assert!(
            (sim.nodes[radio as usize].soc_wh - cap).abs() < 1e-12,
            "the post-walk dock interval must recharge energy drained during the walk"
        );
    }

    #[test]
    fn docked_energy_segments_remain_charged_to_their_source_kiosk() {
        let mut sim = test_sim(Mode::Flood);
        let radio = sim.name_to_idx["a"];
        let source = sim.name_to_idx["b"];
        let destination = sim.name_to_idx["c"];
        sim.cfg.kiosk.panel_w = 0.0;
        {
            let n = &mut sim.nodes[radio as usize];
            n.grid = false;
            n.docked = true;
            n.kiosk = Some(source);
            n.soc_wh = 0.0;
            n.energy_alive = false;
        }
        for kiosk in [source, destination] {
            sim.kiosk_banks.insert(
                kiosk,
                KioskBank {
                    soc_wh: 50.0,
                    cap_wh: 50.0,
                },
            );
        }

        sim.now = 300.0;
        sim.accrue_node_energy_state(radio);
        sim.nodes[radio as usize].kiosk = Some(destination);
        sim.now = 600.0;
        sim.handle_energy();

        let expected_debit = sim.cfg.kiosk.charge_w_per_bay * 300.0 / 3600.0;
        assert!((sim.kiosk_banks[&source].soc_wh - (50.0 - expected_debit)).abs() < 1e-12);
        assert!((sim.kiosk_banks[&destination].soc_wh - (50.0 - expected_debit)).abs() < 1e-12);
    }

    #[test]
    fn walk_interval_excludes_its_exact_endpoint() {
        let mut sim = rental_test_sim(3600.0, 1.0);
        sim.now = 11.0 * 3600.0;
        sim.handle_dispatch(0);
        let radio = sim.walkers[0].radio.expect("radio checked out");
        sim.now += 3600.0;
        assert!(!sim.walking(radio));
    }

    #[test]
    fn zero_start_soc_is_initially_unavailable() {
        let mut relay = site(false);
        relay.power = "battery".to_string();
        let sites = HashMap::from([
            ("relay".to_string(), relay),
            ("gateway".to_string(), site(true)),
        ]);
        let links = HashMap::from([(
            "relay|gateway".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        )]);
        let mut cfg = test_config();
        cfg.battery.start_soc = 0.0;
        let sim = Sim::new(
            cfg,
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            test_params(Mode::MinHop),
        );
        let relay = &sim.nodes[sim.name_to_idx["relay"] as usize];
        assert!(!relay.energy_alive);
        assert!(!relay.alive);
        assert_eq!(relay.unavailable_since, Some(0.0));
    }

    #[test]
    fn final_partial_energy_step_rebuilds_invalidated_duty_tree() {
        let mut relay = site(false);
        relay.power = "battery".to_string();
        let sites = HashMap::from([
            ("relay".to_string(), relay),
            ("gateway".to_string(), site(true)),
        ]);
        let links = HashMap::from([(
            "relay|gateway".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        )]);
        let mut params = test_params(Mode::DutySync);
        params.days = 60.0 / 86400.0;
        params.energy_step_s = 600.0;
        params.telemetry_iv = 1.0e12;
        let mut sim = Sim::new(
            test_config(),
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.0,
                    snow_factor: 1.0,
                }],
            },
            params,
        );
        let relay = sim.name_to_idx["relay"];
        sim.nodes[relay as usize].soc_wh = 1.0e-9;
        sim.run();

        assert!(!sim.nodes[relay as usize].alive);
        assert_eq!(sim.route_tree_t, sim.now);
        assert_eq!(sim.route_next[relay as usize], None);
    }

    #[test]
    fn event_exactly_at_horizon_does_not_create_zero_duration_rental() {
        let mut sim = rental_test_sim(3600.0, 11.0 / 24.0);
        sim.run();
        assert_eq!(sim.rental.walker_days, 0);
        assert_eq!(sim.rental.served, 0);
    }

    #[test]
    fn route_progress_remains_continuous_across_utc_midnight() {
        let mut sim = rental_test_sim(20.0 * 3600.0, 2.0);
        sim.now = 11.0 * 3600.0;
        sim.handle_dispatch(0);
        let radio = sim.walkers[0].radio.expect("radio checked out");
        sim.now = 25.0 * 3600.0;

        assert_eq!(sim.track_t2(radio), Some(14.0 * 3600.0));
        let kiosk = sim.name_to_idx["kiosk"];
        assert!((sim.loss_db(radio, kiosk) - 114.0).abs() < 1e-12);
    }

    #[test]
    fn route_path_depth_is_bounded_by_topology_not_a_magic_constant() {
        let mut sites = HashMap::new();
        for i in 0..26 {
            sites.insert(format!("n{i:02}"), site(false));
        }
        sites.insert("gateway".to_string(), site(true));
        let mut links = HashMap::new();
        for i in 0..25 {
            links.insert(
                format!("n{i:02}|n{:02}", i + 1),
                Link {
                    loss_db_q50: 100.0,
                    loss_db_q90: 100.0,
                },
            );
        }
        links.insert(
            "n25|gateway".to_string(),
            Link {
                loss_db_q50: 100.0,
                loss_db_q90: 100.0,
            },
        );
        let mut sim = Sim::new(
            test_config(),
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            test_params(Mode::MinHop),
        );
        let source = sim.name_to_idx["n00"];
        let path = sim.route_to_mqtt_public(source).expect("long valid route");
        assert_eq!(path.len(), 27);
        assert_eq!(path.last().copied(), Some(sim.name_to_idx["gateway"]));
    }

    #[test]
    fn selective_duty_keeps_every_route_parent_awake() {
        let mut sites = HashMap::new();
        for name in ["a", "b", "c"] {
            let mut relay = site(false);
            relay.power = "solar".to_string();
            sites.insert(name.to_string(), relay);
        }
        sites.insert("gateway".to_string(), site(true));
        let mut links = HashMap::new();
        for key in ["a|gateway", "b|gateway", "c|a", "c|b"] {
            links.insert(
                key.to_string(),
                Link {
                    loss_db_q50: 100.0,
                    loss_db_q90: 100.0,
                },
            );
        }
        let sim = Sim::new(
            test_config(),
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::new(),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            test_params(Mode::SelectiveDuty),
        );
        for parent in sim.route_next.iter().filter_map(|value| *value) {
            let node = &sim.nodes[parent as usize];
            assert!(
                node.mqtt || node.grid || node.duty == 1.0,
                "route parent {} was allowed to sleep",
                node.name
            );
        }
    }

    #[test]
    fn selective_duty_uses_the_documented_shared_phase() {
        let mut sim = test_sim(Mode::SelectiveDuty);
        let receiver = sim.name_to_idx["c"];
        sim.nodes[receiver as usize].duty = 0.05;
        let air = sim.airtime_s2(40);
        assert!(sim.receiver_acquires_preamble_at(receiver, 0.020, 0.020 + air));
        assert!(!sim.receiver_acquires_preamble_at(receiver, 0.200, 0.200 + air));
    }

    #[test]
    fn duty_tree_rebuilds_in_the_same_availability_event() {
        let mut sim = test_sim(Mode::DutySync);
        let relay = sim.name_to_idx["a"];
        sim.now = 10.0;
        sim.handle(Ev::OutageStart { node: relay }, 1);
        assert!(!sim.nodes[relay as usize].alive);
        assert_eq!(sim.route_tree_t, 10.0);
    }

    #[test]
    fn half_duplex_check_uses_exact_overlap_not_latest_tx_end() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let receiver = sim.name_to_idx["c"];
        let inbound = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, inbound);
        let boundary = sim.active[&0].end;

        sim.now = boundary;
        let outbound = sim.new_flight2(receiver, Kind::Tel, 40, Dest::Node(sender), true);
        sim.transmit(receiver, outbound);
        sim.handle_tx_end(0);
        assert_eq!(
            sim.nodes[receiver as usize].stats.rx_ok, 1,
            "TX beginning exactly at RX end is not an overlap"
        );
    }

    #[test]
    fn airtime_and_tx_energy_are_clipped_at_simulation_horizon() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        sim.nodes[sender as usize].grid = false;
        let air = sim.airtime_s2(40);
        sim.p.days = (air / 2.0) / 86400.0;
        let baseline_ma = sim.cfg.energy.rx_listen_ma;
        let expected_tx_wh = (sim.cfg.energy.tx_current_ma - baseline_ma) / 1000.0
            * sim.cfg.energy.battery_v
            * (air / 2.0)
            / 3600.0;
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);
        assert!((sim.total_offered_airtime_s - air / 2.0).abs() < 1e-12);
        assert!((sim.nodes[sender as usize].stats.tx_airtime_s - air / 2.0).abs() < 1e-12);
        assert!((sim.nodes[sender as usize].stats.energy_tx_wh - expected_tx_wh).abs() < 1e-12);
    }

    #[test]
    fn traffic_draws_are_stable_under_unrelated_node_mac_and_phy_activity() {
        let mut baseline = test_sim(Mode::Flood);
        let mut perturbed = test_sim(Mode::Flood);
        let a = baseline.name_to_idx["a"] as u64;
        let b = baseline.name_to_idx["b"] as u64;

        let expected = baseline.event_uniform(RNG_TRAFFIC_TELEMETRY, a, 0.9, 1.1);
        for _ in 0..1000 {
            perturbed.event_uniform(RNG_MAC_BUSY_BACKOFF, b, 0.0, 1.0);
        }
        // A different node's telemetry generator has its own counter.
        perturbed.event_uniform(RNG_TRAFFIC_TELEMETRY, b, 0.9, 1.1);
        let pa = perturbed.name_to_idx["a"];
        let pb = perturbed.name_to_idx["b"];
        for _ in 0..20 {
            perturbed.shadow_sample2(pa, pb);
        }
        let actual = perturbed.event_uniform(RNG_TRAFFIC_TELEMETRY, a, 0.9, 1.1);
        assert_eq!(actual, expected);

        let next_day_sender = Rng::keyed_f64(baseline.p.seed, RNG_INCIDENT_SENDER, 8);
        // A day with no hikers skips sender selection entirely.  Because the
        // following day is keyed by day rather than stream position, it is
        // unchanged by that skipped draw or any unrelated activity above.
        let after_skipped_day = Rng::keyed_f64(perturbed.p.seed, RNG_INCIDENT_SENDER, 8);
        assert_eq!(after_skipped_day, next_day_sender);
    }

    #[test]
    fn kiosk_charging_debits_only_actual_battery_headroom() {
        let mut sim = test_sim(Mode::Flood);
        let radio = sim.name_to_idx["a"] as usize;
        let kiosk = sim.name_to_idx["c"];
        sim.cfg.kiosk.panel_w = 0.0;
        sim.nodes[radio].grid = false;
        sim.nodes[radio].docked = true;
        sim.nodes[radio].kiosk = Some(kiosk);
        sim.kiosk_banks.insert(
            kiosk,
            KioskBank {
                soc_wh: 50.0,
                cap_wh: 100.0,
            },
        );

        sim.now = 600.0;
        sim.handle_energy();
        assert_eq!(
            sim.kiosk_banks[&kiosk].soc_wh, 50.0,
            "a full radio must not drain the kiosk bank"
        );

        sim.nodes[radio].soc_wh = sim.nodes[radio].cap_wh - 1.0;
        sim.now = 1200.0;
        sim.handle_energy();
        assert!((sim.nodes[radio].soc_wh - sim.nodes[radio].cap_wh).abs() < 1e-12);
        assert!(
            (sim.kiosk_banks[&kiosk].soc_wh - 49.0).abs() < 1e-12,
            "bank debit must equal energy actually accepted"
        );
    }

    #[test]
    fn pending_baseline_energy_is_settled_before_transmission() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        {
            let n = &mut sim.nodes[sender as usize];
            n.grid = false;
            n.solar = false;
            n.duty = 1.0;
            n.soc_wh = 0.001;
        }
        sim.now = 600.0;
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);

        assert!(sim.active.is_empty());
        assert_eq!(sim.nodes[sender as usize].stats.tx, 0);
        assert!(!sim.nodes[sender as usize].alive);
        assert_eq!(sim.nodes[sender as usize].stats.deaths, 1);
    }

    #[test]
    fn insufficient_tx_energy_does_not_create_a_phantom_frame() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        sim.nodes[sender as usize].grid = false;
        sim.nodes[sender as usize].soc_wh = 1.0e-6;
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);

        assert!(sim.active.is_empty());
        assert_eq!(sim.nodes[sender as usize].stats.tx, 0);
        assert_eq!(sim.nodes[sender as usize].stats.tx_airtime_s, 0.0);
        assert_eq!(sim.nodes[sender as usize].stats.energy_tx_wh, 0.0);
        assert!(!sim.nodes[sender as usize].alive);
    }

    #[test]
    fn energy_integration_uses_the_actual_elapsed_step() {
        let mut sim = test_sim(Mode::Flood);
        let node = sim.name_to_idx["a"] as usize;
        sim.nodes[node].grid = false;
        sim.nodes[node].solar = false;
        sim.nodes[node].duty = 1.0;
        let start = sim.nodes[node].soc_wh;
        sim.now = 300.0;
        sim.handle_energy();
        let expected =
            sim.cfg.energy.rx_listen_ma / 1000.0 * sim.cfg.energy.battery_v * 300.0 / 3600.0;
        assert!((sim.nodes[node].soc_wh - (start - expected)).abs() < 1e-12);
        assert_eq!(sim.energy_last_t, 300.0);
    }

    #[test]
    fn availability_integrates_unavailable_duration_not_death_event_count() {
        let mut sim = test_sim(Mode::Flood);
        let node = sim.name_to_idx["a"];
        sim.now = 10.0;
        sim.nodes[node as usize].energy_alive = false;
        sim.nodes[node as usize].stats.deaths = 1;
        sim.refresh_node_availability(node);
        sim.now = 40.0;
        sim.nodes[node as usize].energy_alive = true;
        sim.refresh_node_availability(node);
        assert_eq!(sim.nodes[node as usize].stats.deaths, 1);
        assert_eq!(sim.nodes[node as usize].unavailable_s_through(100.0), 30.0);
        assert!((sim.nodes[node as usize].availability_through(100.0) - 0.70).abs() < 1e-12);
    }

    #[test]
    fn availability_interruption_invalidates_an_in_flight_reception() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let receiver = sim.name_to_idx["c"];
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);
        let end = sim.active[&0].end;

        sim.now = end / 3.0;
        sim.nodes[receiver as usize].forced_outage = true;
        sim.refresh_node_availability(receiver);
        sim.now = 2.0 * end / 3.0;
        sim.nodes[receiver as usize].forced_outage = false;
        sim.refresh_node_availability(receiver);
        sim.now = end;
        sim.handle_tx_end(0);

        assert!(sim.nodes[receiver as usize].alive);
        assert_eq!(sim.nodes[receiver as usize].stats.rx_ok, 0);
    }

    #[test]
    fn dock_and_recheckout_during_a_frame_invalidates_reception() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let receiver = sim.name_to_idx["c"];
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);
        let end = sim.active[&0].end;
        sim.now = end / 3.0;
        sim.set_docked(receiver, true);
        sim.now = 2.0 * end / 3.0;
        sim.set_docked(receiver, false);
        sim.now = end;
        sim.handle_tx_end(0);
        assert_eq!(sim.nodes[receiver as usize].stats.rx_ok, 0);
    }

    #[test]
    fn transmit_energy_uses_the_actual_duty_baseline() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        sim.nodes[sender as usize].grid = false;
        sim.nodes[sender as usize].duty = 0.05;
        sim.p.relay_rx_ma = 100.0;
        let air = sim.airtime_s2(40);
        let baseline_ma = 0.05 * 100.0 + 0.95 * sim.cfg.energy.light_sleep_ma;
        let expected =
            (sim.cfg.energy.tx_current_ma - baseline_ma) / 1000.0 * sim.cfg.energy.battery_v * air
                / 3600.0;

        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.transmit(sender, flight);
        assert!((sim.nodes[sender as usize].stats.energy_tx_wh - expected).abs() < 1e-12);
    }

    #[test]
    fn forwarding_load_decays_when_other_relays_carry_traffic() {
        let mut sim = test_sim(Mode::LbEnergy);
        let avoided = sim.name_to_idx["a"];
        let active = sim.name_to_idx["b"];
        sim.record_forward(avoided);
        for _ in 0..200 {
            sim.record_forward(active);
        }
        assert_eq!(sim.nodes[avoided as usize].fwd_ewma, 1.0);
        sim.decay_forward_loads();
        assert!(sim.nodes[avoided as usize].fwd_ewma < 0.37);
        assert!(sim.nodes[active as usize].fwd_ewma > sim.nodes[avoided as usize].fwd_ewma);
    }

    #[test]
    fn settled_packet_cannot_transmit_late() {
        let mut sim = test_sim(Mode::Flood);
        let sender = sim.name_to_idx["a"];
        let flight = sim.new_flight2(sender, Kind::Tel, 40, Dest::Mqtt, false);
        sim.pkt_meta.remove(&flight.id);
        sim.handle_tx_attempt(sender, flight, 0, false);
        assert!(sim.active.is_empty());
        assert_eq!(sim.nodes[sender as usize].stats.tx, 0);
    }

    #[test]
    fn regional_channel_mobile_attachment_stays_in_its_component() {
        let mut sites = HashMap::new();
        sites.insert("a".to_string(), site(false));
        sites.insert("b".to_string(), site(false));
        sites.insert("g0".to_string(), site(true));
        sites.insert("g1".to_string(), site(true));
        let mut links = HashMap::new();
        for key in ["a|g0", "b|g1"] {
            links.insert(
                key.to_string(),
                Link {
                    loss_db_q50: 100.0,
                    loss_db_q90: 100.0,
                },
            );
        }
        let route = Route {
            kiosk: "a".to_string(),
            return_kiosk: "a".to_string(),
            duration_s: 3600.0,
            t_s: vec![0.0, 3600.0],
            lat: vec![44.0, 44.0],
            lon: vec![-71.0, -71.0],
            loss_t_s: vec![0.0, 3600.0],
            loss_db_q50: HashMap::from([
                ("a".to_string(), vec![120.0, 120.0]),
                ("b".to_string(), vec![90.0, 90.0]),
            ]),
        };
        let mut params = test_params(Mode::Etx);
        params.regional_channels = true;
        let mut sim = Sim::new(
            test_config(),
            Topology { sites, links },
            RoutesFile {
                routes: HashMap::from([("route".to_string(), route)]),
            },
            WeatherFile {
                start_date: "2026-01-01".to_string(),
                days: vec![WeatherDay {
                    date: "2026-01-01".to_string(),
                    kt: 0.4,
                    snow_factor: 1.0,
                }],
            },
            params,
        );
        let radio = sim.n_fixed as u32;
        let a = sim.name_to_idx["a"];
        sim.nodes[radio as usize].docked = false;
        sim.nodes[radio as usize].route = Some(0);
        sim.nodes[radio as usize].channel = sim.nodes[a as usize].channel;
        let path = sim
            .route_to_mqtt_public(radio)
            .expect("same-channel route to gateway");
        assert_eq!(path[1], a);
        assert!(path
            .iter()
            .all(|&node| sim.nodes[node as usize].channel == sim.nodes[radio as usize].channel));
    }

    #[test]
    fn sos_initial_burst_reuses_id_at_absolute_offsets_and_retry_is_fresh() {
        let mut sim = rental_test_sim(3600.0, 1.0);
        sim.p.sos_retry = true;
        let radio = sim.n_fixed as u32;
        sim.set_docked(radio, false);
        sim.nodes[radio as usize].route = Some(0);
        sim.nodes[radio as usize].start_s = 0.0;

        sim.handle_sos(u32::MAX, 0, 0);
        let (&sos_id, incident) = sim.sos_incidents.iter().next().unwrap();
        assert_eq!(incident.1, 1);
        let mut burst = Vec::new();
        let mut initial_tx_id = None;
        let mut retry_t = None;
        for Reverse(s) in &sim.heap {
            match &s.ev {
                Ev::SosBurst { node, flight } if *node == radio => {
                    burst.push((s.t, flight.id, flight.sos_id));
                }
                Ev::TxAttempt { node, flight, .. }
                    if *node == radio && flight.okind == Kind::Sos =>
                {
                    initial_tx_id = Some(flight.id);
                }
                Ev::SosSend {
                    node,
                    sos_id: sid,
                    stage: 1,
                } if *node == radio && *sid == sos_id => {
                    retry_t = Some(s.t);
                }
                _ => {}
            }
        }
        burst.sort_by(|a, b| a.0.total_cmp(&b.0));
        assert_eq!(burst, vec![(30.0, sos_id, sos_id), (60.0, sos_id, sos_id)]);
        assert_eq!(initial_tx_id, Some(sos_id));
        assert_eq!(retry_t, Some(300.0));

        sim.now = 300.0;
        sim.handle_sos(radio, sos_id, 1);
        let retry_packet_ids: Vec<u64> = sim
            .heap
            .iter()
            .filter_map(|Reverse(s)| match &s.ev {
                Ev::TxAttempt { node, flight, .. }
                    if *node == radio
                        && flight.okind == Kind::Sos
                        && flight.sos_id == sos_id
                        && flight.id != sos_id =>
                {
                    Some(flight.id)
                }
                _ => None,
            })
            .collect();
        assert_eq!(retry_packet_ids.len(), 1);
        assert_eq!(sim.sos_incidents[&sos_id].1, 2);
    }

    #[test]
    fn sos_retry_stops_when_the_walk_interval_has_ended() {
        let mut sim = rental_test_sim(3600.0, 1.0);
        let radio = sim.n_fixed as u32;
        sim.set_docked(radio, false);
        sim.nodes[radio as usize].route = Some(0);
        sim.nodes[radio as usize].start_s = 0.0;
        sim.now = 3600.0;
        sim.sos_incidents.insert(99, (0.0, 1, false, 0.0));
        let queued_before = sim.heap.len();

        sim.handle_sos(radio, 99, 1);

        assert_eq!(sim.sos_incidents[&99].1, 1);
        assert_eq!(sim.heap.len(), queued_before);
    }
}

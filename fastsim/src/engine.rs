//! Sim construction + event handlers + run loop + summary.

use crate::inputs::*;
use crate::sim::*;
use crate::solar::{solar_power_w, SiteSolar};
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, HashSet};

const DEAD_DB: f64 = 300.0;

impl Sim {
    pub fn new(
        cfg: Config,
        topo: Topology,
        routes_file: RoutesFile,
        weather: WeatherFile,
        p: Params,
    ) -> Sim {
        let mut nodes: Vec<Node> = Vec::new();
        let mut name_to_idx = HashMap::new();

        // fixed sites (stable order for reproducibility)
        let mut site_names: Vec<&String> = topo.sites.keys().collect();
        site_names.sort();
        for name in &site_names {
            let s = &topo.sites[*name];
            let idx = nodes.len() as u32;
            name_to_idx.insert((*name).clone(), idx);
            let solar = s.power == "solar";
            let cap_wh = cfg.battery.capacity_wh * cfg.battery.usable_fraction;
            let soc_wh = cap_wh * cfg.battery.start_soc;
            let energy_alive = s.power == "grid" || soc_wh > 0.0;
            nodes.push(Node {
                name: (*name).clone(),
                lat: s.lat,
                lon: s.lon,
                grid: s.power == "grid",
                solar,
                mqtt: s.mqtt_uplink,
                horizon: s.horizon_deg.clone(),
                site_solar: if solar {
                    Some(SiteSolar {
                        pyramid: true,
                        tilt_deg: cfg.solar.pyramid_tilt_deg,
                        canopy_tau: if s.elev_m < TREELINE_M {
                            cfg.solar.canopy_tau_16ft
                        } else {
                            1.0
                        },
                    })
                } else {
                    None
                },
                cap_wh,
                soc_wh,
                energy_alive,
                forced_outage: false,
                alive: energy_alive,
                availability_epoch: 0,
                unavailable_since: (!energy_alive).then_some(0.0),
                docked: false,
                checkout_generation: 0,
                duty: 1.0,
                is_radio: false,
                channel: 0,
                kiosk: None,
                route: None,
                start_s: 0.0,
                tx_until: -1.0,
                energy_state_t: 0.0,
                energy_segments: Vec::new(),
                fwd_ewma: 0.0,
                fwd_ewma_seq: 0,
                death_score: 0.0,
                seen: HashSet::new(),
                pending: HashMap::new(),
                stats: NodeStats::default(),
            });
        }
        let n_fixed = nodes.len();

        // fixed link matrix + adjacency
        let mut fixed_loss = HashMap::new();
        let mut fixed_adj = vec![Vec::new(); n_fixed];
        let sens = cfg.radio.rx_sensitivity_dbm;
        let received_power_reference = cfg.radio.received_power_reference_dbm();
        for (key, l) in &topo.links {
            let mut it = key.split('|');
            let (Some(a), Some(b)) = (it.next(), it.next()) else {
                continue;
            };
            let (Some(&ia), Some(&ib)) = (name_to_idx.get(a), name_to_idx.get(b)) else {
                continue;
            };
            fixed_loss.insert((ia, ib), l.loss_db_q50);
            fixed_loss.insert((ib, ia), l.loss_db_q50);
            let margin = received_power_reference - l.loss_db_q50 - sens;
            if margin >= 3.0 {
                fixed_adj[ia as usize].push((ib, margin));
                fixed_adj[ib as usize].push((ia, margin));
            }
        }
        // `Topology::links` is deserialized into a HashMap whose iteration
        // order is intentionally randomized for each process.  Dijkstra uses
        // insertion sequence as its final tie-break, so leaving adjacency in
        // that order made equal-cost routes (especially min_hop) change across
        // otherwise identical same-seed runs.  Canonicalize every neighbor
        // list before it can affect components or routing.
        for neighbors in &mut fixed_adj {
            neighbors.sort_by(|(left_node, left_margin), (right_node, right_margin)| {
                left_node
                    .cmp(right_node)
                    .then_with(|| left_margin.total_cmp(right_margin))
            });
        }

        // regional channels: connected components of the usable-link graph
        // (each gateway region = one frequency; MQTT backhaul bridges them)
        let mut comp = vec![u32::MAX; n_fixed];
        let mut next_comp = 0u32;
        for start in 0..n_fixed {
            if comp[start] != u32::MAX {
                continue;
            }
            let mut stack = vec![start];
            comp[start] = next_comp;
            while let Some(u) = stack.pop() {
                for &(v, _) in &fixed_adj[u] {
                    if comp[v as usize] == u32::MAX {
                        comp[v as usize] = next_comp;
                        stack.push(v as usize);
                    }
                }
            }
            next_comp += 1;
        }
        if p.regional_channels {
            for i in 0..n_fixed {
                nodes[i].channel = (comp[i] % 250) as u8;
            }
        }

        // routes (stable order) + per-route/site loss tables
        let mut route_names: Vec<&String> = routes_file.routes.keys().collect();
        route_names.sort();
        let routes: Vec<Route> = route_names
            .iter()
            .map(|n| routes_file.routes[*n].clone())
            .collect();
        let mut route_site_loss = Vec::with_capacity(routes.len());
        for r in &routes {
            let mut per_site = vec![vec![DEAD_DB; r.loss_t_s.len()]; n_fixed];
            for (sname, losses) in &r.loss_db_q50 {
                if let Some(&si) = name_to_idx.get(sname) {
                    per_site[si as usize] = losses.clone();
                }
            }
            route_site_loss.push(per_site);
        }

        // walkers from route-popularity demand tiers (AMC usage data);
        // renters_per_route acts as a global scale factor (2 = 100% tiers)
        const TIER_A: [&str; 4] = [
            "franconia_ridge_loop",
            "tuckerman_loop",
            "monadnock_white_dot",
            "ammo_jewell_loop",
        ];
        const TIER_B: [&str; 8] = [
            "lonesome_lake_family",
            "carter_wildcat",
            "crawford_traverse",
            "valley_way_madison",
            "pack_monadnock_loop",
            "kearsarge_winslow",
            "cardigan_west_ridge",
            "chocorua_piper",
        ];
        let mut route_names_sorted: Vec<&String> = routes_file.routes.keys().collect();
        route_names_sorted.sort();
        let scale = p.renters_per_route as f64 / 2.0;
        let mut walkers = Vec::new();
        let mut kiosk_load: HashMap<u32, u32> = HashMap::new();
        for (ri, r) in routes.iter().enumerate() {
            let rname = route_names_sorted[ri].as_str();
            let tier = if TIER_A.contains(&rname) {
                cfg.kiosk.demand_tier_a
            } else if TIER_B.contains(&rname) {
                cfg.kiosk.demand_tier_b
            } else {
                cfg.kiosk.demand_tier_c
            };
            let n_walk = ((tier as f64 * scale).round() as u32).max(1);
            let Some(&kiosk) = name_to_idx.get(&r.kiosk) else {
                continue;
            };
            let ret = *name_to_idx.get(&r.return_kiosk).unwrap_or(&kiosk);
            for k in 0..n_walk {
                // checkouts spread 07:00–13:00 ET (11:00–17:00 UTC)
                let frac = k as f64 / n_walk.max(1) as f64;
                walkers.push(Walker {
                    route: ri as u32,
                    start_s: (11.0 + 6.0 * frac) * 3600.0,
                    kiosk,
                    return_kiosk: ret,
                    radio: None,
                });
                *kiosk_load.entry(kiosk).or_insert(0) += 1;
            }
        }
        let mut kiosk_ids: Vec<u32> = kiosk_load.keys().copied().collect();
        kiosk_ids.sort();
        let mut kiosk_banks = std::collections::HashMap::new();
        for kiosk in kiosk_ids {
            kiosk_banks.insert(
                kiosk,
                KioskBank {
                    soc_wh: cfg.kiosk.battery_wh,
                    cap_wh: cfg.kiosk.battery_wh,
                },
            );
            let n_radios = kiosk_load[&kiosk]
                .saturating_add(p.kiosk_spares)
                .min(cfg.kiosk.capacity);
            for i in 0..n_radios {
                let base = &nodes[kiosk as usize];
                let (lat, lon) = (base.lat, base.lon);
                let name = format!("radio_{}_{}", base.name, i);
                let idx = nodes.len() as u32;
                name_to_idx.insert(name.clone(), idx);
                let cap_wh = cfg.battery.capacity_wh * cfg.battery.usable_fraction;
                let soc_wh = cap_wh * cfg.battery.start_soc;
                let energy_alive = soc_wh > 0.0;
                nodes.push(Node {
                    name,
                    lat,
                    lon,
                    grid: false,
                    solar: false,
                    mqtt: false,
                    horizon: Vec::new(),
                    site_solar: None,
                    cap_wh,
                    soc_wh,
                    energy_alive,
                    forced_outage: false,
                    alive: energy_alive,
                    availability_epoch: 0,
                    unavailable_since: (!energy_alive).then_some(0.0),
                    docked: true,
                    checkout_generation: 0,
                    duty: 1.0,
                    is_radio: true,
                    channel: 0,
                    kiosk: Some(kiosk),
                    route: None,
                    start_s: 0.0,
                    tx_until: -1.0,
                    energy_state_t: 0.0,
                    energy_segments: Vec::new(),
                    fwd_ewma: 0.0,
                    fwd_ewma_seq: 0,
                    death_score: 0.0,
                    seen: HashSet::new(),
                    pending: HashMap::new(),
                    stats: NodeStats::default(),
                });
            }
        }

        let start_date = weather.start_date.clone();
        let weather_v: Vec<(f64, f64)> =
            weather.days.iter().map(|d| (d.kt, d.snow_factor)).collect();
        let weather_calendar: Vec<(u32, usize)> = weather
            .days
            .iter()
            .map(|d| (doy_from_date(&d.date), month_index_from_date(&d.date)))
            .collect();

        let n_nodes = nodes.len();
        let mut sim = Sim {
            cfg,
            p,
            draw_counters: HashMap::new(),
            link_rng: HashMap::new(),
            now: 0.0,
            energy_last_t: 0.0,
            seq: 0,
            heap: BinaryHeap::new(),
            nodes,
            n_fixed,
            name_to_idx,
            fixed_loss,
            fixed_adj,
            routes,
            route_site_loss,
            walkers,
            weather: weather_v,
            weather_calendar,
            start_date,
            active: HashMap::new(),
            completed_overlap: HashMap::new(),
            next_tx_idx: 0,
            pkt_seq: 0,
            pkt_meta: HashMap::new(),
            agg: HashMap::new(),
            sos_incidents: HashMap::new(),
            sos_acked: HashSet::new(),
            route_next: vec![None; n_nodes],
            route_cost: vec![f64::INFINITY; n_nodes],
            route_tree_t: -1e18,
            fwd_median: 0.0,
            forward_event_seq: 0,
            shadow: HashMap::new(),
            link_health: HashMap::new(),
            kiosk_banks,
            rental: RentalStats {
                walker_days: 0,
                served: 0,
                starved: 0,
                starved_no_stock: 0,
                starved_unserviceable: 0,
                unusable_at_checkout: 0,
                checkout_soc_sum: 0.0,
            },
            total_offered_airtime_s: 0.0,
            local_busy: vec![BusyUnion::default(); n_nodes],
            soc_series: Vec::new(),
            solar_profile: HashMap::new(),
            airtime_lut: HashMap::new(),
        };
        // Duty state is part of the initial condition, not a side effect of
        // whichever routed packet happens to arrive first. Without this, the
        // first energy interval and any early flooded traffic used a perfect
        // 100% wake state.
        if sim.p.mode.is_duty() {
            sim.build_route_tree();
        }
        sim.bootstrap();
        sim
    }

    fn push(&mut self, t: f64, ev: Ev) -> u64 {
        self.seq += 1;
        let prio = event_rank(&ev);
        self.heap.push(Reverse(Sched {
            t,
            prio,
            seq: self.seq,
            ev,
        }));
        self.seq
    }

    fn bootstrap(&mut self) {
        let iv = self.p.telemetry_iv;
        for i in 0..self.n_fixed {
            if !self.nodes[i].mqtt {
                let d = self.event_uniform(RNG_TRAFFIC_TELEMETRY, i as u64, 0.0, iv);
                self.push(d, Ev::Telemetry { node: i as u32 });
            }
        }
        for i in self.n_fixed..self.nodes.len() {
            let b = self.event_uniform(RNG_TRAFFIC_BEACON, i as u64, 0.0, self.p.beacon_iv);
            self.push(b, Ev::Beacon { node: i as u32 });
            let f = self.event_uniform(RNG_TRAFFIC_FAMILY, i as u64, 1200.0, 2400.0);
            self.push(f, Ev::Family { node: i as u32 });
        }
        // msg partner pairs: consecutive walker waves on the same route
        let mut by_route: HashMap<u32, Vec<u32>> = HashMap::new();
        for (wi, w) in self.walkers.iter().enumerate() {
            by_route.entry(w.route).or_default().push(wi as u32);
        }
        let mut route_keys: Vec<u32> = by_route.keys().copied().collect();
        route_keys.sort();
        for rk in route_keys {
            let ws = &by_route[&rk];
            for pair in ws.windows(2) {
                let entity = ((pair[0] as u64) << 32) | pair[1] as u64;
                let d = self.event_uniform(RNG_TRAFFIC_MESSAGE, entity, 600.0, 1800.0);
                self.push(
                    d,
                    Ev::MsgPair {
                        route: rk,
                        wa: pair[0],
                        wb: pair[1],
                        turn: 0,
                    },
                );
            }
        }
        for wi in 0..self.walkers.len() {
            let t0 = self.walkers[wi].start_s;
            self.push(t0, Ev::Dispatch { walker: wi as u32 });
        }
        self.push(0.0, Ev::SosDay { day: 0 });
        let outages = self.p.outages.clone();
        for (site, d0, d1) in outages {
            if let Some(&idx) = self.name_to_idx.get(&site) {
                self.push(d0 * 86400.0, Ev::OutageStart { node: idx });
                self.push(d1 * 86400.0, Ev::OutageEnd { node: idx });
            } else {
                eprintln!("outage site not found: {site}");
            }
        }
        self.push(self.p.energy_step_s, Ev::EnergyStep);
        self.push(21600.0, Ev::SocSample);
        self.push(3600.0, Ev::Prune);
        self.push(86400.0 + 3.0 * 3600.0, Ev::Shuttle);
    }

    // ── PHY ──────────────────────────────────────────────────────────────────

    fn day(&self) -> usize {
        (self.now / 86400.0) as usize
    }

    fn radio_pos(&self, i: u32) -> (f64, f64) {
        let node = &self.nodes[i as usize];
        if let Some(ri) = node.route {
            let r = &self.routes[ri as usize];
            let tt = (self.now - node.start_s).clamp(0.0, r.duration_s);
            let (la, lo) = interp2(&r.t_s, &r.lat, &r.lon, tt);
            return (la, lo);
        }
        (node.lat, node.lon)
    }

    pub fn loss_db(&self, a: u32, b: u32) -> f64 {
        let (na, nb) = (&self.nodes[a as usize], &self.nodes[b as usize]);
        match (na.is_radio, nb.is_radio) {
            (false, false) => *self.fixed_loss.get(&(a, b)).unwrap_or(&DEAD_DB),
            (true, true) => {
                if na.route.is_none() || nb.route.is_none() {
                    return DEAD_DB; // docked radios are off
                }
                let (la1, lo1) = self.radio_pos(a);
                let (la2, lo2) = self.radio_pos(b);
                let d = haversine_m(la1, lo1, la2, lo2).max(10.0);
                if d > 8000.0 {
                    return DEAD_DB;
                }
                let fspl = 20.0 * d.log10() + 20.0 * self.cfg.radio.freq_mhz.log10() - 27.55;
                fspl + 20.0 + 12.0 * (d / 1000.0 - 1.5).max(0.0)
            }
            _ => {
                let (radio, site) = if na.is_radio { (a, b) } else { (b, a) };
                let rn = &self.nodes[radio as usize];
                let Some(ri) = rn.route else { return DEAD_DB };
                let r = &self.routes[ri as usize];
                let tt = (self.now - rn.start_s).clamp(0.0, r.duration_s);
                interp1(
                    &r.loss_t_s,
                    &self.route_site_loss[ri as usize][site as usize],
                    tt,
                )
            }
        }
    }

    // ── packets ──────────────────────────────────────────────────────────────

    // ── routing ──────────────────────────────────────────────────────────────

    fn scarcity(&mut self, i: u32) -> f64 {
        let node = &self.nodes[i as usize];
        if node.grid {
            return 1.0;
        }
        let mut runway = node.soc_wh;
        if node.solar {
            runway += self.solar_forecast_remaining_wh(i);
        }
        let cap = self.nodes[i as usize].cap_wh;
        let rf = (runway / cap).min(1.0);
        1.0 + 3.0 * (1.0 - rf) / rf.max(0.05)
    }

    /// Remaining generation estimate available to routing.  This deliberately
    /// uses only monthly climatology for the calendar date.  Realized daily kt
    /// and snow remain inputs to physical charging in `handle_energy`, but are
    /// not oracle knowledge exposed to a route decision.
    fn solar_forecast_remaining_wh(&mut self, i: u32) -> f64 {
        let day = self.day() as u32;
        let key = (i, day);
        if !self.solar_profile.contains_key(&key) {
            let node = &self.nodes[i as usize];
            let calendar_index = (day as usize).min(self.weather_calendar.len().saturating_sub(1));
            let (doy, month) = self.weather_calendar[calendar_index];
            let kt = self
                .cfg
                .solar
                .monthly_kt_mean
                .get(month)
                .copied()
                .unwrap_or(0.40);
            let mut prof = [0.0f64; 24];
            if let Some(ss) = &node.site_solar {
                for (h, p) in prof.iter_mut().enumerate() {
                    *p = solar_power_w(
                        node.lat,
                        node.lon,
                        doy,
                        h as f64 * 3600.0,
                        kt,
                        &node.horizon,
                        ss,
                        self.cfg.solar.panel_w_nominal,
                        self.cfg.solar.system_efficiency,
                    );
                }
            }
            self.solar_profile.insert(key, prof);
        }
        let hour = ((self.now % 86400.0) / 3600.0) as usize;
        self.solar_profile[&key][hour.min(23)..].iter().sum()
    }

    fn edge_weight(&mut self, v: u32, margin: f64) -> f64 {
        let m = self.p.mode.weight_mode();
        if m == Mode::MinHop {
            return 1.0;
        }
        let sigma = self.cfg.shadowing.sigma_db;
        let p_ok = 0.5 * (1.0 + erf(margin / (sigma * std::f64::consts::SQRT_2))).max(0.04);
        if m == Mode::Etx {
            return 1.0 / p_ok;
        }
        let e = &self.cfg.energy;
        let etx_j = e.tx_current_ma / 1000.0 * e.battery_v * 0.5;
        let mut w = (etx_j / p_ok) * self.scarcity(v);
        if m == Mode::LbEnergy {
            let node = &self.nodes[v as usize];
            let med = self.fwd_median.max(1e-6);
            let overuse = (node.fwd_ewma / med - 1.0).max(0.0);
            w *= (1.0 + 2.0 * overuse) * (1.0 + 1.5 * node.death_score);
        }
        w
    }

    pub(crate) fn build_route_tree(&mut self) {
        if matches!(self.p.mode.weight_mode(), Mode::LbEnergy) {
            // Apply the implicit zero observations from forwarding events
            // handled by other nodes. The former per-node-only update never
            // decayed an avoided relay and was not a true network-load EWMA.
            self.decay_forward_loads();
            let mut fwds: Vec<f64> = self.nodes[..self.n_fixed]
                .iter()
                .filter(|n| !n.mqtt)
                .map(|n| n.fwd_ewma)
                .collect();
            fwds.sort_by(f64::total_cmp);
            self.fwd_median = if fwds.is_empty() {
                0.0
            } else {
                fwds[fwds.len() / 2]
            };
        }
        let n = self.nodes.len();
        let mut dist = vec![f64::INFINITY; n];
        let mut next: Vec<Option<u32>> = vec![None; n];
        let mut pq: BinaryHeap<Reverse<Sched>> = BinaryHeap::new();
        let mut seq = 0u64;
        for (i, d) in dist.iter_mut().enumerate().take(self.n_fixed) {
            if self.nodes[i].mqtt && self.nodes[i].alive {
                *d = 0.0;
                seq += 1;
                // Every Dijkstra entry is a TxEnd payload, so the rank is
                // uniform and relaxation order stays (cost, seq) as before.
                pq.push(Reverse(Sched {
                    t: 0.0,
                    prio: 0,
                    seq,
                    ev: Ev::TxEnd { idx: i as u64 },
                }));
            }
        }
        while let Some(Reverse(s)) = pq.pop() {
            let Ev::TxEnd { idx } = s.ev else { continue };
            let u = idx as usize;
            if s.t > dist[u] {
                continue;
            }
            let neighbors = self.fixed_adj[u].clone();
            for (v, margin) in neighbors {
                let nv = &self.nodes[v as usize];
                if !nv.alive || nv.docked {
                    continue;
                }
                // The reverse Dijkstra relaxation represents a packet sent
                // from upstream node `v` to gatewayward relay `u`.  Charge the
                // relay that will receive and forward the packet, matching the
                // Python reference and the documented scarcity(relay) cost.
                let w = self.edge_weight(u as u32, margin);
                if s.t + w < dist[v as usize] {
                    dist[v as usize] = s.t + w;
                    next[v as usize] = Some(u as u32);
                    seq += 1;
                    pq.push(Reverse(Sched {
                        t: s.t + w,
                        prio: 0,
                        seq,
                        ev: Ev::TxEnd { idx: v as u64 },
                    }));
                }
            }
        }
        self.route_next = next;
        self.route_cost = dist;
        self.route_tree_t = self.now;

        // duty assignment
        if self.p.mode.is_duty() {
            let on_tree: HashSet<u32> = self
                .route_next
                .iter()
                .filter_map(|x| *x)
                .chain((0..self.n_fixed as u32).filter(|&i| self.nodes[i as usize].mqtt))
                .collect();
            // selective_duty keeps every current route-tree parent awake, plus
            // all connectivity-critical cut vertices. Articulation points alone
            // are not a connected awake backbone in redundant/diamond graphs.
            let critical: HashSet<u32> = if matches!(self.p.mode, Mode::SelectiveDuty) {
                self.critical_relays()
            } else {
                HashSet::new()
            };
            for i in 0..self.n_fixed {
                if self.nodes[i].mqtt || self.nodes[i].grid {
                    continue;
                }
                self.accrue_node_energy_state(i as u32);
                self.nodes[i].duty = match self.p.mode {
                    Mode::DutySync => 0.05,
                    Mode::SelectiveDuty => {
                        if critical.contains(&(i as u32)) || on_tree.contains(&(i as u32)) {
                            1.0
                        } else {
                            0.05
                        }
                    }
                    Mode::DutyAdaptive => {
                        let runway = self.nodes[i].soc_wh
                            + if self.nodes[i].solar {
                                self.solar_forecast_remaining_wh(i as u32)
                            } else {
                                0.0
                            };
                        let rf = (runway / self.nodes[i].cap_wh).min(1.0);
                        (0.02 + 0.23 * rf).clamp(0.02, 0.25)
                    }
                    Mode::RotateLb => {
                        if on_tree.contains(&(i as u32)) {
                            1.0
                        } else {
                            0.02
                        }
                    }
                    _ => 1.0,
                };
            }
        }
    }

    /// Relays whose removal would strand another node from every gateway — the
    /// cut-vertices of the live connectivity graph. Iterative Tarjan
    /// articulation-point search over alive/undocked fixed sites plus a virtual
    /// super-source joined to all live gateways. O(V+E) per rebuild.
    fn critical_relays(&self) -> HashSet<u32> {
        let n = self.n_fixed;
        let s = n; // virtual super-source index
        let mut adj: Vec<Vec<u32>> = vec![Vec::new(); n + 1];
        let live = |i: usize| self.nodes[i].alive && !self.nodes[i].docked;
        for u in 0..n {
            if !live(u) {
                continue;
            }
            for &(v, _margin) in &self.fixed_adj[u] {
                let vv = v as usize;
                if vv < n && live(vv) {
                    adj[u].push(v);
                }
            }
            if self.nodes[u].mqtt {
                adj[u].push(s as u32);
                adj[s].push(u as u32);
            }
        }
        let mut disc = vec![-1i64; n + 1];
        let mut low = vec![0i64; n + 1];
        let mut parent = vec![u32::MAX; n + 1];
        let mut ap: HashSet<u32> = HashSet::new();
        let mut timer = 0i64;
        // DFS from the super-source (its own articulation status is irrelevant).
        disc[s] = timer;
        low[s] = timer;
        timer += 1;
        let mut stack: Vec<(usize, usize)> = vec![(s, 0)];
        while let Some(&(u, ei)) = stack.last() {
            if ei < adj[u].len() {
                stack.last_mut().unwrap().1 += 1;
                let v = adj[u][ei] as usize;
                if disc[v] == -1 {
                    parent[v] = u as u32;
                    disc[v] = timer;
                    low[v] = timer;
                    timer += 1;
                    stack.push((v, 0));
                } else if v as u32 != parent[u] {
                    low[u] = low[u].min(disc[v]);
                }
            } else {
                stack.pop();
                if let Some(&(p, _)) = stack.last() {
                    low[p] = low[p].min(low[u]);
                    if parent[p] != u32::MAX && low[u] >= disc[p] {
                        ap.insert(p as u32);
                    }
                }
            }
        }
        ap.into_iter()
            .filter(|&i| (i as usize) < n && !self.nodes[i as usize].mqtt)
            .collect()
    }

    fn tree_path(&self, start: u32) -> Option<Vec<u32>> {
        let mut path = vec![start];
        let mut cur = start;
        // A Dijkstra tree is acyclic, but bound defensively by the actual
        // fixed-site population rather than an undocumented 24-node constant.
        for _ in 0..=self.n_fixed {
            match self.route_next[cur as usize] {
                None => {
                    return if self.nodes[cur as usize].mqtt {
                        Some(path)
                    } else {
                        None
                    };
                }
                Some(nh) => {
                    path.push(nh);
                    cur = nh;
                }
            }
        }
        None
    }

    pub fn route_to_mqtt_public(&mut self, origin: u32) -> Option<Vec<u32>> {
        if self.now - self.route_tree_t > self.p.route_refresh_s {
            self.build_route_tree();
        }
        if !self.nodes[origin as usize].is_radio {
            return self.tree_path(origin);
        }
        // mobile: attach to the best reachable fixed site
        let mut best: Option<(u32, f64)> = None;
        let origin_channel = self.nodes[origin as usize].channel;
        for s in 0..self.n_fixed as u32 {
            let ns = &self.nodes[s as usize];
            if !ns.alive || ns.docked {
                continue;
            }
            if self.p.regional_channels && ns.channel != origin_channel {
                continue;
            }
            let c = self.route_cost[s as usize];
            if !c.is_finite() {
                continue;
            }
            let loss = self.loss_db(origin, s);
            let margin = self.cfg.radio.received_power_reference_dbm()
                - loss
                - self.cfg.radio.rx_sensitivity_dbm;
            if margin < 3.0 {
                continue;
            }
            let total = c + self.edge_weight(s, margin);
            if best.is_none_or(|(_, bc)| total < bc) {
                best = Some((s, total));
            }
        }
        let (s, _) = best?;
        let sub = self.tree_path(s)?;
        let mut path = vec![origin];
        path.extend(sub);
        Some(path)
    }
}

pub fn haversine_m(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let r = 6_371_000.0;
    let (p1, p2) = (lat1.to_radians(), lat2.to_radians());
    let dp = (lat2 - lat1).to_radians();
    let dl = (lon2 - lon1).to_radians();
    let a = (dp / 2.0).sin().powi(2) + p1.cos() * p2.cos() * (dl / 2.0).sin().powi(2);
    2.0 * r * a.sqrt().atan2((1.0 - a).sqrt())
}

fn month_index_from_date(date: &str) -> usize {
    date.split('-')
        .nth(1)
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(1)
        .clamp(1, 12)
        - 1
}

pub fn erf(x: f64) -> f64 {
    // Abramowitz–Stegun 7.1.26 (|err| < 1.5e-7)
    let sign = if x < 0.0 { -1.0 } else { 1.0 };
    let x = x.abs();
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let y = 1.0
        - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
            + 0.254829592)
            * t
            * (-x * x).exp();
    sign * y
}

pub fn interp1(xs: &[f64], ys: &[f64], x: f64) -> f64 {
    if xs.is_empty() {
        return DEAD_DB;
    }
    if x <= xs[0] {
        return ys[0];
    }
    if x >= xs[xs.len() - 1] {
        return ys[ys.len() - 1];
    }
    let mut lo = 0usize;
    let mut hi = xs.len() - 1;
    while hi - lo > 1 {
        let mid = (lo + hi) / 2;
        if xs[mid] <= x {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let f = (x - xs[lo]) / (xs[hi] - xs[lo]).max(1e-9);
    ys[lo] + (ys[hi] - ys[lo]) * f
}

pub fn interp2(xs: &[f64], la: &[f64], lo_: &[f64], x: f64) -> (f64, f64) {
    (interp1(xs, la, x), interp1(xs, lo_, x))
}

pub fn doy_from_date(date: &str) -> u32 {
    let parts: Vec<u32> = date.split('-').filter_map(|p| p.parse().ok()).collect();
    if parts.len() < 3 {
        return 182;
    }
    let (y, m, d) = (parts[0], parts[1], parts[2]);
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    let cum = [0u32, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    cum[(m as usize - 1).min(11)] + d + if leap && m > 2 { 1 } else { 0 }
}

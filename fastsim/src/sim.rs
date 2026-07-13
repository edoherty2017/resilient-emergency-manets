//! Event-driven port of scripts/mesh_sim.py (kiosk-pool semantics).
//! Summary-only: no trace emission — fastsim is the sweeps/CI engine;
//! the Python sim remains the visual-trace generator.

use crate::inputs::*;
use crate::rng::Rng;
use crate::solar::SiteSolar;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, HashSet};
use std::sync::Arc;

pub const SLOT_S: f64 = 0.040;
pub const CARRIER_SENSE_DBM: f64 = -124.0;
pub const REVIVE_FRACTION: f64 = 0.05;
pub const MIN_CHECKOUT_SOC_FRACTION: f64 = 0.20;
/// Low-power-listening CAD cadence.  A receiver must overlap the LoRa
/// preamble for at least two symbols during its deterministic awake window.
pub const CAD_PERIOD_S: f64 = 1.0;
pub const CAD_MIN_SYMBOLS: f64 = 2.0;
pub const TREELINE_M: f64 = 1100.0;
pub const LATENCY_SAMPLE_CAP: usize = 2000;

pub const RNG_TRAFFIC_TELEMETRY: u64 = 0x5452_4146_5400_0001;
pub const RNG_TRAFFIC_BEACON: u64 = 0x5452_4146_4200_0002;
pub const RNG_TRAFFIC_FAMILY: u64 = 0x5452_4146_4600_0003;
pub const RNG_TRAFFIC_MESSAGE: u64 = 0x5452_4146_4d00_0004;
pub const RNG_INCIDENT_OCCURRENCE: u64 = 0x494e_435f_4f43_4301;
pub const RNG_INCIDENT_TIME: u64 = 0x494e_435f_5449_4d02;
pub const RNG_INCIDENT_SENDER: u64 = 0x494e_435f_5345_4e03;
pub const RNG_MAC_BUSY_BACKOFF: u64 = 0x4d41_435f_4255_5301;
pub const RNG_MAC_DIFS: u64 = 0x4d41_435f_4449_4602;
pub const RNG_MAC_REBROADCAST: u64 = 0x4d41_435f_5245_4203;
pub const RNG_PHY: u64 = 0x5048_5900_0000_0004;
pub const RNG_CAD_PHASE: u64 = 0x4341_445f_5048_4105;
pub const RNG_LATENCY_SAMPLE: u64 = 0x4c41_545f_5341_4d06;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Flood,
    MinHop,
    Etx,
    EnergyAware,
    LbEnergy,
    DutySync,
    DutyAdaptive,
    RotateLb,
}

impl Mode {
    pub fn parse(s: &str) -> Option<Mode> {
        Some(match s {
            "flood" => Mode::Flood,
            "min_hop" => Mode::MinHop,
            "etx" => Mode::Etx,
            "energy_aware" => Mode::EnergyAware,
            "lb_energy" => Mode::LbEnergy,
            "duty_sync" => Mode::DutySync,
            "duty_adaptive" => Mode::DutyAdaptive,
            "rotate_lb" => Mode::RotateLb,
            _ => return None,
        })
    }
    pub fn is_duty(self) -> bool {
        matches!(self, Mode::DutySync | Mode::DutyAdaptive | Mode::RotateLb)
    }
    pub fn is_routed(self) -> bool {
        !matches!(self, Mode::Flood)
    }
    /// duty modes route with lb_energy weights
    pub fn weight_mode(self) -> Mode {
        if self.is_duty() {
            Mode::LbEnergy
        } else {
            self
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Tel,
    Pos,
    Fam,
    Msg,
    Sos,
    Ack,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Dest {
    Mqtt,
    Node(u32),
}

#[derive(Clone)]
pub struct Flight {
    pub id: u64,
    pub origin: u32,
    pub okind: Kind,
    pub bytes: u32,
    pub hop_limit: i32,
    pub dest: Dest,
    pub flood: bool,
    pub route: Option<Arc<Vec<u32>>>,
    pub sos_id: u64,  // 0 = n/a
    pub ack_for: u64, // 0 = n/a
    pub is_fwd: bool,
}

pub struct PktMeta {
    pub origin: u32,
    pub t0: f64,
    pub delivered: bool,
    pub latency: f64,
}

/// Per-origin counters plus an order-independent bottom-k sample of delivered
/// latencies.  The keyed priorities make the sample uniform over packet IDs
/// without coupling results to prune timing or another RNG stream.
#[derive(Default)]
pub struct OriginAgg {
    pub sent: u64,
    pub delivered: u64,
    pub delivered_latency_count: u64,
    pub latency_sample: Vec<(u64, f64)>, // (stable priority, latency seconds)
    latency_sample_worst: Option<(usize, u64)>,
}

impl OriginAgg {
    pub fn record(&mut self, master_seed: u64, packet_id: u64, delivered: bool, latency: f64) {
        self.sent += 1;
        if !delivered {
            return;
        }
        self.delivered += 1;
        self.delivered_latency_count += 1;
        let priority =
            Rng::mix64(master_seed ^ Rng::mix64(RNG_LATENCY_SAMPLE) ^ Rng::mix64(packet_id));
        if self.latency_sample.len() < LATENCY_SAMPLE_CAP {
            self.latency_sample.push((priority, latency));
            if self
                .latency_sample_worst
                .is_none_or(|(_, worst)| priority > worst)
            {
                self.latency_sample_worst = Some((self.latency_sample.len() - 1, priority));
            }
            return;
        }
        let (worst_i, worst_priority) = self
            .latency_sample_worst
            .expect("non-empty full latency sample");
        if priority < worst_priority {
            self.latency_sample[worst_i] = (priority, latency);
            self.latency_sample_worst = self
                .latency_sample
                .iter()
                .enumerate()
                .max_by_key(|(_, (p, _))| *p)
                .map(|(i, (p, _))| (i, *p));
        }
    }
}

#[derive(Default, Clone)]
pub struct NodeStats {
    pub tx: u64,
    pub rx_ok: u64,
    pub collisions: u64,
    pub duty_misses: u64,
    pub dup_suppressed: u64,
    pub tx_airtime_s: f64,
    pub energy_tx_wh: f64,
    /// Energy-depletion transitions.  Repeated deplete/revive cycles remain
    /// events; availability is reported separately from unavailable time.
    pub deaths: u64,
    pub unavailable_s: f64,
    pub solar_wh: f64,
}

pub struct Node {
    pub name: String,
    pub lat: f64,
    pub lon: f64,
    pub grid: bool,
    pub solar: bool,
    pub mqtt: bool,
    pub horizon: Vec<f64>,
    pub site_solar: Option<SiteSolar>,
    pub cap_wh: f64,
    pub soc_wh: f64,
    /// Battery state and forced outages are tracked independently; `alive` is
    /// their conjunction and remains the fast-path radio availability flag.
    pub energy_alive: bool,
    pub forced_outage: bool,
    pub alive: bool,
    pub unavailable_since: Option<f64>,
    pub docked: bool,
    pub duty: f64,
    pub is_radio: bool,
    pub channel: u8,
    pub kiosk: Option<u32>, // fixed-site index of current box
    pub route: Option<u32>,
    pub start_s: f64,
    pub tx_until: f64,
    pub fwd_ewma: f64,
    pub death_score: f64,
    pub seen: HashSet<(u32, u64)>,
    pub pending: HashMap<(u32, u64), u64>, // rebroadcast tombstones (event seq)
    pub stats: NodeStats,
}

impl Node {
    pub fn unavailable_s_through(&self, end_time: f64) -> f64 {
        self.stats.unavailable_s
            + self
                .unavailable_since
                .map_or(0.0, |t| (end_time - t).max(0.0))
    }

    pub fn availability_through(&self, end_time: f64) -> f64 {
        if end_time <= 0.0 {
            return 1.0;
        }
        (1.0 - self.unavailable_s_through(end_time) / end_time).clamp(0.0, 1.0)
    }
}

pub struct ActiveTx {
    pub start: f64,
    pub end: f64,
    pub sender: u32,
    pub rssi_at: Vec<(u32, f64)>,
    /// Receivers whose awake/CAD window acquired the preamble at TxStart.
    pub cad_acquired: HashSet<u32>,
    pub flight: Flight,
}

#[derive(Default, Clone, Debug)]
pub struct BusyUnion {
    pub closed_s: f64,
    pub open: Option<(f64, f64)>,
}

impl BusyUnion {
    /// Insert intervals in nondecreasing start-time order (the event loop's
    /// transmission-start order), maintaining their exact union.
    pub fn add(&mut self, start: f64, end: f64) {
        if end <= start {
            return;
        }
        match self.open {
            None => self.open = Some((start, end)),
            Some((s, e)) if start <= e => self.open = Some((s, e.max(end))),
            Some((s, e)) => {
                self.closed_s += e - s;
                self.open = Some((start, end));
            }
        }
    }

    pub fn total_through(&self, end_time: f64) -> f64 {
        self.closed_s + self.open.map_or(0.0, |(s, e)| e.min(end_time).max(s) - s)
    }
}

pub struct KioskBank {
    pub soc_wh: f64,
    pub cap_wh: f64,
}

pub struct Walker {
    pub route: u32,
    pub start_s: f64,
    pub kiosk: u32,
    pub return_kiosk: u32,
    pub radio: Option<u32>,
}

pub enum Ev {
    Telemetry {
        node: u32,
    },
    Beacon {
        node: u32,
    },
    Family {
        node: u32,
    },
    MsgPair {
        route: u32,
        wa: u32,
        wb: u32,
        turn: u64,
    },
    SosDay {
        day: u32,
    },
    SosSend {
        node: u32,
        sos_id: u64,
        stage: u32,
    },
    SosBurst {
        node: u32,
        flight: Flight,
    },
    TxAttempt {
        node: u32,
        flight: Flight,
        tries: u32,
        post_difs: bool,
    },
    TxEnd {
        idx: u64,
    },
    RebroadcastFire {
        node: u32,
        key: (u32, u64),
        flight: Flight,
    },
    EnergyStep,
    SocSample,
    Prune,
    Dispatch {
        walker: u32,
    },
    WalkEnd {
        walker: u32,
    },
    Shuttle,
    OutageStart {
        node: u32,
    },
    OutageEnd {
        node: u32,
    },
}

pub struct Sched {
    pub t: f64,
    pub seq: u64,
    pub ev: Ev,
}

impl PartialEq for Sched {
    fn eq(&self, o: &Self) -> bool {
        self.t == o.t && self.seq == o.seq
    }
}
impl Eq for Sched {}
impl PartialOrd for Sched {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Sched {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        self.t.total_cmp(&o.t).then(self.seq.cmp(&o.seq))
    }
}

pub struct LinkHealth {
    pub tries: u64,
    pub ok: u64,
    pub margin_sum: f64,
}

pub struct RentalStats {
    pub walker_days: u64,
    pub served: u64,
    pub starved: u64,
    pub starved_no_stock: u64,
    pub starved_unserviceable: u64,
    pub unusable_at_checkout: u64,
    pub checkout_soc_sum: f64,
}

pub struct Params {
    pub mode: Mode,
    pub days: f64,
    pub seed: u64,
    pub renters_per_route: u32,
    pub kiosk_spares: u32,
    pub sos_retry: bool,
    pub telemetry_iv: f64,
    pub beacon_iv: f64,
    pub route_refresh_s: f64,
    pub energy_step_s: f64,
    pub relay_rx_ma: f64, // fixed-site listen current (0 = config value)
    pub hiker_rx_ma: f64, // rental-radio listen current (0 = config value)
    pub regional_channels: bool,
    pub outages: Vec<(String, f64, f64)>, // (site, start_day, end_day)
}

pub struct Sim {
    pub cfg: Config,
    pub p: Params,
    /// Counter-based streams keyed by phenomenon and entity.  Event ordering
    /// at another node/generator cannot consume this generator's next draw.
    pub draw_counters: HashMap<(u64, u64), u64>,
    /// Slow/fast fading innovations are isolated per undirected RF link.
    pub link_rng: HashMap<(u32, u32), Rng>,
    pub now: f64,
    pub seq: u64,
    pub heap: BinaryHeap<Reverse<Sched>>,

    pub nodes: Vec<Node>,
    pub n_fixed: usize,
    pub name_to_idx: HashMap<String, u32>,
    pub fixed_loss: HashMap<(u32, u32), f64>,
    pub fixed_adj: Vec<Vec<(u32, f64)>>, // margin dB
    pub routes: Vec<Route>,
    pub route_site_loss: Vec<Vec<Vec<f64>>>, // [route][site][sample]
    pub walkers: Vec<Walker>,
    pub kiosk_banks: std::collections::HashMap<u32, KioskBank>,
    pub weather: Vec<(f64, f64)>, // (kt, snow_factor)
    pub start_doy: u32,

    pub active: HashMap<u64, ActiveTx>,
    /// Recently completed transmissions retained until every overlapping
    /// active reception is resolved.  This removes TxEnd insertion-order bias.
    pub completed_overlap: HashMap<u64, ActiveTx>,
    pub next_tx_idx: u64,
    pub pkt_seq: u64,
    pub pkt_meta: HashMap<u64, PktMeta>,
    pub agg: HashMap<u32, OriginAgg>,
    pub sos_incidents: HashMap<u64, (f64, u32, bool, f64)>, // t0, tries, delivered, lat
    pub sos_acked: HashSet<u64>,

    pub route_next: Vec<Option<u32>>,
    pub route_cost: Vec<f64>,
    pub route_tree_t: f64,
    pub fwd_median: f64,
    pub shadow: HashMap<(u32, u32), (f64, f64)>,
    pub link_health: HashMap<(u32, u32), LinkHealth>,
    pub rental: RentalStats,
    /// Sum of transmitter airtime.  This is offered load, not channel
    /// occupancy, because simultaneous/spatially separate TXs are additive.
    pub total_offered_airtime_s: f64,
    /// Per-node union of intervals whose received power crosses the carrier
    /// sense threshold (plus the node's own transmit intervals).
    pub local_busy: Vec<BusyUnion>,
    pub soc_series: Vec<(f64, f64, f64, f64, f64)>, // day, p10, p50, p90, std
    pub solar_profile: HashMap<(u32, u32), [f64; 24]>, // (node, day)
    pub airtime_lut: HashMap<u32, f64>,
}

impl Sim {
    pub(crate) fn event_uniform(&mut self, domain: u64, entity: u64, lo: f64, hi: f64) -> f64 {
        let counter = self.draw_counters.entry((domain, entity)).or_insert(0);
        let key = Rng::mix64(entity) ^ Rng::mix64(*counter);
        *counter += 1;
        lo + (hi - lo) * Rng::keyed_f64(self.p.seed, domain, key)
    }
}

#[cfg(test)]
mod tests {
    use super::{BusyUnion, OriginAgg, LATENCY_SAMPLE_CAP};

    #[test]
    fn busy_union_counts_overlaps_once() {
        let mut busy = BusyUnion::default();
        busy.add(0.0, 2.0);
        busy.add(0.5, 1.0);
        busy.add(1.5, 3.0);
        busy.add(5.0, 6.0);
        assert_eq!(busy.total_through(10.0), 4.0);
        assert_eq!(busy.total_through(5.5), 3.5);
    }

    #[test]
    fn latency_bottom_k_is_order_independent_and_not_early_censored() {
        let mut forward = OriginAgg::default();
        let mut reverse = OriginAgg::default();
        let count = LATENCY_SAMPLE_CAP as u64 * 3;
        for id in 1..=count {
            forward.record(123, id, true, id as f64);
        }
        for id in (1..=count).rev() {
            reverse.record(123, id, true, id as f64);
        }
        forward
            .latency_sample
            .sort_unstable_by_key(|(priority, _)| *priority);
        reverse
            .latency_sample
            .sort_unstable_by_key(|(priority, _)| *priority);
        assert_eq!(forward.latency_sample, reverse.latency_sample);
        assert_eq!(forward.latency_sample.len(), LATENCY_SAMPLE_CAP);
        assert!(forward
            .latency_sample
            .iter()
            .any(|(_, latency)| *latency > LATENCY_SAMPLE_CAP as f64));
        assert_eq!(forward.delivered_latency_count, count);
    }
}

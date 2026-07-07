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
pub const KIOSK_CHARGE_W: f64 = 10.0;
pub const T_SNIFF_S: f64 = 1.0;
pub const TREELINE_M: f64 = 1100.0;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Flood, MinHop, Etx, EnergyAware, LbEnergy, DutySync, DutyAdaptive, RotateLb,
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
        if self.is_duty() { Mode::LbEnergy } else { self }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind { Tel, Pos, Fam, Msg, Sos, Ack }

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Dest { Mqtt, Node(u32) }

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
    pub sos_id: u64,      // 0 = n/a
    pub ack_for: u64,     // 0 = n/a
    pub is_fwd: bool,
}

pub struct PktMeta {
    pub origin: u32,
    pub t0: f64,
    pub delivered: bool,
    pub latency: f64,
}

#[derive(Default, Clone)]
pub struct NodeStats {
    pub tx: u64,
    pub rx_ok: u64,
    pub collisions: u64,
    pub dup_suppressed: u64,
    pub tx_airtime_s: f64,
    pub energy_tx_wh: f64,
    pub deaths: u64,
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
    pub alive: bool,
    pub docked: bool,
    pub duty: f64,
    pub is_radio: bool,
    pub kiosk: Option<u32>,          // fixed-site index of current box
    pub route: Option<u32>,
    pub start_s: f64,
    pub tx_until: f64,
    pub fwd_ewma: f64,
    pub death_score: f64,
    pub seen: HashSet<(u32, u64)>,
    pub pending: HashMap<(u32, u64), u64>, // rebroadcast tombstones (event seq)
    pub stats: NodeStats,
}

pub struct ActiveTx {
    pub start: f64,
    pub end: f64,
    pub sender: u32,
    pub rssi_at: Vec<(u32, f64)>,
    pub flight: Flight,
}

pub struct Walker {
    pub route: u32,
    pub start_s: f64,
    pub kiosk: u32,
    pub return_kiosk: u32,
    pub radio: Option<u32>,
}

pub enum Ev {
    Telemetry { node: u32 },
    Beacon { node: u32 },
    Family { node: u32 },
    MsgPair { route: u32, wa: u32, wb: u32, turn: u64 },
    SosDay { day: u32 },
    SosSend { node: u32, sos_id: u64, stage: u32 },
    TxAttempt { node: u32, flight: Flight, tries: u32, post_difs: bool },
    TxEnd { idx: u64 },
    RebroadcastFire { node: u32, key: (u32, u64), seq: u64, flight: Flight },
    EnergyStep,
    SocSample,
    Prune,
    Dispatch { walker: u32 },
    WalkEnd { walker: u32 },
    Shuttle,
}

pub struct Sched {
    pub t: f64,
    pub seq: u64,
    pub ev: Ev,
}

impl PartialEq for Sched {
    fn eq(&self, o: &Self) -> bool { self.t == o.t && self.seq == o.seq }
}
impl Eq for Sched {}
impl PartialOrd for Sched {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> { Some(self.cmp(o)) }
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
}

pub struct Sim {
    pub cfg: Config,
    pub p: Params,
    pub rng: Rng,
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
    pub weather: Vec<(f64, f64)>, // (kt, snow_factor)
    pub start_doy: u32,

    pub active: HashMap<u64, ActiveTx>,
    pub next_tx_idx: u64,
    pub pkt_seq: u64,
    pub pkt_meta: HashMap<u64, PktMeta>,
    pub agg: HashMap<u32, (u64, u64, Vec<f64>)>, // origin -> sent, delivered, lats
    pub sos_incidents: HashMap<u64, (f64, u32, bool, f64)>, // t0, tries, delivered, lat
    pub sos_acked: HashSet<u64>,

    pub route_next: Vec<Option<u32>>,
    pub route_cost: Vec<f64>,
    pub route_tree_t: f64,
    pub fwd_median: f64,
    pub shadow: HashMap<(u32, u32), (f64, f64)>,
    pub link_health: HashMap<(u32, u32), LinkHealth>,
    pub rental: RentalStats,
    pub total_airtime_s: f64,
    pub soc_series: Vec<(f64, f64, f64, f64, f64)>, // day, p10, p50, p90, std
    pub solar_profile: HashMap<(u32, u32), [f64; 24]>, // (node, day)
    pub airtime_lut: HashMap<u32, f64>,
}

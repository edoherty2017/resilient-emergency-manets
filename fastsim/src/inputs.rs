//! Input file schemas: topology_statewide.json, routes_statewide.json,
//! weather_year.json, config/sim/wmnf_sim.yaml. Field names mirror the
//! Python artifacts exactly.

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct Topology {
    pub sites: HashMap<String, Site>,
    pub links: HashMap<String, Link>,
}

#[derive(Deserialize, Clone)]
pub struct Site {
    pub lat: f64,
    pub lon: f64,
    #[allow(dead_code)]
    pub hg_m: f64,
    pub power: String,
    pub mqtt_uplink: bool,
    #[serde(default)]
    pub elev_m: f64,
    pub horizon_deg: Vec<f64>,
}

#[derive(Deserialize)]
pub struct Link {
    pub loss_db_q50: f64,
    #[allow(dead_code)]
    #[serde(default)]
    pub loss_db_q90: f64,
}

#[derive(Deserialize)]
pub struct RoutesFile {
    pub routes: HashMap<String, Route>,
}

#[derive(Deserialize, Clone)]
pub struct Route {
    pub kiosk: String,
    pub return_kiosk: String,
    pub duration_s: f64,
    pub t_s: Vec<f64>,
    pub lat: Vec<f64>,
    pub lon: Vec<f64>,
    pub loss_t_s: Vec<f64>,
    pub loss_db_q50: HashMap<String, Vec<f64>>,
}

#[derive(Deserialize)]
pub struct WeatherFile {
    pub start_date: String,
    pub days: Vec<WeatherDay>,
}

#[derive(Deserialize)]
pub struct WeatherDay {
    pub kt: f64,
    #[serde(default = "one")]
    pub snow_factor: f64,
}

fn one() -> f64 { 1.0 }

#[derive(Deserialize)]
pub struct Config {
    pub radio: RadioCfg,
    pub shadowing: ShadowCfg,
    pub energy: EnergyCfg,
    pub battery: BatteryCfg,
    pub solar: SolarCfg,
    pub traffic: TrafficCfg,
}

#[derive(Deserialize)]
pub struct RadioCfg {
    pub sf: u32,
    pub bw_hz: f64,
    pub cr: u32,
    pub preamble_syms: f64,
    pub eirp_dbm: f64,
    pub rx_sensitivity_dbm: f64,
    pub noise_figure_db: f64,
    pub snr_demod_threshold_db: f64,
    pub capture_threshold_db: f64,
    pub hop_limit: i32,
}

#[derive(Deserialize)]
pub struct ShadowCfg {
    pub sigma_db: f64,
    pub fast_fading_db: f64,
    pub coherence_s: f64,
}

#[derive(Deserialize)]
pub struct EnergyCfg {
    pub battery_v: f64,
    pub tx_current_ma: f64,
    pub rx_listen_ma: f64,
    pub light_sleep_ma: f64,
    pub gps_active_ma: f64,
}

#[derive(Deserialize)]
pub struct BatteryCfg {
    pub capacity_wh: f64,
    pub usable_fraction: f64,
    pub start_soc: f64,
}

#[derive(Deserialize)]
pub struct SolarCfg {
    pub panel_w_nominal: f64,
    pub system_efficiency: f64,
    pub canopy_tau_16ft: f64,
    pub pyramid_tilt_deg: f64,
}

#[derive(Deserialize)]
pub struct TrafficCfg {
    pub telemetry_payload_b: u32,
    pub position_payload_b: u32,
    pub sos_payload_b: u32,
}

/// Semtech airtime (port of scripts/lora_airtime.py), milliseconds.
pub fn airtime_ms(payload_bytes: u32, sf: u32, bw_hz: f64, cr: u32,
                  preamble_syms: f64) -> f64 {
    let t_sym = (1u64 << sf) as f64 / bw_hz * 1000.0;
    let de = if t_sym >= 16.38 { 1.0 } else { 0.0 };
    let num = 8.0 * payload_bytes as f64 - 4.0 * sf as f64 + 28.0 + 16.0;
    let n_payload = 8.0
        + ((num / (4.0 * (sf as f64 - 2.0 * de))).ceil() * (cr as f64 + 4.0)).max(0.0);
    (preamble_syms + 4.25 + n_payload) * t_sym
}

//! Input file schemas: topology_statewide.json, routes_statewide.json,
//! weather_year.json, config/sim/wmnf_sim.yaml. Field names mirror the
//! Python artifacts exactly.

use serde::Deserialize;
use std::collections::{HashMap, HashSet};

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
    pub date: String,
    pub kt: f64,
    #[serde(default = "one")]
    pub snow_factor: f64,
}

fn one() -> f64 {
    1.0
}

#[derive(Deserialize)]
pub struct Config {
    pub radio: RadioCfg,
    pub shadowing: ShadowCfg,
    pub energy: EnergyCfg,
    pub battery: BatteryCfg,
    pub solar: SolarCfg,
    pub traffic: TrafficCfg,
    #[serde(default)]
    pub sim: SimCfg,
    #[serde(default)]
    pub kiosk: KioskCfg,
}

#[derive(Deserialize)]
pub struct KioskCfg {
    pub capacity: u32,
    pub panel_w: f64,
    pub battery_wh: f64,
    pub charge_w_per_bay: f64,
    #[serde(default = "default_min_checkout_soc")]
    pub min_checkout_soc: f64,
    pub demand_tier_a: u32,
    pub demand_tier_b: u32,
    pub demand_tier_c: u32,
}

impl Default for KioskCfg {
    fn default() -> Self {
        KioskCfg {
            capacity: 20,
            panel_w: 200.0,
            battery_wh: 1000.0,
            charge_w_per_bay: 10.0,
            min_checkout_soc: default_min_checkout_soc(),
            demand_tier_a: 20,
            demand_tier_b: 10,
            demand_tier_c: 4,
        }
    }
}

fn default_min_checkout_soc() -> f64 {
    0.20
}

#[derive(Deserialize)]
pub struct RadioCfg {
    #[serde(default = "default_freq_mhz")]
    pub freq_mhz: f64,
    pub sf: u32,
    pub bw_hz: f64,
    pub cr: u32,
    pub preamble_syms: f64,
    /// Canonical link-budget inputs.  `eirp_dbm` is accepted only as a legacy
    /// combined TX-plus-RX reference so old external configs retain their
    /// numerical behavior without double-counting receiver gain.
    #[serde(default)]
    pub tx_eirp_dbm: Option<f64>,
    #[serde(default)]
    pub rx_antenna_gain_dbi: f64,
    #[serde(default)]
    pub rx_feed_loss_db: f64,
    #[serde(default, rename = "eirp_dbm")]
    pub legacy_link_budget_dbm: Option<f64>,
    pub rx_sensitivity_dbm: f64,
    pub noise_figure_db: f64,
    pub snr_demod_threshold_db: f64,
    pub capture_threshold_db: f64,
    pub hop_limit: i32,
}

fn default_freq_mhz() -> f64 {
    915.0
}

impl RadioCfg {
    pub fn received_power_reference_dbm(&self) -> f64 {
        if let Some(tx_eirp) = self.tx_eirp_dbm {
            tx_eirp + self.rx_antenna_gain_dbi - self.rx_feed_loss_db
        } else {
            self.legacy_link_budget_dbm.expect(
                "radio requires tx_eirp_dbm (canonical) or eirp_dbm (legacy combined reference)",
            )
        }
    }
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
    /// Operational routing forecast: monthly climatology, never the realized
    /// current/future weather used by the physical energy model.
    #[serde(default = "default_monthly_kt")]
    pub monthly_kt_mean: Vec<f64>,
}

fn default_monthly_kt() -> Vec<f64> {
    vec![
        0.38, 0.41, 0.44, 0.44, 0.45, 0.44, 0.45, 0.45, 0.44, 0.41, 0.36, 0.35,
    ]
}

#[derive(Deserialize)]
pub struct TrafficCfg {
    #[serde(default = "default_telemetry_interval_s")]
    pub telemetry_interval_s: f64,
    #[serde(default = "default_position_interval_s")]
    pub position_interval_s: f64,
    pub telemetry_payload_b: u32,
    pub position_payload_b: u32,
    pub sos_payload_b: u32,
}

fn default_telemetry_interval_s() -> f64 {
    900.0
}
fn default_position_interval_s() -> f64 {
    300.0
}

#[derive(Deserialize)]
pub struct SimCfg {
    #[serde(default = "default_solar_step_s")]
    pub solar_step_s: f64,
}

impl Default for SimCfg {
    fn default() -> Self {
        Self {
            solar_step_s: default_solar_step_s(),
        }
    }
}

fn default_solar_step_s() -> f64 {
    60.0
}

/// Semtech airtime (port of scripts/lora_airtime.py), milliseconds.
pub fn airtime_ms(payload_bytes: u32, sf: u32, bw_hz: f64, cr: u32, preamble_syms: f64) -> f64 {
    let t_sym = (1u64 << sf) as f64 / bw_hz * 1000.0;
    let de = if t_sym >= 16.38 { 1.0 } else { 0.0 };
    let num = 8.0 * payload_bytes as f64 - 4.0 * sf as f64 + 28.0 + 16.0;
    let n_payload =
        8.0 + ((num / (4.0 * (sf as f64 - 2.0 * de))).ceil() * (cr as f64 + 4.0)).max(0.0);
    (preamble_syms + 4.25 + n_payload) * t_sym
}

fn finite(name: &str, value: f64) -> Result<(), String> {
    if value.is_finite() {
        Ok(())
    } else {
        Err(format!("{name} must be finite"))
    }
}

fn positive(name: &str, value: f64) -> Result<(), String> {
    finite(name, value)?;
    if value > 0.0 {
        Ok(())
    } else {
        Err(format!("{name} must be greater than zero"))
    }
}

fn nonnegative(name: &str, value: f64) -> Result<(), String> {
    finite(name, value)?;
    if value >= 0.0 {
        Ok(())
    } else {
        Err(format!("{name} cannot be negative"))
    }
}

fn strictly_increasing(name: &str, values: &[f64]) -> Result<(), String> {
    if values.is_empty() {
        return Err(format!("{name} cannot be empty"));
    }
    if values.iter().any(|value| !value.is_finite()) {
        return Err(format!("{name} contains a non-finite value"));
    }
    if values.windows(2).any(|pair| pair[1] <= pair[0]) {
        return Err(format!("{name} must be strictly increasing"));
    }
    Ok(())
}

fn valid_iso_date(value: &str) -> bool {
    let parts: Vec<&str> = value.split('-').collect();
    if parts.len() != 3 || parts[0].len() != 4 || parts[1].len() != 2 || parts[2].len() != 2 {
        return false;
    }
    let Ok(year) = parts[0].parse::<u32>() else {
        return false;
    };
    let Ok(month) = parts[1].parse::<usize>() else {
        return false;
    };
    let Ok(day) = parts[2].parse::<u32>() else {
        return false;
    };
    if !(1..=12).contains(&month) {
        return false;
    }
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let month_days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    (1..=month_days[month - 1]).contains(&day)
}

fn next_iso_date(value: &str) -> Option<String> {
    if !valid_iso_date(value) {
        return None;
    }
    let mut parts = value.split('-');
    let mut year = parts.next()?.parse::<u32>().ok()?;
    let mut month = parts.next()?.parse::<u32>().ok()?;
    let mut day = parts.next()?.parse::<u32>().ok()?;
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let month_days = [
        31,
        if leap { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    day += 1;
    if day > month_days[(month - 1) as usize] {
        day = 1;
        month += 1;
        if month > 12 {
            month = 1;
            year += 1;
        }
    }
    Some(format!("{year:04}-{month:02}-{day:02}"))
}

/// Fail-closed validation for every model input used by FastSim. The compact
/// serde structs intentionally ignore unrelated project metadata, so semantic
/// checks live here rather than relying on deserialization alone.
pub fn validate_model_inputs(
    cfg: &Config,
    topology: &Topology,
    routes: &RoutesFile,
    weather: &WeatherFile,
    days: f64,
) -> Result<(), String> {
    // Route durations are serialized to one decimal place while some derived
    // time arrays retain full precision. Accept only that bounded rounding
    // residue; interpolation itself clamps to the declared duration.
    const ROUTE_TIME_ROUNDING_S: f64 = 0.1;
    positive("days", days)?;

    let radio = &cfg.radio;
    positive("radio.freq_mhz", radio.freq_mhz)?;
    if !(5..=12).contains(&radio.sf) {
        return Err("radio.sf must be between 5 and 12".to_string());
    }
    positive("radio.bw_hz", radio.bw_hz)?;
    if !(1..=4).contains(&radio.cr) {
        return Err("radio.cr must be between 1 and 4".to_string());
    }
    positive("radio.preamble_syms", radio.preamble_syms)?;
    match (radio.tx_eirp_dbm, radio.legacy_link_budget_dbm) {
        (Some(value), None) => finite("radio.tx_eirp_dbm", value)?,
        (None, Some(value)) => finite("radio.eirp_dbm", value)?,
        (Some(_), Some(_)) => {
            return Err("radio must not specify both tx_eirp_dbm and legacy eirp_dbm".to_string())
        }
        (None, None) => return Err("radio requires tx_eirp_dbm or legacy eirp_dbm".to_string()),
    }
    for (name, value) in [
        ("radio.rx_antenna_gain_dbi", radio.rx_antenna_gain_dbi),
        ("radio.rx_feed_loss_db", radio.rx_feed_loss_db),
        ("radio.rx_sensitivity_dbm", radio.rx_sensitivity_dbm),
        ("radio.noise_figure_db", radio.noise_figure_db),
        ("radio.snr_demod_threshold_db", radio.snr_demod_threshold_db),
        ("radio.capture_threshold_db", radio.capture_threshold_db),
    ] {
        finite(name, value)?;
    }
    if radio.hop_limit < 0 {
        return Err("radio.hop_limit cannot be negative".to_string());
    }

    nonnegative("shadowing.sigma_db", cfg.shadowing.sigma_db)?;
    nonnegative("shadowing.fast_fading_db", cfg.shadowing.fast_fading_db)?;
    positive("shadowing.coherence_s", cfg.shadowing.coherence_s)?;
    positive("energy.battery_v", cfg.energy.battery_v)?;
    for (name, value) in [
        ("energy.tx_current_ma", cfg.energy.tx_current_ma),
        ("energy.rx_listen_ma", cfg.energy.rx_listen_ma),
        ("energy.light_sleep_ma", cfg.energy.light_sleep_ma),
        ("energy.gps_active_ma", cfg.energy.gps_active_ma),
    ] {
        nonnegative(name, value)?;
    }
    if cfg.energy.tx_current_ma < cfg.energy.rx_listen_ma
        || cfg.energy.tx_current_ma < cfg.energy.light_sleep_ma
    {
        return Err("energy.tx_current_ma must cover the configured radio baseline".to_string());
    }
    positive("battery.capacity_wh", cfg.battery.capacity_wh)?;
    positive("battery.usable_fraction", cfg.battery.usable_fraction)?;
    if cfg.battery.usable_fraction > 1.0 {
        return Err("battery.usable_fraction must not exceed one".to_string());
    }
    for (name, value) in [
        ("battery.start_soc", cfg.battery.start_soc),
        ("solar.system_efficiency", cfg.solar.system_efficiency),
        ("solar.canopy_tau_16ft", cfg.solar.canopy_tau_16ft),
    ] {
        finite(name, value)?;
        if !(0.0..=1.0).contains(&value) {
            return Err(format!("{name} must be between zero and one"));
        }
    }
    nonnegative("solar.panel_w_nominal", cfg.solar.panel_w_nominal)?;
    finite("solar.pyramid_tilt_deg", cfg.solar.pyramid_tilt_deg)?;
    if cfg.solar.monthly_kt_mean.len() != 12
        || cfg
            .solar
            .monthly_kt_mean
            .iter()
            .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
    {
        return Err("solar.monthly_kt_mean must contain 12 finite values in [0,1]".to_string());
    }
    positive(
        "traffic.telemetry_interval_s",
        cfg.traffic.telemetry_interval_s,
    )?;
    positive(
        "traffic.position_interval_s",
        cfg.traffic.position_interval_s,
    )?;
    positive("sim.solar_step_s", cfg.sim.solar_step_s)?;
    if cfg.kiosk.capacity == 0 {
        return Err("kiosk.capacity must be greater than zero".to_string());
    }
    for (name, value) in [
        ("kiosk.panel_w", cfg.kiosk.panel_w),
        ("kiosk.battery_wh", cfg.kiosk.battery_wh),
        ("kiosk.charge_w_per_bay", cfg.kiosk.charge_w_per_bay),
    ] {
        nonnegative(name, value)?;
    }
    finite("kiosk.min_checkout_soc", cfg.kiosk.min_checkout_soc)?;
    if !(0.0..=1.0).contains(&cfg.kiosk.min_checkout_soc) {
        return Err("kiosk.min_checkout_soc must be between zero and one".to_string());
    }

    if topology.sites.is_empty() {
        return Err("topology.sites cannot be empty".to_string());
    }
    if !topology.sites.values().any(|site| site.mqtt_uplink) {
        return Err("topology must contain at least one MQTT gateway".to_string());
    }
    for (name, site) in &topology.sites {
        finite(&format!("site {name} latitude"), site.lat)?;
        finite(&format!("site {name} longitude"), site.lon)?;
        if !(-90.0..=90.0).contains(&site.lat) || !(-180.0..=180.0).contains(&site.lon) {
            return Err(format!("site {name} has coordinates outside valid bounds"));
        }
        positive(&format!("site {name} antenna height"), site.hg_m)?;
        finite(&format!("site {name} elevation"), site.elev_m)?;
        if !matches!(site.power.as_str(), "grid" | "solar" | "battery") {
            return Err(format!(
                "site {name} has unknown power type {:?}",
                site.power
            ));
        }
        if site.horizon_deg.is_empty() || site.horizon_deg.iter().any(|value| !value.is_finite()) {
            return Err(format!(
                "site {name} requires a finite, non-empty horizon mask"
            ));
        }
    }

    let mut undirected_links = HashSet::new();
    for (key, link) in &topology.links {
        let parts: Vec<&str> = key.split('|').collect();
        if parts.len() != 2 || parts[0].is_empty() || parts[1].is_empty() {
            return Err(format!("invalid link key {key:?}; expected site_a|site_b"));
        }
        let (a, b) = (parts[0], parts[1]);
        if a == b {
            return Err(format!("self-link is not allowed: {key}"));
        }
        if !topology.sites.contains_key(a) || !topology.sites.contains_key(b) {
            return Err(format!("link {key} references an unknown site"));
        }
        let pair = if a < b { (a, b) } else { (b, a) };
        if !undirected_links.insert(pair) {
            return Err(format!("duplicate undirected link: {key}"));
        }
        nonnegative(&format!("link {key} loss_db_q50"), link.loss_db_q50)?;
    }

    for (route_name, route) in &routes.routes {
        if !topology.sites.contains_key(&route.kiosk) {
            return Err(format!(
                "route {route_name} has unknown kiosk {:?}",
                route.kiosk
            ));
        }
        if !topology.sites.contains_key(&route.return_kiosk) {
            return Err(format!(
                "route {route_name} has unknown return_kiosk {:?}",
                route.return_kiosk
            ));
        }
        positive(&format!("route {route_name} duration_s"), route.duration_s)?;
        if route.duration_s > 86400.0 {
            return Err(format!(
                "route {route_name} duration_s exceeds one daily checkout interval"
            ));
        }
        strictly_increasing(&format!("route {route_name} t_s"), &route.t_s)?;
        strictly_increasing(&format!("route {route_name} loss_t_s"), &route.loss_t_s)?;
        if route.lat.len() != route.t_s.len() || route.lon.len() != route.t_s.len() {
            return Err(format!(
                "route {route_name} coordinate/time arrays have different lengths"
            ));
        }
        if route.t_s[0] < -ROUTE_TIME_ROUNDING_S
            || route.t_s[route.t_s.len() - 1] > route.duration_s + ROUTE_TIME_ROUNDING_S
        {
            return Err(format!("route {route_name} t_s lies outside duration_s"));
        }
        if route.loss_t_s[0] < -ROUTE_TIME_ROUNDING_S
            || route.loss_t_s[route.loss_t_s.len() - 1] > route.duration_s + ROUTE_TIME_ROUNDING_S
        {
            return Err(format!(
                "route {route_name} loss_t_s lies outside duration_s"
            ));
        }
        for (&lat, &lon) in route.lat.iter().zip(&route.lon) {
            if !lat.is_finite()
                || !lon.is_finite()
                || !(-90.0..=90.0).contains(&lat)
                || !(-180.0..=180.0).contains(&lon)
            {
                return Err(format!("route {route_name} contains invalid coordinates"));
            }
        }
        for (site, losses) in &route.loss_db_q50 {
            if !topology.sites.contains_key(site) {
                return Err(format!(
                    "route {route_name} loss table references unknown site {site}"
                ));
            }
            if losses.len() != route.loss_t_s.len()
                || losses
                    .iter()
                    .any(|value| !value.is_finite() || *value < 0.0)
            {
                return Err(format!(
                    "route {route_name} loss table for {site} has invalid values or length"
                ));
            }
        }
    }

    if !valid_iso_date(&weather.start_date) {
        return Err(format!(
            "weather.start_date must be a real YYYY-MM-DD date, got {:?}",
            weather.start_date
        ));
    }
    let required_days = days.ceil() as usize;
    if weather.days.len() < required_days {
        return Err(format!(
            "weather has {} days but simulation requires {required_days}",
            weather.days.len()
        ));
    }
    let mut expected_date = weather.start_date.clone();
    for (index, day) in weather.days.iter().enumerate() {
        if day.date != expected_date {
            return Err(format!(
                "weather day {index} date must be {expected_date}, got {:?}",
                day.date
            ));
        }
        expected_date = next_iso_date(&expected_date).expect("validated weather date");
    }
    for (index, day) in weather.days.iter().take(required_days).enumerate() {
        if !day.kt.is_finite() || !(0.0..=1.0).contains(&day.kt) {
            return Err(format!(
                "weather day {index} kt must be finite and in [0,1]"
            ));
        }
        if !day.snow_factor.is_finite() || !(0.0..=1.0).contains(&day.snow_factor) {
            return Err(format!(
                "weather day {index} snow_factor must be finite and in [0,1]"
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::RadioCfg;

    const COMMON: &str = r#"
sf: 11
bw_hz: 250000
cr: 1
preamble_syms: 16
rx_sensitivity_dbm: -131
noise_figure_db: 6
snr_demod_threshold_db: -17.5
capture_threshold_db: 6
hop_limit: 3
"#;

    #[test]
    fn canonical_and_legacy_link_budget_inputs_are_equivalent() {
        let canonical: RadioCfg = serde_yaml::from_str(&format!(
            "{COMMON}tx_eirp_dbm: 24.15\nrx_antenna_gain_dbi: 2.15\nrx_feed_loss_db: 0\n",
        ))
        .unwrap();
        let legacy: RadioCfg = serde_yaml::from_str(&format!("{COMMON}eirp_dbm: 26.3\n",)).unwrap();
        assert!((canonical.received_power_reference_dbm() - 26.3).abs() < 1e-12);
        assert!(
            (canonical.received_power_reference_dbm() - legacy.received_power_reference_dbm())
                .abs()
                < 1e-12
        );
    }
}

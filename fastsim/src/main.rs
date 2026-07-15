//! fastsim — compiled twin of scripts/mesh_sim.py (kiosk-pool semantics),
//! summary-only. Purpose: multi-seed sweeps and parameter scans at ~10-30×
//! Python speed. The Python sim remains the visual-trace generator.
//!
//! Usage:
//!   fastsim --topology T.json --routes R.json --weather W.json \
//!           --config wmnf_sim.yaml --mode lb_energy --days 365 --seed 42 \
//!           --renters-per-route 2 --sos-retry --out summary.json

mod engine;
mod engine2;
mod inputs;
mod rng;
mod sim;
mod solar;

use inputs::*;
use serde_json::json;
use sim::*;
use std::collections::{HashMap, HashSet};
use std::fmt::Display;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::str::FromStr;

fn arg(args: &HashMap<String, String>, k: &str, d: &str) -> String {
    args.get(k).cloned().unwrap_or_else(|| d.to_string())
}

fn die(message: impl Display) -> ! {
    eprintln!("fastsim: error: {message}");
    std::process::exit(2);
}

fn parse_cli(raw: &[String]) -> Result<(HashMap<String, String>, HashSet<String>), String> {
    const VALUE_OPTIONS: &[&str] = &[
        "topology",
        "routes",
        "weather",
        "config",
        "mode",
        "days",
        "seed",
        "renters-per-route",
        "kiosk-spares",
        "telemetry-interval-s",
        "beacon-interval-s",
        "route-refresh-s",
        "energy-step-s",
        "relay-rx-ma",
        "hiker-rx-ma",
        "outage",
        "out",
    ];
    const FLAG_OPTIONS: &[&str] = &["sos-retry", "regional-channels"];

    let mut args = HashMap::new();
    let mut flags = HashSet::new();
    let mut i = 0;
    while i < raw.len() {
        let Some(key) = raw[i].strip_prefix("--") else {
            return Err(format!("unexpected positional argument {:?}", raw[i]));
        };
        if key.is_empty() {
            return Err("empty option name".to_string());
        }
        if FLAG_OPTIONS.contains(&key) {
            if !flags.insert(key.to_string()) {
                return Err(format!("duplicate flag --{key}"));
            }
            i += 1;
            continue;
        }
        if !VALUE_OPTIONS.contains(&key) {
            return Err(format!("unknown option --{key}"));
        }
        let Some(value) = raw.get(i + 1) else {
            return Err(format!("--{key} requires a value"));
        };
        if value.starts_with("--") {
            return Err(format!("--{key} requires a value"));
        }
        if args.insert(key.to_string(), value.clone()).is_some() {
            return Err(format!("duplicate option --{key}"));
        }
        i += 2;
    }
    Ok((args, flags))
}

fn parse_value<T>(args: &HashMap<String, String>, key: &str, default: &str) -> T
where
    T: FromStr,
    T::Err: Display,
{
    let raw = arg(args, key, default);
    raw.parse::<T>()
        .unwrap_or_else(|error| die(format!("invalid --{key} value {raw:?}: {error}")))
}

fn read_text(path: &str, label: &str) -> String {
    std::fs::read_to_string(path)
        .unwrap_or_else(|error| die(format!("cannot read {label} {path:?}: {error}")))
}

fn parse_outages(
    raw: &str,
    days: f64,
    topology: &Topology,
) -> Result<Vec<(String, f64, f64)>, String> {
    let mut by_site: HashMap<String, Vec<(f64, f64)>> = HashMap::new();
    if raw.is_empty() {
        return Ok(Vec::new());
    }
    for spec in raw.split(',') {
        let parts: Vec<&str> = spec.split(':').collect();
        if parts.len() != 3 || parts[0].is_empty() {
            return Err(format!(
                "invalid outage {spec:?}; expected site:start_day:end_day"
            ));
        }
        let site = parts[0];
        if !topology.sites.contains_key(site) {
            return Err(format!("outage references unknown site {site:?}"));
        }
        let start = parts[1]
            .parse::<f64>()
            .map_err(|error| format!("invalid outage start in {spec:?}: {error}"))?;
        let end = parts[2]
            .parse::<f64>()
            .map_err(|error| format!("invalid outage end in {spec:?}: {error}"))?;
        if !start.is_finite() || !end.is_finite() || start < 0.0 || end <= start || end > days {
            return Err(format!(
                "outage {spec:?} must satisfy finite 0 <= start < end <= simulation days"
            ));
        }
        by_site
            .entry(site.to_string())
            .or_default()
            .push((start, end));
    }

    let mut sites: Vec<String> = by_site.keys().cloned().collect();
    sites.sort();
    let mut merged = Vec::new();
    for site in sites {
        let intervals = by_site.get_mut(&site).expect("known outage site");
        intervals.sort_by(|left, right| {
            left.0
                .total_cmp(&right.0)
                .then_with(|| left.1.total_cmp(&right.1))
        });
        let mut union: Vec<(f64, f64)> = Vec::new();
        for &(start, end) in intervals.iter() {
            if let Some(last) = union.last_mut() {
                if start <= last.1 {
                    last.1 = last.1.max(end);
                    continue;
                }
            }
            union.push((start, end));
        }
        merged.extend(
            union
                .into_iter()
                .map(|(start, end)| (site.clone(), start, end)),
        );
    }
    Ok(merged)
}

fn validate_params(params: &Params, cfg: &Config, routes: &RoutesFile) -> Result<(), String> {
    for (name, value) in [
        ("days", params.days),
        ("telemetry-interval-s", params.telemetry_iv),
        ("beacon-interval-s", params.beacon_iv),
        ("route-refresh-s", params.route_refresh_s),
        ("energy-step-s", params.energy_step_s),
    ] {
        if !value.is_finite() || value <= 0.0 {
            return Err(format!("--{name} must be finite and greater than zero"));
        }
    }
    if params.renters_per_route == 0 {
        return Err("--renters-per-route must be greater than zero".to_string());
    }
    let max_tier = cfg
        .kiosk
        .demand_tier_a
        .max(cfg.kiosk.demand_tier_b)
        .max(cfg.kiosk.demand_tier_c);
    // Extreme-but-valid u32 tiers can wrap this product in a narrower type
    // and slip past the limit; checked u128 arithmetic fails closed instead.
    let worst_case_walkers = (routes.routes.len() as u128)
        .checked_mul(max_tier as u128)
        .and_then(|walkers| walkers.checked_mul(params.renters_per_route as u128))
        .map(|walkers| walkers / 2)
        .ok_or_else(|| {
            "routes x demand tier x renters-per-route overflows the walker guard".to_string()
        })?;
    if worst_case_walkers > 100_000 {
        return Err(format!(
            "--renters-per-route would create up to {worst_case_walkers} walkers; limit is 100000"
        ));
    }
    if params.kiosk_spares > cfg.kiosk.capacity {
        return Err(format!(
            "--kiosk-spares cannot exceed kiosk.capacity ({})",
            cfg.kiosk.capacity
        ));
    }
    for (name, value) in [
        ("relay-rx-ma", params.relay_rx_ma),
        ("hiker-rx-ma", params.hiker_rx_ma),
    ] {
        if !value.is_finite() || value < 0.0 {
            return Err(format!("--{name} must be finite and non-negative"));
        }
        if value > cfg.energy.tx_current_ma {
            return Err(format!(
                "--{name} cannot exceed energy.tx_current_ma ({})",
                cfg.energy.tx_current_ma
            ));
        }
    }
    Ok(())
}

fn normalized_path(path: &str) -> Result<PathBuf, String> {
    let candidate = Path::new(path);
    if candidate.exists() {
        return candidate
            .canonicalize()
            .map_err(|error| format!("cannot resolve path {path:?}: {error}"));
    }
    let absolute = if candidate.is_absolute() {
        candidate.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| format!("cannot resolve working directory: {error}"))?
            .join(candidate)
    };
    let parent = absolute
        .parent()
        .ok_or_else(|| format!("output path has no parent: {path:?}"))?
        .canonicalize()
        .map_err(|error| format!("cannot resolve output parent for {path:?}: {error}"))?;
    let file_name = absolute
        .file_name()
        .ok_or_else(|| format!("output path has no file name: {path:?}"))?;
    Ok(parent.join(file_name))
}

fn reject_output_alias(output: &str, inputs: &[(&str, &str)]) -> Result<(), String> {
    let resolved_output = normalized_path(output)?;
    for (label, input) in inputs {
        if resolved_output == normalized_path(input)? {
            return Err(format!("output path aliases the {label} input: {output:?}"));
        }
    }
    Ok(())
}

fn atomic_write(path: &str, contents: &str) -> Result<(), String> {
    let output = Path::new(path);
    let parent = output
        .parent()
        .filter(|value| !value.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    let file_name = output
        .file_name()
        .ok_or_else(|| format!("output path has no file name: {path:?}"))?
        .to_string_lossy();
    let temporary = parent.join(format!(".{file_name}.tmp-{}", std::process::id()));
    let result = (|| -> Result<(), String> {
        let mut handle = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|error| format!("cannot create temporary output {temporary:?}: {error}"))?;
        handle
            .write_all(contents.as_bytes())
            .and_then(|_| handle.sync_all())
            .map_err(|error| format!("cannot write temporary output {temporary:?}: {error}"))?;
        std::fs::rename(&temporary, output)
            .map_err(|error| format!("cannot replace output {path:?}: {error}"))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let (args, flags) = parse_cli(&raw).unwrap_or_else(|error| die(error));
    let topology_path = arg(&args, "topology", "artifacts/sim/topology_statewide.json");
    let routes_path = arg(&args, "routes", "artifacts/sim/routes_statewide.json");
    let weather_path = arg(&args, "weather", "artifacts/sim/weather_year.json");
    let config_path = arg(&args, "config", "config/sim/wmnf_sim.yaml");
    let out_path = arg(&args, "out", "fastsim_summary.json");

    reject_output_alias(
        &out_path,
        &[
            ("topology", &topology_path),
            ("routes", &routes_path),
            ("weather", &weather_path),
            ("config", &config_path),
        ],
    )
    .unwrap_or_else(|error| die(error));

    let topo: Topology = serde_json::from_str(&read_text(&topology_path, "topology"))
        .unwrap_or_else(|error| die(format!("cannot parse topology {topology_path:?}: {error}")));
    let routes: RoutesFile = serde_json::from_str(&read_text(&routes_path, "routes"))
        .unwrap_or_else(|error| die(format!("cannot parse routes {routes_path:?}: {error}")));
    let weather: WeatherFile = serde_json::from_str(&read_text(&weather_path, "weather"))
        .unwrap_or_else(|error| die(format!("cannot parse weather {weather_path:?}: {error}")));
    let cfg: Config = serde_yaml::from_str(&read_text(&config_path, "config"))
        .unwrap_or_else(|error| die(format!("cannot parse config {config_path:?}: {error}")));

    let mode_name = arg(&args, "mode", "lb_energy");
    let mode =
        Mode::parse(&mode_name).unwrap_or_else(|| die(format!("unknown mode {mode_name:?}")));
    let days = parse_value(&args, "days", "365");
    let outages =
        parse_outages(&arg(&args, "outage", ""), days, &topo).unwrap_or_else(|error| die(error));
    let p = Params {
        mode,
        days,
        seed: parse_value(&args, "seed", "42"),
        renters_per_route: parse_value(&args, "renters-per-route", "2"),
        kiosk_spares: parse_value(&args, "kiosk-spares", "2"),
        sos_retry: flags.contains("sos-retry"),
        telemetry_iv: args
            .get("telemetry-interval-s")
            .map_or(cfg.traffic.telemetry_interval_s, |_| {
                parse_value(&args, "telemetry-interval-s", "0")
            }),
        beacon_iv: args
            .get("beacon-interval-s")
            .map_or(cfg.traffic.position_interval_s, |_| {
                parse_value(&args, "beacon-interval-s", "0")
            }),
        route_refresh_s: parse_value(&args, "route-refresh-s", "900"),
        energy_step_s: args.get("energy-step-s").map_or(cfg.sim.solar_step_s, |_| {
            parse_value(&args, "energy-step-s", "0")
        }),
        relay_rx_ma: parse_value(&args, "relay-rx-ma", "0"),
        hiker_rx_ma: parse_value(&args, "hiker-rx-ma", "0"),
        regional_channels: flags.contains("regional-channels"),
        outages,
    };
    validate_params(&p, &cfg, &routes).unwrap_or_else(|error| die(error));
    validate_model_inputs(&cfg, &topo, &routes, &weather, p.days)
        .unwrap_or_else(|error| die(error));
    let days = p.days;
    let seed = p.seed;

    let t0 = std::time::Instant::now();
    let mut sim = Sim::new(cfg, topo, routes, weather, p);
    sim.run();
    let wall = t0.elapsed().as_secs_f64();
    let dur = days * 86400.0;

    // ── summary (schema mirrors mesh_sim.py) ─────────────────────────────────
    let mut per_node = serde_json::Map::new();
    let mut sent_total = 0u64;
    let mut delivered_total = 0u64;
    for (i, n) in sim.nodes.iter().enumerate() {
        let channel_busy_s = sim.local_busy[i].total_through(dur);
        let dead_time_s = n.unavailable_s_through(dur);
        per_node.insert(
            n.name.clone(),
            json!({
                "tx": n.stats.tx, "rx_ok": n.stats.rx_ok,
                "collisions": n.stats.collisions,
                "duty_misses": n.stats.duty_misses,
                "dup_suppressed": n.stats.dup_suppressed,
                "tx_airtime_s": round2(n.stats.tx_airtime_s),
                "energy_tx_wh": round5(n.stats.energy_tx_wh),
                "deaths": n.stats.deaths,
                "death_events": n.stats.deaths,
                "ever_died": n.stats.deaths > 0,
                "dead_time_s": round2(dead_time_s),
                "availability": round5(n.availability_through(dur)),
                "channel_busy_s": round2(channel_busy_s),
                "channel_busy_ratio": round5(channel_busy_s / dur.max(f64::EPSILON)),
                "solar_wh": round2(n.stats.solar_wh),
                "final_soc": round4(n.soc_wh / n.cap_wh),
                "power": if n.grid { "grid" } else if n.solar { "solar" }
                         else { "battery" },
            }),
        );
    }
    let mut per_origin = serde_json::Map::new();
    for (origin, agg) in &sim.agg {
        sent_total += agg.sent;
        delivered_total += agg.delivered;
        let mut l: Vec<f64> = agg
            .latency_sample
            .iter()
            .map(|(_, latency)| *latency)
            .collect();
        l.sort_by(f64::total_cmp);
        let q = |p: f64| {
            linear_quantile_sorted(&l, p)
                .map_or(serde_json::Value::Null, |value| json!(round2(value)))
        };
        per_origin.insert(
            sim.nodes[*origin as usize].name.clone(),
            json!({
                "sent": agg.sent, "delivered": agg.delivered,
                "pdr": if agg.sent > 0 {
                    json!(round4(agg.delivered as f64 / agg.sent as f64))
                }
                       else { serde_json::Value::Null },
                "latency_p50_s": q(0.5), "latency_p95_s": q(0.95),
                "latency_observations": agg.delivered_latency_count,
                "latency_sample_size": l.len(),
                "latency_delivered_count": agg.delivered_latency_count,
                "latency_sample_count": l.len(),
                "latency_sample_method": "stable_order_independent_bottom_k_packet_ids",
            }),
        );
    }

    let solar_nodes: Vec<&Node> = sim.nodes.iter().filter(|n| n.solar).collect();
    let socs: Vec<f64> = solar_nodes.iter().map(|n| n.soc_wh / n.cap_wh).collect();
    let mean_soc = socs.iter().sum::<f64>() / socs.len().max(1) as f64;
    let soc_std = (socs.iter().map(|x| (x - mean_soc).powi(2)).sum::<f64>()
        / socs.len().max(1) as f64)
        .sqrt();
    let mut relay_e: Vec<f64> = solar_nodes.iter().map(|n| n.stats.energy_tx_wh).collect();
    relay_e.sort_by(f64::total_cmp);
    let gini = if relay_e.is_empty() || relay_e.iter().sum::<f64>() <= 0.0 {
        serde_json::Value::Null
    } else {
        let n = relay_e.len() as f64;
        let s: f64 = relay_e.iter().sum();
        let num: f64 = relay_e
            .iter()
            .enumerate()
            .map(|(i, x)| (2.0 * (i as f64 + 1.0) - n - 1.0) * x)
            .sum();
        json!(round4(num / (n * s)))
    };
    let deaths_total: u64 = solar_nodes.iter().map(|n| n.stats.deaths).sum();
    let unique_nodes_died = solar_nodes.iter().filter(|n| n.stats.deaths > 0).count();
    let dead_time_s_total: f64 = solar_nodes
        .iter()
        .map(|n| n.unavailable_s_through(dur))
        .sum();
    let fleet_availability = if solar_nodes.is_empty() || dur <= 0.0 {
        1.0
    } else {
        1.0 - dead_time_s_total / (solar_nodes.len() as f64 * dur)
    };
    let mean_duty =
        solar_nodes.iter().map(|n| n.duty).sum::<f64>() / solar_nodes.len().max(1) as f64;

    let soc_series: Vec<serde_json::Value> = sim
        .soc_series
        .iter()
        .map(|(d, p10, p50, p90, std)| {
            json!([
                round2(*d),
                round4(*p10),
                round4(*p50),
                round4(*p90),
                round4(*std)
            ])
        })
        .collect();

    let mut link_health_keys: Vec<(u32, u32)> = sim.link_health.keys().copied().collect();
    link_health_keys.sort_unstable();
    let mut link_rows: Vec<serde_json::Value> = Vec::new();
    for (a, b) in link_health_keys {
        let lh = &sim.link_health[&(a, b)];
        if lh.tries < 20 {
            continue;
        }
        let prr = lh.ok as f64 / lh.tries as f64;
        let margin = lh.margin_sum / lh.tries as f64;
        if prr < 0.05 && margin < 0.0 {
            continue;
        }
        link_rows.push(json!({
            "a": sim.nodes[a as usize].name, "b": sim.nodes[b as usize].name,
            "tries": lh.tries, "prr": round4(prr),
            "mean_margin_db": round2(margin),
            "struggling": prr < 0.8 || margin < 10.0,
        }));
    }

    let mut sos_lats: Vec<f64> = sim
        .sos_incidents
        .values()
        .filter(|i| i.delivered)
        .map(|i| i.latency_s)
        .collect();
    sos_lats.sort_by(f64::total_cmp);
    let mean_tries = sim
        .sos_incidents
        .values()
        .map(|i| i.tries as f64)
        .sum::<f64>()
        / sim.sos_incidents.len().max(1) as f64;

    let offered_ratio = sim.total_offered_airtime_s / dur.max(f64::EPSILON);
    let duty_misses_total: u64 = sim.nodes.iter().map(|n| n.stats.duty_misses).sum();
    let mut receiver_busy_ratios: Vec<f64> = sim.local_busy[..sim.n_fixed]
        .iter()
        .map(|b| b.total_through(dur) / dur.max(f64::EPSILON))
        .collect();
    receiver_busy_ratios.sort_by(f64::total_cmp);
    let busy_q = |p: f64| linear_quantile_sorted(&receiver_busy_ratios, p).unwrap_or(0.0);
    let summary = json!({
        "engine": "fastsim (rust)",
        "mode": mode_name,
        "days": days,
        "seed": seed,
        "resolved_parameters": {
            "renters_per_route": sim.p.renters_per_route,
            "kiosk_spares": sim.p.kiosk_spares,
            "sos_retry": sim.p.sos_retry,
            "telemetry_interval_s": sim.p.telemetry_iv,
            "beacon_interval_s": sim.p.beacon_iv,
            "route_refresh_s": sim.p.route_refresh_s,
            "energy_step_s": sim.p.energy_step_s,
            "relay_rx_ma_override": sim.p.relay_rx_ma,
            "hiker_rx_ma_override": sim.p.hiker_rx_ma,
            "regional_channels": sim.p.regional_channels,
            "radio_frequency_mhz": sim.cfg.radio.freq_mhz,
            "outages": sim.p.outages.iter().map(|(site, start, end)| json!({
                "site": site,
                "start_day": start,
                "end_day": end,
            })).collect::<Vec<_>>(),
        },
        "rng_stream_model": "counter_keyed_per_phenomenon_and_entity; keyed_per_day_incidents; per_link_phy_streams",
        "traffic_clock_model": "exogenous_arrivals_independent_of_mac_service",
        "simulation_interval": "half_open_[0,duration)",
        "mobility_time_basis": "absolute_checkout_time_across_utc_day_boundaries",
        "energy_state_accounting": "ordered_piecewise_duty_docking_and_kiosk_segments_between_integration_steps",
        "start_date": sim.start_date,
        "n_nodes": sim.nodes.len(),
        "n_renters": sim.walkers.len(),
        "channel_utilization": round5(offered_ratio),
        "channel_utilization_definition": "DEPRECATED alias for aggregate_offered_airtime_ratio; not physical channel occupancy",
        "aggregate_offered_airtime_ratio": round5(offered_ratio),
        "aggregate_offered_airtime_definition": "sum of all transmitter airtime divided by duration; overlapping and spatially isolated transmissions are additive",
        "duty_misses_total": duty_misses_total,
        "channel_occupancy": {
            "n_receivers": receiver_busy_ratios.len(),
            "receiver_busy_ratio_p50": round5(busy_q(0.50)),
            "receiver_busy_ratio_p95": round5(busy_q(0.95)),
            "receiver_busy_ratio_max": round5(busy_q(1.0)),
            "definition": "per-fixed-site physical RF interval union above the carrier-sense threshold, including own transmit intervals and periods when a site's receiver is unavailable; ratios use full run duration",
        },
        "routing_solar_forecast": "monthly_climatology_no_future_weather",
        "duty_wake_model": if sim.p.mode.is_duty() {
            json!({
                "model": "deterministic_periodic_cad",
                "sniff_period_s": CAD_PERIOD_S,
                "cad_min_symbols": CAD_MIN_SYMBOLS,
                "phase": if matches!(sim.p.mode, Mode::DutySync | Mode::SelectiveDuty) {
                    "shared_zero"
                } else {
                    "stable_per_node"
                },
                "missed_reception_possible": true,
                "mobile_ingress": "route_cost_selected; a low-duty ingress leaf remains CAD-gated",
            })
        } else {
            serde_json::Value::Null
        },
        "packets_originated": sent_total,
        "packet_ttl_s": PACKET_TTL_S,
        "pdr_overall": if sent_total > 0 {
            json!(round4(delivered_total as f64 / sent_total as f64))
        } else { serde_json::Value::Null },
        "sos": {
            "sent": sim.sos_incidents.len(),
            "delivered": sim.sos_incidents.values().filter(|i| i.delivered).count(),
            "latencies_s": sos_lats.iter().map(|l| round2(*l)).collect::<Vec<f64>>(),
            "mean_tries": cohort_stat(!sim.sos_incidents.is_empty(), mean_tries, round2),
            "level": "incident",
        },
        "rental": {
            "walker_days": sim.rental.walker_days,
            "served": sim.rental.served,
            "starved": sim.rental.starved,
            "starved_no_stock": sim.rental.starved_no_stock,
            "starved_unserviceable": sim.rental.starved_unserviceable,
            "unusable_at_checkout": sim.rental.unusable_at_checkout,
            "min_checkout_soc": sim.cfg.kiosk.min_checkout_soc,
            "minimum_checkout_soc_fraction": sim.cfg.kiosk.min_checkout_soc,
            "availability": round4(sim.rental.served as f64
                / sim.rental.walker_days.max(1) as f64),
            "mean_checkout_soc": cohort_stat(
                sim.rental.served > 0,
                sim.rental.checkout_soc_sum / sim.rental.served.max(1) as f64,
                round4,
            ),
        },
        "fleet_energy": {
            "mean_duty": cohort_stat(!solar_nodes.is_empty(), mean_duty, round4),
            "final_soc_std": cohort_stat(!solar_nodes.is_empty(), soc_std, round4),
            "final_soc_min": cohort_stat(
                !socs.is_empty(),
                socs.iter().copied().fold(f64::INFINITY, f64::min),
                round4,
            ),
            "deaths_total": deaths_total,
            "death_events_total": deaths_total,
            "unique_nodes_died": unique_nodes_died,
            "dead_time_s_total": round2(dead_time_s_total),
            "availability": cohort_stat(!solar_nodes.is_empty(), fleet_availability, round5),
            "relay_energy_gini": gini,
            "soc_series_6h": soc_series,
        },
        "link_health": link_rows,
        "per_origin": per_origin,
        "per_node": per_node,
    });
    let serialized = serde_json::to_string_pretty(&summary)
        .unwrap_or_else(|error| die(format!("cannot serialize summary: {error}")));
    atomic_write(&out_path, &serialized).unwrap_or_else(|error| die(error));
    eprintln!(
        "fastsim: {} days of {} in {:.1}s ({:.0} sim-days/s) -> {}",
        days,
        mode_name,
        wall,
        days / wall.max(1e-9),
        out_path
    );
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}
fn round4(x: f64) -> f64 {
    (x * 10000.0).round() / 10000.0
}
fn round5(x: f64) -> f64 {
    (x * 100000.0).round() / 100000.0
}

/// Cohort statistics serialize as JSON null when the cohort is empty, so an
/// absent population (no solar nodes, no SOS incidents, no served checkouts)
/// is distinguishable from a measured zero — the same convention the
/// relay-energy Gini and latency quantiles already follow.
fn cohort_stat(populated: bool, value: f64, digits: fn(f64) -> f64) -> serde_json::Value {
    if populated {
        json!(digits(value))
    } else {
        serde_json::Value::Null
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine2::tests::{test_config, test_params};

    fn guard_routes(count: usize) -> RoutesFile {
        let route = Route {
            kiosk: "kiosk".to_string(),
            return_kiosk: "kiosk".to_string(),
            duration_s: 3600.0,
            t_s: vec![0.0, 3600.0],
            lat: vec![44.0, 44.1],
            lon: vec![-71.0, -71.0],
            loss_t_s: vec![0.0, 3600.0],
            loss_db_q50: HashMap::new(),
        };
        RoutesFile {
            routes: (0..count)
                .map(|i| (format!("r{i}"), route.clone()))
                .collect(),
        }
    }

    #[test]
    fn extreme_demand_tiers_fail_closed_without_overflow() {
        // A maximal but valid tier must produce a clean guard error.
        let mut cfg = test_config();
        cfg.kiosk.demand_tier_a = u32::MAX;
        let params = test_params(Mode::MinHop);
        let error = validate_params(&params, &cfg, &guard_routes(1)).unwrap_err();
        assert!(
            error.contains("limit is 100000"),
            "unexpected error: {error}"
        );

        // 4 routes x 2^31 x 2^31 / 2 wrapped a u64 product to exactly zero,
        // silently passing the old guard; the checked u128 guard rejects it.
        let mut cfg = test_config();
        cfg.kiosk.demand_tier_a = 1 << 31;
        let mut params = test_params(Mode::MinHop);
        params.renters_per_route = 1 << 31;
        let error = validate_params(&params, &cfg, &guard_routes(4)).unwrap_err();
        assert!(
            error.contains("limit is 100000"),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn empty_cohort_statistics_serialize_as_null_not_zero() {
        // Zero SOS incidents (mean_tries) and zero served checkouts
        // (mean_checkout_soc) both degenerate to a numeric 0.0 mean.
        assert_eq!(cohort_stat(false, 0.0, round2), serde_json::Value::Null);
        assert_eq!(cohort_stat(false, 0.0, round4), serde_json::Value::Null);
        // An empty solar cohort degenerates to availability 1.0 and duty/std
        // 0.0; none of these may masquerade as measurements.
        assert_eq!(cohort_stat(false, 1.0, round5), serde_json::Value::Null);
        assert_eq!(
            cohort_stat(false, f64::INFINITY, round4),
            serde_json::Value::Null,
            "final_soc_min's empty fold must not leak"
        );
        // Populated cohorts keep the existing rounded numeric encoding.
        assert_eq!(cohort_stat(true, 0.123449, round4), json!(0.1234));
        assert_eq!(cohort_stat(true, 0.0, round2), json!(0.0));
    }
}

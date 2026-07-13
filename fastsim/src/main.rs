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
use std::collections::HashMap;

fn arg(args: &HashMap<String, String>, k: &str, d: &str) -> String {
    args.get(k).cloned().unwrap_or_else(|| d.to_string())
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut args: HashMap<String, String> = HashMap::new();
    let mut flags: Vec<String> = Vec::new();
    let mut i = 0;
    while i < raw.len() {
        let k = raw[i].trim_start_matches("--").to_string();
        if i + 1 < raw.len() && !raw[i + 1].starts_with("--") {
            args.insert(k, raw[i + 1].clone());
            i += 2;
        } else {
            flags.push(k);
            i += 1;
        }
    }

    let topo: Topology = serde_json::from_str(
        &std::fs::read_to_string(arg(
            &args,
            "topology",
            "artifacts/sim/topology_statewide.json",
        ))
        .expect("topology"),
    )
    .expect("topology parse");
    let routes: RoutesFile = serde_json::from_str(
        &std::fs::read_to_string(arg(&args, "routes", "artifacts/sim/routes_statewide.json"))
            .expect("routes"),
    )
    .expect("routes parse");
    let weather: WeatherFile = serde_json::from_str(
        &std::fs::read_to_string(arg(&args, "weather", "artifacts/sim/weather_year.json"))
            .expect("weather"),
    )
    .expect("weather parse");
    let cfg: Config = serde_yaml::from_str(
        &std::fs::read_to_string(arg(&args, "config", "config/sim/wmnf_sim.yaml")).expect("config"),
    )
    .expect("config parse");

    let mode = Mode::parse(&arg(&args, "mode", "lb_energy")).expect("mode");
    let p = Params {
        mode,
        days: arg(&args, "days", "365").parse().unwrap(),
        seed: arg(&args, "seed", "42").parse().unwrap(),
        renters_per_route: arg(&args, "renters-per-route", "2").parse().unwrap(),
        kiosk_spares: arg(&args, "kiosk-spares", "2").parse().unwrap(),
        sos_retry: flags.iter().any(|f| f == "sos-retry"),
        telemetry_iv: arg(&args, "telemetry-interval-s", "3600").parse().unwrap(),
        beacon_iv: arg(&args, "beacon-interval-s", "900").parse().unwrap(),
        route_refresh_s: arg(&args, "route-refresh-s", "3600").parse().unwrap(),
        energy_step_s: arg(&args, "energy-step-s", "600").parse().unwrap(),
        relay_rx_ma: arg(&args, "relay-rx-ma", "0").parse().unwrap(),
        hiker_rx_ma: arg(&args, "hiker-rx-ma", "0").parse().unwrap(),
        regional_channels: flags.iter().any(|f| f == "regional-channels"),
        outages: arg(&args, "outage", "")
            .split(',')
            .filter(|s| !s.is_empty())
            .filter_map(|spec| {
                let p: Vec<&str> = spec.split(':').collect();
                (p.len() == 3)
                    .then(|| (p[0].to_string(), p[1].parse().ok()?, p[2].parse().ok()?).into())
                    .and_then(|t: Option<(String, f64, f64)>| t)
            })
            .collect(),
    };
    let mode_name = arg(&args, "mode", "lb_energy");
    let out_path = arg(&args, "out", "fastsim_summary.json");
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
            if l.is_empty() {
                serde_json::Value::Null
            } else {
                json!(round2(l[((l.len() - 1) as f64 * p) as usize]))
            }
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

    let mut link_rows: Vec<serde_json::Value> = Vec::new();
    for ((a, b), lh) in &sim.link_health {
        if lh.tries < 20 {
            continue;
        }
        let prr = lh.ok as f64 / lh.tries as f64;
        let margin = lh.margin_sum / lh.tries as f64;
        if prr < 0.05 && margin < 0.0 {
            continue;
        }
        link_rows.push(json!({
            "a": sim.nodes[*a as usize].name, "b": sim.nodes[*b as usize].name,
            "tries": lh.tries, "prr": round4(prr),
            "mean_margin_db": round2(margin),
            "struggling": prr < 0.8 || margin < 10.0,
        }));
    }

    let mut sos_lats: Vec<f64> = sim
        .sos_incidents
        .values()
        .filter(|i| i.2)
        .map(|i| i.3)
        .collect();
    sos_lats.sort_by(f64::total_cmp);
    let mean_tries = sim.sos_incidents.values().map(|i| i.1 as f64).sum::<f64>()
        / sim.sos_incidents.len().max(1) as f64;

    let offered_ratio = sim.total_offered_airtime_s / dur.max(f64::EPSILON);
    let duty_misses_total: u64 = sim.nodes.iter().map(|n| n.stats.duty_misses).sum();
    let mut receiver_busy_ratios: Vec<f64> = sim.local_busy[..sim.n_fixed]
        .iter()
        .map(|b| b.total_through(dur) / dur.max(f64::EPSILON))
        .collect();
    receiver_busy_ratios.sort_by(f64::total_cmp);
    let busy_q = |p: f64| {
        if receiver_busy_ratios.is_empty() {
            0.0
        } else {
            receiver_busy_ratios[((receiver_busy_ratios.len() - 1) as f64 * p) as usize]
        }
    };
    let summary = json!({
        "engine": "fastsim (rust)",
        "wall_seconds": round2(wall),
        "mode": mode_name,
        "days": days,
        "seed": seed,
        "rng_stream_model": "counter_keyed_per_phenomenon_and_entity; keyed_per_day_incidents; per_link_phy_streams",
        "traffic_clock_model": "exogenous_arrivals_independent_of_mac_service",
        "start_date": "from-weather-file",
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
            "definition": "per-fixed-receiver union of intervals above the carrier-sense threshold, including own transmit intervals; ratios are union busy seconds divided by duration",
        },
        "routing_solar_forecast": "monthly_climatology_no_future_weather",
        "duty_wake_model": if sim.p.mode.is_duty() {
            json!({
                "model": "deterministic_periodic_cad",
                "sniff_period_s": CAD_PERIOD_S,
                "cad_min_symbols": CAD_MIN_SYMBOLS,
                "phase": if sim.p.mode == Mode::DutySync {
                    "shared_zero"
                } else {
                    "stable_per_node"
                },
                "missed_reception_possible": true,
            })
        } else {
            serde_json::Value::Null
        },
        "packets_originated": sent_total,
        "pdr_overall": if sent_total > 0 {
            json!(round4(delivered_total as f64 / sent_total as f64))
        } else { serde_json::Value::Null },
        "sos": {
            "sent": sim.sos_incidents.len(),
            "delivered": sim.sos_incidents.values().filter(|i| i.2).count(),
            "latencies_s": sos_lats.iter().map(|l| round2(*l)).collect::<Vec<f64>>(),
            "mean_tries": round2(mean_tries),
            "level": "incident",
        },
        "rental": {
            "walker_days": sim.rental.walker_days,
            "served": sim.rental.served,
            "starved": sim.rental.starved,
            "starved_no_stock": sim.rental.starved_no_stock,
            "starved_unserviceable": sim.rental.starved_unserviceable,
            "unusable_at_checkout": sim.rental.unusable_at_checkout,
            "min_checkout_soc": MIN_CHECKOUT_SOC_FRACTION,
            "minimum_checkout_soc_fraction": MIN_CHECKOUT_SOC_FRACTION,
            "availability": round4(sim.rental.served as f64
                / sim.rental.walker_days.max(1) as f64),
            "mean_checkout_soc": round4(sim.rental.checkout_soc_sum
                / sim.rental.served.max(1) as f64),
        },
        "fleet_energy": {
            "mean_duty": round4(mean_duty),
            "final_soc_std": round4(soc_std),
            "final_soc_min": round4(socs.iter().copied()
                .fold(f64::INFINITY, f64::min)),
            "deaths_total": deaths_total,
            "death_events_total": deaths_total,
            "unique_nodes_died": unique_nodes_died,
            "dead_time_s_total": round2(dead_time_s_total),
            "availability": round5(fleet_availability),
            "relay_energy_gini": gini,
            "soc_series_6h": soc_series,
        },
        "link_health": link_rows,
        "per_origin": per_origin,
        "per_node": per_node,
    });
    std::fs::write(&out_path, serde_json::to_string_pretty(&summary).unwrap())
        .expect("write summary");
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

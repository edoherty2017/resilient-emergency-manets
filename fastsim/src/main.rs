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
        &std::fs::read_to_string(arg(&args, "topology",
            "artifacts/sim/topology_statewide.json")).expect("topology"))
        .expect("topology parse");
    let routes: RoutesFile = serde_json::from_str(
        &std::fs::read_to_string(arg(&args, "routes",
            "artifacts/sim/routes_statewide.json")).expect("routes"))
        .expect("routes parse");
    let weather: WeatherFile = serde_json::from_str(
        &std::fs::read_to_string(arg(&args, "weather",
            "artifacts/sim/weather_year.json")).expect("weather"))
        .expect("weather parse");
    let cfg: Config = serde_yaml::from_str(
        &std::fs::read_to_string(arg(&args, "config",
            "config/sim/wmnf_sim.yaml")).expect("config"))
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
    };
    let mode_name = arg(&args, "mode", "lb_energy");
    let out_path = arg(&args, "out", "fastsim_summary.json");
    let days = p.days;
    let seed = p.seed;

    let t0 = std::time::Instant::now();
    let mut sim = Sim::new(cfg, topo, routes, weather, p);
    sim.run();
    let wall = t0.elapsed().as_secs_f64();

    // ── summary (schema mirrors mesh_sim.py) ─────────────────────────────────
    let mut per_node = serde_json::Map::new();
    let mut sent_total = 0u64;
    let mut delivered_total = 0u64;
    for n in &sim.nodes {
        per_node.insert(n.name.clone(), json!({
            "tx": n.stats.tx, "rx_ok": n.stats.rx_ok,
            "collisions": n.stats.collisions,
            "dup_suppressed": n.stats.dup_suppressed,
            "tx_airtime_s": round2(n.stats.tx_airtime_s),
            "energy_tx_wh": round5(n.stats.energy_tx_wh),
            "deaths": n.stats.deaths,
            "solar_wh": round2(n.stats.solar_wh),
            "final_soc": round4(n.soc_wh / n.cap_wh),
            "power": if n.grid { "grid" } else if n.solar { "solar" }
                     else { "battery" },
        }));
    }
    let mut per_origin = serde_json::Map::new();
    for (origin, (sent, delivered, lats)) in &sim.agg {
        sent_total += sent;
        delivered_total += delivered;
        let mut l = lats.clone();
        l.sort_by(f64::total_cmp);
        let q = |p: f64| if l.is_empty() { serde_json::Value::Null }
            else { json!(round2(l[((l.len() - 1) as f64 * p) as usize])) };
        per_origin.insert(sim.nodes[*origin as usize].name.clone(), json!({
            "sent": sent, "delivered": delivered,
            "pdr": if *sent > 0 { json!(round4(*delivered as f64 / *sent as f64)) }
                   else { serde_json::Value::Null },
            "latency_p50_s": q(0.5), "latency_p95_s": q(0.95),
        }));
    }

    let solar_nodes: Vec<&Node> = sim.nodes.iter().filter(|n| n.solar).collect();
    let socs: Vec<f64> = solar_nodes.iter().map(|n| n.soc_wh / n.cap_wh).collect();
    let mean_soc = socs.iter().sum::<f64>() / socs.len().max(1) as f64;
    let soc_std = (socs.iter().map(|x| (x - mean_soc).powi(2)).sum::<f64>()
        / socs.len().max(1) as f64).sqrt();
    let mut relay_e: Vec<f64> = solar_nodes.iter()
        .map(|n| n.stats.energy_tx_wh).collect();
    relay_e.sort_by(f64::total_cmp);
    let gini = if relay_e.is_empty() || relay_e.iter().sum::<f64>() <= 0.0 {
        serde_json::Value::Null
    } else {
        let n = relay_e.len() as f64;
        let s: f64 = relay_e.iter().sum();
        let num: f64 = relay_e.iter().enumerate()
            .map(|(i, x)| (2.0 * (i as f64 + 1.0) - n - 1.0) * x)
            .sum();
        json!(round4(num / (n * s)))
    };
    let deaths_total: u64 = solar_nodes.iter().map(|n| n.stats.deaths).sum();
    let mean_duty = solar_nodes.iter().map(|n| n.duty).sum::<f64>()
        / solar_nodes.len().max(1) as f64;

    let soc_series: Vec<serde_json::Value> = sim.soc_series.iter()
        .map(|(d, p10, p50, p90, std)| json!([round2(*d), round4(*p10),
            round4(*p50), round4(*p90), round4(*std)]))
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

    let mut sos_lats: Vec<f64> = sim.sos_incidents.values()
        .filter(|i| i.2).map(|i| i.3).collect();
    sos_lats.sort_by(f64::total_cmp);
    let mean_tries = sim.sos_incidents.values().map(|i| i.1 as f64).sum::<f64>()
        / sim.sos_incidents.len().max(1) as f64;

    let dur = days * 86400.0;
    let summary = json!({
        "engine": "fastsim (rust)",
        "wall_seconds": round2(wall),
        "mode": mode_name,
        "days": days,
        "seed": seed,
        "start_date": "from-weather-file",
        "n_nodes": sim.nodes.len(),
        "n_renters": sim.walkers.len(),
        "channel_utilization": round5(sim.total_airtime_s / dur),
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
            "relay_energy_gini": gini,
            "soc_series_6h": soc_series,
        },
        "link_health": link_rows,
        "per_origin": per_origin,
        "per_node": per_node,
    });
    std::fs::write(&out_path, serde_json::to_string_pretty(&summary).unwrap())
        .expect("write summary");
    eprintln!("fastsim: {} days of {} in {:.1}s ({:.0} sim-days/s) -> {}",
              days, mode_name, wall, days / wall.max(1e-9), out_path);
}

fn round2(x: f64) -> f64 { (x * 100.0).round() / 100.0 }
fn round4(x: f64) -> f64 { (x * 10000.0).round() / 10000.0 }
fn round5(x: f64) -> f64 { (x * 100000.0).round() / 100000.0 }

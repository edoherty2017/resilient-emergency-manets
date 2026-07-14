#!/usr/bin/env python3
"""Decision-oriented metrics from the corrected release.

Raw counts (death events, packets) answer "what happened in the simulator."
These metrics answer the questions a SAR planner would actually ask —
computed per mode across all seeds of a corrected release:

  SOS response      p50/p95/max distress latency, delivery rate, mean tries
  Site availability fleet availability %, site-years dark, unique sites that
                    ever died, sites below 90% availability (chronic dark spots)
  Winter severity   days with >=10% of the solar fleet depleted (p10 SOC <= 5%)
  Efficiency        TX energy per delivered packet (mWh/delivery)
  Channel truth     receiver-local busy p95 (physical occupancy), offered air
  Rental service    walker-days served / starved

All values remain MODEL-ONLY and uncalibrated; the point is asking better
questions of the model, not claiming field truth.

Run: .venv/bin/python scripts/build_meaningful_metrics.py \
       [--release artifacts/sim/corrected/release_v1]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ["flood", "min_hop", "etx", "energy_aware", "lb_energy",
         "duty_sync", "duty_adaptive", "rotate_lb", "selective_duty"]


def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def build(release: Path) -> dict:
    per_mode: dict[str, dict] = {}
    for mode in MODES:
        files = sorted(release.glob(f"fs_{mode}_s*.json"))
        if not files:
            continue
        sos_lat: list[float] = []
        sos_sent = sos_del = 0
        tries: list[float] = []
        avail: list[float] = []
        dead_site_years: list[float] = []
        unique_died: list[int] = []
        chronic: list[int] = []
        worst_avail: list[float] = []
        mwh_per_delivery: list[float] = []
        rx_busy_p95: list[float] = []
        offered: list[float] = []
        winter_days: list[int] = []
        served: list[int] = []
        starved: list[int] = []
        for f in files:
            d = json.loads(f.read_text())
            s = d.get("sos", {}) or {}
            sos_lat += s.get("latencies_s", [])
            sos_sent += s.get("sent", 0)
            sos_del += s.get("delivered", 0)
            if s.get("mean_tries") is not None:
                tries.append(s["mean_tries"])
            fe = d["fleet_energy"]
            avail.append(fe["availability"])
            dead_site_years.append(fe["dead_time_s_total"] / 86400.0 / 365.0)
            unique_died.append(fe["unique_nodes_died"])
            solar = {n: v for n, v in d["per_node"].items()
                     if v.get("power") == "solar"}
            chronic.append(sum(1 for v in solar.values()
                               if v["availability"] < 0.90))
            worst_avail.append(min((v["availability"] for v in solar.values()),
                                   default=1.0))
            total_tx_wh = sum(v["energy_tx_wh"] for v in d["per_node"].values())
            delivered_pkts = d["packets_originated"] * d["pdr_overall"]
            mwh_per_delivery.append(1000.0 * total_tx_wh / max(delivered_pkts, 1))
            occ = d.get("channel_occupancy", {}) or {}
            if occ.get("receiver_busy_ratio_p95") is not None:
                rx_busy_p95.append(occ["receiver_busy_ratio_p95"])
            offered.append(d.get("aggregate_offered_airtime_ratio",
                                 d.get("channel_utilization", 0.0)))
            # winter severity: 6-h samples where the 10th-percentile solar SOC
            # is essentially empty -> >=10% of the fleet is depleted
            samples = fe.get("soc_series_6h", [])
            bad = {int(row[0]) for row in samples if row[1] <= 0.05}
            winter_days.append(len(bad))
            r = d.get("rental") or {}
            served.append(r.get("served", 0))
            starved.append(r.get("starved", 0))
        sos_lat.sort()
        per_mode[mode] = {
            "sos": {
                "delivery_rate": round(sos_del / max(sos_sent, 1), 4),
                "latency_p50_s": round(quantile(sos_lat, 0.50), 2),
                "latency_p95_s": round(quantile(sos_lat, 0.95), 2),
                "latency_max_s": round(sos_lat[-1], 2) if sos_lat else None,
                "mean_tries": round(statistics.mean(tries), 2) if tries else None,
                "incidents": sos_sent,
            },
            "availability": {
                "fleet_availability": round(statistics.mean(avail), 4),
                "site_years_dark_per_year": round(
                    statistics.mean(dead_site_years), 2),
                "unique_sites_ever_died": round(statistics.mean(unique_died), 1),
                "sites_below_90pct": round(statistics.mean(chronic), 1),
                "worst_site_availability": round(
                    statistics.mean(worst_avail), 4),
            },
            "winter": {
                "days_fleet_p10_depleted": round(
                    statistics.mean(winter_days), 1),
            },
            "efficiency": {
                "tx_mwh_per_delivered_packet": round(
                    statistics.mean(mwh_per_delivery), 4),
            },
            "channel": {
                "receiver_busy_p95": round(statistics.mean(rx_busy_p95), 5)
                if rx_busy_p95 else None,
                "offered_airtime": round(statistics.mean(offered), 4),
            },
            "rental": {
                "walker_days_served": round(statistics.mean(served), 0),
                "walker_days_starved": round(statistics.mean(starved), 0),
            },
            "n_seeds": len(files),
        }
    return {
        "claim_status": "MODEL_ONLY_uncalibrated",
        "definitions": {
            "fleet_availability": "1 - (solar-node unavailable time / total solar node-time)",
            "site_years_dark_per_year": "total solar dead time per simulated year, in site-years",
            "sites_below_90pct": "solar sites individually available <90% of the year (chronic dark spots)",
            "days_fleet_p10_depleted": "days where >=10% of the solar fleet was at <=5% charge",
            "tx_mwh_per_delivered_packet": "fleet transmit energy divided by delivered packets",
            "receiver_busy_p95": "95th-percentile per-site physical RF busy fraction (interval union), NOT summed airtime",
        },
        "modes": per_mode,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", default="artifacts/sim/corrected/release_v1")
    a = ap.parse_args(argv)
    rel = ROOT / a.release if not Path(a.release).is_absolute() else Path(a.release)
    out = build(rel)
    (rel / "meaningful_metrics.json").write_text(
        json.dumps(out, indent=2) + "\n")
    print(f"{'mode':<15}{'SOS%':>6}{'p95 lat':>9}{'avail%':>8}"
          f"{'site-yr dark':>13}{'<90% sites':>11}{'winter days':>12}"
          f"{'mWh/pkt':>9}")
    for m, v in out["modes"].items():
        s, av, w, e = v["sos"], v["availability"], v["winter"], v["efficiency"]
        print(f"{m:<15}{100*s['delivery_rate']:>6.1f}{s['latency_p95_s']:>9}"
              f"{100*av['fleet_availability']:>8.2f}"
              f"{av['site_years_dark_per_year']:>13}"
              f"{av['sites_below_90pct']:>11}"
              f"{w['days_fleet_p10_depleted']:>12}"
              f"{e['tx_mwh_per_delivered_packet']:>9}")
    print(f"wrote {rel / 'meaningful_metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

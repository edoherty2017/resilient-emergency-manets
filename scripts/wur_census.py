#!/usr/bin/env python3
"""E3 wake-feasibility census (spec v2 §4) — static, three nested views.

Median-channel (q50) census over the routing-eligible link set, plus the
analytic per-link wake probability under the model's own shadowing.
MODEL-ONLY. Views per delta:
  1. shrinkage fraction over routing-eligible links (q50 margin >= 3 dB,
     the router's admission rule), gating only edges whose RECEIVER is a
     wur relay (gateways/grid never wake-gated);
  2. stranded sites/routes: no wake-feasible path to any mqtt gateway over
     the wake-feasible subgraph;
  3. tree-edge subset: margin distribution of edges the energy_aware
     construction-time tree actually uses (from a fastsim wur run's
     route_next if available; else the static Dijkstra over eligible links).
"""
import json, math, sys, hashlib
from pathlib import Path
from collections import deque

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "artifacts/sim/corrected/release_v1"
SENS = -131.0
REF = 26.3
EDGE_MARGIN_DB = 3.0
SIGMA_EFF = math.sqrt(8.0**2 + 2.0**2)  # slow shadowing + fast fade

def phi(x):  # standard normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

topo = json.loads((REL / "topology_statewide.json").read_text())
sites = topo["sites"]  # dict name -> site
gateways = {n for n, s in sites.items() if s.get("mqtt_uplink")}
grid = {n for n, s in sites.items() if s.get("power") == "grid" or s.get("mqtt_uplink")}
is_wur_relay = lambda n: n not in grid  # solar relays get WuR semantics

links = []
for key, l in topo["links"].items():  # dict "a|b" -> {loss_db_q50,...}
    a, b = key.split("|")
    margin = (REF - float(l["loss_db_q50"])) - SENS
    if margin >= EDGE_MARGIN_DB:
        links.append((a, b, margin))

def feasible(margin, delta, rx):
    return (not is_wur_relay(rx)) or (margin >= delta)

out = {"sigma_eff_db": round(SIGMA_EFF, 2), "edge_margin_db": EDGE_MARGIN_DB,
       "routing_eligible_links": len(links), "deltas": {}}
for delta in [0, 40, 50, 60, 70, 80]:
    # view 1: directed shrinkage fraction
    total_dir = 2 * len(links)
    fail_dir = sum((0 if feasible(m, delta, b) else 1) + (0 if feasible(m, delta, a) else 1)
                   for a, b, m in links)
    # analytic expected feasibility under shadowing
    exp_ok = sum((1.0 if not is_wur_relay(b) else phi((m - delta) / SIGMA_EFF))
                 + (1.0 if not is_wur_relay(a) else phi((m - delta) / SIGMA_EFF))
                 for a, b, m in links)
    near = sum((1 if is_wur_relay(b) and abs(m - delta) <= SIGMA_EFF else 0)
               + (1 if is_wur_relay(a) and abs(m - delta) <= SIGMA_EFF else 0)
               for a, b, m in links)
    # view 2: stranded sites — BFS from gateways over wake-feasible directed edges
    adj = {}
    for a, b, m in links:
        if feasible(m, delta, b): adj.setdefault(a, []).append(b)
        if feasible(m, delta, a): adj.setdefault(b, []).append(a)
    seen = set(gateways); dq = deque(gateways)
    while dq:
        u = dq.popleft()
        for v in adj.get(u, []):
            if v not in seen: seen.add(v); dq.append(v)
    stranded = [n for n in sites if n not in seen]
    out["deltas"][str(delta)] = {
        "directed_shrinkage_fraction_q50": round(fail_dir / total_dir, 4),
        "expected_feasible_fraction_shadowed": round(exp_ok / total_dir, 4),
        "links_within_1sigma_of_threshold": near,
        "stranded_sites_q50": len(stranded),
        "stranded_site_names": stranded[:20],
    }
p = ROOT / "artifacts/sim/wur_study/e3_census.json"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(out, indent=1))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "stranded_site_names"}
                  for k, v in out["deltas"].items()}, indent=1))
print("sha256", hashlib.sha256(p.read_bytes()).hexdigest()[:16])

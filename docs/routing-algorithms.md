# Routing Algorithm Candidates — design, trade-offs, pre-registered expectations

Five algorithms, all implemented in `scripts/mesh_sim.py` (`--mode`), all
evaluated on the identical statewide topology (217 sites), identical traffic,
identical real-weather year (2025-07 → 2026-06), identical seed. Routed modes
share one mechanism — a gateway-rooted shortest-path tree (multi-source
Dijkstra from every live gateway, refreshed hourly or on any death/revival,
the way RPL/distance-vector protocols converge) — and differ **only in the
edge-cost function**, so differences in outcome are attributable to the cost
design, not implementation accidents.

Metrics: PDR, SOS delivery, channel utilization, network TX energy, and three
**drain-consistency** measures — final-SOC standard deviation, minimum SOC,
and the **Gini coefficient of relay energy** (0 = perfectly even burden,
1 = one node does everything) plus a 6-hourly fleet SOC series.

---

## 1. `flood` — Meshtastic managed flooding (baseline)

Every node rebroadcasts every new packet (hop-limited, SNR-scaled contention,
duplicate suppression). **Why it could be better:** no routing state at all —
no tree to go stale, no wrong choices possible; delivery uses *every* path
simultaneously, so it is maximally robust to node loss and mobility; it is
what stock Meshtastic ships. **Why it could be worse:** cost grows with node
count — at 262 nodes it demanded 136% of the channel at full traffic cadence
(saturation), and every packet drains *all* nodes in earshot, so fleet energy
is worst-case by construction. Winter: dying relays don't hurt routing (there
is none) but drain everywhere accelerates the fleet-wide collapse.

## 2. `min_hop` — shortest hop count (classic distance-vector)

Edge cost = 1. **Better:** minimal latency and airtime per packet; trivially
simple; well understood. **Worse:** hop count ignores link quality — it
happily picks one long marginal 8 km link over two solid 4 km links, so
retries/losses concentrate exactly where the margin is thinnest; and it
ignores energy entirely — the topologically central nodes (chokepoints like
jewell_relay, lakes_hut) carry everything until they die, then the tree
re-converges onto the *next* chokepoint and kills it too. Expect: decent PDR
in summer, high relay-energy Gini, serial chokepoint deaths in shoulder
season.

## 3. `etx` — expected transmission count (De Couto et al., classic WMN metric)

Edge cost = 1/P(success), from the link's fade margin through the calibrated
shadowing model. **Better:** maximizes end-to-end delivery probability per
transmission — the throughput-optimal classic; avoids marginal links that
min_hop loves. **Worse:** still energy-blind — the *best radio path* is
static, so the same well-placed nodes relay forever; good links get used
*because* they're good until their batteries object. Expect: highest summer
PDR of the routed modes, but Gini nearly as bad as min_hop and the same
serial-death pattern in November.

## 4. `energy_aware` — runway-weighted energy cost (our v1)

Edge cost = (TX energy × 1/P) × **scarcity(relay)**, where scarcity is the
relay's *energy runway* (battery + expected solar until midnight, from the
per-site horizon/canopy model) — poor nodes are expensive, rich nodes cheap.
**Better:** routes bend away from struggling nodes *before* they die; the
solar forecast means a node that will recharge this afternoon is spent freely
while one facing a cloudy week is spared. **Worse — and this is the failure
the user called out:** it is *greedy and memoryless*. All traffic moves to
the currently-cheapest path **simultaneously**, drains it, then stampedes to
the next path. The fleet oscillates between a few good corridors; drain is
smoother than etx but still herd-shaped, and the same few nodes near
gateways stay overworked because scarcity only reacts *after* their state
degrades. Expect: fewer deaths than etx, moderate Gini, visible sawtooth in
the SOC series.

## 5. `lb_energy` — self-monitoring load balancer (the new one)

`energy_aware` cost **× (1 + 2·overuse) × (1 + 1.5·death_score)** where:

- **overuse** = the node's relay-burden EWMA (decays 0.5%/forward) divided by
  the *fleet median* burden, minus 1 — a node doing more than its share gets
  progressively expensive **even while its battery still looks fine**. This
  is the algorithm noticing "I keep leaning on the same nodes" *from its own
  behavior*, not from the damage.
- **death_score** = decaying memory of the node's deaths (×0.7 per rebuild,
  +1 per death) — a node that keeps dying faster than the rest is
  structurally penalized, so the tree stops re-converging onto known-fragile
  relays after every revival.
- Tree refresh is hourly with event-driven rebuild on death/revival;
  the EWMA gives hysteresis, so paths rotate on the hours-scale rather than
  flapping per packet.

**Better:** explicitly equalizes drain (min-max fairness) — expect the lowest
final-SOC σ, lowest relay-energy Gini, fewest total deaths, longest time to
first winter outage; the rotation also pre-positions capacity for SOS
bursts. **Worse:** it deliberately routes *away* from the radio-optimal path,
paying more transmissions (slightly lower PDR / higher airtime than etx in
easy conditions); the penalty terms are two more knobs that could
oscillate if set aggressively (mitigated by EWMA + hourly refresh, but the
year run is the test); and fleet-median normalization needs global knowledge
— fine in simulation and for a Pi-side routing daemon with MQTT telemetry,
harder fully in-network.

---

## Pre-registered expectations (to be checked against the year runs)

| metric (year, statewide) | flood | min_hop | etx | energy_aware | lb_energy |
|---|---|---|---|---|---|
| PDR (annual) | mid | mid-high | **highest** | high | high |
| channel util | **saturating** | low | low | low | low+ε |
| TX energy | **worst** | low | low | low | low+ε |
| relay Gini | n/a (uniform-ish) | worst | bad | mid | **best** |
| final-SOC σ | high (uniform drain but high) | high | high | mid | **lowest** |
| solar deaths | most | serial chokepoints | serial | fewer | **fewest** |
| winter SOS availability | worst | poor | poor | better | **best** |

If lb_energy does NOT win the fairness metrics, the penalty design is wrong —
that is a falsifiable claim, not a hope. All numbers land in
`artifacts/sim/algo_year/` with `build_algo_comparison.py` producing the
table and SOC-dispersion figure.

## Traffic model (v2 — realistic message classes)

- **SOS → SAR HQ**: ~0.5 incidents/day statewide (≈NH F&G's ~180 missions/yr),
  MAC-prioritized (PIFS-like short backoff, relays forward first, originator
  triple-sends), and **flooded in every mode** — the Oct storm-week A/B showed
  a routed-only SOS dying with a broken tree while flood delivered 7/7; SOS
  airtime is negligible, so redundancy wins for exactly this packet class
  (hybrid design). Delivery = any gateway (backhaul to SAR dispatch).
- **Hiker↔hiker DMs** (`msg`): partner pairs on the same route text every
  30–60 min while walking; flooded with hop limit (Meshtastic DM behavior);
  delivered when the partner hears it.
- **Hiker→family** (`fam`): every 45–90 min while walking; routed to any
  MQTT gateway → the outside world.
- **Position/telemetry**: routed per the mode under test.
- Hiker↔hiker PHY fixed: ground-level model (FSPL + 20 dB clutter +
  12 dB/km beyond 1.5 km, hard gate 8 km) — the old flat model let hikers
  hear each other across the state.

**Caveats:** energy constants remain BENCH-CALIBRATE; the routed modes assume
a routing layer above stock Meshtastic (decision G1); ERA5 kt is
valley-blended (sunnier than summit truth), so winter results are, if
anything, optimistic.

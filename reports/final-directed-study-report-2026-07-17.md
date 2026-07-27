> **SUPERSEDED (2026-07-26):** this draft is retained for history only. The current report is `final-directed-study-report-2026-07-26.pdf`; see `ADVISOR-GUIDE.md` at the repo root.

# Resilient Emergency MANETs for Wilderness Safety — Directed Study Final Report

**Date:** 2026-07-17  
**Scope:** New Hampshire only (Brenta/Italy descoped)  
**Claim policy:** every quantitative statement in this report is either (a) an
artifact-backed measurement or software check reproduced on the current code, or
(b) a **MODEL-ONLY** simulation result explicitly labeled as such. Withdrawn
pre-audit statistics are not cited here; they are quarantined under
`WITHDRAWN-DO-NOT-CITE/` with a manifest explaining each withdrawal. The
authoritative defect index is `docs/audit-correction-ledger-2026-07-13.md`.

## Executive summary

This directed study set out to empirically validate a propagation model
(AIRMap) for LoRa/Meshtastic mesh networking in the White Mountains. The
controlled empirical dataset that plan required was **not collected**: Trial 1
(2026-05-23, Mt. Washington) was a systems shakedown that produced zero
calibration-eligible observations, and the controlled Trial 2 has not yet run
(it is scheduled for 2026-07-18/19; §7). The project's completed central
contribution is instead a **purpose-built, two-engine (Python/Rust)
discrete-event simulation framework** for year-scale energy and reliability
analysis of a Meshtastic-style wilderness mesh, together with a terrain-aware
(Longley–Rice ITM) planning layer, a hardened field-data pipeline, and a
preregistration-ready protocol (freeze scheduled before collection) that makes
the missing empirical validation executable.

The principal new technical insight (§5.3): **in this model, network
survivability is governed by the idle-listening/duty-cycling policy, not by the
choice of routing algorithm.** Across five materially different always-on
routing modes, annual energy-depletion events vary by less than 0.3%
(29,164–29,234 per year), while changing the duty-cycling policy changes
depletion events by a factor of ≈5.5–24× (down to 1,217–5,311 per year) at a
quantified cost in delivery ratio and SOS latency. Idle listening dominates the
energy budget; routing choice redistributes a comparatively small remainder.
This is a MODEL-ONLY result awaiting field calibration; it is robust across
seeds, and — if it survives calibration — would reorder the design priorities
for solar-powered mesh infrastructure: duty/wake architecture first, routing
second.

**Abbreviations.** PDR: packet delivery ratio · FSPL: free-space path loss ·
ITM: Irregular Terrain Model (Longley–Rice) · ETX: expected transmission count
· CAD: channel-activity detection (LoRa preamble sniffing) · DIFS/backoff:
carrier-sense wait times · EWMA: exponentially weighted moving average ·
q50/q90: 50th/90th-percentile model quantiles · SOS p95: 95th-percentile
latency of emergency messages.

## 1. Original objectives and what changed

The original plan (preserved unedited in `docs/execution-roadmap-weekly.md`)
had five success criteria. Their outcomes:

| # | Original objective | Outcome |
|---|---|---|
| 1 | Architecture and design documentation | Delivered (`docs/system-architecture.md` and related docs) |
| 2 | ≥2,500 empirical field points | **Not met.** Trial 1 produced 0 calibration-eligible observations (§6.1). The Trial 2 protocol proposes replacing the unqualified point count with a per-stratum opportunity requirement (≥40 scheduled opportunities per primary stratum) — a proposed amendment for advisor review, since a raw packet count at a 30 s cadence was infeasible (5–8.3 h per stratum) and says nothing about stratum coverage |
| 3 | AIRMap calibration files | **Not produced** — blocked on controlled data; the gated pipeline that will produce them is built and tested |
| 4 | 10–15 page validation report (RMSE/MAE, predictive-vs-actual heatmaps, infrastructure failure matrix) | **Deferred, not abandoned.** All builder tooling exists (`error_quantifier.py`, `build_coverage_heatmap.py`, `build_failure_matrix.py`); the report becomes producible immediately after Trial 2 (§7) |
| 5 | Large-scale simulation as optional future appendix | **Inverted:** simulation became the central completed contribution (§2–§5) |

Additional scope changes: the study area is New Hampshire only (the
contemplated Brenta/Italy deployment is dead and quarantined); the planned
Tuckerman/Huntington trail campaigns were replaced by the Ammonoosuc–Jewell
system; and the defensible scientific claim narrowed from "a validated
emergency-network design" to "an uncalibrated planning and sensitivity
framework plus a field-acquisition system awaiting controlled empirical
validation."

## 2. Simulator architecture

Two independent implementations of one model:

- **`scripts/mesh_sim.py`** — SimPy reference engine; emits detailed event
  traces; also hosts two exploratory Python-only learned modes (q_routing,
  rl_duty).
- **`fastsim/`** (Rust) — summary-only event engine for long horizons and
  multi-seed sweeps; implements the nine shared modes (flood, min_hop, etx,
  energy_aware, lb_energy, duty_sync, duty_adaptive, rotate_lb,
  selective_duty); validates all inputs before start and writes output
  atomically; time-ordered binary heap with deterministic tie-breaking.

Randomness is keyed per phenomenon and entity (traffic, incidents, MAC
backoff, fading, mobility do not consume one another's draws), so workloads
are comparable across algorithms and a congested MAC cannot alter the offered
load.

**Propagation/reception.** Received power = 26.30 dBm reference (24.15 dBm TX
EIRP + 2.15 dBi RX antenna gain + assumed 0 dB feed loss — the reference is
*not* EIRP) minus a link-specific median loss, plus Gauss–Markov slow
shadowing (σ = 8 dB, 30 s coherence) and a 2 dB per-packet fast term. Median
loss: fixed↔fixed links use precomputed Longley–Rice ITM q50 over USGS 3DEP
terrain; mobile↔fixed uses time-interpolated precomputed route-loss tables;
mobile↔mobile uses an explicit heuristic (FSPL + 20 dB clutter + 12 dB/km
beyond 1.5 km, 8 km cutoff) that is a workload model, not a fitted law.
Reception requires RSSI ≥ −131 dBm (an assumed, datasheet-derived threshold —
bench-unverified) and SNR ≥ −17.5 dB against a −114.0 dBm noise floor
(−174 + 10·log₁₀(250 kHz) + 6 dB NF). All propagation constants are
uncalibrated planning values pending Trial 2.

**MAC/airtime.** LoRa SF11 / 250 kHz / CR 4/5 airtime; carrier-sense
threshold −124 dBm; 40 ms slots; random DIFS/backoff; priority for SOS;
SNR-scaled flood contention; duplicate suppression; frozen-overlap collision
resolution (insertion-order independent); 6 dB co-SF capture; half-duplex
senders. Duty modes model per-second CAD preamble sampling requiring ≥2
preamble symbols of overlap. The engine separates *aggregate offered airtime*
(additive, can exceed 1) from *per-site physical occupancy* (interval union) —
conflating these invalidated all pre-audit "channel utilization" numbers.

**Routing/duty policies.** Routed modes build a multi-source shortest-path
tree rooted at live gateways with per-mode edge costs (hop count; ETX from
modeled success probability; energy-aware battery/forecast scarcity;
load-balanced variants adding forwarding-EWMA and death-score penalties). Duty
assignments: uniform 5% (duty_sync); energy-runway-adaptive 2–25%
(duty_adaptive); route-tree-awake (rotate_lb); backbone+articulation-awake
(selective_duty). Routing never sees realized future weather, only monthly
climatology.

**Energy/solar/weather.** 37 Wh portable batteries (85% usable); drain =
duty × listen + (1−duty) × light-sleep + GPS for mobile radios; incremental
TX charging; ordered energy segments so state changes never apply
retroactively; depletion/outage/revival state machine; 600 s packet TTL
(an explicit modeling assumption). Board currents (245 mA TX / 68 mA listen /
12 mA sleep / 25 mA GPS) are **BENCH-CALIBRATE placeholders**, not
measurements. Solar: NOAA sun position, Haurwitz clear-sky, clearness-index
direct/diffuse split, 48-azimuth DEM horizon shading, 0.15 canopy
transmittance below treeline, four-face 35° panels, 6 W relay panels at 75%
system efficiency. The weather series is a single Mt Washington-area
ERA5/Open-Meteo-derived daily series applied statewide — not site-specific.

**Mobility/logistics/traffic.** Timestamped trail routes with linear
interpolation; kiosk rental model (20 bays, tiered demand, charge-gated
checkout, nightly shuttle, explicit starvation counts); traffic = fixed-site
telemetry + position beacons + hiker messaging + synthetic SOS incidents with
logical duplicates at +30 s/+60 s and fresh-packet retries every 5 minutes
until a gateway ACK or the retry ceiling — the retry loop that produces the
SOS latency structure in §5.2. Traffic rates are scenario inputs, not
measured demand.

## 3. Why a purpose-built simulator rather than ns-3

This is an ex-post engineering rationale (no contemporaneous ns-3 selection
study exists in the repo), and it supports only a narrow claim.

**Advantages for this project.** The research variables are not primarily
packet-forwarding mechanics: they are terrain-indexed loss tables, daily
weather and solar horizon masks, battery death/revival, kiosk stock and
shuttle logistics, and route-popularity traffic — first-class objects in the
custom model but substantial custom work in any general framework. The
summary-only Rust engine runs year-scale multi-seed sweeps without writing
packet traces; keyed randomness gives paired workloads across algorithms; the
model natively reports the project's decision metrics (SOS tail latency,
fleet availability, dark-site census, energy per delivered packet). Two
independently written engines create a real opportunity to catch coding
divergence (§4) — several semantic bugs were in fact found this way.

**Limitations and ns-3's proper role.** The custom simulator has far less
external validation and protocol depth than ns-3: it abstracts the PHY,
carrier sensing, capture, CAD timing, buffering, retransmission, clock drift,
and firmware queues, and shared model assumptions can survive in both engines.
It does not prove compatibility with stock Meshtastic firmware. The
defensible division of labor: purpose-built model for NH planning and
sensitivity studies; controlled analytical cases, cross-engine tests, and
selected ns-3 or hardware-in-the-loop scenarios for MAC/protocol fidelity;
Trial 2 plus bench measurements for empirical calibration. Porting to ns-3
would not create field calibration.

## 4. Python/Rust cross-validation

Four distinct questions, answered separately. All evidence in this section
was regenerated on the current code (git HEAD `6e2e33f`) on 2026-07-17 and
archived — nothing here rests on unarchived prose claims.

**4.1 Software regressions.** `cargo test` at HEAD: **47 unit tests + 3
integration tests, all passing** (0 failed/ignored).

**4.2 Cross-process reproducibility.** Four independent runs of the Rust
engine (min_hop, 1.3 days, seed 4242, the hash-locked release_v1 inputs)
produced byte-identical 419,738-byte outputs, SHA-256
`9d182b0d75cb…987c66`. Archived with command line and engine hash in
`artifacts/sim/corrected/repro_check_2026-07-17/repro_manifest.json`. (An
earlier equivalent check was recorded only in report prose at a previous
engine commit; this one supersedes it with an artifact.)

**4.3 Cross-engine agreement (micro-scenario).** The two independently
implemented engines were compared on the shared pilot micro-scenario
(`scripts/sim_micro_parity.py`: 3 days, seed 42, modes flood / duty_sync /
selective_duty) after reconciling seven semantic gaps in the Python engine
(route-track timing, duty-miss aggregation, selective-duty route-parent wake,
forward-event EWMA, duty-weighted TX energy, horizon truncation, initial duty
assignment). Re-run 2026-07-17 at HEAD and archived to
`artifacts/sim/corrected/micro_parity_2026-07-17.json`: **all six metrics
(PDR, offered airtime, deaths, duty-misses, SOS sent/delivered) pass every
pre-registered tolerance band in all three modes.** The maximum observed
discrepancies are 0.0045 absolute PDR (duty_sync; tolerance 0.03), 1.3%
relative offered airtime (selective_duty; tolerance 10%), and 0.3% relative
duty-misses (tolerance 15%); deaths and SOS counts agree exactly. For scale:
before the reconciliation work, selective-duty offered-airtime divergence was
13.9%. Three engine differences remain deferred and documented (ordered
energy-segment integration, the 600 s packet TTL, mid-frame availability
invalidation) — parity passes without them, and the CAD wake-phase RNG is
engine-specific by design, so cross-engine traces are not expected to be
byte-identical.

Historical context, retained but **withdrawn**: the old nine-pair statewide
comparison (pre-correction engines; files quarantined in
`WITHDRAWN-DO-NOT-CITE/artifacts/sim/xval/`) showed maxima of 0.0057 absolute
PDR (0.67% relative), 2.58% relative on offered airtime, 3.87% relative on
death events, and 15.6% relative on SOS counts. Those numbers describe
old-engine agreement only and must not be quoted as current validation.

**4.4 Statewide two-engine parity: not yet run.** The Python engine is too
slow for full-year multi-seed statewide sweeps (~48 s per pilot-day), so the
preregistered statewide parity (9 modes × seeds 42–46 against the tolerance
bands in `docs/sim-replacement-analysis-plan.md`) remains pending; the
micro-scenario comparison in §4.3 is the current substitute. Consequently, a
"current maximum statewide Python/Rust discrepancy" does not exist yet and is
not claimed. And in all cases: **engine agreement is a software check, not
empirical validation** — two implementations can agree on a wrong shared
assumption.

## 5. Main findings

### 5.1 What the field campaign actually established

1. **Trial 1 tested the collection system, not the propagation model.** The
   decoded receiver log contains 686 records from 50 decoded node IDs in the
   afternoon hike window and 764 RF observations from 41 source IDs (24 with
   GPS) in the pre-hike soak — two overlapping windows (18 IDs in both) on one
   receiver log, reconciled by `scripts/reconcile_trial1_counts.py` and
   re-verified 2026-07-17. **Zero** observations are calibration-eligible
   (`artifacts/airmap/live_trial/quality_gates.json`): no hop-count telemetry,
   a co-located forwarder contaminating RSSI/geometry pairs, and no controlled
   transmitter. This negative finding redesigned Trial 2 (controlled beacon,
   sequence-number denominators, `hops_away == 0` eligibility).
2. **The free-space coverage story did not survive terrain modeling
   (MODEL-ONLY).** Longley–Rice ITM over real USGS 3DEP terrain reverses the
   FSPL screen on the summit-facing links: Ammo relay→summit −132.2 dBm
   (below the assumed −131 dBm sensitivity; terrain up to 53 m above the
   direct ray) and Jewell relay→summit −118.7 dBm (marginal), while the
   below-treeline relay→gateway links stay strong in the terrain-only model
   (−76.6 / −74.1 dBm, geometric clear LOS; both paths run ≈100% below
   treeline and ITM excludes canopy loss, which must be budgeted separately). Worst-case FSPL-vs-ITM disagreement on a summit-facing link:
   **62.3 dB** on the path-loss basis (ITM q50 158.5 dB vs the in-artifact
   FSPL 96.2 dB — the like-for-like comparison); the RSSI-basis gap vs the
   historical screen is 59.3 dB (−72.9 → −132.2 dBm), ~3 dB smaller because
   the historical screen used its own link-budget reference rather than the
   corrected 26.30 dBm receiver-power reference. Collector-gap (Ammo Ravine) coverage at ITM q90: 100% of 84
   sampled points above raw sensitivity but only **45.2%** above the −100 dBm
   planning threshold — "the gap would have been covered" is downgraded to
   *marginal, unproven*. This ≈60 dB disagreement is directly measurable in a
   future Ammonoosuc field day; the 2026-07-18/19 field days test the same
   model class on Moosilauke/Kearsarge terrain, where ITM predicts a
   non-monotonic distance profile free-space physics cannot produce (§7).
3. **The current statewide planning topology fails its controlling screen
   (MODEL-ONLY).** With 52 uncalibrated short-link substitutions excluded,
   the −100 dBm planning screen (q90 modeled backhaul power; q50 trail
   path-loss arrays) reports 87 of 217 sites stranded and 15 of 25 routes
   below 85% modeled coverage; even restoring the 52 links leaves 53 sites
   stranded. Only the raw-sensitivity floor passes. An internal model
   failure, not measured coverage.

### 5.2 Corrected year-scale simulation results (MODEL-ONLY, single-engine)

Nine modes × seeds 42–46 × 365 days on the corrected Rust engine
(`artifacts/sim/corrected/release_v1/`, hash-locked inputs, t-based 95% CIs;
values are means across the five seeds — SOS counts are therefore
fractional):

| Mode | PDR | Deaths/yr | SOS delivered | SOS p95 | Fleet avail. | Sites <90% avail. | mWh/pkt |
|---|---|---|---|---|---|---|---|
| flood | 0.911 | 29,234 | 189.2/189.2 (100%) | 32 s | 53.5% | 118 | 1.44 |
| min_hop | 0.862 | 29,164 | 189.2/189.2 (100%) | 5 s | 53.7% | 118 | 0.42 |
| etx | 0.866 | 29,165 | 189.2/189.2 (100%) | 31 s | 53.7% | 118 | 0.42 |
| energy_aware | 0.866 | 29,164 | 189.2/189.2 (100%) | 4 s | 53.7% | 118 | 0.42 |
| lb_energy | 0.866 | 29,164 | 189.0/189.2 (99.9%) | 5 s | 53.7% | 118 | 0.42 |
| duty_sync | 0.728 | 1,217 | 179.2/189.2 (94.7%) | **35.0 min** | **96.5%** | **7** | 0.30 |
| duty_adaptive | 0.755 | 1,737 | 187.8/189.2 (99.3%) | 15.0 min | 94.7% | 13 | 0.40 |
| rotate_lb | 0.809 | 4,877 | 188.2/189.2 (99.5%) | **33 s** | 91.0% | 31 | 0.35 |
| selective_duty | 0.811 | 5,311 | 187.8/189.2 (99.3%) | **62 s** | 89.7% | 33 | 0.36 |

![Year-scale survivability by mode (MODEL-ONLY, uncalibrated; 9 modes × seeds 42–46, 365 days, `release_v1`). Left: annual battery-depletion events — the five always-on routing modes are indistinguishable (<0.3% spread) while duty policies cut depletions ≈5.5–24×. Right: fleet availability. Data: `corrected_stats.json`, `meaningful_metrics.json`.](figures/mode_survivability_tradeoff.png)

All PDR 95% CIs are below ±0.003, and the deaths-per-year CIs are similarly
tight (t-based 95% CI half-widths of roughly ±1–5 events on 1,200–29,000
annual events across all nine modes): given a seed the engine is
near-deterministic, so the dominant uncertainty is the uncalibrated model, not
seed noise. Two things raw counts hid: (a) always-on modes leave ~46% of
solar fleet-time dark — 118 of the topology's 159 solar sites are available
<90% of the year; (b) uniform duty_sync's 94.7% SOS delivery conceals a
35-minute p95 latency (deliveries ride the 5-minute retry loop), while the
backbone-awake duty modes hold 33–62 s p95 at ~99.3–99.5% delivery. Every
mode retains rare 1–2 h worst-case SOS incidents (retry-ceiling limit, shared
across modes). **No overall winner is declared**: delivery, availability, and
SOS tail latency still trade off, statewide two-engine parity is pending, and
the model is uncalibrated — the corrected model's role is to expose the
envelope, not pick the operating point.

### 5.3 The central insight: duty policy dominates survivability, not routing

The five always-on modes span materially different routing strategies —
flooding, shortest-hop, link-quality (ETX), energy-aware, and load-balanced
cost trees — yet their annual depletion events sit within a **0.3% band**
(29,164–29,234/yr), and four of five share identical availability (53.7%) and
dark-site counts (118). Switching the *duty/wake policy* while holding the
routing family fixed moves deaths by **≈5.5–24×** (to 1,217–5,311/yr) and
fleet availability from ~54% to 90–96%. The energy budget is dominated by
idle listening (68 mA modeled listen vs 12 mA sleep); what a node does while
*not* forwarding matters far more to survival than which tree its packets
follow. The design consequence, if the result survives calibration: solar
relay hardware and firmware should be selected around the wake/CAD
architecture, and routing sophistication is a second-order optimization. The
quantified cost side — PDR −0.05 to −0.14 versus the routed always-on modes
(−0.10 to −0.18 versus flood, the highest-PDR mode) plus the SOS-latency
structure in §5.2 — makes this an explicit, tunable trade rather than a free
win.
(MODEL-ONLY; the listen/sleep currents are bench-calibration placeholders,
which is precisely why the discharge bench test and Trial 2 are the critical
path.)

### 5.4 Process findings

Reproducibility defects were real and repairable (randomized map iteration
once made same-seed runs differ; outputs are now byte-identical, §4.2), and
the audit that produced this report's claim policy found implementation
mistakes and overstatements but no evidence of deliberate deception — the
full record is `docs/audit-correction-ledger-2026-07-13.md`, and every
withdrawn statistic now lives in `WITHDRAWN-DO-NOT-CITE/`.

## 6. Limitations

### 6.1 Empirical (the binding constraint)

- **No controlled Trial 2 dataset exists yet**; Trial 1 has zero
  calibration-grade observations, so the project has no held-out field
  estimate of RSSI error, PDR error, or shadow variance.
- Receiver sensitivity (−131 dBm), feed/body/foliage losses, board currents,
  cold-battery capacity, and panel yield are assumptions or placeholders, not
  measurements of the project hardware.
- Trial 2 will calibrate propagation and direct-link PDR on its sampled
  routes; it cannot by itself validate statewide traffic, routing, kiosk, or
  annual energy behavior (those need bench + hardware-in-the-loop work).

### 6.2 Modeling

- ITM q50 medians without a validated residual model; q90 route arrays absent.
- σ = 8 dB shadowing, 2 dB fast fade, capture threshold, mobile-mobile
  heuristic, synthetic traffic/SOS rates, and the 600 s TTL are assumptions.
- The MAC is not stock Meshtastic firmware; siting, permits, maintenance,
  security, and human factors are outside the simulation.
- One statewide weather series; solar geometry simplified.

### 6.3 Software and release

- Statewide two-engine parity is pending (§4.4); corrected-labeled artifacts
  outside `release_v1/` are stale relative to the repaired engine and marked
  accordingly (`artifacts/sim/corrected/README-STALE-WARNING.md`).
- release_v1 was generated 2026-07-14 from a dirty worktree (its manifest
  records this), and subsequent engine repairs mean the current HEAD engine
  would not reproduce it byte-for-byte; a full regeneration (release_v2) is in
  progress and incomplete. The §5.2 numbers are therefore bound to the
  archived release_v1 artifacts, not to the current binary.
- The release_v1 manifest's own parity note ("within tolerance except
  duty-mode offered_airtime") predates the 2026-07-17 parity re-run; the
  current, all-metrics-passing status is the archived
  `micro_parity_2026-07-17.json` (§4.3).
- A known minor provenance inconsistency inside release_v1 is disclosed:
  `release_manifest.json` records git HEAD `d37172c` while `input_hashes.txt`
  records `f5e83f0`; the four locked input hashes agree in both, and the
  aggregate's SHA-256 was independently recomputed and confirmed.
- Passing tests bound, but do not prove, the absence of defects; a dedicated
  PHY-abort model for mid-frame availability loss remains future work.

## 7. Future work: Trial 2 and the original validation deliverable

Trial 2 is scheduled for **2026-07-18/19** (two-person team) on **Mt
Moosilauke** (Gorge Brook out-and-back; rule-selected beacon at the treeline
break, 44.01708/−71.83777, ≈1352 m) and **Mt Kearsarge** (Winslow
out-and-back; mid-slope beacon at 43.38735/−71.85970, ≈771 m) — chosen over a
Mt Washington repeat to keep the weekend feasible while preserving
above-treeline strata (Moosilauke's summit is genuinely alpine) and a real
FSPL-vs-ITM discriminating test: the archived Moosilauke predictions are
non-monotonic with distance (−92 dBm at 0.5–1 km above treeline, −114 dBm in
the terrain-shadowed below-treeline band, recovering to −73 dBm at 2–4 km), a
shape free-space physics cannot produce. The ≈60 dB Ammonoosuc blocked-link
hypothesis (§5.1) is explicitly deferred to a future Washington field day.

Protocol (to be frozen the night before fieldwork): one rule-selected beacon
site per field day at a measured ≈1.2 m no-mast mount, 30 s cadence with
monotonic sequence numbers and position broadcasts, `hops_away == 0`
eligibility, time-window opportunity denominators with sequence numbers as
the audit check, ≥40 scheduled opportunities per primary stratum across
ascent/descent passes, underpowered strata retained as descriptive. The
prospective predictions are archived
(`artifacts/trial2/predictions_fieldday.csv` + manifest binding rule,
coordinates, heights, DEM hashes, git state); execution logistics in
`docs/trial2-weekend-execution-plan-2026-07-18.md`.

The analysis path: score the frozen predictions first (±12 dB RSSI / ±0.15
PDR preregistered engineering screens as diagnostics); recalibrate
parsimoniously on training passes only; evaluate on held-out passes/days;
then regenerate route-loss tables and rerun both engines from locked inputs.
That output feeds the original deliverable — the 10–15 page validation report
with out-of-sample RMSE/MAE (`error_quantifier.py`), predictive-vs-actual
heatmaps (`build_coverage_heatmap.py`), and the weather-joined infrastructure
failure matrix (`weather_enrich.py` → `build_failure_matrix.py`) — all
existing, tested tooling awaiting eligible data. Operational success is
defined as executing the frozen protocol and preserving the evidence, even if
a quality gate fails: a failed gate produces an evidence release, not a
calibration file. The layers Trial 2 cannot validate (MAC fidelity, board
currents, firmware behavior) are assigned to bench discharge tests and
hardware-in-the-loop follow-ups.

## Appendix A. Evidence map

| Claim area | Artifact |
|---|---|
| Corrected multi-seed results | `artifacts/sim/corrected/release_v1/{corrected_stats.json, meaningful_metrics.json, release_manifest.json, input_hashes.txt}` |
| Decision metrics | `artifacts/sim/corrected/release_v1/meaningful_metrics.json` (`scripts/build_meaningful_metrics.py`) |
| Micro-parity | `artifacts/sim/corrected/micro_parity_2026-07-17.json` (`scripts/sim_micro_parity.py`) |
| Reproducibility | `artifacts/sim/corrected/repro_check_2026-07-17/` |
| Test suite | `fastsim/` (`cargo test`), 47 + 3 passing at HEAD `6e2e33f` |
| ITM screens | `artifacts/itm/{itm_summary.json, relay_links_itm.csv, lora_airtime.json}` |
| Statewide screen | `artifacts/sim/coverage_audit_statewide.json` |
| Trial 1 status | `reports/project_report.md`; `artifacts/airmap/live_trial/quality_gates.json`; `scripts/reconcile_trial1_counts.py` |
| Trial 2 protocol | `docs/trial2-weekend-execution-plan-2026-07-18.md`, `docs/trial2-runbook.md`, `artifacts/trial2/{predictions_fieldday.csv, predictions_fieldday_manifest.json}` (`scripts/trial2_predictions_field.py`); historical Ammo/Jewell tables in `docs/trial2-preregistration.md` |
| Withdrawn material | `WITHDRAWN-DO-NOT-CITE/` (manifest in its README) |

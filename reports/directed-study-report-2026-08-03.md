# Resilient Emergency MANETs for Wilderness Safety — Directed Study Report

**Date:** 2026-08-03 (supersedes the 2026-07-17 draft)
**Scope:** New Hampshire only
**Code, data, and all cited artifacts:** <https://github.com/edoherty2017/resilient-emergency-manets-final>
## Executive summary

This directed study's completed contributions are fourfold. (1) A
purpose-built, **two-engine (Python/Rust) discrete-event simulation
framework** for year-scale energy and reliability analysis of a
Meshtastic-style wilderness mesh — cross-validated on a shared micro-scenario between independently written engines (§4; statewide parity pending), byte-reproducible, and released with hash-locked
inputs (release_v1: 9 modes × 5 seeds × 365 days). (2) A **terrain-aware
planning layer** (Longley–Rice ITM over USGS 3DEP) whose screens replaced
free-space analysis and materially changed the project's coverage
conclusions (§5.1). (3) A **preregistration-grade field methodology and
working acquisition system** — frozen prediction packs, hash-bound
registrations, eligibility gates, checksummed raw evidence — receiver side proven end-to-end in the field (§6). (4) The study's principal research insight
(§5.3): **in this model, network survivability is governed by the
idle-listening/duty-cycling policy, not by the choice of routing
algorithm.** Across five materially different always-on routing modes,
annual energy-depletion events vary by less than 0.3% (29,164–29,234 per
year), while changing the duty policy moves depletions ≈5.5–24× (to
1,217–5,311 per year) at a quantified cost in delivery ratio and SOS
latency. This is a MODEL-ONLY result awaiting field calibration; if it
survives, it reorders the design priorities for solar-powered mesh
infrastructure: duty/wake architecture first, routing second. Three
completed follow-on campaigns sharpen this result: a pre-registered
wake-up-radio study whose registered claims were both refuted — always-on
2 mA-class silicon dominates every wake-receiver variant on every axis,
including the physically ideal one (§5.4) — a ten-year ERA5 climate
campaign showing the duty-survival advantage holds in every weather year
(15–27×, §5.5), and a re-earn campaign that re-ran the previously
withdrawn claims on the corrected engine, restoring four claim families,
trimming two to their defensible cores, and converting the
reinforcement-learning results into a documented negative result (§5.5).

The empirical program was adjusted in flight, with every adjustment
registered before the data it affected was collected. Trial 1 (2026-05-23,
Mt. Washington) served as a systems shakedown; Trial 2 ran as a field
campaign of four field days plus a fifth registered siting (2026-07-18 to
2026-07-26), re-planned after **the beacon node's hardware failed** (its
internal battery would not charge, then its USB-C port broke). The
campaign's final day (Pack Monadnock, 2026-07-26) executed the receiver-side protocol end-to-end — radio logging all day, 1 Hz GPS, raw evidence preserved with checksums — and produced two quantified field findings that measure the failure modes the controlled-beacon design exists to defeat (§6.6): opportunistic public-mesh validation fails on transmit-opportunity
starvation (measured station cadence: 0–4 packets/hour) and on hop ambiguity (measured: no origin-decoded frame was a direct reception), alongside a
systems observation of multi-hop delivery from stations 86–88 km distant.

What the adjusted campaign could not produce is the controlled calibration
dataset: 0 of the ≥2,500 planned points exist (§1, §6.7), the registered
contact predictions scored no confirmations in either provenance tier
(with nulls that hold only trivially under the same censoring, §6.5), and
the beacon prediction packs remain frozen and unscored. Closing that gap
is a small, fully specified step — a replacement beacon board (≈$25) and
one two-radio field day under the already-frozen protocol (§8).

**Abbreviations.** PDR: packet delivery ratio · FSPL: free-space path loss ·
ITM: Irregular Terrain Model (Longley–Rice) · ETX: expected transmission
count · CAD: channel-activity detection · EWMA: exponentially weighted moving
average · q50/q90: 50th/90th-percentile model quantiles · SOS p95:
95th-percentile latency of emergency messages.

## 1. Original objectives and what changed

The original plan (preserved unedited in `docs/execution-roadmap-weekly.md`)
had five success criteria. Their outcomes:

| # | Original objective | Outcome |
|---|---|---|
| 1 | Architecture and design documentation | Delivered (`docs/system-architecture.md` and related docs) |
| 2 | ≥2,500 empirical field points | **Not met — 0 calibration-grade points.** Trial 1 produced 0 calibration-eligible observations (§5.1). Trial 2's four field days (plus a fifth registered siting, §6.4) were ended by beacon hardware failure before any controlled link could run; the campaign's measured findings (§6.6) quantify why no opportunistic substitute exists. The Trial 2 protocol proposes replacing the unqualified point count with a per-stratum opportunity requirement (≥40 scheduled opportunities per primary stratum) — a proposed amendment for advisor review |
| 3 | AIRMap calibration files | **Not produced** — blocked on controlled data; the gated pipeline that will produce them is built and tested |
| 4 | 10–15 page validation report (RMSE/MAE, heatmaps, failure matrix) | **Deferred, not abandoned.** All builder tooling exists (`error_quantifier.py`, `build_coverage_heatmap.py`, `build_failure_matrix.py`); producible immediately after a two-radio field day (§8) |
| 5 | Large-scale simulation as optional future appendix | **Inverted:** simulation became the central completed contribution (§2–§5) |

Amendments and their standing: the RSRP→ESP substitution is drafted but
unsigned (open decision A1) and is disclosed here rather than assumed; the
≥40-opportunity rule is proposed, not approved; the study area is New
Hampshire only; the planned Tuckerman/Huntington campaigns were replaced by
the Ammonoosuc–Jewell system and then, in the field week, by the
Moosilauke → Monadnock → Pack Monadnock sequence (§6, each step registered).
Radio operation across all field days used stock FCC-certified consumer
hardware in its as-marketed configuration (§6.5); production-deployment authorization deferred (§7).
The defensible scientific claim narrowed from "a validated emergency-network
design" to "an uncalibrated planning and sensitivity framework plus a
field-acquisition system awaiting controlled empirical validation."

## 2. Simulator architecture

Two independent implementations of one model:

- **`scripts/mesh_sim.py`** — SimPy reference engine; emits detailed event
  traces.
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
uncalibrated planning values pending a controlled field day.

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
load-balanced variants adding forwarding-EWMA and death-score penalties).
Duty assignments: uniform 5% (duty_sync); energy-runway-adaptive 2–25%
(duty_adaptive); route-tree-awake (rotate_lb); backbone+articulation-awake
(selective_duty). Routing never sees realized future weather, only monthly
climatology.

**Energy/solar/weather.** 37 Wh portable batteries (85% usable); drain =
duty × listen + (1−duty) × light-sleep + GPS for mobile radios; incremental
TX charging; ordered energy segments so state changes never apply
retroactively; depletion/outage/revival state machine; 600 s packet TTL (an
explicit engine constant, `fastsim/src/sim.rs`). Board currents (245 mA TX /
68 mA listen / 12 mA sleep / 25 mA GPS) are **BENCH-CALIBRATE placeholders**,
not measurements. Solar: NOAA sun position, Haurwitz clear-sky,
clearness-index direct/diffuse split, 48-azimuth DEM horizon shading, 0.15
canopy transmittance below treeline, four-face 35° panels, 6 W relay panels
at 75% system efficiency. The weather series is a single Mt Washington-area
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
and firmware queues, and shared model assumptions can survive in both
engines. It does not prove compatibility with stock Meshtastic firmware. The
defensible division of labor: purpose-built model for NH planning and
sensitivity studies; controlled analytical cases, cross-engine tests, and
selected ns-3 or hardware-in-the-loop scenarios for MAC/protocol fidelity; a
controlled field day plus bench measurements for empirical calibration.
Porting to ns-3 would not create field calibration.

## 4. Python/Rust cross-validation

Four distinct questions, answered separately. Evidence in this section was
regenerated on current code and archived — nothing rests on unarchived prose.

**4.1 Software regressions.** `cargo test` at HEAD `2225c26` on 2026-07-26:
**47 unit tests + 3 integration tests, all passing** (0 failed/ignored). Log
archived: `artifacts/sim/corrected/cargo_test_2026-07-26.log`.

**4.2 Cross-process reproducibility.** Four independent runs of the Rust
engine (min_hop, 1.3 days, seed 4242, the hash-locked release_v1 inputs)
produced byte-identical 419,738-byte outputs, SHA-256 `9d182b0d75cb…987c66`.
Archived with command line and engine hash in
`artifacts/sim/corrected/repro_check_2026-07-17/repro_manifest.json`.

**4.3 Cross-engine agreement (micro-scenario).** The two independently
implemented engines were compared on the shared pilot micro-scenario
(`scripts/sim_micro_parity.py`: 3 days, seed 42, modes flood / duty_sync /
selective_duty) after reconciling seven semantic gaps in the Python engine.
Re-run 2026-07-17 and archived to
`artifacts/sim/corrected/micro_parity_2026-07-17.json`: **all six metrics
(PDR, offered airtime, deaths, duty-misses, SOS sent/delivered) pass every
pre-registered tolerance band in all three modes.** Maximum observed
discrepancies: 0.0045 absolute PDR (duty_sync; tolerance 0.03), 1.3% relative
offered airtime (selective_duty; tolerance 10%), 0.3% relative duty-misses
(tolerance 15%); deaths and SOS counts agree exactly. Three engine
differences remain deferred and documented (ordered energy-segment
integration, the 600 s packet TTL, mid-frame availability invalidation) —
parity passes without them. Note: the release_v1 manifest's own parity remark
("within tolerance except duty-mode offered_airtime") predates this re-run;
the archived 2026-07-17 result supersedes it.

Historical context, retained but **withdrawn**: an older nine-pair statewide
comparison exists in quarantine
(`WITHDRAWN-DO-NOT-CITE/artifacts/sim/xval/`); it describes pre-correction
engines only and must not be quoted as current validation.

**4.4 Statewide two-engine parity: not yet run.** The Python engine is too
slow for full-year multi-seed statewide sweeps, so the preregistered
statewide parity (9 modes × seeds 42–46 against the tolerance bands in
`docs/sim-replacement-analysis-plan.md`) remains pending; the micro-scenario
comparison in §4.3 is the current substitute. A "current maximum statewide
Python/Rust discrepancy" does not exist yet and is not claimed. In all
cases: **engine agreement is a software check, not empirical validation** —
two implementations can agree on a wrong shared assumption.

## 5. Main findings

### 5.1 What Trial 1 established, and the model screens it motivated

1. **Trial 1 tested the collection system, not the propagation model.** The
   decoded receiver log contains 686 records from 50 decoded node IDs in the
   afternoon hike window and 764 RF observations from 41 source IDs (24 with
   GPS) in the pre-hike soak — two overlapping windows (18 IDs in both) on
   one receiver log, reconciled by `scripts/reconcile_trial1_counts.py`.
   **Zero** observations are calibration-eligible
   (`artifacts/airmap/live_trial/quality_gates.json`; note its top-level
   `"passed": true` reflects the relaxed operational ingest gate run with
   `require_calibration_grade=false` — the calibration gate itself records
   the failure, calibration-eligible rows 0 < 30): no hop-count telemetry, a
   co-located forwarder contaminating RSSI/geometry pairs, and no controlled
   transmitter. This negative finding designed Trial 2's protocol (controlled
   beacon, sequence-number denominators, `hops_away == 0` eligibility) — a design whose necessity the Trial 2 campaign then substantiated empirically (§6.6).
2. **The free-space coverage story did not survive terrain modeling
   (MODEL-ONLY; a model-to-model comparison, not a headline claim).**
   Longley–Rice ITM over real USGS 3DEP terrain reverses the FSPL screen on
   the summit-facing links: Ammo relay→summit −132.2 dBm (below the assumed
   −131 dBm sensitivity; terrain-blocked path) and Jewell relay→summit
   −118.7 dBm (marginal), while the below-treeline relay→gateway links stay
   strong in the terrain-only model (−76.6 / −74.1 dBm, geometric clear LOS;
   both paths run ≈100% below treeline and ITM excludes canopy loss, which
   must be budgeted separately). Worst-case FSPL-vs-ITM disagreement on a
   summit-facing link: **62.3 dB** on the path-loss basis (ITM q50 158.5 dB
   vs the in-artifact FSPL 96.2 dB). Collector-gap (Ammo Ravine) coverage at
   ITM q90: 100% of 84 sampled points above raw sensitivity but only
   **45.2%** above the −100 dBm planning threshold — "the gap would have
   been covered" is downgraded to *marginal, unproven*. This ≈60 dB
   model-to-model disagreement is directly measurable in a future
   Ammonoosuc field day.
3. **The current statewide planning topology fails its controlling screen
   (MODEL-ONLY; internal model-to-model check).** With 52 uncalibrated
   short-link substitutions excluded, the −100 dBm planning screen reports
   87 of 217 sites stranded and 15 of 25 routes below 85% modeled coverage;
   even restoring the 52 links leaves 53 sites stranded. Only the
   raw-sensitivity floor passes. An internal model failure, not measured
   coverage.

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

![Year-scale survivability by mode (MODEL-ONLY, uncalibrated; 9 modes × seeds 42–46, 365 days, `release_v1`). Left: annual battery-depletion events — the five always-on routing modes are indistinguishable (<0.3% spread) while duty policies cut depletions ≈5.5–24×. Right: fleet availability. Data: `release_v1/corrected_stats.json`, `release_v1/meaningful_metrics.json`.](figures/mode_survivability_tradeoff.png)

All PDR 95% CIs are below ±0.003 and the deaths-per-year CIs are similarly
tight: given a seed the engine is near-deterministic, so the dominant
uncertainty is the uncalibrated model, not seed noise. Two things raw counts
hid: (a) always-on modes leave ~46% of solar fleet-time dark — 118 of the
topology's 159 solar sites are available <90% of the year; (b) uniform
duty_sync's 94.7% SOS delivery conceals a 35-minute p95 latency (deliveries
ride the 5-minute retry loop), while the backbone-awake duty modes hold
33–62 s p95 at ~99.3–99.5% delivery. Every mode retains rare 1–2 h worst-case
SOS incidents (retry-ceiling limit, shared across modes). **No overall winner
is declared**: delivery, availability, and SOS tail latency still trade off,
statewide two-engine parity is pending, and the model is uncalibrated — the
corrected model's role is to expose the envelope, not pick the operating
point.

### 5.3 The central insight: duty policy dominates survivability, not routing

The five always-on modes span materially different routing strategies —
flooding, shortest-hop, link-quality (ETX), energy-aware, and load-balanced
cost trees — yet their annual depletion events sit within a **0.3% band**
(29,164–29,234/yr), and four of five share identical availability (53.7%)
and dark-site counts (118). Switching the *duty/wake policy* while holding
the routing family fixed moves deaths by **≈5.5–24×** (to 1,217–5,311/yr) and
fleet availability from ~54% to 90–96%. The energy budget is dominated by
idle listening (68 mA modeled listen vs 12 mA sleep); what a node does while
*not* forwarding matters far more to survival than which tree its packets
follow. The design consequence, if the result survives calibration: solar
relay hardware and firmware should be selected around the wake/CAD
architecture, and routing sophistication is a second-order optimization. The
quantified cost side — PDR −0.05 to −0.14 versus the routed always-on modes
(−0.10 to −0.18 versus flood, the highest-PDR mode) plus the SOS-latency
structure in §5.2 — makes this an explicit, tunable trade rather than a free
win. The separation is bound to release_v1 pending regeneration (§7.3); the
concrete reason it is unlikely to be an engine artifact is scale — the
5.5–24× effect dwarfs the worst cross-engine discrepancy observed on the
repaired engine (≤1.3%, §4.3). (MODEL-ONLY; the listen/sleep currents are
bench-calibration placeholders, which is precisely why the discharge bench
test and a controlled field day are the critical path.)

### 5.4 Testing the hardware alternative: the wake-up-radio study

Appendix B.1 identifies the idle receive path as the decisive design lever
and named the wake-up-receiver (WuR) architecture as the natural follow-on.
That study was subsequently designed with pre-registered, falsifiable
criteria (`docs/wur-design-2026-07-31.md`), implemented in **both** engines
(micro-parity verified at two operating points), and executed as three
experiments (E1–E3; artifacts and hash manifest at
`artifacts/sim/wur_study/`; results in
`docs/wur-study-results-2026-08-01.md`). In a WuR node the main radio
sleeps entirely behind an always-on micro-power (~3 µW) wake receiver that
is Δ dB less sensitive than the main radio; senders precede frames with a
wake chirp. The registered competitor was deliberately not the stock 68 mA
fleet but the **ideal-hardware null**: identical always-on routing on 2 mA
nRF52-class silicon (B.1's viability row).

| Arm (5 seeds × 365 d) | PDR | Depl./yr | Avail. | SOS del. | SOS p95 |
|---|---|---|---|---|---|
| **energy_aware @ 2 mA (null)** | **0.832** | **0** | **100.0%** | **100%** | **3 s** |
| wur Δ0 (physically ideal) | 0.827 | 489 | 99.2% | 100% | 3.3 s |
| wur Δ40 (realistic) | 0.728 | 488 | 99.2% | 99.7% | 10.0 min |
| wur Δ50 | 0.694 | 488 | 99.2% | 99.2% | 20.0 min |
| wur Δ60 | 0.668 | 488 | 99.2% | 98.7% | 45.1 min |
| wur Δ70 | 0.661 | 488 | 99.2% | 96.2% | 60.0 min |
| wur Δ80 | 0.660 | 488 | 99.2% | 94.6% | 55.0 min |
| energy_aware @ 68 mA (stock) | 0.843 | 29,176 | 53.5% | 100% | 4 s |
| duty_sync (incumbent) | 0.688 | 1,255 | 96.3% | 94.5% | 35.0 min |
| selective_duty | 0.778 | 5,309 | 89.6% | 99.5% | 5.0 min |
| rotate_lb | 0.775 | 4,860 | 91.1% | 99.8% | 61 s |

(MODEL-ONLY. Blind-routing arms shown; informed routing is statistically
indistinguishable — e.g. 0.734 vs 0.728 at Δ40 — the loss is wake-budget
physics, not routing blindness.)

**Both pre-registered claims were refuted.** The survivability criterion
(WuR depletions = 0 at every Δ *and* availability within 0.5 pp of the
null) fails on both halves: every Δ shows ≈488 depletions/yr (boot-energy
cycling at marginal sites) and availability sits 0.81 pp below the null.
The binding-onset claim (Δ\* ∈ (40, 70] with depletions still zero) fails
because the depletion disqualifier fires everywhere and, on delivery alone,
even the physically unrealizable Δ=0 arm sits below the null (0.827 vs
0.832) — the claimed viability window never exists. E2 showed main-radio
boot latency (50–200 ms) is second-order (PDR 0.679→0.677). E3, a static
wake-feasibility census, supplies the mechanism: at the realistic Δ=40,
40.1% of routing-eligible directed links cannot carry the wake chirp and a
median of 89 of 457 sites lose every wake-feasible path to a gateway
(σ_eff = 8.25 dB).

The engineering conclusion is sharper than the sweep alone: the question
WuR answers — how to listen without paying 68 mA — is answered better by
silicon that listens at 2 mA than by a second radio that cannot hear. The
2 mA null keeps always-on routing semantics (no chirp airtime, no boot
stalls, no wake-budget black holes), zero modeled depletions, and 100% SOS
delivery at interactive latency. Within this model, wake-up receivers are
not worth hardware-prototyping for this network; the deployment
recommendation stays with nRF52/RAK-class relays. (MODEL-ONLY; a study
that refutes its own pre-registered claims is reported with the same
standing as one that confirms them.)

### 5.5 Re-earning withdrawn claims on the corrected engine

The audit ledger (`docs/audit-correction-ledger-2026-07-13.md`) withdrew
every claim tied to the defective development engine. The
withdrawn-but-cheap families were re-run on the corrected engine: a 24-run
campaign (365 d, seeds 42–44; manifest
`artifacts/sim/reearn/manifest.json`) plus a 20-run climate campaign (10
pinned ERA5 weather years × duty_sync/energy_aware;
`artifacts/sim/weather_decade/`). Full analysis:
`docs/reearn-report-2026-08-01.md`. Verdicts:

| Withdrawn claim | Verdict | Headline (re-earn runs) |
|---|---|---|
| SOS-retry ablation | **Re-earned** | +3.9 pp ±1.6 SOS delivery (0.958→0.996), airtime +0.01%; cost is tail-only (worst case 61 s → 25–100 min) |
| Regional channels rejected | **Re-earned** (decision) | PDR −2.24 pp, identical in all 3 seeds; airtime relief only −0.24 pt — single shared channel stands |
| Kiosk zero spares | **Re-earned** (tested cell) | 100% rental availability at 0 spares: 77,380/77,380 walker-days, zero starvation, all seeds |
| Peak demand 4× | **Mixed** | Duty degrades gracefully (PDR +1.1 pt, ≈2.3× airtime headroom — not the withdrawn 3×); flood saturates (offered airtime 2.23, −7.5 pt PDR, first SOS losses). "SOS survived everywhere" does *not* re-earn |
| Gateway redundancy | **Mixed** | Single-gateway 30-day midwinter outage: zero SOS cost, ΔPDR −0.17 pp (reroute absorbed by ridge relays at no energy penalty); the dual-gateway wording remains withdrawn pending a dual-outage rerun |
| Climate robustness (decade) | **Mixed** (survival re-earned, stronger) | Duty survival advantage holds in *every* ERA5 year 2016–2025: 15.4–26.5× (mean 20.7×; 27,013 ±621 fewer depletions/yr). But duty's PDR/SOS-parity sub-claims flip (PDR −15.5 pp, SOS 94.6–96.8%) and must not be carried forward |
| RL routing/duty wins | **Still withdrawn** (confirmed negative) | q_routing −4.25 PDR pp vs etx; rl_duty has fewest depletions (−31% vs duty_sync) but at PDR −10.1 pp the pre-registered equivalent-PDR gate fails — the learned policy slid down the survival-vs-delivery curve rather than beating it |

(MODEL-ONLY. Within-family comparisons are seed-matched on one engine
build; the campaign runs a hotter traffic cadence than release_v1, so
re-earn absolutes are not quotable as release baselines — e.g. rotate_lb
PDR 0.775 here vs 0.809 in §5.2.)

Four families therefore survive contact with the corrected engine intact,
two re-earn their headline direction while shedding sub-claims, and the RL
victories convert to a documented negative result: the learned duty policy
collapsed to the 2% floor in 50 of 57 visited states — consistent with
§5.3, it found no structure that the hand-tuned backbone policies had
missed. The decade campaign also hardens the central insight of §5.3
against weather choice: the duty-survival separation is not a property of
one lucky winter.

## 6. Trial 2: the field campaign

**The causal frame, stated plainly: the two-radio controlled-beacon protocol
could not be executed because the beacon node's hardware failed during the
field week — its internal battery would not hold charge, and its USB-C
charging port then broke. Trial 2 was therefore adjusted — with every
adjustment registered before the data it affected was collected — to a
receiver-only field day scoring prospective public-station contact
predictions. The controlled-beacon prediction packs remain frozen and
unscored for a future two-radio day.**

### 6.1 Preregistration and freezes

The strongest freeze in the record is the 2026-07-19 preregistration
(`artifacts/trial2/prereg_manifest.json`): 12 hashed inputs — prediction
tables, generator, DEM manifest, radio metadata, the eligibility gate, and
the analysis code — bound at git `3d15a57` with a clean worktree, before any
calibration-eligible data existed. (Disclosure: 22 telemetry rows tagged
`trial2-moosilauke-20260719` — rig-bringup rows containing no beacon packets
— predate the freeze timestamp by minutes; zero calibration-eligible rows
ever existed.) The field-day prediction pack for
Moosilauke/Kearsarge/Monadnock (`predictions_fieldday.csv` + manifest) is
registered via SHA-256 digests recorded in the dated siting documents
(2026-07-23; CSV `a85e4d08…`, manifest `3e6df03f…`), re-verified matching on
2026-07-26; these registrations were git-timestamped by commit `1229309` on 2026-07-26.

### 6.2 Campaign log: attempts 1–3 (Jul 18–21)

Sat Jul 18: the rig never ran (0 GPS, 0 telemetry rows). Sun Jul 19
(Moosilauke): preserved GPS and telemetry evidence covers 09:10–10:19 EDT (≈1.1 h; 35,891 NMEA sentences), with the receiver radio's serial live only 09:14–10:13 EDT; **zero beacon packets — the beacon was already
broken.** Tue Jul 21 (retry): GPS logged throughout the ≈3-hour attempt (13:21–16:23 UTC, 110,115 sentences); the radio never enumerated on USB (power-only cable; 0 radio rows). All raw evidence preserved:
`artifacts/trial2/raw_pull_20260721/` (telemetry_stream.jsonl: 65,271 lines, 65,268 parseable JSON rows; nmea_stream.jsonl: 190,680 lines; SHA256SUMS added 2026-07-26). Per the frozen protocol's own definition,
these are operational failures with preserved evidence.

### 6.3 The siting-decision basis and the re-siting criterion

With the beacon dead, the only possible RF sources were public Meshtastic
stations, so the field day had to sit inside the live public-mesh region. A
checksummed snapshot of the NHMesh community's live dashboard (2026-07-23,
`artifacts/trial2/nhmesh_live_snapshot_20260723/`) showed the regional
ecosystem had largely migrated to a different protocol: **544 of 550
recently-positioned nodes were MeshCore — a protocol Meshtastic radios cannot
receive — leaving 6 Meshtastic stations on the map, none in the White
Mountains** (point-in-time caveat, stated plainly: this was a collector-view snapshot,
not an ecosystem census — a same-dashboard pull on 2026-07-26 12:20 UTC,
archived at `artifacts/trial2/nhmesh_activity_20260726/`, shows 276
positioned Meshtastic nodes seen within 12 h; the 2026-07-23 snapshot is
preserved because it is what the siting decision was made on). ITM feasibility ranking over the statewide DEM
selected Mt Monadnock, then — when a dog-policy constraint ruled Monadnock
State Park out — Pack Monadnock (Miller State Park). Both sitings were
registered in dated documents before their field days.

### 6.4 Monadnock: registered, never executed

The Monadnock pack (beacon point 42.86010/−72.10682 at 909 m by the ≥850 m
first-ascent rule; 33 route samples; 8 prediction rows appended to
`predictions_fieldday.csv` with prior sites verified byte-identical; DEM
`usgs_3dep_monadnock.npz`, sha `57936e6b…`; public-station contact
predictions `monadnock_livemesh_predictions_20260723.json`, sha
`aba23c13…`) was fully registered on 2026-07-23 and never walked. It stands as a frozen sibling registration.

### 6.5 Pack Monadnock (2026-07-26): the first operationally successful day

Executed under `trial_id trial2-packmonadnock-20260726` on the OSM-routed
Wapack loop. The rig ran end-to-end: radio logging all day, 1 Hz GPS,
summit reached (714.6 m raw GGA maximum, 13:50:13 UTC) with a 13:31–14:04 UTC dwell
within 60 vertical meters of the maximum. Raw evidence:
`artifacts/trial2/raw_pull_20260726/` with SHA256SUMS (extended to the
post-hike tail files). Trial-ID bookkeeping is disclosed in full: the rig was powered at home from
10:01 UTC; 8 field-day boot rows (10:01–10:06 UTC) plus 55 rows from a
2026-07-22 bench session carry the superseded `trial2-moosilauke-20260722`
tag (the field tag activates at 10:07:38 UTC); 27 pre-departure rows and 8
post-hike drive-tail rows carry the field tag.

Radio operation, all field days: stock FCC-certified consumer hardware
(Heltec V3 / CP2102 receiver), unmodified firmware and transmit power,
standard US 915 MHz ISM-band frequencies (LongFast defaults), default
channel-access behavior, the default public channel carrying the project's
own traffic, all equipment placed and retrieved the same day.

**Registered contact predictions and outcomes — scored in two provenance
tiers, never aggregated** (the receiver's decode capability is independently
evidenced: it logged foreign frames during the campaign, including one during
the summit dwell at −117 dBm):

*Tier 1 — the pre-departure registered pack*
(`packmonadnock_livemesh_predictions_20260726.json`, sha `71db9f00…e9e2`,
recorded pre-collection in the siting doc in truncated form, full digest in
its addendum): Greenville, CONTACT_PREDICTED at −87.9 dBm best-along-route —
**not heard (0/1)**. Keene Court St, NO_CONTACT_PREDICTED at −144.4 dBm —
**null held (1/1)**. Three MARGINAL links — none heard.

*Tier 2 — the trailhead supplement*
(`packmonadnock_livemesh_supplement_20260726.json`, sha `f50bda83…53c5f`;
provenance explicitly weaker: its digest was first durably recorded
post-collection and its pre-walk timestamp is self-asserted): three
additional CONTACT_PREDICTED links (−90.2 to −91.1 dBm) — none heard; four
additional predicted nulls — all held.

Null confirmations are scored but carry little evidential weight: the same
transmit censoring that voids the contact misses (§6.6) applies
symmetrically — a station that does not transmit produces a held null
regardless of link physics — and the Keene prediction (−144.4 dBm) lies
≈13 dB below the assumed decode floor, making its null near-trivial.

### 6.6 Field findings: the empirical case for the controlled beacon

The contact misses are **transmit-censored, and the campaign measured the
censoring**:

1. **Transmit-opportunity starvation.** The public stations' measured
   transmit cadence (60-minute activity window generated 2026-07-26 15:02:52 UTC; archived with checksums at `artifacts/trial2/nhmesh_activity_20260726/`; an adjacent-hour estimate, ≈14:03–15:03 UTC, assumed representative of the dwell window) is 0–4 packets per hour per station — Greenville sent 1 packet in the archived hour, i.e. ≈0.6 expected transmissions during the 33-minute GPS-verified summit dwell (13:31–14:04 UTC); two of the three Tier-2 CONTACT-predicted stations sent 0. (A scoreable opportunity = a station transmission while the receiver sits inside that link's predicted-contact route segment.)
   The receiving side was equally starved in reverse: the project node kept
   stock broadcast cadence and was never heard by any NHMesh collector all
   day. A link prediction cannot be confirmed by a station that does not
   transmit during the window — with these cadences the expected number of
   scoreable opportunities per field day is approximately zero, regardless
   of link quality.
2. **Hop ambiguity.** All six origin-decoded foreign frames logged across the day carry `hops_away` between 1 and 5 (or undecodable hop fields) — **zero direct receptions among origin-decoded frames** (one additional frame with undecodable origin carries `hops_away=0`; disclosed, not scored).
   Mesh-relayed packets attribute their RSSI to an unknown last-hop
   transmitter, not to the origin path, so none of the six decodes is usable
   as a path-loss observation. (Systems observation, reported as such:
   packets originating at stations 86–88 km away reached the project radio through the mesh — both such decodes logged in the post-hike vehicle segment — multi-hop delivery functioning in the wild.)

Together these two measurements are the empirical justification for the
frozen protocol's two central rules — a controlled beacon at 30 s cadence
(defeats opportunity starvation) and `hops_away == 0` eligibility (defeats
hop ambiguity). Opportunistic validation against a public mesh fails not on
RF physics but on opportunity statistics and attribution; the controlled
two-radio design is necessary, not merely preferable.

### 6.7 The remaining step

Zero calibration-eligible strata exist; the ≥40-opportunity-per-stratum
target was never reached on any day; the Moosilauke, Kearsarge, and Monadnock
beacon packs remain frozen and unscored. None of this is dropped or
relabeled. The concrete remaining step is small and fully specified: a
replacement beacon board (≈$25), the already-frozen protocol, and one
two-radio field day (§8). The raw-dataset package item was built 2026-07-26:
`artifacts/dataset_release/evidence-2026-07-26/` — 128,721 observations, 0 calibration-grade, with MANIFEST.json and data dictionary.

## 7. Limitations

### 7.1 Empirical (the binding constraint)

- **No controlled dataset exists**; Trial 1 and the Trial 2 campaign together
  yield zero calibration-grade observations, so the project has no held-out
  field estimate of RSSI error, PDR error, or shadow variance.
- Receiver sensitivity (−131 dBm), feed/body/foliage losses, board currents,
  cold-battery capacity, and panel yield are assumptions or placeholders, not
  measurements of the project hardware.
- Public-mesh observations are non-calibration-grade by construction
  (unknown station EIRP/antennas/uptime; §6.6) and are never used as
  path-loss data.
- A future controlled field day calibrates propagation and direct-link PDR on
  its sampled routes; it cannot by itself validate statewide traffic,
  routing, kiosk, or annual energy behavior (bench + hardware-in-the-loop
  work).
- Field sites are restricted: one shakedown (Mt. Washington) and one
  operationally successful receiver-only day (Pack Monadnock), summer only.

### 7.2 Modeling

- ITM q50 medians without a validated residual model; q90 route arrays
  absent.
- σ = 8 dB shadowing, 2 dB fast fade, capture threshold, mobile-mobile
  heuristic, synthetic traffic/SOS rates, and the 600 s TTL are assumptions.
- The MAC is not stock Meshtastic firmware; siting, permits, maintenance,
  security, and human factors are outside the simulation.
- One statewide weather series; solar geometry simplified; geology priors in
  the repo are uncited placeholders not wired into any prediction (open
  decision A3) and are not model inputs here.
- The purpose-built simulator is not independently validated through a widely
  used third-party framework (ns-3 spot-validation is future work, §9).

### 7.3 Software, release, and provenance

- Statewide two-engine parity is pending (§4.4); corrected-labeled artifacts
  outside `release_v1/` are stale relative to the repaired engine and marked
  accordingly (`artifacts/sim/corrected/README-STALE-WARNING.md`).
- release_v1 was generated 2026-07-14 from a dirty worktree (its manifest
  records this) and carries a disclosed manifest inconsistency (git HEAD
  `d37172c` in `release_manifest.json` vs `f5e83f0` in `input_hashes.txt`;
  the four locked input hashes agree in both). Subsequent engine repairs mean
  current HEAD would not reproduce it byte-for-byte; regeneration
  (release_v2) is incomplete (5 of 9 modes, no manifest) and **not citable**.
  The §5.2 numbers are bound to the archived release_v1 artifacts.
- Post-2026-07-19 Trial 2 registrations were committed 2026-07-26
  (`1229309`); their pre-commit provenance was in-doc SHA-256 digests, as
  disclosed in the header note.
- Authorization for a production fixed-relay deployment remains an open
  question (`docs/fcc-part15-compliance-memo.md`); field-day operation used
  certified consumer hardware as marketed (§6.5).
- Passing tests bound, but do not prove, the absence of defects; a dedicated
  PHY-abort model for mid-frame availability loss remains future work.

## 8. Future work

1. **The two-radio field day** (the critical path): replacement beacon board
   (≈$25), the already-frozen protocol (30 s cadence, sequence numbers,
   `hops_away == 0`, ≥40 opportunities per primary stratum), scoring the
   frozen Moosilauke and/or Monadnock packs; output feeds the original
   validation deliverable (RMSE/MAE via `error_quantifier.py`,
   predictive-vs-actual heatmaps, failure matrix) — all tooling exists.
2. Bench calibration of the BENCH-CALIBRATE constants (board currents,
   discharge behavior, panel yield) — the other half of the critical path.
3. Complete release_v2 on the repaired engine with a full manifest;
   regenerate §5.2 from it.
4. Statewide two-engine parity per the preregistered tolerance plan.
5. ns-3 spot-validation of selected MAC/protocol scenarios.
6. Advisor-decided amendments: the RSRP→ESP substitution (A1) and the
   ≥40-opportunity rule.
7. ~~Dataset release packaging~~ — completed 2026-07-26
   (`artifacts/dataset_release/evidence-2026-07-26/`, §6.7).

## 9. Data and reproducibility statement

All quantitative statements in this report are artifact-backed measurements,
archived software checks, or simulation results labeled MODEL-ONLY.
Simulation numbers cite the corrected multi-seed release (`release_v1`,
hash-locked inputs) or the manifested follow-on campaigns of §5.4–5.5
(`artifacts/sim/wur_study/manifest.json`,
`artifacts/sim/reearn/manifest.json`,
`artifacts/sim/weather_decade/manifest.json`; every campaign runner is
committed, so all run files regenerate from the frozen inputs). The
repository also ships an interactive replay viewer
(`scripts/run_replay_traces.sh` → `scripts/render_replay_viewer.py`) that
animates recorded packet-level traces of all eight policy arms over the
darkest five-day window of the pinned weather year — every displayed hop,
collision, and failed wake is a recorded simulation event, not a rendering
estimate. Superseded development-phase outputs are archived
separately in the repository (`WITHDRAWN-DO-NOT-CITE/`, with a manifest) and
are not cited here, per the acceptance requirement that superseded numbers be
clearly archived and not mixed with final results. Same-seed engine output is
byte-identical (§4). Trial 2 registrations made after 2026-07-19 are
git-timestamped by commit `1229309`; every SHA-256 digest cited in this
report was re-verified against its artifact on 2026-07-26. All artifacts
cited by path in this report resolve in the project repository:
<https://github.com/edoherty2017/resilient-emergency-manets-final>
(branch `main`, release `directed-study-final`).

## Appendix A. Frozen prediction packs and scoring ledger

| Pack | Registered | Status |
|---|---|---|
| Mt. Washington (Ammo/Jewell strata) | 2026-07-19 freeze, git `3d15a57`, clean worktree | Deferred — never walked; retained |
| Moosilauke (Gorge Brook; beacon 44.01708/−71.83777 @1352 m) | fieldday pack, digests recorded 2026-07-23 | Frozen, unscored (beacon failure); awaits two-radio day |
| Kearsarge (Winslow; beacon 43.38735/−71.85970 @771 m) | same pack | Deferred (ITM predicts no public-mesh contact from site); retained |
| Monadnock (White Dot; beacon 42.86010/−72.10682 @909 m) | pack + livemesh JSON (`aba23c13…`), 2026-07-23 | Registered, never executed (site dog policy); retained |
| Pack Monadnock (Wapack loop) | livemesh JSON (`71db9f00…`) pre-departure; supplement (`f50bda83…`) weaker tier | **Executed 2026-07-26.** Tier 1: 0/1 contact, 1/1 null held. Tier 2: 0/3 contacts, 4/4 nulls held. Misses transmit-censored (§6.6); evidence basis: complete Pi instrument log (no other evidence exists) |

Propagation method detail for all packs: Longley–Rice ITM q50 point-to-point
over USGS 3DEP DEMs, 26.30 dBm receiver-power reference (the registration
files label this quantity "EIRP ref" — a terminology carry-over in those
frozen documents, not a numerical discrepancy; the value is identical), receiver height
1.5 m, station heights as documented per pack (assumed stock where
unpublished, labeled in the registration files).

## Appendix B. Design implications: sensitivity of the survivability result

This appendix responds to the advisor's request (2026-07-30) to translate the
idle-listening finding of §5.3 into engineering terms. All values are
MODEL-ONLY (uncalibrated constants, §7); the new sweeps ran on the current
repaired engine against the release_v1 frozen inputs (17 runs, 365 days each;
hash manifest at `artifacts/sim/appendixB_sweeps/`). The 68 mA baseline
reproduces the release_v1 depletion count within 0.04% (29,175 vs 29,164 at
seed 42), while its PDR differs modestly (0.843 vs 0.866) reflecting
post-release engine repairs — comparisons below are therefore made within
the sweep.

**B.1 — What listen current makes always-on viable?** Sweeping router listen
current under always-on energy-aware routing (stock 37 Wh battery, 6 W panel):

| Listen current | Depletions/yr | Fleet availability | PDR |
|---|---|---|---|
| 68 mA (ESP32-class, stock) | 29,175 | 53.5% | 0.843 |
| 40 mA | 13,647 | 72.4% | 0.836 |
| 20 mA | 2,824 | 90.6% | 0.832 |
| 10 mA | **27** | **99.8%** | 0.831 |
| 5 mA | 0 | 100.0% | 0.831 |
| 2 mA (nRF52-class) | 0 (3 seeds) | 100.0% | 0.832 |

Always-on operation becomes viable at ~10 mA on the stock energy kit, and at
the nRF52-class 2–5 mA receive currents the modeled fleet loses no node all
year — while delivery is essentially flat across the sweep. In this model,
sufficiently low listen current dominates every duty-cycling policy on both
axes at once, which quantifies the hardware target: bring the radio's idle
receive path under ~10 mA and the duty-versus-delivery trade of §5.3
dissolves. (It also identifies listen current as the first constant to pin at
the bench. The wake-up-receiver follow-on study this row motivated was
subsequently executed and is reported in §5.4: the architecture was refuted
against this same 2 mA null.)

**B.2 — What capacity reaches 90–95% availability at stock current?**
Holding 68 mA and sweeping the energy kit:

| Battery | Panel | Depletions/yr | Fleet availability | PDR |
|---|---|---|---|---|
| 37 Wh (stock) | 6 W (stock) | 29,175 | 53.5% | 0.843 |
| 74 Wh | 6 W | 14,856 | 54.9% | 0.842 |
| 148 Wh | 6 W | 6,546 | 57.2% | 0.842 |
| 74 Wh | 12 W | 9,657 | 77.9% | 0.835 |
| 148 Wh | 12 W | 4,014 | 79.9% | 0.835 |
| 296 Wh | 12 W | 1,776 | 84.0% | 0.834 |
| 148 Wh | 24 W | 1,551 | **94.6%** | 0.832 |
| 296 Wh | 24 W | 235 | **98.5%** | 0.831 |

Availability is panel-dominated: at the stock 6 W panel, even 4× battery
moves availability only 53.5%→57.2%, because winter harvest — not storage —
is binding. Reaching the 90–95% band at stock listen current requires roughly
4× battery *and* 4× panel (148 Wh / 24 W → 94.6%); 8×/4× reaches 98.5%. Per
relay, that capacity route is materially more expensive than the
listen-current route of B.1, which reaches higher availability on the stock
kit — the design lever is the receiver, not the battery.

**B.3 — What duty cycle preserves acceptable SOS latency?** From the released
policy comparison (§5.2, no new runs): the threshold is structural rather
than a percentage. Uniform low-duty (duty_sync, 5%) buys the largest
survivability gain (24×) but crosses the latency cliff — 94.7% SOS delivery
with a 35-minute p95, because deliveries ride the 5-minute retry loop.
Backbone-awake policies (rotate_lb, selective_duty), which keep the current
routing tree's relays listening and duty-cycle everyone else, hold SOS p95 at
33–62 s with 99.3–99.5% delivery while retaining a 5.5–6× survivability gain.
Within this model, any deployment with an SOS-latency requirement should
duty-cycle *off-tree* nodes only; uniform duty cycling is a survivability
tool for networks without latency-critical traffic.

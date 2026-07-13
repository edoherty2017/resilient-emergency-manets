# Academic Rigor Review — 2026-06-12

Scope: full audit of `resilient-emergency-manets` (pipeline code, artifacts, Trial 1 report,
directed-study proposal V3) for mathematical correctness, statistical validity, and
defensibility in front of an expert committee. Written as the harshest plausible reviewer.

> **Historical snapshot:** This document describes the 2026-06-12 worktree. Some cited
> code and claims have since been changed, while other findings remain open. It is not a
> current-state certification and must not be used to claim that a listed defect is still
> present—or fixed—without checking the present code, regenerated artifacts, and tests.

**Verdict up front:** the measurement *platform* (Pi + Meshtastic collector + Garmin ground
truth + Starlink gRPC telemetry + schema/provenance discipline) is sound and should be kept.
The *modeling and evaluation layer* is not yet defensible: the propagation model is pure FSPL
mislabeled as terrain-aware ITM, the calibration is an in-sample mean shift, the terrain
features come from a synthetic sine-wave DEM, and the Trial 1 report contains verifiable
factual and arithmetic errors. None of this requires a restart — Trial 1's structural data
gaps were already correctly diagnosed in the report itself, and the Trial 2 design (static
node + hop filtering) is the right fix. The remediation plan in Part 4 fixes what exists.

---

## Part 1 — Verified factual and mathematical errors

These are checked claims, not style points. Each would be caught by a knowledgeable reviewer.

### 1.1 The Meshtastic LongFast preset is misstated (trial1_report.tex §5.4, §5.5)

The report states: sensitivity −130 dBm "corresponds to SF12, BW=125 kHz, CR=4/5 — the
Meshtastic LongFast modem preset", data rate ≈0.29 kbps, link budget 156.3 dB.

Per Meshtastic's official radio-settings documentation, **LONG_FAST is SF11, BW 250 kHz,
CR 4/5, data rate 1.07 kbps, link budget 153 dB** (at 22 dBm TX, 0 dBi antenna — implying
sensitivity ≈ −131 dBm). SF12/BW125/CR4-8 is the deprecated LONG_SLOW preset (0.18 kbps,
158.5 dB). Consequences:

- Link budget with the stated 2×2.15 dBi antennas is ≈ 157.3 dB, not 156.3 dB (minor).
- The data-rate figure is wrong by 3.7× (in the favorable direction for the SOS-latency
  claim, but wrong).
- Every appearance of "SF12 BW125" describing the trial configuration must be corrected,
  or the actual radio config from the trial must be confirmed and pinned in
  `config/airmap/model-baseline.yaml` (the config currently pins only frequency).

### 1.2 The maximum-range numbers contradict the stated equation (trial1_report.tex §6.3)

Eq. (dmax) is stated as d_max = 10^((L − L_T − 91.65)/20) km with L = 156.3 dB
("Setting P_r = P_sens"). Evaluating it as written:

- Alpine (L_T = 3): 10^((156.3−3−91.65)/20) = 10^3.08 ≈ **1,209 km**, not the printed 38.2 km.
- Forest (L_T = 25): 10^((156.3−25−91.65)/20) = 10^1.98 ≈ **96 km**, not the printed 3.0 km.

The printed values (38.2 km, 3.0 km) correspond exactly to a **−100 dBm receive threshold**
(PL_max = 126.3 dB), not to P_sens = −130 dBm. Either the report silently used a −100 dBm
planning threshold (a defensible choice — fade margin + reliable demodulation) or the
arithmetic is wrong. Fix: define the planning threshold explicitly (e.g., "P_r ≥ −100 dBm,
i.e., 30 dB fade margin above sensitivity") and present both the threshold-range and the
absolute-sensitivity range. As printed, the section is internally inconsistent by a factor
of ~32 and will be caught by anyone with a calculator.

### 1.3 The floating-intercept ↔ reference-distance relation is garbled (trial1_report.tex Eq. after eq:floating)

The stated relation d₀ = (4π/λ²)·10^(−α/10(β−2)) is dimensionally incoherent (4π/λ² has
units of m⁻²; the exponent grouping is ambiguous). The correct relation between
PL(d) = PL(d₀) + 10n·log₁₀(d/d₀) and PL(d) = α + 10β·log₁₀(d) is simply:

  n = β,  α = PL(d₀) − 10β·log₁₀(d₀),  with PL(d₀) = 20·log₁₀(4πd₀/λ) for a free-space anchor.

Replace or delete the garbled equation.

### 1.4 The report misstates what the calibration code does (trial1_report.tex §8)

§8 says the pipeline "fits a residual bias term Δ via Eq. (floating)" — i.e., the
floating-intercept model α + 10β·log₁₀(d). The code (`scripts/airmap_live_trial.py:297`)
fits **only a constant mean bias** (β fixed at 2 implicitly): one number, the mean of
(observed − predicted). No slope is estimated. Likewise `config/airmap/calibration-and-eval.yaml`
declares `method: residual_bias_then_scale` but no scale term is implemented, and
`target_metric_priority` lists `rssi_dbm` before `rsrp_dbm` while the code prefers RSRP.
Either implement the floating-intercept fit (required anyway — see Part 3) or describe the
method accurately.

### 1.5 `pred_snr_db` is not SNR (`scripts/airmap_live_trial.py:237`)

`pred_snr_db = pred_rssi_dbm − RX_SENS_DBM` is **link margin**, not SNR. SNR is signal
relative to the noise floor: N = −174 + 10·log₁₀(BW_Hz) + NF ≈ −120 dBm for BW 250 kHz
with NF ≈ 6 dB. LoRa SF11 demodulates down to SNR ≈ −17.5 dB, which is exactly why
sensitivity sits *below* the noise floor. Publishing a column named `pred_snr_db` that is
actually margin invites an instant committee question. Rename to `pred_link_margin_db` and,
if SNR is predicted at all, compute it against the noise floor.

### 1.6 Internal inconsistencies across documents

- Nodes with GPS: `trial1_report.tex` says 12; `reports/project_report.md` says 24;
  `catalog_summary.json` says 24. Pick one, explain the difference (e.g., before/after
  position-packet dedup), and make all documents agree.
- `TODO-ANCHOR.md` P5 freezes "RMSE=37.1 dB" as a recomputed result while the current
  artifact `artifacts/airmap/live_trial/metrics_global.json` says RMSE=55.2 dB, and the
  project report (correctly) says the calibration numbers should not be cited at all.
  Stale numbers in the anchor file must be struck or annotated as superseded/invalid.

---

## Part 2 — Integrity and provenance problems (highest presentation risk)

These are worse than math errors: they are claims the artifacts themselves contradict.

### 2.1 The "terrain features" come from a synthetic DEM, but the report says USGS 3DEP

`scripts/dem_transformer.py:47-67` generates elevation from a deterministic sine-wave
function (`synthetic_dem`) — **always**; there is no code path that loads real elevation
data. The artifact manifest is honest about it
(`artifacts/dem/feature_provenance_manifest.json`: `"source": "synthetic-dem-deterministic"`),
but `reports/project_report.md` describes the same artifacts as "Cached USGS 3DEP tile for
the Mt. Washington region" and "Elevation, slope, terrain class per GPS point along the
route." If a committee member opens the manifest, the project's credibility is gone.

Worse, the DEM window in the manifest spans lat 22.7→44.2, lon −72.6→**+114.3** — the
bounding box was computed from unfiltered GPS rows including junk/far-field mesh coordinates,
so the 512×512 "terrain grid" covers roughly a third of the planet at ~50 km resolution.
Every downstream slope/topography/geology feature derived from it is meaningless.

**Fix:** implement real 3DEP ingestion (the `config/airmap/dem-sources.yaml` stub already
exists), filter GPS to the AOI before computing the window, and correct the project report.
Until then, label every DEM-derived artifact "synthetic — pipeline validation only" in the
report, not just in the manifest.

### 2.2 The model provenance claims ITM/Longley-Rice; the code is FSPL

`config/airmap/model-baseline.yaml` pins `name: itm_longley_rice_baseline`, and every
artifact's provenance carries that name. The implemented model
(`scripts/airmap_live_trial.py:21-23`) is the free-space path loss equation. ITM models
diffraction and troposcatter over a terrain profile; FSPL is the n=2 lower bound. The model
hash is still `"TBD_PINNED_HASH"`. Rename the model to `fspl_baseline_v1` (or actually
implement ITM — Part 4), and pin a real hash. Provenance that misnames the model is worse
than no provenance.

### 2.3 The geology attenuation priors are invented constants, presented with false precision

`scripts/geology_loss.py:33-50` assigns e.g. `mixed_talus: 12.0 dB`, `cliff_or_ridge: +5.5 dB`,
scaled by `(f/915)^0.25`. None of these numbers carries a citation; the frequency exponent
appears to be invented. The proposal promises "Path Loss Exponents (n) for the specific
metamorphic geology (schist/gneiss)" — these priors are not that, and (critically) **they
are never used by the prediction**: `airmap_live_trial.py` computes FSPL only. So the repo
contains a decorative pseudo-physical module that inflates apparent rigor without affecting
results. Either (a) ground the vegetation/terrain excess-loss terms in citable sources
(ITU-R P.833 for vegetation; Bianco et al. 2021 for mountain LoRa exponents) *and* wire them
into the prediction, or (b) delete the module. "Where does 12.0 dB for mixed talus come
from?" is an unanswerable committee question today.

### 2.4 Two incompatible topography taxonomies

`geology_loss.py` classifies {cliff_or_ridge, steep_hillside, valley_floor, rolling_highlands}
by slope+elevation; `airmap_live_trial.py:210-214` classifies {alpine_ridge, sub_alpine,
valley_forest} by elevation alone; the trial1 report's L_T(z) uses a third scheme
{alpine, sub-alpine, forested} with different dB values (3/15/25) than geology_loss produces.
Stratified metrics keyed on `topography_class` are therefore not joinable across artifacts.
Define one taxonomy in one module, with citations for any attached dB values.

---

## Part 3 — Statistical methodology gaps

Even with clean Trial 2 data, the current evaluation design would not survive review.

### 3.1 In-sample calibration with no held-out evaluation

`airmap_live_trial.py:295-303` fits the bias on *all* matched rows and then reports
RMSE/MAE on the *same* rows. With a single fitted parameter the optimism is small, but the
moment the calibration grows (slope, terrain terms) this becomes circular. Required:
**spatially blocked cross-validation** — split by trail segment or distance block, never by
random row, because consecutive rows are heavily autocorrelated in space and time. Report
pre-calibration and held-out post-calibration error.

### 3.2 No uncertainty quantification anywhere

No confidence intervals on RMSE/MAE, on the residual bias, on stratified metrics, or on
coverage percentages. Telemetry rows are a time series — naive n (e.g., n=412) wildly
overstates the effective sample size. Required:

- **Moving-block bootstrap** (block length ≥ the residual autocorrelation time, plausibly
  30–120 s) for CIs on all error metrics and fitted parameters.
- **Wilson intervals** on proportions. Example: the "87.1% covered" MESH_ONLY claim
  (122/140 rows) carries a 95% Wilson CI of ≈ [80.6%, 91.7%] — and the 140 rows are
  autocorrelated, so even that is optimistic. State it.
- Stratified metrics: `calibration-and-eval.yaml` declares `min_samples_per_stratum: 30`
  but nothing enforces it. Suppress (or flag) cells below threshold; with a 4-way
  stratification the table is mostly noise cells today.

### 3.3 Left-censoring: you only observe packets that survived

Only successfully demodulated packets produce RSSI rows. Packets below the sensitivity/SNR
floor vanish, so the observed RSSI-vs-distance cloud is truncated from below and any path-loss
fit on received packets is **biased optimistic** — a known pitfall in LoRa propagation
studies. Mitigations, in order of strength:

1. Make **PDR (packet delivery ratio)** a primary endpoint: with a beacon transmitting at a
   known cadence and sequence numbers, missing packets are *observed failures*, not invisible
   ones. The proposal already commits to PDR; the current pipeline never computes it.
2. Fit path loss on **ESP** (ESP = RSSI + SNR − 10·log₁₀(1+10^{0.1·SNR}), already cited in
   the report as Eq. eq:esp) rather than raw RSSI — near the floor, RSSI is noise-dominated
   and ESP is the meaningful signal estimate. The pipeline logs `snr_db` but never uses it.
3. At minimum, state the censoring direction and bound its effect.

### 3.4 The quality gates are vacuous

`p6_integrated_run.py` passes the error quantifier at `--max-rmse-db 60`. RSSI spans roughly
−130…−30 dBm; predicting a constant near the mean would pass a 60 dB RMSE gate. A gate that
cannot fail is not evidence. Set falsifiable targets tied to literature: post-fit shadowing
σ ≤ 8–10 dB (Bianco et al. report σ ≈ 6–8 dB), path-loss exponent within [1.6, 4.5], held-out
RMSE ≤ 12 dB, join match rate ≥ X%, GPS-fix rate ≥ Y%.

### 3.5 Distance handling bugs that contaminate every metric

- `airmap_live_trial.py:234` — `fillna(0.0).clip(lower=1.0)`: rows with **no distance at
  all** become d = 1 m, predict P_r ≈ −5 dBm, and then enter the calibration fit and
  RMSE. This single line manufactures enormous errors from missing data.
- `head_displacement_from_ref` (lines 201-206): when the source has no GPS, "distance" is
  the head's displacement from the trailhead reference — not a link distance. Physically
  meaningless as an FSPL input, yet these rows are matched and scored.
- **Fix:** only rows with `distance_source == "source_to_head_gps"` (and, post-Trial-2,
  `hops_away == 0`) are eligible for calibration and error metrics. Everything else is
  reported in the join audit as excluded-with-reason. This rule alone probably explains most
  of the 55 dB RMSE.
- Haversine is 2D (`airmap_live_trial.py:26-32`). On steep terrain use 3D slant distance:
  d = √(d_haversine² + Δelev²). At 1.7 km horizontal / 700 m vertical that is a 0.7 dB
  FSPL difference — small but free to fix, and reviewers notice.
- Source positions are joined with a **30-minute** tolerance (`airmap_live_trial.py:175`).
  A hiker moves ~1.5–2 km in 30 min; that is a several-dB FSPL ambiguity at short range.
  Tighten to ≤60 s for moving nodes (interpolate between fixes), or carry a per-row
  `distance_uncertainty_m` derived from fix staleness and propagate it.

### 3.6 Time-of-day bins are computed in UTC, labeled as local

`airmap_live_trial.py:245` uses `timestamp_utc.dt.hour` as `local_hour`. New Hampshire is
UTC−4 in summer: "evening_peak (20–22)" actually captures 16:00–18:00 EDT. Every
`satellite_timebin_metrics.csv` row and any time-of-day Starlink claim is mislabeled by four
hours. Convert to `America/New_York` before binning.

### 3.7 "Zero dead zones" is not a supportable claim (trial1_report.tex §3)

The observation is: in every 5-min window of the descent, the HEAD *received ≥1 packet from
some node* — any of ~50 strangers at unknown distances, possibly relayed. This does not
establish (a) bidirectional communication capability, (b) reachability of any gateway,
(c) anything about a specific link. "Network contact was maintained… contradicts the common
assumption that LoRa is only viable in open terrain" is an overclaim. Reframe precisely:
"≥1 Meshtastic packet (any source, any hop count) was demodulated in every 5-minute window
during the descent" — interesting as ambient mesh density evidence, silent on coverage.
Coverage claims need an operational definition (Part 4.4).

### 3.8 The relay-infrastructure predictions ignore terrain geometry

The proposed-relay link table and the "Coverage if Deployed" map layer use FSPL + a flat
elevation-class loss with 2D distance from the *nearest* relay (`hike_data_map.py:140-163`).
No line-of-sight check, no Fresnel clearance, no diffraction — on Mt. Washington, where the
2h48m gap segment is inside a glacial cirque (Ammonoosuc Ravine headwall). A treeline relay
does not necessarily see into the ravine. The claim "the 2h48m gap would have been fully
covered" is the centerpiece of the infrastructure proposal and is currently supported by a
model that cannot represent the terrain that caused the problem. Fix in Part 4.2 (ITM on
real DEM + viewshed). The 3σ shadowing-margin arithmetic in §6.2 is correct *given the
model*, but the model omits the dominant loss mechanism (diffraction), so the "robust link"
conclusion is unsupported.

---

## Part 4 — Remediation plan

Ordered; each block is independently mergeable. P0 before any presentation; P1 before/with
Trial 2; P2 for the final report.

### P0 — Truth and labeling (1–2 days, no new data needed)

1. **Fix trial1_report.tex:** LongFast = SF11/BW250/CR4-5, 1.07 kbps, link budget ≈157.3 dB
   with stated antennas (§1.1); restate d_max with an explicit −100 dBm planning threshold
   and show both threshold and sensitivity ranges (§1.2); fix or delete the d₀ relation
   (§1.3); describe the calibration as implemented (§1.4); reframe "zero dead zones" (§3.7);
   add a "model limitations" paragraph to §6 noting absence of diffraction (§3.8); reconcile
   the 12-vs-24 GPS node count (§1.6).
2. **Fix provenance:** rename model to `fspl_baseline_v1`, pin a real hash, align
   `calibration-and-eval.yaml` (method, metric priority) with the code (§2.2, §1.4).
3. **Fix project_report.md:** DEM artifacts are synthetic; remove the "USGS 3DEP" description
   until real data is wired (§2.1). Strike the stale RMSE=37.1 line in TODO-ANCHOR (§1.6).
4. **Bug fixes in `airmap_live_trial.py`:** remove the d=1 m fill; gate calibration/metrics
   on `distance_source == "source_to_head_gps"`; rename `pred_snr_db` →
   `pred_link_margin_db`; convert hours to America/New_York; 3D slant distance; tighten
   source-position join tolerance to 60 s with `distance_uncertainty_m` column (§3.5, §3.6,
   §1.5).
5. **Reproducibility hygiene:** commit a pinned `requirements.txt` (versions), and add a CI
   step (or at least a make target) that runs `airmap_dry_run.py` + schema validation on
   every commit.

### P1 — Statistical core (3–5 days, before Trial 2 analysis)

6. **Replace mean-bias calibration with a floating-intercept fit:** OLS of observed ESP
   (not raw RSSI; compute ESP from RSSI+SNR per eq:esp) on 10·log₁₀(d), per terrain class
   when n permits. Report α, β (=n̂), σ̂ (residual std = shadowing), R², with moving-block
   bootstrap 95% CIs. This is exactly the "Digital Twin Calibration File: Path Loss
   Exponents (n)" the proposal promises and the current code cannot produce.
7. **Held-out evaluation:** spatially blocked CV by trail segment; report held-out RMSE/MAE
   pre/post calibration (§3.1).
8. **Enforce `min_samples_per_stratum`** in all stratified outputs; add Wilson CIs to every
   proportion artifact, including the coverage-transition summary (§3.2).
9. **Replace the 60 dB RMSE gate** with falsifiable gates: held-out RMSE ≤ 12 dB,
   σ̂ ≤ 10 dB, n̂ ∈ [1.6, 4.5], calibration-eligible row count ≥ 200 (§3.4).
10. **PDR module:** `scripts/pdr_analysis.py` — given a beacon node ID and known cadence,
    compute per-window PDR with Wilson CIs, stratified by distance bin × terrain. Makes the
    censoring problem an observable instead of a bias (§3.3).

### P2 — Terrain-real modeling (1–2 weeks, parallel with Trial 2)

11. **Real DEM:** implement 3DEP fetch in `dem_transformer.py` per `dem-sources.yaml`;
    filter GPS to the AOI before windowing; regenerate terrain features; delete or clearly
    quarantine the synthetic path behind a `--synthetic` flag used only by the dry run (§2.1).
12. **ITM/Longley-Rice point-to-point** for the three proposed relay links plus a viewshed/
    coverage grid over the trail corridor (SPLAT! or the NTIA ITM reference implementation —
    both are free; the model-baseline.yaml already *claims* this model). Re-issue the relay
    link table with terrain-profile losses and re-evaluate the "gap would have been covered"
    claim honestly. If the ravine segment is NLOS to all relays, the proposal changes (add a
    ravine-rim node) — better you discover that than the committee.
13. **Geology priors:** either cite (ITU-R P.833-10 vegetation attenuation; Bianco 2021
    mountain exponents) and wire into the augmented model as documented terms, or delete the
    module (§2.3). Unify the topography taxonomy across all scripts (§2.4).

### P3 — Trial 2 design (the data-collection change you asked about)

The Trial 2 plan in the report (static node + dual-radio hop truth) is correct. Strengthen it
into a pre-registered design:

14. **Controlled links:** ≥2 static beacon nodes at surveyed positions (one treeline, one
    valley/forest), each transmitting position beacons at a **fixed, recorded cadence with
    sequence numbers**. This gives PDR (denominators known) and clean distance–ESP pairs.
    Hop filtering: calibration set = rows with `hops_away == 0` only (collector now logs
    `hop_limit`/`hop_start`). Blacklist co-located devices; drop rows with RSSI > −20 dBm as
    physically implausible for >10 m links.
15. **Sample-size target — corrected 2026-07-13:** the original paragraph called for
    600–1,000 raw packets per stratum without checking field duration. At a fixed 30 s
    cadence that consumes 5–8.3 hours *per stratum* and is infeasible on this route. It
    also treated a heuristic autocorrelation multiplier as a power analysis without a
    specified covariance model. The amended plan targets ≥40 scheduled opportunities per
    primary stratum across independent full passes and reports exact counts. Packet-level
    Wilson intervals are descriptive only if independence is defensible; primary
    uncertainty must use whole-pass summaries or a pass/block-aware method. Smaller
    strata remain underpowered. A larger independent-sample claim
    requires a pilot-derived correlation structure and a prospective power calculation;
    raw packet count must never be presented as independent sample size.
16. **Protocol discipline:** GPS on both ends at ≥0.2 Hz; chrony/GPS time sync verified
    pre-departure (clock-offset audit artifact); pre-departure `head_readiness_report` gate;
    ≥2 repeat runs per segment (your own advisor-grade gate already requires this); fixed
    radio config pinned in the repo before the trial.
17. **Operational coverage endpoint:** define coverage as
    P(SOS message delivered end-to-end within 60 s | position), measured by scripted test
    messages at waypoints — not "heard any packet." This is the metric the State Park
    proposal actually needs, and it aligns with the P4 service-layer-availability
    methodology note (which is correct and should be kept verbatim).
18. **Scope amendment memo:** the proposal promises RSRP in the dataset; the repo correctly
    identifies LoRa-RSSI-vs-cellular-RSRP comparison as a category error. Write a half-page
    amendment (signed off by the advisor) replacing RSRP with service-layer availability +
    ESP, so the deliverables list and the methodology can't be played against each other at
    the defense.

### P4 — Items the committee will ask that the repo is silent on

19. **FCC Part 15 analysis (the proposal lists it as a KPI):** Meshtastic transmits on a
    single LoRa channel; it does not frequency-hop. §15.247 FHSS requires ≥50 hopping
    channels at 915 MHz, and the digital-transmission provision requires ≥500 kHz 6-dB
    bandwidth — LoRa at 250 kHz on one channel satisfies neither on its face. Document the
    actual compliance basis (conducted power, §15.249 limits, or the SX1262 module's FCC
    grant conditions) before proposing *fixed infrastructure* to a state agency. This needs
    a real answer, not a checkbox.
20. **Winter survivability:** the proposed relays sit at treeline on Mt. Washington (rime
    icing, 100+ mph winds, months of no solar). The $690 BOM has no engineering basis for
    year-round operation. Either scope the proposal to seasonal (May–Oct) deployment or add
    an environmental-hardening section with power budget math (panel tilt/icing derating,
    battery Wh at −30 °C).
21. **Mesh capacity / duty cycle:** the <30 s SOS latency target should be supported by an
    airtime calculation (SF11/250 kHz packet airtime × expected beacon load × 3-hop relay)
    showing channel utilization stays well under congestion collapse.

---

## Part 5 — Does the approach need to change?

**Keep:** the hardware/collection platform, the schema + provenance + gate architecture
(genuinely better engineering discipline than most academic field studies), the service-layer
availability framing for cross-technology comparison, the Trial 2 static-node/hop-count plan,
and the honest Trial-1 postmortem (its three structural gaps are correctly diagnosed).

**Rework (not restart):** the modeling/eval layer — from
"FSPL + invented terrain constants + in-sample mean-bias on contaminated opportunistic data"
to
"controlled-link ESP/PDR measurement → floating-intercept fit with blocked CV and bootstrap
CIs → ITM-on-real-DEM for all infrastructure claims."

**Drop or fix:** synthetic DEM masquerading as terrain features; uncited geology constants;
the vacuous 60 dB gate; the "zero dead zones" framing; the ITM label on an FSPL model.

The single most important sentence for the defense: *Trial 1 was a successful systems
shakedown that demonstrated the platform and exposed exactly which controls a propagation
measurement requires; Trial 2 implements those controls.* That is a strong, honest story —
stronger than any number currently in the artifacts.

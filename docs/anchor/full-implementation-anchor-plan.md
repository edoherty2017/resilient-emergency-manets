# MANET + AIRMap Full Implementation Anchor Plan

> **Anchor document:** This is the canonical execution plan for all future work on the three-repo MANET system. Any new task must map to a priority block, gate, and acceptance criterion in this file before execution.

**Goal:** Fully implement and operationalize the 7-module architecture (hardware ingest, DEM/topography, geology attenuation, AIRMap inference, dataset quality controls, error analytics, weather safety automation) across the existing three repositories with reproducible field validation.

**Architecture:** Runtime repos (`meshradio-head-runtime`, `meshradio-node-runtime`) are responsible for resilient data capture and transport. Research/orchestration repo (`resilient-emergency-manets`) is responsible for model pipelines, data contracts, quality gates, calibration, overlays, and reporting. Delivery is priority-gated and verification-first.

**Repos in scope:**
- `/home/doher/projects/manet/resilient-emergency-manets`
- `/home/doher/projects/manet/meshradio-head-runtime`
- `/home/doher/projects/manet/meshradio-node-runtime`

---

## 1) Non-Negotiable Sequencing Rules (Anchor Constraints)

1. **Data integrity before modeling:** No new inference logic may be promoted until ingest validation + schema pass rates meet Priority 1 exit gates.
2. **Fallback transparency required:** Any run that uses `rssi_dbm` fallback must mark this in artifacts and pass fallback-specific QA gates.
3. **Runtime-first safety:** Node/head runtime stability and spool reliability are required before advanced analytics expansions.
4. **Weather guard before full autonomy:** Autonomous field recommendations require weather/lightning guardrails enabled and tested.
5. **No cross-repo ownership drift:** Runtime repos do capture/transport only; modeling and analytics belong in `resilient-emergency-manets`.
6. **Priority and order over time:** Work is tracked by strict priority order, not by calendar estimate.

---

## 2) Repo Ownership Map (Source of Truth)

## `meshradio-head-runtime`
Owns:
- Serial/USB telemetry collection daemon and parsers
- Head-side systemd service/timer units
- Store-and-forward sync spool behavior
- Runtime diagnostics scripts for head node

Must not own:
- AIRMap model logic
- Calibration/evaluation metrics pipelines
- Visualization/report artifact generation

## `meshradio-node-runtime`
Owns:
- Field-node telemetry collection daemon and parsers
- Node-side systemd service/timer units
- Offline-first backlog/sync behavior
- Runtime diagnostics scripts for hiker nodes

Must not own:
- Model training/inference/calibration code
- Cross-trial analysis/reporting

## `resilient-emergency-manets`
Owns:
- Pipeline orchestration, feature recipes, model configs
- AIRMap inference/calibration/evaluation
- Dataset quality sentinel and anomaly detection
- Overlay/visualization artifacts and report outputs
- Validation plans, architecture docs, compliance/safety logic

---

## 3) Priority-Ordered Implementation Plan

## Priority 1: Telemetry Contract Hardening + Runtime Validation

**Objective:** Make ingest trustworthy and field-robust.

**Implementation scope:**
- Add explicit shared telemetry schema contract (required/optional fields, units, null policy) in `resilient-emergency-manets/docs/data-dictionary.md` + machine-readable schema file.
- Upgrade both runtime collectors to emit schema-conformant records and include deterministic parser status fields.
- Add strict GNSS sentence validation path (checksum-valid/invalid counters; malformed frame counters).
- Add field-ready script pack (detect device, verify field population, pass/fail matrix) and run against node + head.

**Target files:**
- `meshradio-head-runtime/scripts/telemetry_collector.py`
- `meshradio-node-runtime/scripts/telemetry_collector.py`
- `meshradio-head-runtime/scripts/telemetry_sync_spool.sh`
- `meshradio-node-runtime/scripts/telemetry_sync_spool.sh`
- `resilient-emergency-manets/docs/data-dictionary.md`
- `resilient-emergency-manets/scripts/validation/` (new)

**Exit gates (must all pass):**
- ≥ 99% records parse without fatal error over soak testing.
- Device-detect matrix prints PASS for expected serial devices on both nodes.
- Required telemetry fields population meets thresholds:
  - `timestamp_utc`: 100%
  - `trial_id`, `node_id`: 100%
  - `rssi_dbm` or `rsrp_dbm`: ≥ 95%
  - GPS (`lat`,`lon`): ≥ configured floor for active test windows
- Sync spool retries and backlog flush verified after induced network outage.

---

## Priority 2: DEM + Topography + Geology Loss Modules

**Objective:** Build physical-world feature layers feeding inference.

**Implementation scope:**
- Implement `dem-transformer` pipeline with terrain tile fetch/caching + route-window extraction.
- Implement feature generation for slope, aspect, elevation deltas, obstruction proxies.
- Implement `geology-loss` baseline attenuation model with configurable material classes.
- Add deterministic feature recipe versioning and provenance tags.

**Target files (new, in `resilient-emergency-manets`):**
- `scripts/dem_transformer.py`
- `scripts/geology_loss.py`
- `config/airmap/dem-sources.yaml` (extend)
- `config/airmap/model-baseline.yaml` (extend feature schema)
- `artifacts/features/` outputs

**Exit gates:**
- DEM extraction reproducible for fixed route/time window.
- Feature generation checksum/provenance stable across reruns.
- Geology-loss outputs produced for all modeled segments (no silent drops).

---

## Priority 3: AIRMap Inference Integration (Production Path)

**Objective:** Move from MVP calibration-only behavior to full inference pipeline.

**Implementation scope:**
- Integrate model inference runner (batch and live-trial modes).
- Preserve current fallback chain (`rsrp_dbm` preferred, `rssi_dbm` fallback) with explicit run labeling.
- Emit strict run manifests: model version/hash, feature recipe version, calibration version, input windows.
- Maintain current quality gates and extend for inference validity checks.

**Target files:**
- `resilient-emergency-manets/scripts/airmap_live_trial.py` (upgrade)
- `resilient-emergency-manets/scripts/airmap_dry_run.py` (upgrade)
- `resilient-emergency-manets/config/airmap/*.yaml`
- `resilient-emergency-manets/artifacts/airmap/live_trial/*`

**Exit gates:**
- End-to-end inference run completes with full provenance package.
- Join audit + metrics artifacts generated without schema drift.
- Quality gates block publication on insufficient sample count or malformed inputs.

---

## Priority 4: Dataset Sentinel + Error Quantifier Expansion

**Objective:** Harden trust in model outputs and isolate failure regimes.

**Implementation scope:**
- Implement dataset sentinel anomaly checks and quarantine labels.
- Expand error quantification to stratified environmental slices and confidence/uncertainty bands.
- Add outlier triage output that maps errors to route segments and conditions.

**Target files (new/extended):**
- `resilient-emergency-manets/scripts/dataset_sentinel.py`
- `resilient-emergency-manets/scripts/error_quantifier.py`
- `resilient-emergency-manets/docs/calibration-workflow.md` (extend)
- `resilient-emergency-manets/artifacts/airmap/live_trial/*` (new QA artifacts)

**Exit gates:**
- Sentinel flags are reproducible and traceable.
- Error reports include global + stratified + outlier diagnostics per run.
- PASS/FAIL decisioning is machine-readable and human-auditable.

---

## Priority 5: Weather Guard + Field Safety Automation

**Objective:** Enforce weather/lightning safety constraints in operational runs.

**Implementation scope:**
- Implement weather ingestion and nowcast checks for route/time windows.
- Encode safety state machine: normal / caution / hold.
- Gate model run recommendations and field alerts on weather risk state.

**Target files (new):**
- `resilient-emergency-manets/scripts/weather_guard.py`
- `resilient-emergency-manets/config/weather/*.yaml`
- `resilient-emergency-manets/artifacts/weather/*`

**Exit gates:**
- Safety state updates correctly from test weather scenarios.
- Hold state suppresses autonomous “go” recommendations.
- Safety decisions logged with timestamps + rationale.

---

## Priority 6: Integrated Field Trial + Release Cut

**Objective:** Validate full stack in field-like conditions and ship stable cut.

**Implementation scope:**
- Run integrated pipeline: runtime ingest → sync → feature build → inference → analytics → overlay → safety outputs.
- Generate release evidence pack with reproducibility commands and artifact index.
- Cut release branches/tags in all repos per your repo strategy.

**Exit gates:**
- Full dry-run and live-trial flows pass all mandatory gates.
- Artifact bundle complete and internally consistent.
- Release candidate branches/tags created and documented.

---

## 4) Standard Quality Gates (Applied Every Priority)

- **Schema gate:** No undocumented field changes.
- **Provenance gate:** Every artifact includes run metadata and commit ID.
- **Fallback gate:** `rssi_dbm` fallback runs explicitly marked.
- **Reliability gate:** Runtime services recover from serial disconnect/network outage.
- **Audit gate:** PASS/FAIL matrices emitted for device, field-population, and run quality.

---

## 5) Change-Control Protocol (How this remains the anchor)

Any new task must include:
1. Referenced priority number in this plan.
2. Files touched + repo ownership justification.
3. Acceptance criteria mapped to existing gates.
4. If sequence changes are requested, update this plan first, then execute.

---

## 6) Immediate Next Execution Queue (Strict Order)

1. Priority 1: Create machine-readable telemetry schema + validator.
2. Priority 1: Implement field validation script pack with PASS/FAIL matrix.
3. Priority 1: Patch head/node collectors for schema parity + parser status metrics.
4. Priority 1: Run soak + induced outage sync test and publish gate report.

---

## 7) Frontier Staging (One Expansion Per Node)

Rule used: treat each priority block as a tree node and expand it **one level** into immediate child tasks (new frontier). No deep decomposition yet.

### Priority 1 frontier (Telemetry Contract + Runtime Validation)
- P1-A: Define canonical telemetry schema (fields, units, nullability, enums).
- P1-B: Implement schema validator CLI + JSON report output.
- P1-C: Add parser status counters in both collectors (checksum_ok, checksum_bad, malformed_frame).
- P1-D: Build device/field population PASS/FAIL matrix script pack.
- P1-E: Run soak + outage recovery validation and publish gate summary.

### Priority 2 frontier (DEM + Geology)
- P2-A: Implement DEM source adapter + local tile cache.
- P2-B: Implement windowed terrain extraction along route/time segments.
- P2-C: Implement topographic feature generator (slope/aspect/elevation deltas).
- P2-D: Implement geology attenuation baseline with configurable material constants.
- P2-E: Add feature provenance manifest (recipe version + checksums).

### Priority 3 frontier (Inference Integration)
- P3-A: Standardize inference input contract from feature artifacts.
- P3-B: Integrate batch/live inference runner.
- P3-C: Enforce fallback labeling (`rsrp_dbm` preferred, `rssi_dbm` fallback).
- P3-D: Emit run manifests (model hash, config hash, data window, calibration version).
- P3-E: Extend quality gates for inference validity and publication blocking.

### Priority 4 frontier (Sentinel + Error Quantifier)
- P4-A: Implement anomaly detection pipeline + quarantine tagging.
- P4-B: Add stratified error metrics by route/environment strata.
- P4-C: Add outlier triage mapping (segment-level diagnostics).
- P4-D: Emit machine-readable PASS/FAIL decision artifact.
- P4-E: Add reproducibility checks for sentinel and quantifier outputs.

### Priority 5 frontier (Weather Guard)
- P5-A: Implement weather ingest adapter + normalized weather schema.
- P5-B: Implement risk state machine (normal/caution/hold).
- P5-C: Integrate risk gating into recommendation outputs.
- P5-D: Add lightning-delay buffer policy and audit fields.
- P5-E: Validate hold-state suppression in simulated hazard cases.

### Priority 6 frontier (Integrated Trial + Release)
- P6-A: Define end-to-end orchestration command sequence.
- P6-B: Generate integrated artifact index + evidence bundle format.
- P6-C: Run full dry-run and capture gate outcomes.
- P6-D: Run live-trial pipeline and compare against dry-run baselines.
- P6-E: Create release branches/tags and publish release notes/checklist.

---

## 8) Definition of Done (Program-Level)

Program is complete when:
- All 7 architecture modules are implemented and integrated.
- Runtime ingest is resilient under field outage conditions.
- Inference/calibration pipeline is reproducible and fully audited.
- Overlay and analytics outputs are decision-grade.
- Weather safety guardrails are active and enforceable.
- Release cuts exist across all 3 repos with evidence artifacts.

# TODO Anchor — resilient-emergency-manets

This repo owns orchestration, modeling, analytics, overlays, safety logic, and program documentation.

## Priority Order (Do in sequence)

## [P1] Telemetry contract + validator + validation pack integration
- [x] P1-A Define canonical telemetry schema (`docs/data-dictionary.md` + machine-readable schema).
- [x] P1-B Implement schema validator CLI with JSON output (`scripts/validation/schema_validate.py`).
- [x] P1-D Implement field validation scripts (device detect + field population + PASS/FAIL matrix) under `scripts/validation/`.
- [x] P1-E Create gate report template for soak/outage results (`artifacts/reports/p1_gate_report.md`).

## [P2] DEM + geology feature pipelines
- [x] P2-A Build DEM source adapter + tile cache (`scripts/dem_transformer.py`).
- [x] P2-B Build windowed route extraction.
- [x] P2-C Build topo feature generator (slope/aspect/elevation deltas).
- [x] P2-D Build geology attenuation baseline (`scripts/geology_loss.py`).
- [x] P2-E Emit feature provenance manifest (recipe version + checksums).

## [P3] AIRMap production inference integration
- [ ] P3-A Standardize inference input contract.
- [ ] P3-B Integrate batch/live inference runner (`scripts/airmap_live_trial.py`, `scripts/airmap_dry_run.py`).
- [ ] P3-C Enforce fallback labeling (`rsrp_dbm` preferred, `rssi_dbm` fallback).
- [ ] P3-D Emit run manifests (model/config/data/calibration hashes/versions).
- [ ] P3-E Extend publication quality gates.

## [P4] Dataset sentinel + error quantifier expansion
- [ ] P4-A Implement anomaly detection + quarantine (`scripts/dataset_sentinel.py`).
- [ ] P4-B Add stratified error metrics (`scripts/error_quantifier.py`).
- [ ] P4-C Add outlier triage mapping artifacts.
- [ ] P4-D Emit machine-readable PASS/FAIL decision artifact.
- [ ] P4-E Add reproducibility checks.

## [P5] Weather guard automation
- [ ] P5-A Implement weather ingest adapter + normalized schema (`scripts/weather_guard.py`).
- [ ] P5-B Implement risk state machine (normal/caution/hold).
- [ ] P5-C Gate recommendations on risk state.
- [ ] P5-D Add lightning delay-buffer policy + audit fields.
- [ ] P5-E Validate hold-state suppression under hazard simulations.

## [P6] Integrated trial + release evidence
- [ ] P6-A Define end-to-end orchestration command sequence.
- [ ] P6-B Generate artifact index + evidence bundle format.
- [ ] P6-C Run full dry-run and capture gate outcomes.
- [ ] P6-D Run live-trial and compare to dry-run baselines.
- [ ] P6-E Prepare release checklist + notes.

## Completion condition for this repo
- [ ] All P1–P6 items complete with artifacts committed and cross-repo gates satisfied.

# Release Checklist (P6)

> **Correction (2026-07-13):** `overall_ok: true` in an operational P6 run is not
> by itself a scientific-validity or calibration gate. A release with zero eligible
> rows, fallback inputs, synthetic features, noncanonical provenance, or warning-only
> calibration failures must not be promoted as validated evidence.

## Pre-flight
- [ ] HEAD + Hiker collectors running (`systemctl --user is-active`)
- [ ] Spool timers enabled (`telemetry_sync_spool.timer` on both nodes)
- [ ] Pull + watchdog cron jobs healthy on doher
- [ ] Ingest health report status is `OK`

## Data + model gates
- [ ] Schema validation reports refreshed for head + hiker
- [ ] Field-ready reports refreshed for head + hiker
- [ ] AIRMap dry run artifacts generated
- [ ] AIRMap live-trial artifacts generated
- [ ] Immutable raw-input paths and SHA-256 hashes recorded; HEAD GPX/time base present
- [ ] Direct-link and scheduled-opportunity eligibility enforced; eligible count > 0
- [ ] DEM/topography + geology features generated
- [ ] Dataset sentinel decision artifact generated
- [ ] Error quantifier global + stratified metrics generated
- [ ] Weather guard status generated
- [ ] Coverage overlay timeline + HTML generated

## Integrated gate
- [ ] `python3 scripts/p6_integrated_run.py --ingest-root /home/doher/manet_ingest --trial-id trial-live`
- [ ] `artifacts/release/p6_artifact_index.json` shows `overall_ok: true`
- [ ] Every scientific quality gate passes in strict/fail-closed mode; operational
      readiness and scientific eligibility are reported as separate decisions

## Tag + notes
- [ ] Review `artifacts/release/p6_runlog.json` for warnings
- [ ] Draft release notes with key metrics (MAE/RMSE, sample counts, gate outcomes)
- [ ] Verify a clean checkout can reproduce the bundle and hashes
- [ ] Create an immutable release tag only when all checks pass; preserve failed runs
      and later amendments rather than overwriting them

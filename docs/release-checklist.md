# Release Checklist (P6)

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
- [ ] DEM/topography + geology features generated
- [ ] Dataset sentinel decision artifact generated
- [ ] Error quantifier global + stratified metrics generated
- [ ] Weather guard status generated
- [ ] Coverage overlay timeline + HTML generated

## Integrated gate
- [ ] `python3 scripts/p6_integrated_run.py --ingest-root /home/doher/manet_ingest --trial-id trial-live`
- [ ] `artifacts/release/p6_artifact_index.json` shows `overall_ok: true`

## Tag + notes
- [ ] Review `artifacts/release/p6_runlog.json` for warnings
- [ ] Draft release notes with key metrics (MAE/RMSE, sample counts, gate outcomes)
- [ ] Create release tag and push when all checks pass

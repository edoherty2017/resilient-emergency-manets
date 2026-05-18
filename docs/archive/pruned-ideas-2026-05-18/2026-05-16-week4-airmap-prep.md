# Week 4 AIRMap Prep Checkpoint (2026-05-16)

## Intent
Prepare a reproducible AIRMap prediction + calibration workflow that can be validated against live field telemetry from `meshradiohead` and `meshhikernode1`.

## Entry Readiness (Current)
- Telemetry ingestion is active on both nodes.
- JSONL schema now includes non-null GNSS in new records (post collector patch).
- Storage guard is active (90% warn, 95% offload+verify+prune), reducing data-loss risk during Week 4 experimentation.

## Week 4 Execution Block (Research-Heavy)
1. **Prediction stack selection and constraints**
   - Select first-pass propagation baseline and document assumptions.
   - Pin model/version and feature recipe IDs for repeatability.
2. **Data contract definition**
   - Canonical join keys: `timestamp_utc`, `node_id`, `trial_id`, segment index/bin.
   - Prediction fields: expected RSSI/SNR/path-loss + uncertainty metadata.
   - Observation fields: measured RSSI/SNR/GNSS + QA tier.
3. **Config scaffolding**
   - Build `config/airmap/` templates with explicit metadata fields:
     - model name/version/hash
     - DEM source/resolution/datum
     - attenuation priors version
     - calibration constants version
4. **Calibration workflow draft**
   - Define pre/post-calibration comparison protocol.
   - Define residual export and outlier accounting requirements.
5. **Validation protocol**
   - Global + stratified MAE/RMSE by topography/weather/distance bin.
   - Require sample counts per stratum and outlier table.

## Required Outputs for Week 4 Exit
- `config/airmap/` template set committed.
- `docs/calibration-workflow.md` draft committed.
- First-pass prediction artifacts generated for planned trial AOIs.
- Reproducible command sequence documented end-to-end.

## Known Risks to Research Block
- Feature drift between telemetry preprocessing and prediction inputs.
- CRS/datum mismatch between DEM tiles and telemetry coordinates.
- Silent schema mismatch on join keys causing orphaned predictions.

## Immediate Next Actions (already started)
- [in progress] AIRMap research baseline and schema mapping.
- [pending] Calibration workflow document.
- [pending] Config templates under `config/airmap/`.
- [pending] Validation script/plan for MAE/RMSE.
- [in progress] First dry-run prediction pass with blocker capture.

## Dry-Run Blocker Snapshot (2026-05-16)
Initial toolchain checks showed missing dependencies. Re-check after provisioning:
- `g++`: present
- `make`: present
- `pip`: present (via Python virtual environment)
- Python geospatial/data modules: installed in `.venv` (`numpy`, `pandas`, `pyproj`, `rasterio`, `shapely`)
- `cmake`: present
- `gdalinfo`: present (GDAL 3.8.4)

Implication: blocker is cleared on this host for Python + CLI geospatial dependencies; first-pass prediction/calibration dry runs can proceed.

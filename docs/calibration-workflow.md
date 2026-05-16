# AIRMap Calibration Workflow (Week 4 Draft)

## Purpose
Define a reproducible prediction→observation calibration path for MANET RF performance in mountainous terrain, with explicit metadata pinning and join-key integrity.

## Scope
- Frequency regime: LoRa/Meshtastic-style sub-GHz links (field trial specific channel settings to be pinned in config).
- Terrain regime: NH Presidential Range trial AOIs.
- Model regime: first-pass terrain-aware baseline using ITM/Longley-Rice family assumptions, then calibrated with empirical trial telemetry.

## Source Notes (initial research)
- NTIA ITM model repo states applicability between **20 MHz and 20 GHz**, modeling free-space loss, diffraction, and troposcatter.
- SPLAT! documentation describes terrestrial path/terrain analysis over **20 MHz–20 GHz** and supports point-to-point and area analyses.
- Meshtastic protobuf `Position` encoding uses **1e-7 scaled lat/lon** semantics (already reflected in collector normalization).

## Canonical Data Contracts

### Observation Contract (from telemetry JSONL)
Current live keys present on both nodes:
- `timestamp_utc`
- `trial_id`
- `head_id`
- `node_id`
- `lat`, `lon`, `elev_m`
- `battery_mv`, `battery_pct`, `usb_power`, `is_charging`
- `rsrp_dbm`, `satellite_link_status`, `weather_tag`

### Prediction Contract (to generate)
Required fields for every predicted row:
- `timestamp_utc`
- `trial_id`
- `head_id`
- `node_id`
- `segment_id`
- `distance_m`
- `pred_path_loss_db`
- `pred_rssi_dbm`
- `pred_snr_db`
- `topography_class`
- `material_class`
- `model_name`, `model_version`, `model_hash`
- `feature_recipe_version`
- `calibration_version`

### Join Keys
Primary join keys:
1. `trial_id`
2. `head_id`
3. `node_id`
4. `timestamp_utc` (or nearest-neighbor snapped in bounded window)

Secondary deterministic key for aggregations:
- `segment_id`

## Workflow Steps
1. **Ingest + normalize observations**
   - Enforce schema and type checks.
   - Remove rows without valid geospatial coordinates for model fit set.
2. **Build terrain/material feature table**
   - Fetch DEM tiles for AOI.
   - Generate slope/relief/obstruction features.
   - Attach geology/material priors.
3. **Run first-pass prediction**
   - Execute pinned model with pinned feature recipe.
   - Emit prediction rows + metadata.
4. **Join predictions to observations**
   - Apply canonical keys and strict join audit.
   - Produce orphan report (missing prediction/missing observation).
5. **Calibrate**
   - Fit calibration constants against observed RF metrics.
   - Preserve pre-calibration and post-calibration predictions.
6. **Evaluate**
   - Compute global + stratified MAE/RMSE.
   - Produce outlier table and residual distributions.
7. **Freeze artifact set**
   - Save calibration constants, validation outputs, and reproducibility metadata.

## Mandatory QA Gates
1. **Version pinning gate**
   - Model/version/hash and feature recipe version must be present in outputs.
2. **Join integrity gate**
   - Orphan ratio must be reported and explained.
3. **Units/sign gate**
   - Explicit dB/dBm conventions documented in outputs.
4. **Stratified evidence gate**
   - MAE/RMSE reported with sample counts by stratum.

## Current Blockers (to resolve in Week 4 execution)
1. `rssi_dbm` and `snr_db` are not yet present in current observation JSONL schema snapshot; calibration target may need temporary use of available proxy metric (`rsrp_dbm`) until collector enrichment is added.
2. Need final command runner implementation for selected prediction engine.
3. Need fixed AOI/trial segment index generation script.

## Reproducibility Metadata (must ship with every run)
- `run_id`
- `git_commit`
- `model_name`, `model_version`, `model_hash`
- `feature_recipe_version`
- `dem_source`, `dem_resolution`, `dem_datum`, `crs`
- `attenuation_priors_version`
- `calibration_version`
- `generated_at_utc`

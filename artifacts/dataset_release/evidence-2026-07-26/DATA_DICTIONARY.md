# RF Dataset Release evidence-2026-07-26 — Data Dictionary

| Column | Unit | Description |
|---|---|---|
| `timestamp_utc` | ISO-8601 UTC | Observation timestamp |
| `trial_id` | id | Trial/run grouping |
| `node_id` | id | Receiving node |
| `head_id` | id | Head aggregation target |
| `from_mesh_id` | id | Source mesh node of the packet |
| `segment_id` | id | Deterministic per-row segment key |
| `lat` | deg | HEAD latitude (decimal degrees) |
| `lon` | deg | HEAD longitude (decimal degrees) |
| `src_lat` | deg | Source node latitude |
| `src_lon` | deg | Source node longitude |
| `distance_m` | m | 3D slant link distance (source→head) |
| `distance_source` | enum | How distance was derived (source_to_head_gps is calibration-grade) |
| `hops_away` | count | Mesh relay hops (0 = direct link) |
| `rssi_dbm` | dBm | Received signal strength (last hop) |
| `snr_db` | dB | Signal-to-noise ratio |
| `obs_esp_dbm` | dBm | Effective signal power = RSSI+SNR−10log10(1+10^(SNR/10)) |
| `obs_target_dbm` | dBm | Calibration observable (ESP when available, else RSSI) |
| `obs_target_source` | enum | Which metric obs_target_dbm came from |
| `pred_path_loss_fspl_db` | dB | Free-space path loss baseline |
| `pred_path_loss_itm_db` | dB | Longley-Rice ITM path loss over real DEM (when computed) |
| `pred_rssi_dbm` | dBm | Predicted RSSI from the selected baseline model |
| `predictor` | enum | Baseline predictor used (fspl|itm) |
| `topography_class` | enum | alpine_ridge | sub_alpine | valley_forest |
| `distance_bin` | enum | Distance stratum |
| `weather_tag` | enum | Weather state (from weather feed or field log) |
| `satellite_link_status` | enum | Starlink link state when available |
| `time_bin` | enum | Local-time bin (America/New_York) |
| `calibration_eligible` | bool | Passed the calibration eligibility gate |
| `src_pos_staleness_s` | s | Age of the source position fix used for distance |

**Tiers:** `rf_dataset_all.*` is every joined observation (QA view). `rf_dataset_calibration_grade.csv` is the subset with `calibration_eligible == true` — the only rows valid for path-loss calibration. Use the latter for any modeling claim.
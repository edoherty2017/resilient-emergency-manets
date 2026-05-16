# AIRMap Research Notes — 2026-05-16

## Objective
Establish a defensible first-pass propagation + calibration stack for Week 4 execution.

## Findings (initial pass)

1. **ITM / Longley-Rice suitability**
   - NTIA ITM repository documents applicability for terrestrial propagation from **20 MHz to 20 GHz** and includes free-space loss, diffraction, and troposcatter mechanisms.
   - Relevance: aligns with terrain-aware baseline needs for mountainous MANET paths.
   - Source: https://raw.githubusercontent.com/NTIA/itm/master/README.md

2. **SPLAT! as practical terrain RF engine option**
   - SPLAT! documentation describes terrestrial RF path and terrain analysis and states usage across **20 MHz–20 GHz**.
   - Relevance: candidate engine for reproducible first-pass path predictions if ITM wrapper is not immediately available.
   - Source: https://www.qsl.net/kd2bd/splat.html and https://raw.githubusercontent.com/jmcmellen/splat/master/README

3. **Meshtastic coordinate encoding confirmation**
   - Meshtastic protobuf `Position` comments indicate lat/lon are scaled by **1e-7**.
   - Relevance: validates current collector normalization strategy for GPS join integrity.
   - Source: https://raw.githubusercontent.com/meshtastic/protobufs/master/meshtastic/mesh.proto

4. **USGS 3DEP DEM programmatic access confirmed**
   - National Map API responds with 3DEP/NED product metadata for tile discovery.
   - Relevance: supports reproducible terrain feature generation for AIRMap inputs.
   - Source: https://tnmaccess.nationalmap.gov/api/v1/products

## Immediate Design Decisions
- Use ITM/Longley-Rice-style baseline assumptions for Week 4 model contract.
- Keep prediction schema independent of any one engine to allow ITM/SPLAT swap.
- Pin metadata fields up-front (`model_hash`, `feature_recipe_version`, `calibration_version`).

## Open Questions for next research pass
1. Which executable path is fastest to production here: direct NTIA ITM build, py wrapper, or SPLAT CLI?
2. Which weather/climate parameterization is most defensible for Presidential Range spring/summer trial windows?
3. What exact distance/binning scheme should be used for stratified residual reporting?
4. How should we map geology priors into attenuation constants before first calibration fit?

## Week 4 Artifacts Started
- `docs/calibration-workflow.md`
- `config/airmap/model-baseline.yaml`
- `config/airmap/dem-sources.yaml`
- `config/airmap/calibration-and-eval.yaml`

## Known Blocker
Current observation JSONL snapshot includes `rsrp_dbm` but not explicit `rssi_dbm`/`snr_db`; may require collector enrichment or temporary proxy target policy for early calibration passes.

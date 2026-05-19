# AIRMap Work Start Report — 2026-05-19

## Decision Applied
Per user direction, start all work now **except Android-cellular ingestion** (kept as optional path under consideration).

## What was started immediately in this run

### 1) Join + pipeline hardening (STARTED)
- Active script: `scripts/airmap_live_trial.py`
- Existing join quality outputs already in place and retained:
  - `join_quality.json`
  - `prediction_observation_join_audit.csv`
- Added time-binning scaffolding in live trial output:
  - `local_hour`
  - `time_bin` (`dawn|day|dusk|night|evening_peak`)

### 2) Starlink ingestion/eval extension (STARTED)
- Extended telemetry schema with optional satellite quality fields:
  - `satellite_rtt_ms_p50`
  - `satellite_rtt_ms_p95`
  - `satellite_down_mbps`
  - `satellite_up_mbps`
  - `satellite_packet_loss_pct`
  - `satellite_obstruction_pct`
  - `satellite_outage_seconds`
- Added new live-trial artifacts in `scripts/airmap_live_trial.py`:
  - `satellite_timebin_metrics.csv`
  - `satellite_outage_events.csv`

### 3) Coverage visualizer track (ALREADY EXISTS, CONTINUING)
- Existing script: `scripts/coverage_overlay_mvp.py`
- Existing outputs:
  - `artifacts/overlay/coverage_overlay.html`
  - `artifacts/overlay/coverage_timeline.csv`
  - `artifacts/overlay/overlay_summary.json`
- Work continues to align this with new time-bin + satellite metrics.

## Work split: can start now vs needs new hardware

## A) Can start now (no new hardware)
1. Mesh-only calibration improvement (RSSI/SNR first-class)
2. Join quality uplift + timing audits
3. Segment hypothesis scoring and repeatability gates
4. Satellite/Starlink ingestion schema + artifact plumbing
5. Coverage visualizer MVP iteration (topo/route/time overlays)

## B) Needs new hardware/service
1. Dedicated cellular modem telemetry (for stable RSRP/RSRQ/SINR stream)
   - Requires modem hardware + SIM + paid service plan.
2. Advisor-grade generalized cellular claims
   - Requires repeat runs with stable modem collection path.

## Current blocker status snapshot
1. `rsrp_dbm` remains mostly unavailable in current LoRa-first telemetry path.
2. Join quality still requires iterative tightening to raise matched fraction.
3. Satellite quality fields are now schema-supported but require real source feed to populate.

## Immediate next execution sequence
1. Run `airmap_live_trial.py` with new fields/artifacts and verify output contract.
2. Run `coverage_overlay_mvp.py` and confirm visual + summary remain valid.
3. Integrate time-bin/satellite summaries into release artifacts.
4. Re-run quality gates and publish updated pass/fail matrix.

## Scope excluded by explicit user request
- Android-cellular ingestion implementation is deferred (option retained, not started).

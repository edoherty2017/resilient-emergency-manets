# Live Ingestion Checkpoint — 2026-05-16

## Purpose
Checkpoint after SSH transport restoration to re-validate telemetry ingestion before resuming T4/T5 reporting work.

## A) Dual-Node Ingestion Smoke Test

### Test Context
- Operator host: `LVL3-DSK` (`doher`)
- Targets:
  - `meshradiohead` (`MeshRadioHead`)
  - `meshhikernode1` (`MeshHikerNode1`)
- Access mode: non-interactive SSH (`BatchMode=yes`)

### Results (PASS/FAIL)
| Check | meshradiohead | meshhikernode1 |
|---|---|---|
| SSH batch login | PASS | PASS |
| `/dev/lora_radio` present | PASS (`-> ttyUSB0`) | PASS (`-> ttyUSB1`) |
| Collector process present (`telemetry_collector.py`) | PASS | PASS |
| Service state named `telemetry_collector_head.service` | PASS (`active`) | FAIL (`inactive`) |
| 8s raw serial bytes at 115200 | 0 bytes | 0 bytes |
| Recent JSONL telemetry records present | PASS | PASS |

### Interpretation
- Both nodes are reachable and running collector process(es), with recently written telemetry JSONL files.
- Short direct serial sniff windows returned 0 bytes; classify as **detected but not streaming in this capture window** (not disconnected).
- On hiker node, service naming/state likely differs from head-side unit naming; collector process still running.

## B) Required Field Parity Check (Last 500 Records per Node)

Required fields:
- `timestamp_utc`, `trial_id`, `node_id`, `head_id`
- `lat`, `lon`, `elev_m`
- `rssi_dbm`, `snr_db`, `rsrp_dbm`
- `satellite_link_status`, `weather_tag`

### meshradiohead parity
- Present+nonnull: `timestamp_utc`, `trial_id`, `node_id`, `head_id`, `satellite_link_status`, `weather_tag`
- Intermittent present+nonnull: `rssi_dbm` (82/500), `snr_db` (97/500)
- Present but null: `lat`, `lon`, `elev_m`, `rsrp_dbm`

### meshhikernode1 parity
- Present+nonnull: `timestamp_utc`, `trial_id`, `node_id`, `head_id`
- Intermittent present+nonnull: `rssi_dbm` (102/500), `snr_db` (126/500)
- Missing in sampled records: `lat`, `lon`, `elev_m`, `rsrp_dbm`, `satellite_link_status`, `weather_tag`

## C) Next Documentation/Reporting Work (T4/T5 Continuation)

1. **Schema parity hardening note (immediate)**
   - Align hiker collector output keys with required schema (`satellite_link_status`, `weather_tag`, and nullable geo keys at minimum).
2. **GNSS integration checkpoint**
   - Add explicit status section for GNSS fix pipeline and expected non-null rates before field campaign windows.
3. **T4 method update inputs**
   - Use this checkpoint as precondition evidence for trial-readiness section in reporting artifacts.
4. **Failure-matrix seed evidence**
   - Carry forward observed pattern: collector running while short serial windows are quiet.

## Recommended Immediate Entry Criteria Before New Field Capture
- Both node collectors managed by explicit systemd user units with known names and `active` state.
- Last-500-record parity script returns required key presence on both nodes.
- At least one validation window with non-null geospatial fields (`lat`, `lon`, `elev_m`) per node.

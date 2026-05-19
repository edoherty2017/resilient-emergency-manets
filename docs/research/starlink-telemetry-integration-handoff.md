# Starlink Telemetry Integration Handoff (Live Capture Only)

## Objective
Integrate **live Starlink telemetry capture** into MANET AIRMap field trials so that existing telemetry and evaluation outputs can be populated with real satellite quality evidence:

- `satellite_rtt_ms_p50`
- `satellite_rtt_ms_p95`
- `satellite_down_mbps`
- `satellite_up_mbps`
- `satellite_packet_loss_pct`
- `satellite_obstruction_pct`
- `satellite_outage_seconds`

and downstream artifacts continue to work unchanged:

- `satellite_timebin_metrics.csv`
- `satellite_outage_events.csv`

Primary purpose is **engineering validation + data quality calibration evidence** (not generalized claims yet), with explicit **time-of-day risk tracking**.

---

## Non-goals
1. No Starlink backhaul architecture work.
2. No SSH/Tailscale/network-access setup patterns.
3. No changes to LoRa transport assumptions.
4. No advisor-grade causal claims about Starlink performance until repeatability gates are met.

---

## Current repo/pipeline constraints (verified)
- Repo: `/home/doher/projects/manet/resilient-emergency-manets`
- Live trial script already consumes optional sat fields and emits sat artifacts:
  - `scripts/airmap_live_trial.py`
  - outputs include `satellite_timebin_metrics.csv`, `satellite_outage_events.csv`
- Telemetry schema already supports optional sat fields with ranges:
  - `schemas/telemetry.schema.json`
- Existing context:
  - LoRa-first field trials
  - no dependable cellular modem RSRP path currently
  - workflow includes `local_hour` and `time_bin` (`dawn|day|dusk|evening_peak|night`)
  - current framing is engineering validation while data quality is improved

---

## Telemetry field contract (collector-facing)
Use `null` when unknown/unavailable; never emit sentinel strings for numeric fields.

| Field | Type | Range | Source derivation rule |
|---|---:|---:|---|
| `satellite_link_status` | string/null | enum-ish | Map Starlink state to `connected` / `degraded` / `disconnected` / `unknown` |
| `satellite_rtt_ms_p50` | number/null | 0..100000 | p50 of RTT samples in window (from Starlink history ping latency, drop<1) |
| `satellite_rtt_ms_p95` | number/null | 0..100000 | p95 RTT in window (from per-second latency where available) |
| `satellite_down_mbps` | number/null | 0..10000 | window mean down throughput (bps→Mbps) |
| `satellite_up_mbps` | number/null | 0..10000 | window mean up throughput (bps→Mbps) |
| `satellite_packet_loss_pct` | number/null | 0..100 | from `total_ping_drop/samples * 100` over window |
| `satellite_obstruction_pct` | number/null | 0..100 | `fraction_obstructed * 100` when available |
| `satellite_outage_seconds` | number/null | 0..86400 | count of seconds in window with full drop or disconnected state |

### Windowing contract
- Recommended base poll: **15 s** for status + history stats.
- Aggregation window for telemetry row enrichment: **60 s tumbling** (default), configurable.
- Hard rule from Starlink history behavior: poll interval must be `<900 s` to avoid history loss.

---

## Data collection options comparison

| Method | Hardware/account prerequisites | Available fields (for our schema) | Cadence limits | Field/offline reliability | Legal/ToS risk | Pi complexity | Schema fit |
|---|---|---|---|---|---|---|---|
| **A. Dish local gRPC (recommended)** via `192.168.100.1:9200` using `starlink-grpc-tools` (`dish_grpc_text.py`) | Device must be L2/L3-reachable to dish mgmt IP; no cloud dependency. Location requires explicit app toggle + login once. | RTT, throughput, packet loss, state, obstruction fraction, alerts; enough to compute all required sat fields. | 1–60 s practical; must remain `<900 s` for history continuity. | Best in field; works without internet/cloud as long as local dish interface reachable. | **Medium**: unofficial/undocumented API use, but widely used read-only telemetry. | Medium | **Excellent** |
| **B. Starlink app/manual debug export** (mobile app/UI) | Logged-in app session; operator action needed. | Rich status snapshots, but not robust streaming feed. | Human/manual; not deterministic. | Poor for unattended trials. | Low-Med (official app path, but no stable automation API). | Low for manual, High for automation | Weak |
| **C. Router/admin HTTP surfaces scraping** (`http://192.168.100.1` UI reverse parsing) | Local access to router UI responses; firmware-dependent. | Some status indicators; usually incomplete for p50/p95 and packet loss history. | Unstable with UI changes; no contract. | Fragile in field updates. | Medium-High (unsupported scraping). | Medium-High | Partial |
| **D. Cloud/account portal scraping/API guessing** | Active internet + account session/auth; uncertain APIs. | Potential usage stats, often delayed/coarse; not per-second trial telemetry. | Not suitable for near-real-time. | Poor when backhaul intermittent. | High (auth + anti-automation + unclear permissions). | High | Poor |
| **E. Active speed-test hook (Ookla/librespeed/iperf) over Starlink path** | Internet endpoint + test server; consumes bandwidth/power. | Can derive down/up + latency under load, but does not expose obstruction/outage internals. | Should be sparse (e.g., 5–15 min) to avoid distorting network. | Useful as calibration side-channel only. | Low-Med | Medium | Complementary only |

---

## Recommended architecture

## MVP (P1): local dish gRPC collector + telemetry enricher

### Process topology
1. **starlink_raw_poller.py** (new)
   - Polls dish every 15 s:
     - `status`
     - `ping_drop`, `ping_latency`, `usage` (history stats mode)
   - Writes append-only JSONL:
     - `artifacts/starlink/raw/starlink_status_history.jsonl`
2. **starlink_window_aggregator.py** (new)
   - Reads raw JSONL stream.
   - Maintains 60 s tumbling windows.
   - Emits normalized sat telemetry JSONL:
     - `artifacts/starlink/derived/starlink_window_metrics.jsonl`
3. **merge_starlink_into_telemetry.py** (new)
   - As-of join by UTC timestamp onto node/head telemetry stream.
   - Writes enriched telemetry JSONL/CSV used by AIRMap pipeline.
4. Existing `scripts/airmap_live_trial.py`
   - Runs unchanged and now receives populated sat fields.

### Field mapping (exact)
- `satellite_link_status`:
  - `CONNECTED` -> `connected`
  - `OBSTRUCTED`, `NO_PINGS`, `SLOW/THROTTLED-like alerts` -> `degraded`
  - `SEARCHING`, `NO_SATS`, `NO_DOWNLINK`, unreachable -> `disconnected`
  - else `unknown`
- `satellite_packet_loss_pct` = `(total_ping_drop / samples) * 100`
- `satellite_down_mbps` = `download_usage_bytes * 8 / window_seconds / 1e6` (if using usage stats) OR mean `downlink_throughput_bps/1e6` when available.
- `satellite_up_mbps` similarly.
- `satellite_rtt_ms_p50`:
  - Prefer window median of `pop_ping_latency_ms` valid samples;
  - fallback `mean_full_ping_latency` if only aggregate present.
- `satellite_rtt_ms_p95`:
  - Compute from per-sample latency where present;
  - otherwise null (do not fake from mean).
- `satellite_obstruction_pct` = `fraction_obstructed * 100` when available.
- `satellite_outage_seconds`:
  - count of seconds with full ping drop (`drop==1`) + disconnected-state seconds in window.

### CSV/log outputs (pipeline compatible)
- Keep existing AIRMap outputs untouched.
- Add Starlink-specific operational outputs:
  - `artifacts/starlink/raw/starlink_status_history.jsonl`
  - `artifacts/starlink/derived/starlink_window_metrics.jsonl`
  - `artifacts/starlink/derived/starlink_window_metrics.csv`
  - `artifacts/starlink/qc/starlink_collection_health.csv` (poll success, gap seconds, parse errors)

---

## Hardened phase (P2+)

### P2: reliability + clock integrity
- Run collectors under `systemd` with restart policy.
- Persist monotonic sequence IDs per poll.
- Add `chrony` monitoring and write per-row `clock_offset_ms` in collector QC logs.
- Gap-filling policy: explicit nulls + `collector_status` flags (never interpolated latency).

### P3: optional active test calibration lane
- Add low-duty active probes (ICMP/HTTPS to fixed targets) every 5–15 min.
- Store separately so probes do not contaminate passive sat quality interpretation.

### P4: model-facing time-of-day risk evidence
- Add reproducible report slice generation by `time_bin × topography_class` using populated sat fields.
- Gate any broad claims on repeat runs and matched weather tags.

---

## Practical implementation notes (Pi + field operations)

1. **Use starlink-grpc-tools as dependency baseline**
   - Supports status/history/bulk modes and CSV/text output.
   - Documented local dish target is `192.168.100.1`.
2. **Polling discipline**
   - 15 s status+history stats default.
   - never exceed 900 s history poll interval.
3. **Unreachable handling**
   - On RPC failure, emit heartbeat row with `satellite_link_status=disconnected`, numeric fields null, plus error code.
4. **Timestamping**
   - Use UTC ISO-8601 from collector host at poll receive time.
   - Keep `local_hour`/`time_bin` derivation in existing AIRMap stage.
5. **Obstruction data caveat**
   - Some obstruction subfields are obsolete in newer firmware; use `fraction_obstructed` where still reported and tolerate null.
6. **Location data**
   - Optional; requires explicit Starlink app setting “allow access on local network”. Not required for schema sat fields.

---

## Validation checklist and acceptance gates

## Functional gates
- [ ] Collector can run 60+ minutes in field with no crash.
- [ ] Raw JSONL row count aligns with poll cadence (>=95% expected rows).
- [ ] At least 5 of 7 sat numeric fields populated (non-null) during connected periods.
- [ ] `scripts/airmap_live_trial.py` runs unchanged with enriched telemetry.
- [ ] `satellite_timebin_metrics.csv` and `satellite_outage_events.csv` generated and non-empty when outages occur.

## Data quality gates
- [ ] `satellite_packet_loss_pct` always within [0,100].
- [ ] Throughput fields non-negative and realistic (<1000 Mbps expected for field kit).
- [ ] Outage seconds in each window <= window length.
- [ ] Timestamp monotonicity and max join skew to node telemetry <= configured tolerance (default 5 s).

## Reliability gates
- [ ] Collector restart survives dish reboot/unreachable episodes.
- [ ] QC log explicitly records telemetry gaps and RPC failures.

---

## Open risks / questions for advisor review
1. **API stability risk**: Starlink gRPC is unofficial and may change with firmware.
2. **Policy/ToS ambiguity**: read-only local polling is common, but still unofficial; confirm acceptable-use posture for project publication.
3. **Obstruction semantics drift**: `fraction_obstructed` interpretation may vary by firmware; treat as relative indicator.
4. **RTT percentile fidelity**: if only aggregate latency is available at times, p95 may be sparse/null.
5. **Observer effect**: active speed tests can bias measured link quality; keep strictly separate from passive telemetry.
6. **Clock quality**: field host time drift can corrupt as-of joins; chrony status should be part of run QA.

---

## Recommended implementation plan (P1..Pn)

### P1 — Baseline collector integration (1–2 days)
- Vendor/install `starlink-grpc-tools` in project venv.
- Create `scripts/starlink_raw_poller.py` wrapper to call tool or module API and normalize output.
- Create `scripts/starlink_window_aggregator.py` to compute schema fields every 60 s.
- Produce raw + derived artifacts under `artifacts/starlink/`.

### P2 — Telemetry merge + AIRMap compatibility (1 day)
- Create `scripts/merge_starlink_into_telemetry.py` (as-of UTC join).
- Write enriched stream to staging path consumed by existing AIRMap scripts.
- Verify `scripts/airmap_live_trial.py` outputs include expected sat metrics/events.

### P3 — Operational hardening (1 day)
- Add systemd unit files for poller + aggregator.
- Add health/QC logging and gap alarms.
- Add runbook docs for start/stop/recover procedures.

### P4 — Evidence packaging (ongoing)
- Add repeat-run comparison notebook/script by `time_bin/topography_class`.
- Keep language as engineering validation until repeatability gates pass.

---

## First 10 concrete commands/scripts for the new agent

1. `cd /home/doher/projects/manet/resilient-emergency-manets`
2. `python3 -m venv .venv && source .venv/bin/activate`
3. `pip install -U pip wheel`
4. `pip install pandas numpy pyyaml grpcio grpcio-tools`
5. `git clone --depth 1 https://github.com/sparky8512/starlink-grpc-tools /tmp/starlink-grpc-tools`
6. `pip install -r /tmp/starlink-grpc-tools/requirements.txt`
7. `python /tmp/starlink-grpc-tools/dish_grpc_text.py -t 15 status ping_drop ping_latency usage -O artifacts/starlink/raw/starlink_poll.csv`
8. **Create** `scripts/starlink_raw_poller.py` (wrap/normalize CSV->JSONL with UTC timestamps + error rows).
9. **Create** `scripts/starlink_window_aggregator.py` (60 s windows -> required sat schema fields -> `artifacts/starlink/derived/starlink_window_metrics.jsonl/csv`).
10. **Create** `scripts/merge_starlink_into_telemetry.py` and run:  
   `python scripts/merge_starlink_into_telemetry.py --telemetry /home/doher/manet_ingest/meshhikernode1/jsonl/telemetry_stream.jsonl --starlink artifacts/starlink/derived/starlink_window_metrics.jsonl --out artifacts/starlink/derived/telemetry_enriched_starlink.jsonl`

---

## Appendix: source grounding used for this handoff
- Local project files verified:
  - `schemas/telemetry.schema.json`
  - `scripts/airmap_live_trial.py`
  - `docs/calibration-workflow.md`
  - `docs/status/2026-05-19-airmap-work-start-report.md`
- Starlink telemetry capability references inspected:
  - `starlink-grpc-tools` README and `starlink_grpc.py` field documentation (status/history/obstruction/location/polling behavior).

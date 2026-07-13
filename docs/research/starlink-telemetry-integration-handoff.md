# Starlink Telemetry Integration Handoff (Historical Design Record)

> **Status (2026-07-13): historical, not an executable runbook.** This file
> records the design that preceded the hardened implementation. The current
> deployment and verification authority is
> `meshradio-head-runtime/README.md`, `ops/provision_head2.sh`, and the scripts
> and units installed from `meshradio-head-runtime`. Historical paths, package
> commands, API-field assumptions, and unchecked gates below are not evidence
> that the integration is deployed or has passed a field trial.
>
> Current safety corrections: an RPC failure means **measurement status
> unknown**, not a proved dish disconnect; the external gRPC dependency must be
> installed from a reviewed full 40-character commit; and Phase 2/AIRMap work
> must not treat a prior design checkbox or stale report as a current PASS.

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

## Repo/pipeline constraints at handoff time (historical)
- Historical development checkout: `/home/doher/projects/manet/resilient-emergency-manets`.
  This is not the deployed runtime path.
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
- Aggregation target for telemetry row enrichment: **four complete polls / 60 s**
  at the default cadence. The implementation records both the 60 s target and
  the actually observed first-to-last poll span; it must not represent a
  polling batch as 60 seconds of continuously observed data.
- Hard rule from Starlink history behavior: poll interval must be `<900 s` to avoid history loss.

---

## Data collection options comparison

| Method | Hardware/account prerequisites | Available fields (for our schema) | Cadence limits | Field/offline reliability | Legal/ToS risk | Pi complexity | Schema fit |
|---|---|---|---|---|---|---|---|
| **A. Dish local gRPC (selected design)** via `192.168.100.1:9200` using a pinned `starlink-grpc-tools` revision | Device must be L2/L3-reachable to dish mgmt IP; no cloud dependency. Location requires explicit app toggle + login once. | Candidate source for RTT, throughput, packet loss, state, obstruction fraction, and alerts. Exact fields are version-sensitive and must be verified against the pinned revision and live dish firmware. | 1–60 s practical; must remain `<900 s` for history continuity. | Intended to work without internet/cloud while the local dish interface is reachable; this still requires field proof. | **Medium**: unofficial/undocumented API use, with policy and stability risk. | Medium | Potentially excellent; field-gated |
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
   - Aggregates complete four-poll batches at the default cadence and records
     target duration separately from observed poll span.
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
  - explicit dish states such as `SEARCHING`, `NO_SATS`, `NO_DOWNLINK` may map
    to `disconnected` only when the pinned API revision exposes and documents
    that state consistently
  - RPC timeout/unreachable/parse failure -> `unknown` with
    `_measurement_status=error` and `_heartbeat=true` (never infer a physical
    disconnect from collector failure)
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
   - Use only a reviewed, full 40-character commit and record the resolved
     commit plus Python package freeze in `/opt/manet/software-manifest`.
   - Field names and response shapes are unofficial/version-sensitive; prove
     them against that exact revision and the live firmware.
   - The expected local dish target is `192.168.100.1:9200`, subject to a live
     reachability check.
2. **Polling discipline**
   - 15 s status+history stats default.
   - never exceed 900 s history poll interval.
3. **Unreachable handling**
   - On RPC failure, emit a heartbeat row with
     `satellite_link_status=unknown`, numeric fields null,
     `_measurement_status=error`, and an error code. Collector reachability is
     not evidence of the physical link state.
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
- [ ] The **latest fresh contiguous run** spans 60+ minutes in the field.
- [ ] At least 95% of consecutive intervals align with the configured poll
      cadence; timestamps are strict UTC, unique, and monotonically increasing.
- [ ] At least 95% of rows are real successful measurements with a recognized
      state (`connected|degraded|disconnected`), not timed error heartbeats.
- [ ] At least 95% of rows have acceptable clock-integrity evidence.
- [ ] The last 60 minutes of the poller error log is empty and parseable.
- [ ] `scripts/airmap_live_trial.py` runs unchanged with enriched telemetry.
- [ ] `satellite_timebin_metrics.csv` and `satellite_outage_events.csv` generated and non-empty when outages occur.

## Data quality gates
- [ ] `satellite_packet_loss_pct` always within [0,100].
- [ ] Throughput fields non-negative and realistic (<1000 Mbps expected for field kit).
- [ ] Outage seconds in each window <= window length.
- [ ] Timestamp monotonicity and max join skew to node telemetry <= configured tolerance (default 5 s).
- [ ] Trial/node identity matches exactly across raw, derived, and MANET input;
      the merge achieves its configured match threshold (95% by default).

## Reliability gates
- [ ] Collector restart survives dish reboot/unreachable episodes.
- [ ] QC log explicitly records telemetry gaps and RPC failures.
- [ ] `python3 /opt/manet/head/scripts/starlink_phase1_gate.py` produces a new
      PASS from current evidence. No earlier report or checkbox substitutes for
      rerunning this gate.

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

### P2 — Telemetry merge + AIRMap compatibility (historical estimate)
- Create `scripts/merge_starlink_into_telemetry.py` (as-of UTC join).
- Write enriched stream to staging path consumed by existing AIRMap scripts.
- Verify `scripts/airmap_live_trial.py` outputs include expected sat metrics/events.
- Start this phase only after the current Phase 1 gate passes on new field
  evidence; implementation existence is not measurement validation.

### P3 — Operational hardening (1 day)
- Add systemd unit files for poller + aggregator.
- Add health/QC logging and gap alarms.
- Add runbook docs for start/stop/recover procedures.

### P4 — Evidence packaging (ongoing)
- Add repeat-run comparison notebook/script by `time_bin/topography_class`.
- Keep language as engineering validation until repeatability gates pass.

---

## Historical bootstrap commands (superseded; do not execute)

The original commands cloned an unpinned repository into `/tmp`, installed
unreviewed current dependencies, wrote to development paths, and bypassed the
deployed ownership/service model. They are intentionally retired.

Use `ops/provision_head2.sh` from the reviewed workspace with
`STARLINK_GRPC_COMMIT` set to a reviewed full 40-character commit. The current
layout is:

- root-owned runtime: `/opt/manet/head/scripts`
- root-owned dependency checkout: `/opt/manet/vendor/starlink-grpc-tools`
- root-owned dependency environment: `/opt/manet/venvs/starlink`
- mutable evidence (owned by `pump`): `/home/pump/telemetry_head`
- deployment manifest: `/opt/manet/software-manifest`
- site configuration: root-owned `/etc/manet/head.env`

After provisioning and configuring the site-specific destination and strict
SSH host key, run the head readiness report and current Phase 1 gate. Their
PASS outputs are prerequisites, not generated evidence by themselves.

---

## Appendix: source grounding used for this handoff
- Local project files verified:
  - `schemas/telemetry.schema.json`
  - `scripts/airmap_live_trial.py`
  - `docs/calibration-workflow.md`
  - `docs/status/2026-05-19-airmap-work-start-report.md`
- Starlink telemetry capability references inspected:
  - `starlink-grpc-tools` README and `starlink_grpc.py` field documentation (status/history/obstruction/location/polling behavior).

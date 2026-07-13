# TODO Anchor — resilient-emergency-manets

This anchor was pruned to active, execution-critical items only.

## Priority Order (strict)

## [P1] Data contract + validation gates (must stay green)
- [x] Canonical telemetry schema and validator CLI exist.
- [x] Validation pack and gate report template exist.
- [x] Run cross-repo *schema* validation against the May 20 head/node outputs.
      Historical result: meshradiohead2 parsed 64,001 rows with 0 schema
      violations; meshnode1 was offline. This establishes parseability only,
      not measurement validity, calibration eligibility, or end-to-end service.
      The current strict validator must be rerun on any release candidate.
- [x] Fail builds/reports on schema or provenance violations. p6_integrated_run.py now gates on schema validation before running pipeline; exits 1 on any invalid records.

## [P2] Inference/evaluation pipeline hardening
- [x] AIRMap dry/live scripts exist.
- [x] Sentinel/quantifier/weather-guard scripts exist.
- [x] Confirm these scripts are wired to current runtime field names and null semantics — verified 2026-05-20; fixed hardcoded head_path, satellite_link_status alias, portnum parquet coercion.
- [x] Produce the historical integrated dry-run artifact bundle. The May 20
      `overall_ok=true` result showed that the pipeline executed, but predates
      the Trial 1 eligibility findings below and is not a scientific-validation
      pass. Rebuild the release index before citing any artifact count.

## [P3] Coverage overlay + comparative outputs
- [x] Overlay MVP artifacts exist.
- [x] Extend pipeline to include cellular + satellite + mesh overlap timelines from real runtime exports. — satellite_link_status_starlink aliased in overlay; SATELLITE coverage_mode live 2026-05-20.
- [x] Emit a diagnostic summary for coverage-transition windows (`IP_FULL`,
      `IP_DEGRADED`, `MESH_ONLY`). The historical 87.1% MESH_ONLY number is a
      pipeline-output diagnostic, not independently validated service
      availability; regenerate it with explicit observed/imputed modes before use.

## [P4] Cellular telemetry program integration
**Methodology note (2026-05-24):** The comparison metric between LoRa mesh and cellular is
*service-layer availability*, not raw signal strength. Directly comparing LoRa `rssi_dbm` to
cellular `rsrp_dbm` constitutes a category error: RSSI in a narrowband LoRa/FSK context and
RSRP in an LTE OFDM context quantify fundamentally different physical phenomena and are not
dimensionally comparable as performance indicators. The appropriate cross-technology evaluation
follows the heterogeneous network (HetNet) methodology: link availability (Pr[successful packet
delivery]) and round-trip latency, both conditioned on GPS-verified position and elevation.
Hardware path: Verizon MiFi (existing) tethered to Pi; ping-based availability + latency logged
every 30 s to JSONL; merged post-hike with LoRa observations on timestamp + GPS position.
No M.2 modem or additional HAT required.

- [ ] Define `cellular_telemetry` schema fields: `cell_ping_rtt_ms` (null if unreachable),
      `cell_available` (bool), `cell_carrier`, `cell_tech` (LTE/5G), `lat`, `lon`, `elev_m`.
- [ ] Write `scripts/cellular_ping_collector.py` — 30 s interval ping via MiFi interface,
      appends to `cellular_telemetry.jsonl`; null-safe on timeout; logs carrier from MiFi
      admin API where available.
- [ ] Add ingestion + merge path: `merge_cellular_into_telemetry.py` (merge_asof 35 s tolerance).
- [ ] Add quality gates: flag sessions where `cell_available` is always True (no coverage gradient
      observed — trial segment not useful for comparison).

## [P5] Release-readiness evidence
- [x] Build one advisor-ready evidence index tying scripts -> inputs -> outputs -> figures. — `scripts/build_evidence_index.py` emits `artifacts/release/evidence_index.json` + `evidence_summary.md` 2026-05-20.
- [ ] Recompute RMSE/MAE + failure matrix from current pipeline and freeze versioned outputs.
      — **SUPERSEDED/INVALID (2026-06-12):** the previously frozen RMSE=37.1 dB / MAE=33.8 dB
      (and the later 55.2 dB run) were computed on Trial 1 data that is not calibration-grade
      (no hop filtering, contaminated distance pairs, d=1m fill bug — see
      `docs/academic-rigor-review-2026-06-12.md`). Do not cite these numbers. Re-freeze only
      from Trial 2 calibration-eligible data via the rebuilt pipeline (`--require-calibration-grade`).

## [P2bis] Rigor remediation (docs/academic-rigor-review-2026-06-12.md)
- [x] P0/P1: pipeline rebuilt (eligibility gating, ESP, floating-intercept fit, blocked CV,
      bootstrap CIs, falsifiable gates) — verified against synthetic ground truth 2026-06-12.
- [x] P2 item 11: real USGS 3DEP ingestion (`scripts/dem_3dep.py`; synthetic DEM now dry-run only).
- [x] P2 item 12: ITM/Longley-Rice link verification (`scripts/itm_relay_links.py`) — reversed the
      FSPL screen; summit links blocked by convex cone, gateway links strong, gap coverage marginal.
- [x] Airtime/SOS capacity analysis (`scripts/lora_airtime.py`).
- [x] ITM wired as per-row predictor in airmap_live_trial.py (`--predictor itm`);
      blocked CV ranks FSPL vs floating-intercept vs ITM. The 9.8 dB vs 51 dB
      comparison is from a synthetic terrain fixture and tests implementation
      behavior; it is not field-model validation.
- [x] Dataset release builder (`build_dataset_release.py`): versioned CSV/JSONL + data dictionary + hashes (deliverable #2 packaging).
- [x] Digital-twin calibration file emitter (`build_calibration_file.py`): n per terrain class + bootstrap CIs (deliverable #3).
- [x] Pinned reanalysis enrichment (`weather_enrich.py`, explicit Open-Meteo
      model + response provenance) replaces synthetic weather tags when no
      field weather log is available. Reanalysis must not be labelled measured
      or site-observed weather.
- [x] Cellular service-layer leg (`cellular_ping_collector.py` + `merge_cellular_into_telemetry.py`) — Mesh-vs-World 3rd leg (collectors built; field data pending).
- [x] Deliverable #4 figures: `build_coverage_heatmap.py` (ITM predicted-vs-actual) + `build_failure_matrix.py` (technology×terrain availability).
- [x] Unit tests for new statistics (`tests/test_statistics.py`, 12 tests); system-architecture.md + mesh-vs-world outline filled.
- [ ] P2 item 13: geology priors — cite (ITU-R P.833) and wire in, or delete the module.
- [ ] P4 item 19: FCC Part 15 compliance basis for fixed single-channel LoRa relays (required
      before any state-agency proposal).
- [ ] P4 item 20: winter survivability / power budget for treeline relays.
- [ ] Trial 2: beacon at Ammo relay site; PDR-vs-position discriminates FSPL-vs-ITM (~60 dB apart).

## Completion condition for this repo
- [ ] Project documentation and evidence reflect only active architecture/workflows, with stale speculative plans removed or archived.

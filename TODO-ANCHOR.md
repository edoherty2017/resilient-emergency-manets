# TODO Anchor — resilient-emergency-manets

This anchor was pruned to active, execution-critical items only.

## Priority Order (strict)

## [P1] Data contract + validation gates (must stay green)
- [x] Canonical telemetry schema and validator CLI exist.
- [x] Validation pack and gate report template exist.
- [x] Run fresh cross-repo validation evidence pack against current head/node outputs. → `python3 ops/run_validation_pack.py` (SSHes to both nodes; or `--ingest-root` for local rsync'd copy) — meshradiohead2 PASS (64001 rows, 0 invalid) 2026-05-20; meshnode1 offline (being reflashed). Two validator fixes applied: int-valued floats now accepted for INT_FIELDS; battery_pct range widened to 101 (Meshtastic external-power sentinel).
- [x] Fail builds/reports on schema or provenance violations. p6_integrated_run.py now gates on schema validation before running pipeline; exits 1 on any invalid records.

## [P2] Inference/evaluation pipeline hardening
- [x] AIRMap dry/live scripts exist.
- [x] Sentinel/quantifier/weather-guard scripts exist.
- [x] Confirm these scripts are wired to current runtime field names and null semantics — verified 2026-05-20; fixed hardcoded head_path, satellite_link_status alias, portnum parquet coercion.
- [x] Produce reproducible integrated dry-run artifact bundle from current data. — p6_integrated_run.py PASS 2026-05-20; overall_ok=true, all 9 gates green, 45 artifacts in artifacts/release/p6_artifact_index.json.

## [P3] Coverage overlay + comparative outputs
- [x] Overlay MVP artifacts exist.
- [x] Extend pipeline to include cellular + satellite + mesh overlap timelines from real runtime exports. — satellite_link_status_starlink aliased in overlay; SATELLITE coverage_mode live 2026-05-20.
- [x] Emit operator-facing pass/fail summary for coverage-transition windows (`IP_FULL`, `IP_DEGRADED`, `MESH_ONLY`). — transition_window_summary.json emitted; connectivity_events.jsonl merged via merge_asof; MESH_ONLY window: 87.1% covered (106 SATELLITE + 16 MESH / 140 rows).

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
- [x] Recompute RMSE/MAE + failure matrix from current pipeline and freeze versioned outputs. — RMSE=37.1 dB, MAE=33.8 dB (n=10796, rssi_dbm fallback), sentinel 99.8% accepted, all gates PASS.

## Completion condition for this repo
- [ ] Project documentation and evidence reflect only active architecture/workflows, with stale speculative plans removed or archived.

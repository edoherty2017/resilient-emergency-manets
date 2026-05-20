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
- [ ] Define normalized cellular telemetry schema contract (`rsrp_dbm`, `rsrq_db`, `sinr_db`, serving cell IDs, attach state).
- [ ] Add ingestion/normalization path for host-side modem telemetry.
- [ ] Add quality gates for modem absent/degraded cases (explicit null + state tags, not silent omission).

## [P5] Release-readiness evidence
- [x] Build one advisor-ready evidence index tying scripts -> inputs -> outputs -> figures. — `scripts/build_evidence_index.py` emits `artifacts/release/evidence_index.json` + `evidence_summary.md` 2026-05-20.
- [x] Recompute RMSE/MAE + failure matrix from current pipeline and freeze versioned outputs. — RMSE=37.1 dB, MAE=33.8 dB (n=10796, rssi_dbm fallback), sentinel 99.8% accepted, all gates PASS.

## Completion condition for this repo
- [ ] Project documentation and evidence reflect only active architecture/workflows, with stale speculative plans removed or archived.

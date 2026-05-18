# TODO Anchor — resilient-emergency-manets

This anchor was pruned to active, execution-critical items only.

## Priority Order (strict)

## [P1] Data contract + validation gates (must stay green)
- [x] Canonical telemetry schema and validator CLI exist.
- [x] Validation pack and gate report template exist.
- [ ] Run fresh cross-repo validation evidence pack against current head/node outputs.
- [ ] Fail builds/reports on schema or provenance violations.

## [P2] Inference/evaluation pipeline hardening
- [x] AIRMap dry/live scripts exist.
- [x] Sentinel/quantifier/weather-guard scripts exist.
- [ ] Confirm these scripts are wired to current runtime field names and null semantics.
- [ ] Produce reproducible integrated dry-run artifact bundle from current data.

## [P3] Coverage overlay + comparative outputs
- [x] Overlay MVP artifacts exist.
- [ ] Extend pipeline to include cellular + satellite + mesh overlap timelines from real runtime exports.
- [ ] Emit operator-facing pass/fail summary for coverage-transition windows (`IP_FULL`, `IP_DEGRADED`, `MESH_ONLY`).

## [P4] Cellular telemetry program integration
- [ ] Define normalized cellular telemetry schema contract (`rsrp_dbm`, `rsrq_db`, `sinr_db`, serving cell IDs, attach state).
- [ ] Add ingestion/normalization path for host-side modem telemetry.
- [ ] Add quality gates for modem absent/degraded cases (explicit null + state tags, not silent omission).

## [P5] Release-readiness evidence
- [ ] Build one advisor-ready evidence index tying scripts -> inputs -> outputs -> figures.
- [ ] Recompute RMSE/MAE + failure matrix from current pipeline and freeze versioned outputs.

## Completion condition for this repo
- [ ] Project documentation and evidence reflect only active architecture/workflows, with stale speculative plans removed or archived.

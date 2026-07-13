# Weekly Execution Roadmap — Resilient Emergency MANETs for Wilderness Safety

> **Status (2026-07-13):** this is the original course execution plan, not a record
> that its milestones or acceptance criteria were achieved. Current evidence status,
> superseded artifacts, and blockers are indexed in
> [`audit-correction-ledger-2026-07-13.md`](audit-correction-ledger-2026-07-13.md).

## Scope Rules
- Planning granularity is **weekly only** (no day-level scheduling).
- Success is measured by completion of required course deliverables:
  1. Architecture/design documentation
  2. 2,500+ point empirical dataset
  3. AIRMap calibration file(s)
  4. 10–15 page validation report with RMSE/MAE, heatmaps, and failure matrix

## Milestone Map (Weeks 1–12)

### Weeks 1–3 — Systems Synthesis and Baseline Validation
**Objectives**
- Finalize hardware/software architecture for HEAD and node runtime stacks.
- Complete platform assembly and environmental hardening assumptions.
- Establish baseline radio behavior in controlled conditions.

**Deliverables**
- `docs/system-architecture.md` expanded to 5-page equivalent coverage.
- EMI isolation and power management strategy section finalized.
- Baseline FSPL test dataset plus summary notes.

**QA Gates**
- Architecture doc explicitly covers: data flow, fault handling, EMI, power budget, logging.
- Baseline test run is reproducible from documented procedure.
- Runtime repo structure exists for `meshradio-head-runtime` and `meshradio-node-runtime`.

**Acceptance Criteria**
- Advisor-readable architecture doc draft is complete and internally consistent.
- At least one baseline trial run is logged with parseable output.
- Risks and mitigations captured in `docs/risk-register.md`.

### Week 4 — AIRMap Prediction Setup
**Objectives**
- Build first-pass predictive maps for target field regions.
- Define calibration interface between predictions and empirical trial data.

**Deliverables**
- Initial 2D/3D predictive outputs for target routes/areas.
- `config/airmap/` config templates committed.
- Calibration workflow draft in `docs/calibration-workflow.md`.

**QA Gates**
- AIRMap inputs and outputs are schema-defined and versioned.
- Prediction generation can be rerun with a single documented command sequence.

**Acceptance Criteria**
- Prediction artifacts are generated for all planned trial areas.
- Calibration pipeline entry points are validated end-to-end.

### Weeks 5–7 — Field Trial I (Tuckerman Ravine, Knife-Edge Focus)
**Objectives**
- Execute first major field collection campaign in knife-edge diffraction conditions.
- Validate in-field collection SOP and resilience behavior under degraded conditions.
- Validate Starlink Mini as primary live-control backhaul for meshhead during active field movement.
- Quantify control-plane degradation when remote nodes move out of Starlink/IP reach.

**Deliverables**
- Trial I raw logs plus normalized exports (CSV/JSON).
- Trial I operational logbook (conditions, route segments, anomalies, failures).
- Interim quality report with point counts and missingness statistics.
- Backhaul behavior report: SSH/Tailscale uptime windows, outage windows, and recovery timing.
- Meshtastic fallback logbook with command/heartbeat success rates during IP outage windows.

**QA Gates**
- Safety constraints met (buddy system; weather no-go thresholds).
- Required fields captured: GNSS, RSSI, SNR, RSRP, satellite link status.
- Collection pipeline confirms unique-point accounting and duplicate handling.
- Every control-plane outage window is explicitly tagged (`CONTROL_PLANE_DOWN_START/END`).
- Distinction is preserved between RF mesh degradation and IP backhaul loss.

**Acceptance Criteria**
- Trial I contributes meaningful portion of total target points.
- Data quality thresholds met for completeness and timestamp/location validity.
- At least one observed infrastructure failure mode is documented with evidence.

### Weeks 8–10 — Field Trial II (Huntington/Great Gulf, Multipath Focus)
**Objectives**
- Execute second campaign emphasizing multipath-heavy topographies.
- Complete topography coverage requirements for final dataset.

**Deliverables**
- Trial II raw plus normalized datasets with traceability to trial metadata.
- Combined Trial I and Trial II dataset quality dashboard (counts, coverage, gaps).
- Updated calibration parameters based on combined field evidence.

**QA Gates**
- Three topography classes represented with sufficient point density.
- Combined dataset remains schema-valid and reproducible from source logs.
- Calibration deltas (before and after) are documented quantitatively.

**Acceptance Criteria**
- Dataset is on track to meet or exceed 2,500 unique points.
- Coverage gaps are explicitly identified with mitigation or rationale.
- Calibration file(s) include geology-context path loss exponent values with provenance.

### Weeks 11–12 — Data Synthesis, Validation, and Final Delivery
**Objectives**
- Freeze dataset and calibration artifacts.
- Produce final evaluation package and advisor-ready report.

**Deliverables**
- Final empirical dataset handoff package.
- Final digital twin calibration config.
- "Mesh vs. The World" report (10–15 pages) including:
  - Predictive versus actual 3D heatmaps
  - RMSE/MAE results
  - Infrastructure Failure Matrix
- Optional appendix: initial notes for future 500-node simulation work.

**QA Gates**
- Metric calculations are reproducible from committed scripts.
- Figures in report map directly to versioned source data and scripts.
- Regulatory compliance checklist (FCC Part 15 assumptions) is present.

**Acceptance Criteria**
- All required deliverables are complete, versioned, and reviewable.
- RMSE/MAE, PDR, and SNR results are explicitly reported with methodology.
- Final package can be independently rerun by advisor with provided instructions.

## Cross-Cutting Quality Gates (Every Week)
1. **Reproducibility Gate**
   - Every artifact maps to versioned code/config and source data.
2. **Schema Gate**
   - No unvalidated data enters analysis stage.
3. **Traceability Gate**
   - Trial IDs, node IDs, and topography labels are preserved end-to-end.
4. **Safety and Operations Gate**
   - Field activities must satisfy buddy plus weather no-go policy.
5. **Review Gate**
   - Weekly checkpoint includes completed deliverables, blockers, risk updates, and next-week entry criteria.
6. **Connectivity-Mode Gate**
   - Each trial segment is labeled as one of: `IP_FULL`, `IP_DEGRADED`, `MESH_ONLY`.

## Current Operational Checkpoint (2026-05-16)
- Live-ingestion recovery checkpoint documented in `docs/status/2026-05-16-live-ingestion-checkpoint.md`.
- SSH matrix is restored for all aliases and direct-IP targets.
- Week 4 AIRMap prep checkpoint created in `docs/status/2026-05-16-week4-airmap-prep.md`.
- Pre-reporting gap remains: full required-field parity (especially GNSS and schema consistency across head/hiker collectors).

## Completion Definition
Roadmap execution is complete when all four required course artifacts are accepted as:
- technically reproducible,
- empirically supported,
- quantitatively evaluated,
- and advisor-review ready.

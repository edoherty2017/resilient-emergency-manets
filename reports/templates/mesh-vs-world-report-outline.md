# "Mesh vs. The World" — Validation Report Outline

Target: 10–15 page technical report (directed-study deliverable #4). Each section
lists its evidence source so the report is assembled from artifacts, not memory.

## 1. Executive Summary
- One-paragraph research question: under the sampled terrain and protocol, does a
  terrestrial LoRa mesh add service-layer availability when cellular or satellite
  service is unavailable? State the answer only if eligible observations support it.
- Headline numbers only after gates pass: per-class path-loss exponent n̂ (±CI),
  held-out RMSE of ITM vs FSPL, and the Infrastructure Failure Matrix denominator.

## 2. Background & Motivation
- The "infrastructure gap" in topographically extreme terrain.
- Why service-layer availability, not RSRP, is the cross-technology metric
  (category-error argument). Source: `docs/academic-rigor-review-2026-06-12.md` §P4.

## 3. Methods
- Acquisition platform (summarize `docs/system-architecture.md`): EMI/power, EMI
  isolation, append-only capture, hop-count ground truth.
- Propagation models compared: FSPL baseline vs Longley-Rice ITM over real DEM.
  Source: `config/airmap/model-baseline.yaml`, `scripts/itm_relay_links.py`.
- Statistics: ESP observable, floating-intercept fit, blocked CV, moving-block
  bootstrap, and pass/block-aware PDR uncertainty. Packet-level Wilson intervals
  are descriptive only when independence is defensible. Source:
  `scripts/airmap_live_trial.py`, `tests/`.

## 4. Trial Design
- Trial 1 (Mt. Washington): systems shakedown — what it established and the three
  structural gaps it exposed. Source: `artifacts/coverage_prediction/trial1_report.*`.
- Trial 2 (prospective pack; freeze required): controlled beacon, PDR, hop filtering. Source: report §
  "Plans Going Forward".
- Brenta extension (reduced-canopy, cross-site transfer test; residual confounds). Source:
  `docs/brenta-trial-plan.md`, `artifacts/itm/brenta_*`.

## 5. Predictive Model Setup
- DEM ingestion (real 3DEP / Copernicus). Source: `scripts/dem_3dep.py`,
  `dem_copernicus.py`; manifests in `artifacts/dem/cache/`.
- ITM parameterization and limitations (diffraction yes, vegetation no).

## 6. Empirical Results
- Calibration-eligible dataset summary (counts, distance/terrain coverage).
  Source: `artifacts/dataset_release/`, `build_dataset_release.py`.
- Per-terrain path-loss exponents and shadowing σ vs Bianco et al.
  Source: `config/airmap/digital-twin-calibration.yaml`.

## 7. RMSE/MAE Analysis
- Held-out RMSE: FSPL vs floating-intercept vs ITM (blocked CV), with CIs.
  Source: `artifacts/airmap/live_trial/calibration_deltas.json` → `blocked_cv`.
- The model-discrimination result: where and by how much ITM beats distance-only.

## 8. Predictive-vs-Actual Heatmaps
- ITM coverage grid vs observed RF, residual summary.
  Source: `scripts/build_coverage_heatmap.py` → `artifacts/itm/coverage_heatmap.png`.
- Relay-link verification table (the FSPL→ITM reversal).
  Source: `artifacts/itm/relay_links_itm.csv`, trial1 report §"Terrain-Profile Verification".

## 9. Infrastructure Failure Matrix
- Service-layer availability by technology × terrain (LoRa mesh / cellular /
  satellite), with Wilson CIs and N; missing legs labeled, not fabricated.
  Source: `scripts/build_failure_matrix.py` → `artifacts/failure_matrix/`.
- Connectivity-mode transition windows (IP_FULL / IP_DEGRADED / MESH_ONLY).
  Source: `artifacts/overlay/transition_window_summary.json`.

## 10. SOS Chain & Capacity
- Airtime, 3-hop latency, channel utilization vs node density.
  Source: `scripts/lora_airtime.py` → `artifacts/itm/lora_airtime.json`.

## 11. Limitations
- Pull verbatim from the evidence index `known_limitations` so the report and the
  machine-readable record never diverge. Source: `artifacts/release/evidence_index.json`.

## 12. Conclusions & Next Steps
- What the eligible evidence supports, what was frozen before collection, and what
  remains unresolved.
- Exact-device regulatory/authorization and deployment open items, plus winter survivability.

---
**Assembly note:** an artifact path is not proof. Regenerate the evidence bundle
(`p6_integrated_run.py` + `build_evidence_index.py`) from immutable inputs, require
all eligibility/provenance gates, and independently check each figure and denominator.

# ⚠ WITHDRAWN — DO NOT CITE ⚠

**Every file in this directory is a withdrawn, superseded, or inaccurate report,
statistic, or input.** Nothing here may be quoted, cited, plotted, or used as
evidence in any report, email, or analysis. These artifacts are retained solely
for provenance and audit traceability — deleting them would hide the history;
citing them would repeat the error.

Moved here 2026-07-17 during the pre-submission cleanup. The authoritative
defect index explaining *why* each item is withdrawn is
[`docs/audit-correction-ledger-2026-07-13.md`](../docs/audit-correction-ledger-2026-07-13.md);
the sentence-level claim audit is
[`docs/claims-source-audit-2026-07.md`](../docs/claims-source-audit-2026-07.md).

**Where the current, defensible results live instead:**

| Need | Current source |
|---|---|
| Final directed-study report | `reports/final-directed-study-report-2026-07-17.md` |
| Corrected multi-seed simulation results (MODEL-ONLY) | `artifacts/sim/corrected/release_v1/` (`corrected_stats.json`, `meaningful_metrics.json`, `release_manifest.json`) |
| Cross-engine parity evidence | `artifacts/sim/corrected/micro_parity_2026-07-17.json` |
| Reproducibility evidence | `artifacts/sim/corrected/repro_check_2026-07-17/` |
| ITM terrain screens (MODEL-ONLY) | `artifacts/itm/` |
| Trial 1 honest status | `reports/project_report.md` |
| Trial 2 protocol | `docs/trial2-preregistration.md`, `docs/trial2-runbook.md`, `docs/trial2-weekend-execution-plan-2026-07-18.md` |

## Contents and why each item is withdrawn

### `docs/`

| Item | Why withdrawn |
|---|---|
| `experiment-results-2026-07.md` | Every table (E1–E7, E-BOM, engine agreement, architecture recommendation) is pre-fix simulator output with unpinned weather and invalid RF metadata. All interpretations withdrawn (ledger §2, Critical). |
| `algo-arena-mini-report.html` | Pre-audit "Algorithm Arena" nine-protocol comparison. Its winner rankings (duty_sync PDR 0.908, "deaths down 17×"), "ERA5" weather labels, and "channel utilization" values are all withdrawn (ledger §2, Critical). |
| `brenta-trial-plan.md` | Brenta/Italy is fully descoped — the study is New Hampshire only. Its q50/q90 prediction table is non-evidentiary (ledger §2). |

### `artifacts/sim/`

| Item group | Why withdrawn |
|---|---|
| `archive_preaudit_2026-07/` | Pre-audit kiosk summaries, traces, experiments, THE_YEAR viewers. Its own README says "PRE-AUDIT WITHDRAWN ARTIFACTS — do not cite." |
| `attic/` | Old ARENA/viewer HTML built from pre-correction runs. |
| `xval/` | Old Rust arm of the nine-pair Python/Rust cross-validation — pre-collision-fix engine; "retained but withdrawn" per the methods report §4.2. The historical maxima recomputed from these files describe old-engine agreement only. |
| `sweep_hw/`, `sweep_mixed/` | Jul 7 pre-fix hardware-current sweeps (source of the withdrawn "conclusions verified invariant across 6–130 mA" claim). |
| `statewide_sizing/` | Pre-audit BOM/solar-sizing outputs (withdrawn "74 Wh + 10 W knee", "~34 deaths/yr" optimum). |
| `summary_*.json`, `year_summary_*.json`, `sizing.*`, `sizing_summary.json`, `storm_*`, `region_bom.csv` | Pre-fix run summaries behind the withdrawn coverage/energy/weather/capacity conclusions. |
| `real_trace_duty_sync.jsonl`, `year_trace_*.jsonl` | Raw traces of pre-correction engine runs (fed the archived THE_YEAR viewer). |
| `weather_2016.json` … `weather_2025.json`, `weather_oct.json` | Weather inputs fetched before the provenance fix — labeled "ERA5" without a pinned ERA5 request; all dependent results withdrawn. |
| `*.log` (algo_compare, arena, audit_r*, audit_final*, demo_*, exp*, fleet, fsweep, hwsweep, kiosk_year_*, mega*, mixed, rescue_r*, rigor, sim_*, sizing_*, storm_sweep, xval, year_*) | Transcripts of pre-correction runs that echo the withdrawn statistics. |

### `artifacts/dem-cache/`

| Item | Why withdrawn |
|---|---|
| `dem_tile_bde46df9d7ebdabd.npz` | Synthetic pseudo-DEM tile (extent lat 22.7–44.2, lon −72.6 to +114.3, elevations to 5,400 m — physically impossible for NH). The real, checksum-verified tiles remain in `artifacts/dem/cache/` (usgs_3dep_*). |

## Withdrawn items intentionally left *outside* this directory

Some withdrawn or mixed content could not be moved without breaking live
pipelines or link hubs. Each is marked in place:

- `artifacts/sim/summary.json`, `trace.jsonl` — pre-fix outputs but the literal
  default inputs of `render_sim_viewer.py` (see `artifacts/sim/README.md`).
- `artifacts/sim/corrected/corrected_*.json` and `corrected/sweep/` — stale
  corrected-labeled runs predating the latest engine repairs (see
  `artifacts/sim/corrected/README-STALE-WARNING.md`); `release_v1/` is current.
- `artifacts/airmap/live_trial/` — zero calibration-eligible rows; its displayed
  MAE/RMSE include ineligible rows and must not be cited (see its README).
- `artifacts/sim/ml/` — models/policies trained on pre-correction traces;
  loaded by `mesh_sim.py` for the exploratory Python-only modes.
- `docs/` mixed files (`algorithm-research.md`, `routing-algorithms.md`,
  `execution-roadmap-weekly.md`, `open-decisions.md`, `next-steps-2026-07.md`,
  `academic-rigor-review-2026-06-12.md`) and the root-level `BRANCH-README.md`
  — carry their own correction banners and are link targets of the audit pair.
- `config/sim/wmnf_sim.yaml` lines 52–54 — the comment "conclusions verified
  invariant across 6–130 mA (sweep_hw)" cites withdrawn runs. The in-file
  correction is deferred: the file's SHA-256 is bound into the topology
  provenance chain and the Trial 2 prereg manifest, so editing it must be done
  as a propagated commit (edit → attach_topology_provenance → regenerate
  manifests → tests green). The withdrawal itself is recorded here, in the
  audit ledger, and in the methods report §7.

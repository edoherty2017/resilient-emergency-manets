# Advisor Guide — start here

Everything the final report references, in one page. Three entry points:

1. **The report:** `reports/final-directed-study-report-2026-07-26.pdf`
   (also attached to the GitHub release). This is the only current report —
   earlier drafts are historical.
2. **Run the simulation yourself:** §"Running the simulator" below — a full
   365-day statewide run takes about 3½ minutes on a laptop.
3. **Interactive results explorer:** `reports/results_explorer.html` — open
   in any browser (no install); every number in it is drawn from the
   released `release_v1` aggregates.

**Canonical version note:** the tip of branch `trial2-field-campaign-2026-07`
is the definitive version of everything. `WITHDRAWN-DO-NOT-CITE/` and the
2026-07-17 report draft are retained archives only — please do not review
project claims from them.

## Running the simulator

Requirements: Rust toolchain (`rustup`), or Python 3.12+ for the reference
engine.

```bash
# Build the release engine (Rust) — from repo root:
(cd fastsim && cargo build --release)

# One simulated day, one mode (~2 s) — verified working:
./fastsim/target/release/fastsim \
  --topology artifacts/sim/topology_statewide.json \
  --routes   artifacts/sim/routes_statewide.json \
  --weather  artifacts/sim/weather_year.json \
  --config   config/sim/wmnf_sim.yaml \
  --mode duty_sync --days 1 --seed 42 --out /tmp/smoke.json

# Full 365-day statewide year: same command with --days 365 (~3.5 min).
# Try different --mode values: flood, min_hop, etx, energy_aware, lb_energy,
# duty_sync, duty_adaptive, rotate_lb, selective_duty.

# Reproduce the entire release (9 modes × 5 seeds, hash-locked inputs):
scripts/run_corrected_release.sh /tmp/my_release
# then compare /tmp/my_release/corrected_stats.json against
# artifacts/sim/corrected/release_v1/corrected_stats.json

# Verification suite:
(cd fastsim && cargo test)              # 47 + 3 tests
.venv/bin/python scripts/sim_micro_parity.py   # cross-engine parity
```

## Where every report citation lives

| Report section | Artifact |
|---|---|
| §5.2–5.3 year-scale table + insight | `artifacts/sim/corrected/release_v1/{corrected_stats.json, meaningful_metrics.json}` |
| §4 parity / reproducibility / tests | `artifacts/sim/corrected/{micro_parity_2026-07-17.json, repro_check_2026-07-17/, cargo_test_2026-07-26.log}` |
| §5.1 Trial 1 + ITM screens | `artifacts/airmap/live_trial/quality_gates.json`, `artifacts/coverage_prediction/reconcile_trial1_provenance.json`, `artifacts/itm/` |
| §6 Trial 2 registrations | `artifacts/trial2/` (prediction packs + `prereg_manifest.json`) and `docs/trial2-*siting*.md` |
| §6 field raw evidence | `artifacts/trial2/raw_pull_20260721/`, `raw_pull_20260726/` (SHA256SUMS in each) |
| §6.6 station-cadence evidence | `artifacts/trial2/nhmesh_activity_20260726/` |
| Raw dataset release | `artifacts/dataset_release/evidence-2026-07-26/` |
| Field-day illustrations (non-evidentiary) | `artifacts/trial2/packmonadnock_real_nodes_viewer.html` (animated field-day viewer) |

Registrations are git-timestamped by commit `1229309`; every SHA-256 in the
report re-verifies with `shasum -a 256`.

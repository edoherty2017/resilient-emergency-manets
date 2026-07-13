# simulation-phase-2026-07 — reviewer's guide

Directed study CS 5976 (Doherty; Basagni/Noubir). This branch contains the
complete simulation phase built on top of the Trial 1 field pipeline.

> **Correction notice (2026-07-13):** The numerical findings below were produced
> before the simulator correctness audit. They are retained as a historical run
> record, but are not validated results. Collision handling, duty-cycle reception,
> utilization accounting, weather sampling, engine parity, and run provenance are
> corrected in the present worktree, but no replacement full-scale evidence release
> has been accepted. Cite only a later result set that includes a validated run
> manifest and passes the corrected Python/Rust cross-engine tests. The exact defect,
> supersession, and blocker record is in
> [`docs/audit-correction-ledger-2026-07-13.md`](docs/audit-correction-ledger-2026-07-13.md).

## Historical pre-audit findings (all simulation; field validation still pending)
1. **Idle listening = 99.9% of fleet energy** → routing choice affects
   delivery, not survival (9 algorithms, byte-identical death counts).
2. **Duty-cycled MACs cut winter node deaths ~7–15×** at ~100% SOS delivery
   — historically reported across 10 reanalysis/API years (2016–26) and the full community
   hardware-current bracket (6–130 mA).
3. **Mixed fleet ≡ all-nRF:** nRF52 solar relays + existing Heltec kiosk
   rentals; BOM knee 74 Wh + 10 W (~99.98% site-uptime).
4. **Gateway-redundant:** dual-gateway winter outage costs zero SOS.
   **Regional channels rejected** (cost SOS for ~3 pt utilization).

## Where things are
- `docs/experiment-results-2026-07.md` — the 7-experiment suite + engine
  cross-validation (start here)
- `docs/trial2-preregistration.md` + `docs/trial2-runbook.md` — the field
  test this simulation must survive
- `docs/anchor-final-stretch-2026-07.md` — remaining work plan
- `scripts/mesh_sim.py` — reference simulator (SimPy; traces for viewers)
- `fastsim/` — Rust twin, historically ~115× faster. The old max-ΔPDR comparison
  is not a current validation; corrected parity tests and manifests are required.
- `scripts/build_sim_topology.py` + `statewide_sites.py` + `audit_coverage.py`
  — 217-site statewide topology and threshold/counterfactual model audit. The
  −131 dBm sensitivity-floor screen passes only while retaining an uncalibrated
  FSPL+26 dB short-link substitution. The controlling −100 dBm planning screen
  excludes those 52 policy edges and **fails** (87/217 stranded; 15/25 route
  estimates <85%). Even the counterfactual planning screen that restores them
  fails (53 stranded; 13 routes). The active topology/link matrix now excludes
  the 52 edges from simulation too; the builder requires an explicit opt-in to
  restore them. Trail estimates are q50 model outputs, not field coverage or q90
  reliability.
- `artifacts/sim/sweep*/`, `artifacts/sim/experiments/` — all run outputs
- Viewers (large HTML, regenerable): THE_YEAR_LITE.html (flood vs lb_energy
  vs duty_sync, one year, algorithm switcher)

## Reproduce
```
.venv/bin/python -m pytest tests/            # run the current Python suite
cd fastsim && cargo build --release          # the numbers engine
./fastsim/target/release/fastsim --mode duty_sync --days 365 --seed 1 \
    --renters-per-route 2 --sos-retry --config config/sim/wmnf_sim.yaml \
    --out /tmp/demo.json                     # ~1 min
```
All hardware constants are bracket-sourced and flagged BENCH-CALIBRATE in
`config/sim/wmnf_sim.yaml`; the bench procedure is `scripts/discharge_test.py`.

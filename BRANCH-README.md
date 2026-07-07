# simulation-phase-2026-07 — reviewer's guide

Directed study CS 5976 (Doherty; Basagni/Noubir). This branch contains the
complete simulation phase built on top of the Trial 1 field pipeline.

## Headline findings (all simulation; field validation = Trial 2, late July)
1. **Idle listening = 99.9% of fleet energy** → routing choice affects
   delivery, not survival (9 algorithms, byte-identical death counts).
2. **Duty-cycled MACs cut winter node deaths ~7–15×** at ~100% SOS delivery
   — robust across 10 real weather years (2016–26) and the full community
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
- `fastsim/` — Rust twin, ~115× faster, validated (max ΔPDR 0.006 across
  all 9 modes at year scale); powers the sweeps
- `scripts/build_sim_topology.py` + `statewide_sites.py` + `audit_coverage.py`
  — 217-site statewide topology, falsifiable coverage audit (PASS)
- `artifacts/sim/sweep*/`, `artifacts/sim/experiments/` — all run outputs
- Viewers (large HTML, regenerable): THE_YEAR_LITE.html (flood vs lb_energy
  vs duty_sync, one year, algorithm switcher)

## Reproduce
```
.venv/bin/python -m pytest tests/            # 21 tests
cd fastsim && cargo build --release          # the numbers engine
./fastsim/target/release/fastsim --mode duty_sync --days 365 --seed 1 \
    --renters-per-route 2 --sos-retry --config config/sim/wmnf_sim.yaml \
    --out /tmp/demo.json                     # ~1 min
```
All hardware constants are bracket-sourced and flagged BENCH-CALIBRATE in
`config/sim/wmnf_sim.yaml`; the bench procedure is `scripts/discharge_test.py`.

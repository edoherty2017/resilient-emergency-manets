# Next Steps — after the simulation phase (2026-07-03)

State: the simulation stack is complete and the statewide SAR coverage audit
**PASSES** (158 sites, 0 stranded, all 18 rental trails covered;
`artifacts/sim/coverage_audit_statewide.json`). The 365-day real-weather run
(`artifacts/sim/summary_year.json`) quantifies seasonal survivability. What
follows, in priority order.

## 1. Ground truth (highest scientific value per hour)

- **Brenta trip (this week!)** — execute `docs/brenta-trial-plan.md`: EU_868
  hut-beacon receding sweeps, hop-limit-1 beacon, phone-app verification. This
  is the only calibration-grade RF data until Trial 2.
- **Bench calibration session (G2 + C5, one afternoon home):** USB power meter
  on the Heltec → real tx/rx/sleep currents; 10 Ah bank runtime; lux meter
  under representative canopy → replace canopy_tau 0.15. Every energy number
  in the sim inherits from this.
- **Trial 2 (B1)** — the pre-registered Presidentials PDR experiment; also
  yields the dataset that re-trains the solar/route ML on field data.

## 2. Model validation (turns the sim from proposal into evidence)

- **Short-link policy check:** measure 3–5 sub-1.5 km ridge links (e.g. Zeta
  Pass chain analog on accessible terrain) against the FSPL+26 dB policy.
- **ITM vs field at 2–6 km forest ridge:** the audit's binding constraint; a
  half-day of spot measurements decides whether the dense-relay chains are
  really needed or ITM-at-74 m is pessimistic.
- **MWObs irradiance:** swap ERA5 kt for the Observatory's measured record;
  rerun the year sim (one command) — removes the "valley-blended kt" caveat.

## 3. Engineering decisions now unblocked (need Ethan)

- **G1 routing:** statewide flood collapses (PDR ~0.74 at 158 nodes) while
  energy-aware routing holds; decision = Meshtastic-as-transport + routing
  daemon prototype on the Pi. First artifact: daemon skeleton that reads
  nodedb RSSI and computes the scarcity-weighted route table.
- **A2 FCC basis** (Part 97 vs 500 kHz) — still the gating decision for any
  fixed relay hardware.
- **A4 seasonal scope** — the year sim gives the numbers; recommend May–Oct.
- **Regional channel isolation:** statewide on one LoRa channel is unnecessary
  contention; each gateway region should get its own channel/PSK — design doc
  + sim sweep (1 evening).

## 4. Deliverables to package (defense-ready)

- **NH F&G proposal pack:** coverage audit PASS map + per-region BOM from
  `statewide_sizing/` + FCC memo + seasonal scope = a deployable proposal.
- **Advisor memo (D1)** — now includes: coverage audit, year sim, storm knee,
  routing comparison. Draft on request.
- **Commit everything (E1)** — the working tree holds the entire simulation
  phase uncommitted. Recommend branch `simulation-phase-2026-07`, themed
  commits (sim engine / topology+audit / ML / viewers / docs).

## 5. Known model debts (tracked, not hidden)

- Energy currents + panel wattage: BENCH-CALIBRATE (G2).
- canopy_tau 0.15: literature value, needs lux-meter check.
- Statewide coordinates map-derived ±300 m; fire-tower heights assumed 10 m;
  Magalloway/Blue Job backhaul flagged [SITE-SURVEY].
- ERA5 kt is valley-blended (sunnier than summit reality) — MWObs swap above.
- ITM below ~1 km replaced by policy (documented in build_sim_topology.py);
  policy itself needs the §2 field check.

# Open Decisions — Awaiting Ethan

Single source of truth for every decision the project is waiting on **you** (not me)
to make. I will keep this current; ping me to re-check it any time. Each item has a
recommendation so you can often just say "do the recommended thing."

Status key: ⬜ open · ✅ decided · 🔜 time-sensitive

---

## A. Committee-risk / blocking (resolve before presenting or finalizing Trial 2)

### A1 ⬜ RSRP scope amendment
The proposal promises RSRP in the dataset; we established that LoRa-RSSI-vs-cellular-RSRP
is a category error and replaced it with ESP + service-layer availability. This needs a
**short, advisor-signed scope amendment** so the deliverables list and methodology can't
be played against each other at the defense.
**Need from you:** approve the swap; say whether I should draft the half-page amendment
for Basagni's sign-off.
**My rec:** yes, draft it.

### A2 ⬜🔜 FCC compliance basis (see `docs/fcc-part15-compliance-memo.md`)
LongFast as-operated (single 250 kHz channel, no hopping, +22 dBm) fits **no** Part 15
pathway. Real options: **(A) Part 97 amateur license** (keeps LongFast range; forbids
encryption; needs a licensed operator) or **(B) reconfigure to 500 kHz** Part 15.247
digital modulation (license-free; loses range; re-opens the link budget).
**Need from you:** pick A or B. This drives the radio config and must be set **before
Trial 2 hardware is finalized**.
**My rec:** A (Part 97 Technician license — a weekend of study) for the research trials.

### A3 ⬜ Geology priors — cite or delete
`scripts/geology_loss.py` priors are uncited placeholders and aren't used by the
prediction. Either ground them in ITU-R P.833 (vegetation) + Bianco et al. and wire them
in, or delete the module.
**Need from you:** keep-and-cite vs delete.
**My rec:** delete for now (ITM already handles terrain; vegetation can be a labeled
excess-loss term later) — less surface area to defend.

### A4 ⬜ Winter survivability / seasonal scope — NOW QUANTIFIED
The 365-day simulation on real 2025–26 weather (ERA5 shortwave + snowfall,
artifacts/sim/summary_year.json) settles the physics: with the 37 Wh battery +
6 W panel BOM, **open ridge sites hold ≥68% median minimum SOC May–Oct, then the
fleet collapses Nov–Feb** (median monthly minimum 0% Nov–Jan; even the best sites
die ~20–40 times/year, all in winter). 37 of 365 daily SOS were lost — every one in
the winter outage window. Under-canopy sites are infeasible year-round (τ=0.15 →
~700 Wh/yr vs ~2,500 Wh/yr load).
**Need from you:** scope the relay proposal to **seasonal (May–Oct)** or commit to a
year-round hardening + power-budget section (bigger banks + swaps).
**My rec:** seasonal — now with the year-sim numbers to defend it.

### A5 ⬜ 2,500-point dataset target
Proposal promises ≥2,500 points; currently **0 calibration-grade** (Trial 1 had no
controlled links). This is a Trial 2 dependency, but if Trial 2 falls short the number may
need renegotiation with the advisor.
**Need from you:** awareness now; decision only if Trial 2 underdelivers.

---

## B. Trial 2 design

### B1 ⬜ Pre-registered Trial 2 design sign-off
Static beacon at surveyed position, fixed cadence + sequence numbers, hop filtering
(`hops_away==0`), 600–1,000 packets/terrain-stratum, ≥2 repeat runs/segment. Detailed in
`artifacts/coverage_prediction/trial1_report.tex` §"Plans Going Forward".
**Need from you:** approve as-is or request changes.
**My rec:** approve; it's the minimal controlled design.

### B2 ⬜ Radio config for Trial 2 — follows from A2
LongFast (if Part 97) vs 500 kHz preset (if Part 15). Re-run ITM link budget if B.
**Need from you:** flows from A2.

---

## C. Brenta trip (time-sensitive — trip is happening regardless)

### C1 🔜⬜ EU_868 reconfig + 868 MHz antennas
US 915 MHz is illegal in Italy. Every node → Meshtastic region EU_868 (869.525 MHz); order
868-tuned antennas (~$5 each).
**Need from you:** confirm you'll do the reconfig + order antennas before flying.
**My rec:** do it; it's the one true blocker for the Brenta data being usable/legal.

### C2 🔜⬜ Hut permission emails (Tuckett, Alimonta, Agostini)
Wardens are far more likely to host a powered node if asked in advance, and the reply is
your written permission.
**Need from you:** want me to draft the emails (EN + a short IT version)?
**My rec:** yes — I'll draft; you send.

### C3 🔜⬜ Trento/Bolzano professor outreach
Note + pre-registered ITM prediction table; offer the dataset / node adoption.
**Need from you:** want me to draft this email?
**My rec:** yes — strong first-contact with EURAC (Bianco/Mejia-Aguilar).

### C4 ⬜ Leave-behind strategy
(1) huts host powered nodes (budget as consumables), (2) collect during the July Bolzano
visit, (3) mail back without batteries.
**Need from you:** pick the primary plan (can be per-hut).
**My rec:** (1) as default, (2) as the collection mechanism where feasible.

### C5 🔜⬜ Bench battery test before flights
Confirm a 10 Ah bank actually runs a Heltec ~4 days at EU_868 with GPS off.
**Need from you:** run the bench test; report the number.

---

## D. Advisor communication

### D1 ⬜ Consolidated advisor update memo
A lot changed since the proposal: RSRP→ESP, FSPL→ITM, the relay-proposal reversal
(summit links blocked), falsifiable gates, the FCC basis, Brenta extension. Basagni/Noubir
should see a single coherent update.
**Need from you:** want me to draft a 1–2 page advisor memo pulling these together?
**My rec:** yes — it also pre-empts most defense questions.

---

## E. Housekeeping

### E1 ⬜ Commit / push the working tree
Everything from the rebuild + build-out + memos is **uncommitted**. Large, coherent set of
changes.
**Need from you:** when/how to commit — one big commit vs staged by theme; branch name;
push to a remote or keep local? (I'll only commit/push when you say so.)
**My rec:** stage into a few themed commits on a branch `rigor-rebuild-2026-06`; push only
if you have a private remote.

### E2 ⬜ Defaults I chose (revisit only if you disagree — non-blocking)
- Planning threshold **−100 dBm** (sensitivity + ~31 dB fade margin)
- Gate thresholds: held-out RMSE ≤ **12 dB**, path-loss exponent ∈ **[1.6, 4.5]**, σ ≤ **10 dB**
- ITM antenna heights: relay/beacon **3 m**, hiker **1.5 m**, generic tx **2 m**
- Mt. Washington AOI bounds; Brenta AOI bounds
**Need from you:** nothing unless any of these look wrong.

---

## G. Simulation / ML phase (added 2026-07-03)

### G1 ⬜ Routing architecture: stay Meshtastic or go custom
The WMNF simulation (scripts/mesh_sim.py) compares Meshtastic managed
flooding against energy-aware source routing on identical traffic/terrain.
At the 35-node build-out the gap is decisive: energy-aware routing delivers
**higher PDR (95.5% vs 94.6%) at 12.4× less TX energy and 12× less airtime**
(flooding cost grows ~quadratically with node count — 153k vs 12k
transmissions/3 days; artifacts/sim/ml/ml_report.json). Meshtastic firmware cannot do
energy-aware unicast routing; a custom layer means either (a) Meshtastic as a
dumb transport + our routing daemon on the Pi/companion, or (b) custom firmware.
**Need from you:** direction — stay flood (simplest, proven), or prototype (a).
**My rec:** (a) — keep Meshtastic PHY/MAC, add routing on top; revisit after
Trial 2 field data validates the sim.

### G2 ⬜ Sim energy constants are placeholders
tx/rx/sleep currents + panel wattage in `config/sim/wmnf_sim.yaml` are marked
BENCH-CALIBRATE. Same bench session as C5 can nail all of them (USB power meter).
**Need from you:** run the bench measurements when home.

### G3 ⬜ Duty cycling is the real energy lever (year-run finding, 2026-07-05)
Full-year statewide runs settled it: with always-listening routers, TX energy
is **0.06%** of the fleet budget (217 Wh/yr transmit vs ~350,000 Wh/yr
receive-listen across 159 solar nodes) — routing-algorithm choice moves
delivery (PDR/SOS/channel load), **not survival**: all routed modes produced
identical death counts (28,632/yr). Node survival is set entirely by
solar+battery sizing (A4/G2). Load-balancing routing (lb_energy) becomes
decisive only if relays can **sleep between scheduled listen windows**
(TDMA-style duty cycling) — then "who relays" = "who stays awake" = the whole
energy story. Stock Meshtastic ESP32 routers cannot duty-cycle while routing.
**Need from you:** adopt duty-cycled MAC design (custom firmware territory) as
the Phase-3 research direction?
**My rec:** yes — it is where the load-balancing algorithm actually earns its
keep, and the sim already has everything needed to evaluate it.

## F. Deferred (lower urgency, tracked so they're not lost)

- **F1** Multi-hop propagation analysis — needs a second deployed node (`meshnode1` reflash pending).
- **F2** Cellular + Starlink field data — collectors built; need a trial carrying the MiFi + dish.
- **F3** Real weather rerun — `weather_enrich.py` exists; rerun on Trial 2 data to populate weather strata.

---

_Last updated: 2026-06-15. When you resolve an item, tell me and I'll mark it ✅ and act on it._

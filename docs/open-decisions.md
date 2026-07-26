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

### A2 ✅ FCC compliance basis — DECIDED 2026-07-21: Part 97 amateur (for Trial 2 field ops)
Ethan selected Part 97 amateur operation as the authorization basis for the Trial 2
field days (decision made 2026-07-21, ahead of the 2026-07-22 Moosilauke retry).
Trial-day mitigations that make this specific operation defensible under Part 97:
encryption OFF (Meshtastic ham mode), callsign as station ID in node broadcasts,
only the trial team's own traffic (two nodes, no third-party/SOS relaying), stock
TX power (far below Part 97 limits), beacon placed and retrieved the same day.
**Residual caveats (recorded, not resolved):** the beacon transmits under automatic
control while the team walks the route — Part 97 rules on automatically controlled
data stations/beacons (§97.203, §97.221) are not fully analyzed here; and this
basis covers the *trial*, not a deployed unattended relay network. The memo's
conclusion that a production fixed-relay system needs a real authorization review
(TCB/FCC counsel or Part 5 experimental) still stands as a report limitation.
**Still needed:** Ethan's callsign recorded in the repo + photographs/inventory of
the exact radio hardware labels (also required by advisor acceptance criterion 5).
**UPDATE 2026-07-23 — basis switched to device certification as marketed.** No
valid FCC callsign was provided ("MeshVworld" is not a valid callsign format and
was never programmed into a radio), so per the recorded fallback the field-day
basis is the Heltec V3's FCC device certification operating exactly as marketed:
stock firmware, stock TX power, default public LongFast channel (the 2026-07-24
Monadnock day uses the public channel by design — see
`docs/trial2-monadnock-siting-20260723.md`). Part 97/ham mode flips back on in
~5 min if a valid callsign is ever provided. Hardware label photos still needed.

### A3 ⬜ Geology priors — cite or delete
`scripts/geology_loss.py` priors are uncited placeholders and aren't used by the
prediction. Either ground them in ITU-R P.833 (vegetation) + Bianco et al. and wire them
in, or delete the module.
**Need from you:** keep-and-cite vs delete.
**My rec:** delete for now (ITM already handles terrain; vegetation can be a labeled
excess-loss term later) — less surface area to defend.

### A4 ⬜ Winter survivability / seasonal scope — corrected rerun required
Update 2026-07-13: earlier ten-year runs used an Open-Meteo request that did not
pin the model and are superseded. The corrected fetcher explicitly requests ERA5
reanalysis, rejects missing variables, and hashes the raw API response; corrected
multi-year simulation results are still pending. The earlier BOM, outage, uptime,
and “all years” numbers are non-citable because simulator correctness, engine parity,
weather sampling, and hardware currents were not all validated together.
**Need from you:** keep the deployment scope open (or conservatively seasonal) until
corrected runs and bench measurements support a decision.

### A5 ⬜ 2,500-point dataset target
Proposal promises ≥2,500 points; currently **0 calibration-grade** (Trial 1 had no
controlled links). This is a Trial 2 dependency, but if Trial 2 falls short the number may
need renegotiation with the advisor.
**Need from you:** awareness now; decision only if Trial 2 underdelivers.

---

## B. Trial 2 design

### B1 ⬜ Prospective Trial 2 freeze and design sign-off
Static beacon at surveyed position, fixed cadence + sequence numbers, hop filtering
(`hops_away==0`), normal-pace fixed route, exact opportunity denominators, and independent
full-pass/day replication. The 2026-07-13 amendment targets ≥40 scheduled opportunities
per primary stratum and reports smaller strata as underpowered. The earlier 600–1,000
packets-per-stratum quota was impossible at 30 s cadence (5–8.3 hours in each stratum) and
must not be used to alter walking speed. Detailed in `docs/trial2-preregistration.md`.
**Need from you:** sign off on the amended, feasible protocol before fieldwork.

### B2 ⬜ Radio config for Trial 2 — follows from A2
LongFast vs a 500 kHz preset are engineering candidates, not automatic declarations of
Part 97 or Part 15 compliance. Record exact hardware/grant conditions and authorization
basis; re-run ITM link budget if the radio configuration changes.
**Need from you:** flows from A2.

---

## C. Brenta trip (time-sensitive — trip is happening regardless)

### C1 🔜⬜ EU_868 reconfig + 868 MHz antennas
Do not transmit on the US_915 plan in Italy. EU_868 at 869.525 MHz is a candidate only
after checking current Italian implementation, the exact device's EU declaration of
conformity/RED scope, antenna and ERP, firmware mode, and aggregate airtime (including
mesh forwarding/retries). Silicon tuning range and a settings change are not proof of
conformity.
**Need from you:** obtain those records, use a permitted 868 MHz antenna/configuration,
and record the compliance basis before transmitting.

### C2 🔜⬜ Hut permission emails (Tuckett, Alimonta, Agostini)
A powered transmitter may be left only with the relevant hut/property/park permission.
A reply is evidence only if it covers the radio operation, placement, charging, dates,
retrieval, and responsibility described in the request.
**Need from you:** want me to draft the emails (EN + a short IT version)?
**My rec:** yes — I'll draft; you send.

### C3 🔜⬜ Trento/Bolzano professor outreach
Note + prospective ITM prediction table (clearly marked not yet frozen); offer the
resulting dataset only after an eligible run.
**Need from you:** want me to draft this email?
**My rec:** yes — strong first-contact with EURAC (Bianco/Mejia-Aguilar).

### C4 ⬜ Leave-behind strategy
(1) huts host powered nodes under specific written permission, (2) collect during the
July Bolzano visit, or (3) use a pre-arranged carrier-approved return/disposition plan.
**Need from you:** pick the primary plan (can be per-hut).
**My rec:** no leave-behind default; select per site only after permission, retrieval,
radio conformity, battery safety, and responsibility are documented.

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

### E1 ✅ Commit / push — RESOLVED (2026-07-07); EXTENDED + EXECUTED 2026-07-26
The cited simulation-phase commits were pushed to branch **simulation-phase-2026-07**
(a68e3e4, 248d76d, 69e9fe5), but “everything committed” was only a historical status.
The current audit worktree is dirty; new results require a clean, immutable commit and
run manifest before citation.
**2026-07-26 (Ethan: "commit it"):** the Trial 2 field-campaign registrations,
siting docs, evidence checksums, and the final report were committed on branch
**trial2-field-campaign-2026-07** (registration artifacts under `artifacts/trial2/`
required `git add -f` past the gitignore; bulk raw JSONL/dataset files are bound by
their committed SHA256SUMS/manifests rather than committed wholesale). Not pushed —
push remains Ethan's call.

### E2 ⬜ Defaults I chose (revisit only if you disagree — non-blocking)
- Planning threshold **−100 dBm** (sensitivity + ~31 dB fade margin)
- Gate thresholds: held-out RMSE ≤ **12 dB**, path-loss exponent ∈ **[1.6, 4.5]**, σ ≤ **10 dB**
- ITM antenna heights: relay/beacon **3 m**, hiker **1.5 m**, generic tx **2 m**
- Mt. Washington AOI bounds; Brenta AOI bounds
**Need from you:** nothing unless any of these look wrong.

---

## G. Simulation / ML phase (added 2026-07-03)

### G1 ⬜ Routing architecture — prior result superseded; corrected comparison pending
The earlier nine-algorithm recommendation is not settled by defensible data. The
simulator audit found collision, duty-cycle reception, utilization, weather/provenance,
and engine-parity defects affecting those runs. Treat “single channel,” “regional
channels rejected,” and the named winning modes as hypotheses until a clean manifest,
corrected cross-engine tests, and rerun artifacts exist. Stock-firmware feasibility is
a separate implementation constraint.

### G1 (superseded) Routing architecture: stay Meshtastic or go custom
The WMNF simulation (scripts/mesh_sim.py) compares Meshtastic managed
flooding against energy-aware source routing on identical traffic/terrain.
At the 35-node build-out the gap is decisive: energy-aware routing delivers
**higher PDR (95.5% vs 94.6%) at 12.4× less TX energy and 12× less airtime**
(flooding cost grows ~quadratically with node count — 153k vs 12k
transmissions/3 days; artifacts/sim/ml/ml_report.json). Meshtastic firmware cannot do
energy-aware unicast routing; a custom layer means either (a) Meshtastic as a
dumb transport + our routing daemon on the Pi/companion, or (b) custom firmware.
**Need from you:** defer the architecture choice until corrected reruns and a
stock-firmware/companion feasibility test. Flooding is the existing baseline, not a
proven winning design. Trial 2 can test propagation assumptions; it cannot by itself
validate the statewide traffic, energy, routing, and failure simulator.

### G2 ⬜ Sim energy constants are placeholders
tx/rx/sleep currents + panel wattage in `config/sim/wmnf_sim.yaml` are marked
BENCH-CALIBRATE. Same bench session as C5 can nail all of them (USB power meter).
**Need from you:** run the bench measurements when home.

### G3 ⬜ Duty cycling / hardware path — promising hypothesis; corrected rerun pending
The historical 6–130 mA sweep suggested a large duty-cycling effect, but the exact
7–15× death reduction, mixed-fleet equivalence, ~$5k estimate, 74 Wh/10 W knee, and
99.98% uptime came from superseded runs and unbenchmarked constants. Re-establish the
direction and magnitude with corrected simulator semantics, pinned weather, clean
manifests, and measured board currents before choosing a hardware path.

### G3 (superseded) Duty cycling is the real energy lever (year-run finding, 2026-07-05)
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
- **F3** Weather enrichment rerun — `weather_enrich.py` supplies gridded archive/reanalysis
  estimates, not station measurements; pin the model and provenance when populating Trial 2 strata.

---

_Last updated: 2026-07-13. Resolve an item only when the cited evidence and current
worktree support the status._

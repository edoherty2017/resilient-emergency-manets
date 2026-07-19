# Next Steps — after the simulation phase (2026-07-03)

**Correction, 2026-07-13:** This planning note predates the simulator/provenance
audit. Its simulation findings and “complete/deployable” language are historical,
not validated results. The regenerated 217-site coverage artifact is an uncalibrated
model screen with a crucial policy sensitivity: the −131 dBm sensitivity-floor tier
passes only while retaining an uncalibrated FSPL+26 dB short-link substitution. The
controlling −100 dBm tier excludes those 52 policy edges and **fails** (87/217
stranded; 15/25 route estimates <85%). Even restoring them as a counterfactual still
fails (53 stranded; 13 routes). Backhaul uses modeled q90 RSSI, but routes have only
q50 loss estimates. This does not demonstrate field coverage, installation
feasibility, permission, or legal authorization.

## 1. Ground truth (highest scientific value per hour)

- **Brenta opportunity** — execute `WITHDRAWN-DO-NOT-CITE/docs/brenta-trial-plan.md` (since fully DESCOPED — Brenta is out of scope; retained note only) only after the
  exact radio-conformity, national-rule, land-permission, and safety gates close.
  The collection becomes calibration-grade only if its preregistered provenance,
  direct-link, receiver-health, and denominator gates pass; a trip by itself is
  not calibration evidence.
- **Bench calibration session (G2 + C5, one afternoon home):** USB power meter
  on the Heltec → real tx/rx/sleep currents; 10 Ah bank runtime; lux meter
  under representative canopy → replace canopy_tau 0.15. Every energy number
  in the sim inherits from this.
- **Trial 2 (B1)** — freeze the prospective Presidentials prediction/protocol
  pack before collection. A successful eligible run can evaluate propagation/PDR;
  it does not automatically provide enough independent data to retrain routing ML.

## 2. Model validation (turns the sim from proposal into evidence)

- **Short-link policy check:** measure 3–5 sub-1.5 km ridge links (e.g. Zeta
  Pass chain analog on accessible terrain) against the FSPL+26 dB policy.
- **ITM vs field at 2–6 km forest ridge:** the audit's binding constraint; a
  half-day of spot measurements decides whether the dense-relay chains are
  really needed or ITM-at-74 m is pessimistic.
- **MWObs irradiance:** swap ERA5 kt for the Observatory's measured record;
  rerun the year sim (one command) — removes the "valley-blended kt" caveat.

## 3. Engineering decisions reopened by the audit (need Ethan)

- **G1 routing:** the old flood-vs-energy-aware result is superseded. Re-run the
  corrected engines before deciding whether a companion routing prototype is
  justified; stock-firmware feasibility is a separate constraint.
- **A2 legal basis:** the candidate Part 15, Part 97, or Part 5 path must be tied
  to exact hardware, grant/integration conditions, configuration, operator and use.
- **A4 seasonal scope:** no corrected, bench-grounded year run presently supports
  a May–October recommendation.
- **Regional channel isolation:** retain as a hypothesis for a corrected sweep;
  do not assign channels/PSKs from the withdrawn contention result.

## 4. Deliverables to package (defense-ready)

- **NH F&G research/design pack:** include both coverage tiers, the planning-screen
  failures, route-geometry/quantile limitations, candidate BOM, FCC open questions,
  and field-validation plan. It is not yet a deployable proposal.
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
- The historical weather request did not prove an ERA5 product, and the sign of
  summit bias has not been quantified — use a pinned product or licensed MWObs data.
- ITM below ~1 km replaced by policy (documented in build_sim_topology.py);
  policy itself needs the §2 field check.

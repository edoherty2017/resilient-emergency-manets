# ANCHOR — Final Stretch to Full Credit (2026-07-07 → end of term)

Everything left EXCEPT the Trial 2 field days themselves (late July, Ethan).
Ordered by dependency; [C] = computable now (Claude), [E] = needs Ethan,
[A] = needs advisor. Status updated in place.

## Phase 1 — Trial 2 enablement (this week; field days must be plug-and-play)

- [ ] **1.1 [C] Pre-registered prediction pack** — ITM-predicted RSSI/ESP and
      fastsim-predicted PDR per terrain stratum for the Trial 2 beacon sites
      and walk segments, for BOTH candidate radio configs (LongFast/Part 97
      and 500 kHz/Part 15). Committed BEFORE the trial = pre-registration.
      → `scripts/trial2_predictions.py`, `docs/trial2-preregistration.md`
- [ ] **1.2 [C] Ingest dry-run** — run the full airmap pipeline end-to-end on
      the Trial 1 raw export today, so field day is data collection, not
      debugging. Record command sequence in the runbook.
- [ ] **1.3 [C] Field runbook** — one-page day-of checklist: config freeze,
      beacon survey steps, cadence, verification via phone app, abort criteria.
      → `docs/trial2-runbook.md`
- [ ] **1.4 [C] Discharge-test helper** — `scripts/discharge_test.py`: watch
      telemetry stream, compute live drain rate (%/h → mA), write report.
      One command for the overnight bench item (C5/G2).
- [ ] **1.5 [E] Overnight discharge test** — run 1.4 on a full-charged node.
- [ ] **1.6 [A] FCC basis decision (A2)** — needed by mid-July to freeze config.

## Phase 2 — Proposal deliverables (writing; parallel with Phase 1)

- [ ] **2.1 [C] "Mesh vs the World" report draft** — assemble the 10–15 pp
      report now: intro/methods/simulation chapters complete, field-results
      sections as templated placeholders that Trial 2 data drops into.
      → `reports/mesh-vs-world-draft.md`
- [ ] **2.2 [C] RSRP scope-amendment draft (A1)** — half page for Basagni.
      → `docs/scope-amendment-rsrp.md`
- [ ] **2.3 [C] Branch README** — orient a reviewer landing on the repo:
      what's where, headline findings, how to reproduce.
- [ ] **2.4 [E] Send advisor email** (drafted; Outlook thread context is Ethan's).

## Phase 3 — Model refinements (nice-to-have before Trial 2, cheap on fastsim)

- [ ] **3.1 [C] Higher-resolution weather** — refetch kt from ERA5-Land (9 km)
      vs ERA5 (30 km); quantify summit-kt delta; rerun key years if material.
- [ ] **3.2 [C] Leaf-off canopy seasonality** — month-dependent tau for
      deciduous sites (leaf-off ≈ 0.4–0.6 literature); sensitivity run on
      winter deaths for below-treeline sites.
- [ ] **3.3 [C] Fix 3 chord routes** (Osceola, Rumney, Bear Brook) —
      hand-placed waypoints on mapped OSM segments.

## Phase 4 — End of term

- [ ] **4.1 [E] Trial 2 field days** (late July + early-Aug weather backup)
- [ ] **4.2 [C] Same-day data processing**: dataset release + calibration file
      + gates verdict (machinery exists; one command each)
- [ ] **4.3 [C] Drop field results into 2.1 → final report by 3rd week of Aug**
- [ ] **4.4 [E/A] Final submission + defense scheduling**

## Standing decisions still open (docs/open-decisions.md)
A1 (RSRP amendment — draft = 2.2), A2 (FCC 🔜), A3 (geology cite-or-delete),
A4 (seasonal vs $5k BOM), A5 (2,500-pt target awareness), B1 (Trial 2 sign-off),
C-items (Brenta follow-ups), D1 (advisor memo = the email).

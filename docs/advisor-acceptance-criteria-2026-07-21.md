# Advisor acceptance criteria — email from St. Basagni, 2026-07-21

Received while preparing the Trial 2 retry (attempt 3, planned 2026-07-22).
This is the checklist the final assessment — and Guevara's sign-off — will be
made against. Verbatim requirements, mapped to repo state.

## Framing (confirmed by advisor)

> "Trial 1 as a systems shakedown, the simulation framework as the central
> completed contribution, and Trial 2 as the controlled empirical test of the
> frozen predictions."

This matches `reports/final-directed-study-report-2026-07-17.md` §1. No change
needed.

## Requirements → status

1. **"Report Trial 2 honestly regardless of outcome. If some strata are
   underpowered, noisy, or inconclusive, label them as such rather than
   omitting them."**
   — Already the protocol's honesty rule
   (`docs/trial2-weekend-execution-plan-2026-07-18.md`). Extends to the
   operational record: field attempts of Jul 18 (rig never ran), Jul 19
   (beacon failure; 0 calibration-eligible rows), and Jul 21 (receiver radio
   never enumerated on USB; GPS-only day) are part of the trial record and
   will be reported as such. Raw evidence preserved in
   `artifacts/trial2/raw_pull_20260721/`.

2. **"Any headline claim tied either to the corrected simulation runs or to
   the Trial 2 measurements. Superseded numbers clearly archived and not
   mixed with final results."**
   — Structure in place: `WITHDRAWN-DO-NOT-CITE/` (do-not-cite banner, defect
   index in `docs/audit-correction-ledger-2026-07-13.md`), corrected runs in
   `release_v1` / `corrected_stats.json`. Rule for the final report: every
   headline number cites either the corrected release or Trial 2 data —
   nothing else.

3. **"Focused contribution: year-scale wilderness mesh survivability —
   duty-cycling, idle listening, delivery ratio, SOS latency."**
   — Matches the report's central thesis (idle listening ≫ TX energy;
   duty-cycling as a survival-vs-delivery tradeoff). Resist scope creep in
   the final write-up: statewide build-out, kiosk logistics, and RL modes are
   supporting material, not headlines.

4. **"Limitations explicit: calibration, restricted number of field sites,
   purpose-built simulator not independently validated through a widely used
   third-party framework."**
   — Report §3 already carries the ns-3 comparison and external-validation
   limitation; MODEL-ONLY / BENCH-CALIBRATE tags throughout. Keep §3 and the
   limitations section in the final version; add the actual Trial 2 site
   count (1–2 hills, summer only) once run.

5. **"Remain conservative with safety, weather, and radio operation. Do not
   proceed with any configuration unless you are confident it is compliant
   and appropriate for the setting."**
   — **UPDATED 2026-07-23 — basis is the device's FCC certification as
   marketed** (decision A2 in `docs/open-decisions.md`). The 2026-07-21
   Part 97 selection could not be completed because no valid FCC callsign
   was provided; per the recorded fallback, field days run the stock,
   certified configuration: unmodified Heltec V3 firmware, stock TX power,
   default public LongFast channel, own traffic plus normal public-mesh
   participation, beacon placed and retrieved the same day. Still to record:
   photographs of the exact radio hardware labels (FCC ID). The production
   fixed-relay authorization question remains a report limitation, per the
   compliance memo.

## Final deliverable package (what to send when Trial 2 completes)

> frozen protocol pack · raw dataset · scored results · corrected simulation
> package · full written report

Mapping: `artifacts/trial2/predictions_fieldday.csv` + manifests +
`prereg_manifest.json` (frozen pack) · dataset release via
`build_dataset_release.py` on trial output (raw) · `airmap_live_trial.py`
scored outputs + `error_quantifier.py` (scored) · `release_v1` + fastsim +
`corrected_stats.json` (sim package) · rebuilt final report (report).

# Trial 2 Runbook — one page, day-of

**Purpose:** execute a controlled collection that can qualify as calibration-grade only
if its preregistered eligibility and provenance gates pass (proposal core deliverable).
Predictions and the dated feasibility amendment are recorded in
`docs/trial2-preregistration.md`. Do not silently change the model, strata, or
acceptance thresholds after collection starts; any later change needs a dated
amendment and separate original-versus-amended results.

## T-minus 1 week (home)
- [ ] Exact radio hardware, firmware, channel, power, antenna, and lawful
      authorization basis documented and reviewed; a preset name alone is not
      evidence of FCC compliance. Frozen config/hash: ______________________
- [ ] Overnight discharge test done (`scripts/discharge_test.py`) → measured
      mA recorded in config
- [ ] Ingest dry-run passed (see command sequence below) on Trial 1 data
- [ ] Batteries charged; firmware versions recorded; node IDs labeled
- [ ] Beacon and receiver set to a dedicated trial channel: fixed 30 s cadence,
      monotonic sequence numbers in payload, smart-position OFF, clocks synced.
      Record `hop_start` and `hop_limit`; only `hops_away == 0` packets are
      eligible. A hop-limit setting alone is not a direct-link guarantee.

## Field day (2 people minimum per proposal safety rule; wind <40 mph)
1. **Use one predeclared beacon site for the field day.** Primary:
   ammo_relay (44.26616, −71.32348). Jewell is a separate field-day replicate,
   not a second table to claim from an Ammo-only run. GPS-average 5 min;
   photograph mast/surroundings; measure antenna height and feed arrangement.
2. **Start beacon** on 3 m mast. Verify on phone app: packets at 30 s cadence,
   `hops away: 0` from a 100 m test.
3. **Walk the route frozen before collection** (Ammo–Jewell loop) at normal pace with
   the receiver at 1.5 m (chest strap). Do NOT chase signal — the route is
   the protocol.
4. **Opportunity accounting:** derive scheduled transmissions from the beacon's
   sequence-number range, including missing packets. The phone/app receive
   counter is not the PDR denominator. Target ≥40 scheduled opportunities per
   primary stratum across independent passes; keep smaller strata and label them
   underpowered. Walk normally—do not stop or slow down to manufacture samples.
5. **Replication:** repeat a complete segment in the opposite direction only if
   the schedule and safety margin allow. Otherwise schedule a second field day.
   Packets from one continuous pass are correlated observations, not independent
   replicates.
6. **Every hour:** photo of app status screen (backup evidence), battery %.
7. **Abort criteria:** thunder, wind >40 mph, receiver battery <20%.

## Same evening (data)
```
# pull the raw stream from the head node / phone export, then:
.venv/bin/python scripts/airmap_live_trial.py --predictor itm \
    --dem-npz artifacts/dem/cache/usgs_3dep_presidentials_wide.npz \
    --require-calibration-grade
.venv/bin/python scripts/build_dataset_release.py
.venv/bin/python scripts/build_evidence_index.py
```
- Run `scripts/build_calibration_file.py` only after the strict pipeline reports enough
  eligible data and the exclusion/opportunity audit is reviewed. A raw/evidence release
  should preserve a failed trial; a calibration artifact must not disguise one.
- Preserve raw data before analysis and record file hashes, software commit, exact
  radio config, start/end sequence numbers, exclusions, and aborted segments.
- Score the frozen model against `artifacts/trial2/predictions.csv` using the
  preregistered ±12 dB / ±0.15 engineering rule. Report per-stratum counts and
  Wilson PDR intervals; do not turn the rule into a statistical-equivalence claim.
- Treat RMSE ≤12 dB, fitted n ∈[1.6, 4.5], and σ≤10 dB as separate
  diagnostics. Do not emit a single scientific "PASS" when one is missing or
  computed on the same data used to fit the model.

## Operational success = the frozen protocol was executed and the raw evidence is
preserved, even if a quality gate fails. “Calibration-grade” is a reported outcome,
not a guaranteed label; failed/underpowered results remain part of the study and must
not produce a calibration file or validation claim.

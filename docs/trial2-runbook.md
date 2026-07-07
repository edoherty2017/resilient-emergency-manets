# Trial 2 Runbook — one page, day-of

**Purpose:** collect the calibration-grade dataset (proposal core deliverable).
Predictions are pre-registered in `docs/trial2-preregistration.md` — nothing
about the model may change after this page is executed.

## T-minus 1 week (home)
- [ ] FCC basis decided (A2) → radio config FROZEN: LongFast (Part 97) or
      500 kHz preset (Part 15). Write choice here: ______
- [ ] Overnight discharge test done (`scripts/discharge_test.py`) → measured
      mA recorded in config
- [ ] Ingest dry-run passed (see command sequence below) on Trial 1 data
- [ ] Batteries charged; firmware versions recorded; node IDs labeled
- [ ] Both nodes set: fixed cadence 30 s, sequence numbers in payload,
      smart-position OFF, hop_limit 1 on the beacon (direct-link guarantee)

## Field day (2 people minimum per proposal safety rule; wind <40 mph)
1. **Survey the beacon site** (ammo_relay: 44.26616, −71.32348): GPS-average
   5 min; photograph mast + surroundings; note antenna height.
2. **Start beacon** on 3 m mast. Verify on phone app: packets at 30 s cadence,
   `hops away: 0` from a 100 m test.
3. **Walk the pre-registered route** (Ammo–Jewell loop) at normal pace with
   the receiver at 1.5 m (chest strap). Do NOT chase signal — the route is
   the protocol.
4. **Strata quotas:** ≥600 packets per distance band × treeline stratum —
   the app's packet counter is the live check; slow down in thin strata.
5. **Repeat run** (≥2 passes per segment, opposite directions).
6. **Every hour:** photo of app status screen (backup evidence), battery %.
7. **Abort criteria:** thunder, wind >40 mph, receiver battery <20%.

## Same evening (data)
```
# pull the raw stream from the head node / phone export, then:
.venv/bin/python scripts/airmap_live_trial.py --predictor itm \
    --dem-npz artifacts/dem/cache/usgs_3dep_presidentials_wide.npz \
    --require-calibration-grade
.venv/bin/python scripts/build_dataset_release.py
.venv/bin/python scripts/build_calibration_file.py
.venv/bin/python scripts/build_evidence_index.py
```
- Gates verdict (RMSE ≤ 12 dB, n ∈ [1.6, 4.5], σ ≤ 10 dB) is whatever it is —
  a FAIL is a finding, not an emergency.
- Score strata against `artifacts/trial2/predictions.csv` (±12 dB / ±0.15 rule).

## Success = the dataset exists and is calibration-grade. Everything else
(report, calibration file, sim re-runs) is one command each afterward.

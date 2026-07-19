# Trial 2 Weekend Execution Plan — Sat Jul 18 / Sun Jul 19, 2026 (rev 3: Moosilauke + Kearsarge, no mast)

**Purpose:** collect the controlled empirical dataset the original directed-study
deliverable requires — the 10–15 page validation report with RMSE/MAE,
predictive-versus-actual heatmaps, and an infrastructure failure matrix. All the
analysis tooling exists; the only missing input is calibration-eligible field
data. This plan operationalizes [trial2-runbook.md](trial2-runbook.md) under the
prereg's protocol rules (30 s cadence, sequence numbers, `hops_away == 0`
eligibility, ≥40 opportunities/stratum target, two-person rule, abort criteria).

**Site change (initial-freeze decision, not an amendment — the pack is
explicitly not yet frozen):** the Ammonoosuc/Jewell (Mt Washington) field days
are replaced by **Mt Moosilauke (Sat)** and **Mt Kearsarge (Sun)**. The
runbook's Ammo–Jewell route parenthetical and 3 m-mast line are superseded by
this document. Consequences, stated honestly:

- The ≈60 dB Ammo-relay→summit FSPL-vs-ITM hypothesis is **deferred to a
  future Washington field day** — it is terrain-specific.
- Moosilauke preserves true above-treeline strata (summit 1,463 m > the
  1,100 m model treeline) and its ITM predictions are **non-monotonic with
  distance** (−92 dBm at 0.5–1 km above treeline, −114 dBm in the
  terrain-shadowed 0.5–1 km below-treeline band, recovering to −73 dBm at
  2–4 km) — a shape free-space physics cannot produce, so the weekend still
  carries a real FSPL-vs-ITM discriminating test.
- Kearsarge (summit 893 m) is entirely below the model treeline: its data all
  lands in below-treeline strata (the summit is open ledge; the model files it
  as below-treeline by elevation — noted honestly in the report).

**Team:** 2 people. **Beacon mount (no mast):** node on a chest-high boulder or
strapped to a trekking pole wedged in rocks, target ≈1.2 m; measure and
photograph the actual height. The prediction pack is computed at 1.2 m.

---

## The prediction pack (regenerated 2026-07-17; becomes frozen at tonight's commit)

`scripts/trial2_predictions_field.py` → `artifacts/trial2/predictions_fieldday.csv`
(+ `predictions_fieldday_manifest.json` binding rule, coordinates, heights,
DEM SHA-256s, git state). Beacon points are **rule-selected, not hand-picked**
(first ascending route sample at/above the target elevation):

| Day | Route (existing repo geometry) | Beacon | Coordinates | DEM elev | Trailhead |
|---|---|---|---|---|---|
| Sat 7/18 | `moosilauke_gorge_brook` out-and-back (~7.4 mi RT) | `moosilauke_treeline_beacon` (rule ≥1300 m) | 44.01708, −71.83777 | ~1352 m | Moosilauke Ravine Lodge, end of Ravine Lodge Rd |
| Sun 7/19 | `kearsarge_winslow` out-and-back (~2.2 mi RT) | `kearsarge_midslope_beacon` (rule ≥750 m) | 43.38735, −71.85970 | ~771 m | Winslow State Park |

DEMs: fresh USGS 3DEP tiles fetched 2026-07-17, summit-verified
(`usgs_3dep_moosilauke.npz` ~3.1 m/px, 1460.5 m at summit;
`usgs_3dep_kearsarge.npz` ~2.0 m/px, 892.8 m at summit).

| Deliverable | Tool | Weekend input |
|---|---|---|
| RMSE/MAE per stratum | `airmap_live_trial.py --predictor itm --require-calibration-grade` + `dataset_sentinel.py` → `error_quantifier.py` | direct-link beacon packets + receiver GNSS + beacon position broadcasts |
| Predictive-vs-actual heatmaps | `build_coverage_heatmap.py` (per-beacon `--tx-lat/--tx-lon`, per-day `--dem-npz`) | trial predictions parquet |
| Failure matrix | `weather_enrich.py` → `build_failure_matrix.py` | weather-enriched trial telemetry |
| Calibration file | `build_calibration_file.py` | only if strict gates pass — never forced |

**Honesty rule:** operational success = frozen protocol executed + raw evidence
preserved, even if a gate fails. Scoring the frozen model is valid either way.

---

## Tonight — Friday Jul 17 (freeze night)

1. **Hardware:** 2 Meshtastic nodes (labeled IDs) · **Pi logging rig running
   `telemetry_collector.py` + power bank + storage check** (the Pi's JSONL is
   the pipeline input; the phone app is backup only) · phone · Garmin ·
   trekking-pole/velcro beacon mount · chest strap (receiver ~1.5 m) · tape
   measure · laminated "RESEARCH EQUIPMENT — DO NOT DISTURB" tag with contact
   info.
2. **Radio config (both nodes):** dedicated trial channel;
   `LongFast_candidate` (chosen at freeze as primary); 30 s beacon cadence
   with **monotonic sequence numbers in payload**; smart-position OFF but
   **position broadcasts ON at 30–60 s** (eligibility needs a source fix
   within 60 s — `--src-pos-tolerance-s`); record `hop_start`/`hop_limit`;
   sync all clocks to phone NTP within ~1–2 s (note method); document
   hardware/firmware/TX power/antenna and the lawful-authorization basis.
3. **Denominator decision (record, dated):** scheduled-opportunity
   denominators are time-window-based at fixed 30 s cadence
   (`pdr_analysis.py`'s method); payload sequence numbers are the audit check.
   Adding a seq-parser later is an analysis addition, not a protocol change.
4. **Freeze ordering:** commit the pack (predictions_fieldday.csv + manifest +
   this plan + radio config) → `scripts/freeze_trial2_prereg.py --stamp
   <UTC-ISO> --force` → verify `git_worktree_dirty: false` → commit the
   manifest. Later changes are dated addenda.
5. **Overnight discharge test:** `.venv/bin/python scripts/discharge_test.py
   <telemetry_stream.jsonl> --cell-wh <measured Wh>` on a node logging device
   telemetry (replaces a BENCH-CALIBRATE placeholder).
6. **Ingest dry-run on Trial 1 data** with the exact Day-1 evening command
   below (defaults are wrong for this fleet — never rely on them).
7. **Weather + timeline:** forecast check both days (Moosilauke's summit is
   genuinely alpine — same rules: no thunder risk, wind < 40 mph; Kearsarge
   is low-commitment). Sat: trailhead ~08:00, beacon live ~09:30, **hard
   turnaround 13:00**. Tell a check-in person the route and return window.
   If Saturday aborts, Moosilauke takes Sunday and Kearsarge moves to a
   weekday evening — Moosilauke carries the above-treeline strata.

## Field days

1. Hike together. At the beacon point (nav to the coordinates above; the rule
   pins it near the treeline break on Moosilauke / the mid-slope ledges on
   Kearsarge): GPS-average 5 min; mount the node at ≈1.2 m; **measure +
   photograph height and surroundings (4 sides); attach the research tag;
   record the as-built coordinates/height** (the manifest records the planned
   ones; deviations are data, not sins).
2. Verify from ~100 m: 30 s cadence and `hops away: 0` on the phone, **and
   beacon rows with position + `hop_start`/`hop_limit` + sequence numbers in
   the Pi's JSONL** — the app screen is not verification.
3. Walk the out-and-back at normal pace (receiver chest-mounted, Pi logging,
   Garmin on). Do not chase signal or stop to manufacture samples. The descent
   is the second, opposite-direction pass.
4. Hourly: app screenshot + battery %. Target ≥40 scheduled opportunities per
   primary stratum across both passes; smaller strata (Kearsarge's 0.5–1 km
   band has only ~3 route samples) are kept and labeled underpowered.
5. **Retrieve the beacon on the descent** — the route passes it; no extra
   climbing. Record end sequence number, battery %, pickup time, any aborted
   segments.
6. Abort: thunder, wind > 40 mph, receiver battery < 20%, or the turnaround
   time — whichever first.

## Each evening (preserve, then analyze)

```bash
# 1. Preserve raw FIRST: Pi telemetry_stream.jsonl + phone export + Garmin GPX;
#    SHA-256 hashes, git commit, radio config, start/end sequence numbers.
# 2. Strict pipeline — EXPLICIT args (Sat shown; Sun: trial2-kearsarge-20260719
#    and usgs_3dep_kearsarge.npz):
.venv/bin/python scripts/airmap_live_trial.py \
    --ingest-root /tmp/manet_ingest \
    --node-id meshradiohead2 --head-id meshradiohead2 \
    --trial-id trial2-moosilauke-20260718 \
    --predictor itm \
    --dem-npz artifacts/dem/cache/usgs_3dep_moosilauke.npz \
    --tx-height-m 1.2 \
    --head-gpx <garmin_export.gpx> \
    --require-calibration-grade
.venv/bin/python scripts/build_dataset_release.py
.venv/bin/python scripts/build_evidence_index.py
```

Score the frozen `predictions_fieldday.csv` with the preregistered ±12 dB RSSI
/ ±0.15 PDR screens (diagnostics, not equivalence tests). Denominators per the
recorded decision (time-window; sequence numbers audit).

## Next week — assembling the original deliverable

1. **RMSE/MAE:** `dataset_sentinel.py` on the trial output →
   `error_quantifier.py --input <that sentinel parquet>` (never its stale
   default). Frozen-model scoring first; recalibration only on training
   passes, evaluated on held-out passes/days.
2. **Heatmaps:** `build_coverage_heatmap.py` per beacon — explicit
   `--tx-lat/--tx-lon` (Sat 44.01708/−71.83777; Sun 43.38735/−71.85970) and
   the matching day DEM.
3. **Failure matrix:** `weather_enrich.py` (pin product + request in
   provenance) → `build_failure_matrix.py`.
4. Write the validation report; every number carries its denominator and
   eligibility status.

## Known limits of this weekend (state in the report)

- Two field days, two hills, summer conditions — spatial/seasonal transfer
  untested; the Washington 60 dB blocked-link hypothesis is deferred.
- A ≈1.2 m beacon reduces modeled range vs a masted relay; the frozen
  predictions use the real height, so the comparison is valid, but
  relay-deployment conclusions at other heights need separate modeling.
- ITM excludes canopy loss; below-treeline strata may measure below
  prediction — that is itself a model-limitation finding, not a failure of
  the protocol.
- Kearsarge's far strata are underpowered by construction (short route);
  reported as descriptive.
- Trial 2 calibrates propagation and direct-link PDR only — not statewide
  traffic, routing, kiosk logistics, or annual energy behavior.

# Trial 2 Prospective Prediction Record — NOT YET FROZEN

Generated 2026-07-13T18:27:25.407536+00:00 from Git commit `a4dcdb395ea13869d01536db555d768f4aa4d9ea`
(worktree dirty: `true`). Model: Longley-Rice ITM q50 over USGS 3DEP
+ lognormal shadowing σ=8.0 dB (prospective placeholder;
any fitted σ is a post-trial estimate, not part of the frozen prediction).
TX EIRP 24.15 dBm; RX antenna gain
2.15 dBi; receiver-power reference
26.30 dBm. Heights: beacon 3 m mast,
receiver 1.5 m handheld. Feed losses are presently assumed 0 dB and must
be measured or reported as an assumption.

**Provenance warning:** the commit above is only the worktree's base
commit. Generating this document does not commit or timestamp it, the
generator, its inputs, or the ignored `artifacts/trial2/predictions.csv`.
Before fieldwork, commit/version the complete pack, record SHA-256 hashes
for every input and output, verify a clean worktree, and preserve later
amendments rather than overwriting the frozen record.

**Proposed engineering screen to freeze before collection:** flag a
stratum when measured median RSSI differs by more than 12 dB or measured
PDR differs by more than 0.15 from the model's threshold-exceedance
probability. This is a diagnostic tolerance, not a statistical
equivalence test. Report exact scheduled-opportunity denominators.
Packet-level Wilson intervals may be shown only as descriptive intervals
under an independence assumption; primary uncertainty must respect
within-pass dependence using whole-pass summaries or a pass/block-aware
interval. The propagation model's primary KPI is
out-of-sample RMSE across eligible field strata. Any recalibrated model
must be evaluated on entire held-out passes or days.

The probability in the table is not an empirically calibrated
packet-success probability. It is P(received power > assumed receiver
threshold), averaged over the stratum's modeled route samples, under an
independent Gaussian 8 dB shadowing term. It omits
interference, collisions, protocol behavior, hardware
variation, body/antenna effects, and temporal correlation. Measured direct
packet delivery ratio is the field outcome.

**Feasible protocol (Amendment 1, 2026-07-13, before fieldwork):** one
surveyed static beacon site per field day, fixed 30 s cadence, sequence
numbers, and `hops_away == 0` filtering. Walk the fixed route at normal
pace; never stop to manufacture a quota. Target ≥40 scheduled packet
opportunities per primary stratum across independent passes. Strata with
fewer than 40 are retained and reported as underpowered/descriptive.
Repeat a full segment in the opposite direction only when time and safety
permit; observations within one pass are not independent replicates.
The original 600–1,000 packets/stratum requirement was infeasible: at a
30 s cadence it requires 5–8.3 hours in every stratum.

The two radio rows below are candidate configurations, not claims that
either configuration is legally authorized as deployed.


## Beacon: ammo_relay (Ammonoosuc treeline relay)

| band (m) | stratum | model route samples | config | pred RSSI (dBm) | model P(RSSI > threshold) |
|---|---|---|---|---|---|
| 0-500 | above_treeline | 24 | LongFast_candidate | -51.1 | 1.0 |
| 0-500 | above_treeline | 24 | 500kHz_candidate | -51.1 | 0.985 |
| 0-500 | below_treeline | 8 | LongFast_candidate | -57.3 | 1.0 |
| 0-500 | below_treeline | 8 | 500kHz_candidate | -57.3 | 1.0 |
| 500-1000 | above_treeline | 74 | LongFast_candidate | -115.2 | 0.939 |
| 500-1000 | above_treeline | 74 | 500kHz_candidate | -115.2 | 0.579 |
| 500-1000 | below_treeline | 10 | LongFast_candidate | -73.3 | 1.0 |
| 500-1000 | below_treeline | 10 | 500kHz_candidate | -73.3 | 1.0 |
| 1000-2000 | above_treeline | 246 | LongFast_candidate | -124.3 | 0.712 |
| 1000-2000 | above_treeline | 246 | 500kHz_candidate | -124.3 | 0.298 |
| 1000-2000 | below_treeline | 14 | LongFast_candidate | -74.1 | 1.0 |
| 1000-2000 | below_treeline | 14 | 500kHz_candidate | -74.1 | 1.0 |
| 2000-4000 | above_treeline | 39 | LongFast_candidate | -132.1 | 0.457 |
| 2000-4000 | above_treeline | 39 | 500kHz_candidate | -132.1 | 0.07 |
| 2000-4000 | below_treeline | 18 | LongFast_candidate | -89.8 | 1.0 |
| 2000-4000 | below_treeline | 18 | 500kHz_candidate | -89.8 | 0.979 |

## Beacon: jewell_relay (Jewell Trail treeline relay)

| band (m) | stratum | model route samples | config | pred RSSI (dBm) | model P(RSSI > threshold) |
|---|---|---|---|---|---|
| 0-500 | above_treeline | 9 | LongFast_candidate | -60.4 | 1.0 |
| 0-500 | above_treeline | 9 | 500kHz_candidate | -60.4 | 0.998 |
| 500-1000 | above_treeline | 10 | LongFast_candidate | -108.4 | 0.997 |
| 500-1000 | above_treeline | 10 | 500kHz_candidate | -108.4 | 0.86 |
| 1000-2000 | above_treeline | 84 | LongFast_candidate | -99.3 | 0.98 |
| 1000-2000 | above_treeline | 84 | 500kHz_candidate | -99.3 | 0.873 |
| 1000-2000 | below_treeline | 32 | LongFast_candidate | -130.2 | 0.589 |
| 1000-2000 | below_treeline | 32 | 500kHz_candidate | -130.2 | 0.207 |
| 2000-4000 | above_treeline | 280 | LongFast_candidate | -119.7 | 0.905 |
| 2000-4000 | above_treeline | 280 | 500kHz_candidate | -119.7 | 0.429 |
| 2000-4000 | below_treeline | 18 | LongFast_candidate | -73.7 | 1.0 |
| 2000-4000 | below_treeline | 18 | 500kHz_candidate | -73.7 | 0.999 |

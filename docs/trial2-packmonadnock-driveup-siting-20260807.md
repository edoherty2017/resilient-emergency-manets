# Trial 2 amendment — drive-up beacon day at Pack Monadnock (registered 2026-08-07)

Dated pre-collection amendment per the runbook's amendment rule. Registers a new
beacon site, a new protocol variant, and a new frozen prediction pack. Nothing
here modifies the sealed 2026-07-23 field-day pack (`predictions_fieldday.csv`,
sha256 `a85e4d08…`) or the 2026-07-26 registered contact packs — those seals
were verified byte-intact before and after generation of this pack.

## Protocol variant

The beacon is **placed and retrieved by car** via the Miller State Park auto
road; the hiker walks `pack_monadnock_loop` with the receiver. Sequence:

1. Drive up; place beacon at the summit site; 5-min GPS average; photograph the
   mount, surroundings, and the **FCC ID label** (also feeds advisor
   criterion 5 / decision A2 hardware inventory); measure antenna height
   as-built; verify 30 s cadence and `hops_away == 0` on the phone app from a
   100 m walk test; drive down.
2. Hike the loop with the receiver logging (ascent pass, then descent pass).
3. Drive up; record end sequence number, battery %, pickup time; retrieve.
   **Same-day retrieval**, consistent with the recorded A2 mitigation.

## Beacon

- **Hardware:** Heltec Mesh Node T114 (`HELTEC_MESH_NODE_T114`, nRF52840 +
  SX1262), stock Meshtastic firmware (2.7.15 at registration), LongFast,
  stock TX power — certification-as-marketed basis; A2's hardware inventory
  must be updated to name this device with its label photo before the day.
- **Site (rule-selected):** first ascending track sample ≥ 680 m = the summit
  waypoint, **42.86160, −71.87810**, DEM elev 689.4 m
  (`rescue_miller_hq_pack_monadnock` ~4 m 3DEP raster). The car-accessible
  summit area is the physical placement; as-built coords/height are recorded
  on the day and never retro-edited into the frozen pack.
- **Heights:** modeled `beacon_hg_m = 1.2` (boulder/tripod, no mast),
  `hiker_hg_m = 1.5` — same convention as the sealed field-day pack.

## Frozen predictions (Tier 1: hashes recorded pre-collection)

| file | sha256 |
|---|---|
| `artifacts/trial2/predictions_packmonadnock.csv` | `5e675019c62dbf2a9eefda6bf24199d80d5c02963e2d9131a7083a218860223c` |
| `artifacts/trial2/predictions_packmonadnock_manifest.json` | bound in freeze manifest |
| `artifacts/trial2/prereg_manifest_packmonadnock.json` (11 inputs, `git_head 36b38737`, worktree clean, stamped 2026-08-07T19:37:15Z) | `081149dcd1d76c7dc94104c9cd52bbed16dda451c852a477eb741ce64e7b50df` |

Predicted rows (ITM q50, RX-power reference 26.3 dBm, σ = 8 dB placeholder):

| band | stratum | n | config | pred median RSSI | P(≥ sens) |
|---|---|---|---|---|---|
| 0–500 m | below_treeline | 7 | LongFast | −107.5 dBm | 0.998 |
| 0–500 m | below_treeline | 7 | 500 kHz | −107.5 dBm | 0.899 |
| 500–1000 m | below_treeline | 6 | LongFast | −112.6 dBm | 0.990 |
| 500–1000 m | below_treeline | 6 | 500 kHz | −112.6 dBm | 0.734 |

Falsifiable signature worth noting: the summit knob shadows the upper trail, so
the model predicts *weaker* close-range RSSI here (−107.5 dBm at 0–500 m) than
the Grand Monadnock ledge pack predicted at the same band (−73.9 dBm). If field
medians land near-field-strong instead, that is a specific ITM diffraction miss.

## Registered limitations (stated before collection)

- **Thin pack:** 4 rows, two distance bands (route max separation 991 m on the
  chord track); 1–8 km bands structurally empty; single stratum (site is below
  the 1100 m treeline definition). This day cannot exercise the 2–6 km
  ridge regime — that remains Grand Monadnock / Moosilauke territory.
- **Chord geometry:** the registered track is 150 m chord densification of the
  route waypoints (13 samples, same method as the sealed pack), not the OSM
  trail polyline; descent samples retrace ascent positions, so `n_samples`
  double-counts geometry. Opportunity accounting at scoring time uses
  scheduled transmissions (30 s cadence), not `n_samples`.
- **Unattended beacon:** while the hiker walks the loop, the beacon transmits
  under automatic control unattended at a car-accessible public summit — this
  amplifies the recorded A2 residual caveat (§97.203/§97.221 analysis
  outstanding under a Part 97 basis; moot under certification-as-marketed) and
  carries theft/tamper exposure. Mitigations: tuck placement, label photo,
  serial recorded, same-day retrieval.
- **Staffing:** the runbook's 2-person minimum is not yet resolved for a
  solo drive-up day — resolve before scheduling.
- Auto-road facts (season/hours/fees) are not grounded in this repo; verify
  with NH State Parks before the day.

## Scoring

Same machinery as the sealed pack: eligibility via `airmap_live_trial.py`
(`hops_away == 0`, GPS-fresh), PDR via `pdr_analysis.py --beacon-interval-s 30`
with the sequence-number denominator, screens ±12 dB RSSI / ±0.15 PDR,
out-of-sample RMSE reported per band. Tier-1 status holds only for data
collected **after** this registration.

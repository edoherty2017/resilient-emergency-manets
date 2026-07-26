# Trial 2 field day 4 — site change to Mount Monadnock (2026-07-24)

**Registered 2026-07-23 ~23:10 EDT (2026-07-24 03:10 UTC), before any collection.**
Site selection criterion set by Ethan: *the hike must be inside the live region of
the public Meshtastic mesh* (NHMesh live map + Discord community). This document
records the evidence, the decision, the new frozen predictions, and the protocol
amendments. Prior failed attempts (Jul 18/19/21) and the unscored Moosilauke pack
remain part of the trial record unchanged.

## Evidence: where the mesh is actually alive (2026-07-24 02:52–03:05 UTC)

Source: https://nhmesh.live API snapshot, preserved with checksums in
`artifacts/trial2/nhmesh_live_snapshot_20260723/` (PROVENANCE.txt, SHA256SUMS).

- 393 nodes active in the network's last-60-min window; NHMesh collector healthy
  (28 packets/min). **But 544 of 550 recently positioned nodes are MeshCore** — a
  different protocol our Meshtastic radios cannot hear. Only **6 Meshtastic
  (LongFast) nodes** exist on the map:

  | node | where | last seen | active last 60 min |
  |---|---|---|---|
  | NewMikeshire | Keene (42.9326, −72.2797) | 12 min | **yes (10 pkts)** |
  | Keene NH Court St Rooftop | Keene (42.9130, −72.2731) | 26 min | **yes** |
  | Benchy Radio | Nashua area | 10 h | no |
  | NHMesh WeMo | Hopkinton (43.1358, −71.6833) | 13 h | no |
  | !433c6aa | Washington NH area | 23 h | no |
  | HH10 Washington Beacon | Washington NH area (43.1620, −72.1551) | 23 h | no |

- The White Mountains (Moosilauke etc.) have **zero** Meshtastic nodes on the map;
  nearest anything is MeshCore ~24 km away. Caveat: nhmesh.live only shows what
  NHMesh collectors hear — absence on the map is not proof of RF absence.
- NHMesh beacon message announces **migration from LONG_FAST to MEDIUM_FAST
  "soon"** — a standing risk to any future public-mesh interoperability claims.

## Candidate comparison (ITM q50, statewide 3DEP DEM, EIRP ref 26.3 dBm)

- **Kearsarge (Winslow)** — the pre-frozen "deferred-future-field-day" alternate:
  predicted **deaf to every public node** (loss 174–201 dB from beacon spot *and*
  summit). Fails the siting criterion. Pack stays frozen for a future day.
- **Monadnock (White Dot)**: summit → Keene Court St Rooftop **115 dB,
  line-of-sight → predicted RX ≈ −89 dBm** (above the −100 dBm planning
  threshold); summit → NewMikeshire ≈ −112 dBm (marginal); registered in full in
  `artifacts/trial2/monadnock_livemesh_predictions_20260723.json`.

**Decision: Mount Monadnock, White Dot out-and-back, 2026-07-24,
`trial_id = trial2-monadnock-20260724`.**

## New frozen prediction pack (controlled-beacon validation)

Generated tonight by `scripts/trial2_predictions_field.py` (Monadnock day added;
Moosilauke + Kearsarge rows verified **byte-identical** by diff after regeneration):

- Beacon placement rule: first ascending route sample ≥ 850 m →
  **(42.86010, −72.10682), DEM elev 909 m**, `monadnock_ledge_beacon`, 1.2 m
  no-mast mount, as-built coords/height to be recorded in the field (GPS average
  + photo).
- 33 route samples, Tobler walk ≈ 2.0 h; 8 prediction rows (4 distance bands × 2
  configs) appended to `artifacts/trial2/predictions_fieldday.csv`.
- DEM: `artifacts/dem/cache/usgs_3dep_monadnock.npz` (USGS 3DEP, fetched tonight).

Pre-collection hashes (freeze evidence; git commit still pending Ethan's E1 call):

```
a85e4d0803c95cc826b3ed9783c6f5a0ceca2aac517077544651267a28cf3bbb  artifacts/trial2/predictions_fieldday.csv
3e6df03fe8e8030c46cae965e65c073e825188b848a2eb4da7983ab56700326e  artifacts/trial2/predictions_fieldday_manifest.json
57936e6b2f6364ae8434b81fd455e574c3dc1208f2d7b23e8975a4215e0379b3  artifacts/dem/cache/usgs_3dep_monadnock.npz
f0e4429dd330774f6e7a97d214dbfd3e18e5703f14aa8a2db8922ba9ddfddace  artifacts/dem/cache/usgs_3dep_monadnock_manifest.json
aba23c13ad402fa2d7910ff6ac95059acc100833393ce4abaaeb1b66827eb882  artifacts/trial2/monadnock_livemesh_predictions_20260723.json
5d21e6174f30b6601037c47cb096199a1e90ef67fb46a9454044de7a241e9310  scripts/trial2_predictions_field.py
```

## Protocol amendments & honest deviations (dated 2026-07-23)

1. **Site change** is registered *before* collection — the Monadnock pack is a
   prospective sibling of the Moosilauke pack, not a swap. Moosilauke remains
   frozen and unscored.
2. **Public default LongFast channel** (both radios) instead of a dedicated
   encrypted trial channel. Required for the live-mesh objective anyway.
   Consequences: (a) beacon RSSI eligibility is protected by the existing
   `from_mesh_id` + `hops_away == 0` gate — mesh-relayed copies are excluded by
   design; (b) channel-utilization measurements carry a public-traffic
   contamination caveat.
3. **Stratum label caveat**: the generator's fixed `TREELINE_M = 1100` labels all
   Monadnock samples `below_treeline` although the summit cone is bare rock
   (~965 m). Labels are kept as generated; report must note the local-treeline
   mismatch. Predictions are unaffected (DEM-driven).
4. **Public-node links are NON-calibration-grade** (unknown TX EIRP/antenna/
   uptime) — they score as binary contact predictions only, never as RSSI
   calibration rows.
5. **Compliance basis (A2 update)**: no valid FCC callsign was provided
   ("MeshVworld" is not a valid callsign format and was never programmed), so per
   the recorded fallback the operation basis is **the device's FCC certification
   as marketed**: stock Heltec V3 hardware/firmware, stock TX power, default
   public LongFast channel — i.e., exactly the configuration the device ships
   and is marketed with. Ham-mode/Part 97 remains available within ~5 min if a
   valid callsign is provided. Production-relay authorization remains a report
   limitation.

## Trailhead sequence (amended 2026-07-24: Ethan is away from home — the Pi
## cannot be network-checked before the hike; all verification is in-field)

1. Power the Pi from the bank; plug the receiver in with Monday's known-good
   data cable. Wait ~3 min (boot + 60 s LED timer).
2. **ACT LED solid = GO** (radio enumerated + collector writing fresh rows —
   the watcher runs standalone, no network needed). Fast blink = reseat
   cable/other USB port, power cycle once.
3. Phone Meshtastic app over BLE is the in-field contact display: Keene nodes
   appearing in the node list with RSSI at the summit = the registered
   prediction confirmed live.
4. **Documented labeling deviation (registered pre-collection):** the Pi's
   `TRIAL_ID` env still reads `trial2-moosilauke-20260722` and cannot be
   changed before the hike (no network path to the Pi). Rows collected
   2026-07-24 are attributed to `trial2-monadnock-20260724` by collection
   date + GPS track; the evening pipeline is invoked with the explicit
   `--trial-id trial2-monadnock-20260724`. The env var is corrected when the
   Pi reaches the home LAN tonight.

## Plan B — one-radio day (registered 2026-07-24, pre-departure)

Ethan expects to field **only the receiver** (beacon presumed unusable: dead
internal LiPo + broken USB-C port). Decision recorded: **stay on Meshtastic; do
not reflash to MeshCore** — the collector stack, eligibility gates, frozen radio
metadata, and every registered prediction are Meshtastic LongFast, and the only
live public nodes in range (Keene) are LongFast. A protocol switch hours before
departure recreates the rig-integration failure mode of Jul 18–21.

What a one-radio day IS: a registered contact-validation + systems day.
- Scores the four prospective links in
  `monadnock_livemesh_predictions_20260723.json` as binary contact outcomes,
  plus opportunistic RSSI rows from known-position public nodes
  (non-calibration-grade — unknown TX EIRP/antenna).
- Receiver position broadcasts ON: if Keene gateways hear the node it appears on
  nhmesh.live — independent third-party contact evidence, to be captured from
  the map the same evening.
- Summit dwell 15–20 min (the predicted −89 dBm Keene link is the main event).
- go/no-go: `beacon_heard` FAILs legitimately; five PASSes = GO.

What a one-radio day is NOT: it produces **zero calibration-eligible strata**.
The Monadnock beacon pack (like Moosilauke's) stays frozen and unscored,
awaiting a two-radio day; the ≥40-opportunity target and the 2,500-point
dataset (A5) remain unmet and are reported as such.

If the beacon unexpectedly boots on the good cell in the morning, the original
two-radio plan resumes unchanged — this section then records a contingency that
was not needed.

Future-work note (not for this field day): dual-protocol rig — second board on
MeshCore + a MeshCore serial collector — enables a same-terrain two-PHY
comparison against the same ITM model. MeshCore is where NHMesh's density now
is (544 of 550 mapped nodes, incl. SundayMt repeater 24 km from Moosilauke).

## Field notes to capture (unchanged protocol + new items)

- As-built beacon coords/height (GPS average + photo), placement time.
- Photos of radio hardware labels incl. FCC ID (advisor criterion 5 evidence).
- Summit dwell: hold ≥ 10 min at/near the summit so the receiver gets a fair
  window for the predicted Keene contact.
- Evening: preserve raw FIRST, then the standard `airmap_live_trial.py` scoring
  with `--dem-npz artifacts/dem/cache/usgs_3dep_monadnock.npz`
  `--trial-id trial2-monadnock-20260724 --require-calibration-grade`.

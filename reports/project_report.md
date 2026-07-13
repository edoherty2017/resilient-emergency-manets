# Mt. Washington MANET Trial 1 — Project Report

**Trial date:** 2026-05-23  
**Node:** meshradiohead2 (HEAD) — Heltec LoRa32 V3, 915 MHz, Meshtastic LongFast (SF11 BW250 CR4/5)  
**Route:** Ammo Trail ascent → Mt. Washington summit → Jewell Trail descent  
**GPS source:** Garmin external (8,246 track points, 08:06–18:40 EDT)

---

## What This Project Is

A field-data collection and pipeline study of LoRa/Meshtastic observations in the
White Mountains, with the longer-term goal of evaluating fixed relay infrastructure
for emergency communications. Trial 1 exercised the equipment on a summit hike, but
did not validate end-to-end relay coverage or a propagation model: it lacked a
controlled remote transmitter, direct-hop labels, and an uninterrupted collector
record. A Garmin track supplies independent receiver-position ground truth only; it
does not establish transmitter position or RF-link ground truth.

---

## Artifacts

### Interactive Map
**`artifacts/coverage_prediction/hike_data_map.html`**

The primary deliverable for sharing. Open in any browser — no server required, fully standalone.

What it shows:
- Full GPS route (08:06–18:40 EDT) color-coded by 5-min RSSI window
- Gray segment: Ammo ascent before collector came online
- Red dashed segment: 2h48m collector offline gap (09:36–12:24 EDT)
- Summit pin at 1917m, 14:23 EDT
- The map input contains 50 decoded node IDs; the separately generated mesh catalog
  contains 41 unique RF source IDs, 24 with GPS. These artifact/filter definitions
  have not been reconciled, so neither count should be presented as the single
  authoritative “nodes heard” total.
- Animated HEAD marker that follows the Garmin track in real time (Play/Pause)
- Rolling 30-min node counter
- **"PROPOSED — Relay Infrastructure"** layer: three fixed relay nodes with link budget tables at each marker (click to open)
- **"PROPOSED — Coverage if Deployed"** layer: a historical FSPL screening
  visualization. Its label/legend can imply continuous coverage, but the later ITM
  analysis contradicts that conclusion; do not use the layer as evidence of coverage.
- **AIRMap Overlay button** (green, bottom-right): toggles 138 historical joined
  residual dots. They are not calibration-eligible and their “error/accuracy” color
  labels must not be interpreted as model-performance evidence.

**Layer controls** (bottom-right, above the animation panel): toggle any layer on/off.  
**"The Proposal" button** (top-right): slide-out pitch panel with link budget math, automation chain, and cost breakdown.

---

### Technical Report (PDF)
**`artifacts/coverage_prediction/trial1_report.pdf`**  
**`artifacts/coverage_prediction/trial1_report.tex`** (source)

The PDF was reproducibly rebuilt from the corrected TeX on 2026-07-13 using
Tectonic 0.16.9. `trial1_report_manifest.json` binds SHA-256 hashes for the build
script, TeX source, and PDF (PDF `1c491082…`; source `a6ea9480…`). The PDF,
manifest, and build script are tracked in the current checkpoint. This establishes a
reproducible rendering of the corrected source; it does not turn the historical inputs
into field-validation evidence.

A technical LaTeX report covering (with the historical FSPL proposal explicitly
superseded by its later ITM section):
- Log-distance path loss model (Bianco et al. 2021): PL(d) = PL(d₀) + 10n·log₁₀(d/d₀) + Xσ
- Floating-intercept calibration: PL(d) = α + 10β·log₁₀(d) + Xσ
- FSPL baseline: 32.44 + 20·log₁₀(d_km) + 20·log₁₀(915 MHz)
- Link budget assumption: 22 dBm conducted + 2.15 dBi TX antenna + 2.15 dBi
  RX antenna − (−131 dBm receiver sensitivity) = **157.3 dB**. Transmitter
  EIRP is **24.15 dBm**; the receive-antenna gain is a separate link term.
- LoRa data rate equation and SNR margin
- Effective Signal Power (ESP) combining RSS + SNR
- AIRMap pipeline output and the reasons Trial 1 yields zero defensible calibration
  results (Section 7); the embedded 4-panel figure is historical and non-citable
- Timeline of events, relay node coordinates, proposed infrastructure math

---

### AIRMap Calibration Pipeline Data
**`artifacts/airmap/live_trial/`**

The files currently in this directory are **not a canonical Garmin-ground-truthed
Trial 1 regeneration**. `provenance.json` records a 2026-07-07 run whose input is the
`meshhikernode1` JSONL export and whose `head_gpx` is null; `quality_gates.json` records
zero calibration-eligible rows. The directory README says regeneration with the HEAD
telemetry and Garmin GPX is still required, so the README and presence of the later
run outputs must not be interpreted as a completed Trial 1 evidence pack. The current
code implements an FSPL baseline and gated calibration workflow, but **Trial 1 did not
produce valid calibration measurements** due to three structural gaps:

1. **No `hop_count` field** — Meshtastic logs RSSI of the last hop, not the original sender. Cannot filter to direct links without it.
2. **Adjacent device forwarding** — `!db51af80` (co-located with HEAD) forwarded packets from distant NH/VT/ME nodes. HEAD logged those with the distant node's GPS coordinates but the adjacent device's RSSI (~0 m away). Distance–RSSI pairs are physically invalid.
3. **No independently placed static node** — no controlled source-to-receiver link with GPS on both ends.

These files are retained as pipeline-run artifacts, not raw data. The displayed
delta/RMSE/MAE values include ineligible rows and must not be cited as model results.
Regenerate from hashed raw inputs plus the Garmin GPX and preserve a manifest before
citing even descriptive counts.

---

### Mesh Neighbor Catalog
**`artifacts/mesh_catalog/`**

| File | Contents |
|---|---|
| `observations.parquet` | All RF observations with GPS-joined positions |
| `node_summary.json` | Per-node stats: RSSI, position, packet count, distance |
| `catalog_summary.json` | 764 total RF observations, 41 unique source nodes, 24 with GPS |

The catalog was built before the Garmin GPS integration — HEAD position uses the static
reference point method. The current `live_trial` artifacts do not supersede it with a
valid calibration dataset, and the catalog's forwarded/far-field observations do not
establish physical multi-node link topology. Treat it as a decoded-source inventory
under its own filters.

---

### DEM / Terrain Features — ⚠ SYNTHETIC, pipeline-validation only
**`artifacts/dem/`**

**These artifacts are NOT derived from real elevation data.** `dem_transformer.py`
currently generates a deterministic synthetic pseudo-DEM (see
`feature_provenance_manifest.json`: `"source": "synthetic-dem-deterministic"`), and the
generation window was polluted by far-field GPS coordinates from ambient mesh packets.
The slope/terrain-class/geology features derived from it must not be cited as terrain
analysis. Real USGS 3DEP ingestion is a pending work item (see
`docs/academic-rigor-review-2026-06-12.md`, P2 item 11).

| File | Contents |
|---|---|
| `route_topography_features.parquet/.csv` | SYNTHETIC elevation/slope/terrain class per GPS point |
| `geology_loss_features.parquet/.csv` | Material attenuation priors — uncited engineering placeholders, not used by the prediction model |
| `geology_loss_summary.json` | Summary of the placeholder loss factors |
| `feature_provenance_manifest.json` | Provenance (correctly labels the synthetic source) |
| `cache/dem_tile_bde46df9d7ebdabd.npz` | Cached synthetic pseudo-DEM tile (not USGS data) |

Topography classes used throughout the pipeline: alpine_ridge (≥1500m), sub_alpine (1200–1500m), valley_forest (<1200m) — assigned from observed GPS elevation, not from the DEM.

---

### Schema Validation
**`artifacts/reports/schema_validation_meshradiohead2.json`**

The historical report counted 64,462 parsed rows and 3 parse errors (0.005%). This
establishes parseability under the validator version used for that run, not that all
records are scientifically usable: direct-hop identity, remote-transmitter geometry,
and calibration-grade completeness were not available. Regenerate this result with
the current strict validator before citing exact schema-pass counts.

---

## Proposed Infrastructure Summary

Three fixed nodes at terrain breakpoints on the Ammo/Jewell trail system:

| Node | Location | Elevation | FSPL screen → Summit | **ITM (real terrain) → Summit** | Est. Cost |
|---|---|---|---|---|---|
| Ammo Trail Relay | 44.26616°N, 71.32348°W | 1201 m | ~~−72.9 dBm~~ | **−132 dBm (below sensitivity)** | ~$120 |
| Jewell Trail Relay | 44.28376°N, 71.33583°W | 1199 m | ~~−77.9 dBm~~ | **−119 dBm (marginal)** | ~$120 |
| Trailhead Gateway | 44.26700°N, 71.36083°W | 764 m | — (Starlink uplink) | relay→gateway links **strong** (−74 to −77 dBm, clear LOS) | ~$450 |

Historical concept: Heltec LoRa32 V3 + 5W solar + IP67 enclosure per relay; Pi 4 +
radio + Starlink Mini at the gateway. The **~$690** figure is an unquoted rough hardware
subtotal that excludes mounting, power-system validation, weatherization details,
service, permits, installation, and maintenance; it is not a deployment cost.

### ⚠ ITM terrain-profile verification (2026-06-12) reversed the screening model

Longley-Rice ITM over a USGS 3DEP terrain artifact (`scripts/itm_relay_links.py`,
`artifacts/itm/`) finds terrain up to 53 m above the modeled direct ray from the Ammo
relay. Under the stated model inputs, the treeline-to-summit links the FSPL screen called
"strong" are predicted blocked, while the valley links are predicted clear-LOS and
strong. Modeled 10 m masts, Lakes of the Clouds siting, and a summit node do not produce
a robust single-hop summit link. These are model comparisons, not observed link states.

Collector-gap (Ammo Ravine) coverage, best-of-relays at ITM q90: **100% of sampled
points above raw sensitivity, but only 45% above the −100 dBm planning threshold.**
"The gap would have been covered" is downgraded to *marginal, unproven*. Trial 2 will
place a beacon at the Ammo relay site and measure PDR from the ravine — the ~60 dB
FSPL-vs-ITM disagreement is a directly measurable hypothesis.

Full model outputs: `artifacts/itm/relay_links_itm.csv`,
`artifacts/itm/itm_summary.json`; airtime/load estimates in
`artifacts/itm/lora_airtime.json` (3-hop SOS ≈2.2 s serial airtime; ~22 nodes ≈20%
raw channel demand at the assumed beacon rates, before validating actual protocol load).

---

## Known Limitations

1. **Relay link predictions are screening estimates only** — the original FSPL model
   lacks terrain geometry; ITM adds modeled terrain diffraction but is still uncalibrated
   here and omits/approximates important clutter and hardware effects. Require site
   surveys and controlled PDR measurements before any deployment decision.
2. **rsrp_dbm always null** — pipeline ran on rssi_dbm fallback throughout. rsrp_dbm is a cellular metric irrelevant to LoRa; this is expected.
3. **Distant-node contamination** — 68% of historical matches were at implausible
   apparent distances (>50 km), driving up an ineligible-row RMSE. Co-located forwarding
   means original packet coordinates cannot be paired with the last-hop RSSI; they are
   not direct long-distance link measurements.
4. **meshnode1 offline** — the project records an SD-card fault; single-node data only.
   Multi-hop analysis remains pending a controlled deployment.
5. **Low GNSS fix rate** — the historical report gives 1.8% GPS completeness. Receiver-
   only position does not create source-to-receiver link geometry.
6. **No contemporaneous validated weather measurement** — any gridded/default weather
   labels are covariates with their own provenance, not on-route station observations.

---

## Scripts That Produced These Artifacts

| Script | What it produces |
|---|---|
| `scripts/hike_data_map.py` | `hike_data_map.html` (interactive map) |
| `scripts/airmap_live_trial.py --head-gpx ...` | `artifacts/airmap/live_trial/` (all parquet + JSON) |
| `scripts/airmap_figures.py` | `airmap_figures.png` (4-panel figure) |
| `scripts/mesh_neighbor_catalog.py` | `artifacts/mesh_catalog/` |
| `scripts/dem_transformer.py` | `artifacts/dem/route_topography_features.*` |
| `scripts/geology_loss.py` | `artifacts/dem/geology_loss_features.*` |
| `scripts/validation/schema_validate.py` | `artifacts/reports/schema_validation_*.json` |
| `artifacts/coverage_prediction/trial1_report.tex` | Compiled to `.pdf` via `tectonic` |

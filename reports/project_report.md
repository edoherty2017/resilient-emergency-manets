# Mt. Washington MANET Trial 1 — Project Report

**Trial date:** 2026-05-23  
**Node:** meshradiohead2 (HEAD) — Heltec LoRa32 V3, 915 MHz, Meshtastic LongFast (SF11 BW250 CR4/5)  
**Route:** Ammo Trail ascent → Mt. Washington summit → Jewell Trail descent  
**GPS source:** Garmin external (8,246 track points, 08:06–18:40 EDT)

---

## What This Project Is

A field-validated study of LoRa/Meshtastic mesh radio performance in the White Mountains, with the goal of proposing a fixed relay infrastructure for NH State Park emergency communications coverage. The HEAD node (a Raspberry Pi + Heltec LoRa32) was carried on a full summit hike while logging all received mesh packets. Real Garmin GPS data was used as ground truth for position throughout.

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
- All 50 heard mesh nodes colored by RSSI; 24 have known GPS positions
- Animated HEAD marker that follows the Garmin track in real time (Play/Pause)
- Rolling 30-min node counter
- **"PROPOSED — Relay Infrastructure"** layer: three fixed relay nodes with link budget tables at each marker (click to open)
- **"PROPOSED — Coverage if Deployed"** layer: full trail colored by predicted RSSI from nearest relay, showing the 2h48m gap would have continuous coverage
- **AIRMap Overlay button** (green, bottom-right): toggles 138 pre-calibration prediction error dots colored by magnitude (green = accurate ±5 dB, orange/red/purple = overestimate, blue = underestimate)

**Layer controls** (bottom-right, above the animation panel): toggle any layer on/off.  
**"The Proposal" button** (top-right): slide-out pitch panel with link budget math, automation chain, and cost breakdown.

---

### Technical Report (PDF)
**`artifacts/coverage_prediction/trial1_report.pdf`**  
**`artifacts/coverage_prediction/trial1_report.tex`** (source)

A mathematically rigorous LaTeX report covering:
- Log-distance path loss model (Bianco et al. 2021): PL(d) = PL(d₀) + 10n·log₁₀(d/d₀) + Xσ
- Floating-intercept calibration: PL(d) = α + 10β·log₁₀(d) + Xσ
- FSPL baseline: 32.44 + 20·log₁₀(d_km) + 20·log₁₀(915 MHz)
- Link budget: TX 22 dBm + 2×2.15 dBi ANT − (−130 dBm RX sensitivity) = **156.3 dB**
- LoRa data rate equation and SNR margin
- Effective Signal Power (ESP) combining RSS + SNR
- AIRMap calibration results (Section 7) with the 4-panel figure embedded
- Timeline of events, relay node coordinates, proposed infrastructure math

---

### AIRMap Calibration Pipeline Data
**`artifacts/airmap/live_trial/`**

Raw pipeline outputs from `scripts/airmap_live_trial.py`. The calibration pipeline is correctly implemented (FSPL baseline + residual bias fit) but **Trial 1 did not produce valid calibration measurements** due to three structural gaps:

1. **No `hop_count` field** — Meshtastic logs RSSI of the last hop, not the original sender. Cannot filter to direct links without it.
2. **Adjacent device forwarding** — `!db51af80` (co-located with HEAD) forwarded packets from distant NH/VT/ME nodes. HEAD logged those with the distant node's GPS coordinates but the adjacent device's RSSI (~0 m away). Distance–RSSI pairs are physically invalid.
3. **No independently placed static node** — no controlled source-to-receiver link with GPS on both ends.

These files are retained as raw data for the pipeline record. The calibration numbers (delta, RMSE, MAE) should not be cited as results.

---

### Mesh Neighbor Catalog
**`artifacts/mesh_catalog/`**

| File | Contents |
|---|---|
| `observations.parquet` | All RF observations with GPS-joined positions |
| `node_summary.json` | Per-node stats: RSSI, position, packet count, distance |
| `catalog_summary.json` | 764 total RF observations, 41 unique source nodes, 24 with GPS |

The catalog was built before the Garmin GPS integration — HEAD position uses the static reference point method. The `live_trial` parquet files above supersede this for calibration purposes, but the catalog is still the authoritative source for multi-node topology.

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

64,462 total rows, 0 data-invalid, 3 parse errors (0.005%). All required fields present. Confirms the telemetry stream from meshradiohead2 is clean.

---

## Proposed Infrastructure Summary

Three fixed nodes at terrain breakpoints on the Ammo/Jewell trail system:

| Node | Location | Elevation | FSPL screen → Summit | **ITM (real terrain) → Summit** | Est. Cost |
|---|---|---|---|---|---|
| Ammo Trail Relay | 44.26616°N, 71.32348°W | 1201 m | ~~−72.9 dBm~~ | **−132 dBm (below sensitivity)** | ~$120 |
| Jewell Trail Relay | 44.28376°N, 71.33583°W | 1199 m | ~~−77.9 dBm~~ | **−119 dBm (marginal)** | ~$120 |
| Trailhead Gateway | 44.26700°N, 71.36083°W | 764 m | — (Starlink uplink) | relay→gateway links **strong** (−74 to −77 dBm, clear LOS) | ~$450 |

Hardware: Heltec LoRa32 V3 + 5W solar + IP67 enclosure per relay. Gateway: Pi 4 + Heltec V3 + Starlink Mini. **Total hardware: ~$690 one-time.**

### ⚠ ITM terrain-profile verification (2026-06-12) reversed the screening model

Longley-Rice ITM over real USGS 3DEP terrain (`scripts/itm_relay_links.py`,
`artifacts/itm/`) shows the **summit cone is convex** — terrain rises up to 53 m above
the direct ray from the Ammo relay — so the treeline-to-summit links the FSPL screen
called "strong" are actually blocked, while the forested valley links it called weakest
are clear-LOS and strong. Tested mitigations (10 m masts, Lakes of the Clouds siting,
summit tower node) do not produce a robust single-hop summit link at 915 MHz.

Collector-gap (Ammo Ravine) coverage, best-of-relays at ITM q90: **100% of sampled
points above raw sensitivity, but only 45% above the −100 dBm planning threshold.**
"The gap would have been covered" is downgraded to *marginal, unproven*. Trial 2 will
place a beacon at the Ammo relay site and measure PDR from the ravine — the ~60 dB
FSPL-vs-ITM disagreement is a directly measurable hypothesis.

Full numbers: `artifacts/itm/relay_links_itm.csv`, `artifacts/itm/itm_summary.json`,
airtime/capacity in `artifacts/itm/lora_airtime.json` (3-hop SOS ≈ 2.2 s serial
airtime; ~22 summit nodes ≈ 20% channel load at default beacon rates).

---

## Known Limitations

1. **Relay link predictions are screening estimates only** — the FSPL + elevation-class model has no line-of-sight test, Fresnel clearance, or diffraction. Each proposed link must be re-evaluated with ITM/Longley-Rice over real USGS 3DEP terrain (plus a viewshed analysis) before any deployment decision.
2. **rsrp_dbm always null** — pipeline ran on rssi_dbm fallback throughout. rsrp_dbm is a cellular metric irrelevant to LoRa; this is expected.
2. **Distant-node contamination** — 68% of records were matched at implausible distances (>50 km), driving up RMSE. These are Meshtastic packets from NH/VT/ME mesh users picked up over the air, not the local test network.
3. **meshnode1 offline** — SD card hardware fault; single-node data only. Multi-hop analysis pending deployment.
4. **Low GNSS fix rate** — 1.8% of records have GPS; most calibration points use HEAD position only, not source-to-head geometry.
5. **No live weather feed** — weather stratification uses synthetic defaults.

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

#!/usr/bin/env python3
"""Pre-trial coverage prediction map for Mt. Washington.

No field data required — uses FSPL at 915 MHz plus terrain-class loss estimates.
Outputs:
  artifacts/coverage_prediction/coverage_map.html     — interactive Folium map
  artifacts/coverage_prediction/rssi_vs_distance.png  — range curves
"""
from __future__ import annotations

import argparse
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import folium
import folium.plugins
import matplotlib.pyplot as plt
import numpy as np

from radio_link_budget import (
    RX_ANTENNA_GAIN_DBI,
    RX_POWER_REFERENCE_DBM,
    RX_SENSITIVITY_DBM,
    TX_ANTENNA_GAIN_DBI,
    TX_CONDUCTED_DBM,
    TX_EIRP_DBM,
)

# ---------------------------------------------------------------------------
# Radio parameters (Heltec V3 + LoRa @ 915 MHz, Meshtastic defaults)
# ---------------------------------------------------------------------------
FREQ_MHZ       = 915.0
TX_POWER_DBM   = TX_CONDUCTED_DBM
TX_ANT_GAIN_DBI = TX_ANTENNA_GAIN_DBI
RX_ANT_GAIN_DBI = RX_ANTENNA_GAIN_DBI
RX_SENS_DBM    = RX_SENSITIVITY_DBM
RX_POWER_REF_DBM = RX_POWER_REFERENCE_DBM

LINK_BUDGET_DB = RX_POWER_REF_DBM - RX_SENS_DBM

TERRAIN_LOSS = {
    "Open / Alpine (above treeline)": 3,
    "Mixed / Sub-alpine":             15,
    "Dense Forest (below treeline)":  25,
}

TERRAIN_COLORS = {
    "Open / Alpine (above treeline)": "#2196F3",
    "Mixed / Sub-alpine":             "#FF9800",
    "Dense Forest (below treeline)":  "#795548",
}

# ---------------------------------------------------------------------------
# Key Mt. Washington locations
# ---------------------------------------------------------------------------
LOCATIONS = {
    "Summit (1917 m)":                 (44.27025, -71.30333),
    "Lakes of the Clouds Hut (1528m)": (44.25872, -71.31915),
    "Trailhead / Cog Base Station":    (44.26689, -71.36113),
    "Jewell–Gulfside Junction":        (44.28259, -71.31689),
    "Alpine Garden":                   (44.26780, -71.29220),
}

AMMO_TRAIL:      list[tuple] = []   # (lat, lon) for static polyline display
JEWELL_TRAIL:    list[tuple] = []   # (lat, lon) for static polyline display
AMMO_ANIM:       list[tuple] = []   # (lat, lon, elev_m) finer-res for animation
JEWELL_ANIM:     list[tuple] = []   # (lat, lon, elev_m) finer-res for animation
TREELINE_AMMO:   tuple | None = None
TREELINE_JEWELL: tuple | None = None
GEM_POOL:        tuple | None = None


def parse_gpx(path: Path) -> list[tuple[float, float, float]]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    pts = (root.findall(f".//{prefix}trkpt") or
           root.findall(f".//{prefix}rtept") or
           root.findall(f".//{prefix}wpt"))
    result = []
    for p in pts:
        ele = p.find(f"{prefix}ele")
        result.append((float(p.get("lat")), float(p.get("lon")),
                       float(ele.text) if ele is not None else 0.0))
    return result


def first_crossing(pts: list[tuple], elev: float) -> tuple | None:
    for i in range(len(pts) - 1):
        if pts[i][2] < elev <= pts[i + 1][2]:
            return pts[i]
    return None


def load_trails(mapdata_dir: Path) -> None:
    global AMMO_TRAIL, JEWELL_TRAIL, AMMO_ANIM, JEWELL_ANIM
    global TREELINE_AMMO, TREELINE_JEWELL, GEM_POOL

    ammo_gpx   = mapdata_dir / "Mount_Washington_via_Ammonoosuc_Ravine_Trail.gpx"
    jewell_gpx = mapdata_dir / "Jewell_Trail_.gpx"

    if not ammo_gpx.exists() or not jewell_gpx.exists():
        raise FileNotFoundError(
            f"GPX files not found in {mapdata_dir}. "
            "Download from AllTrails and place in that directory."
        )

    ammo_pts   = parse_gpx(ammo_gpx)
    jewell_pts = parse_gpx(jewell_gpx)

    ammo_summit_idx   = max(range(len(ammo_pts)),   key=lambda i: ammo_pts[i][2])
    jewell_summit_idx = max(range(len(jewell_pts)), key=lambda i: jewell_pts[i][2])

    ammo_ascent   = ammo_pts[:ammo_summit_idx + 1]
    jewell_ascent = jewell_pts[:jewell_summit_idx + 1]

    # Static display — thin polylines only need ~60 pts
    step_a = max(1, len(ammo_ascent)   // 60)
    step_j = max(1, len(jewell_ascent) // 60)
    AMMO_TRAIL[:]   = [(lat, lon) for lat, lon, _ in ammo_ascent[::step_a]]
    JEWELL_TRAIL[:] = [(lat, lon) for lat, lon, _ in reversed(jewell_ascent[::step_j])]

    # Animation — finer resolution with elevation (every 8th pt ≈ 150 frames per trail)
    anim_step = max(1, len(ammo_ascent) // 150)
    AMMO_ANIM[:]   = [(lat, lon, elev) for lat, lon, elev in ammo_ascent[::anim_step]]
    anim_step_j = max(1, len(jewell_ascent) // 150)
    JEWELL_ANIM[:] = [(lat, lon, elev) for lat, lon, elev in reversed(jewell_ascent[::anim_step_j])]

    tl_a = first_crossing(ammo_ascent, 1200)
    tl_j = first_crossing(jewell_ascent, 1200)
    gp   = first_crossing(ammo_ascent, 1068)

    TREELINE_AMMO   = (tl_a[0], tl_a[1]) if tl_a else None
    TREELINE_JEWELL = (tl_j[0], tl_j[1]) if tl_j else None
    GEM_POOL        = (gp[0],   gp[1])   if gp   else None

    print(f"  Ammo:   {len(ammo_ascent)} pts → {len(AMMO_TRAIL)} display, {len(AMMO_ANIM)} anim")
    print(f"  Jewell: {len(jewell_ascent)} pts → {len(JEWELL_TRAIL)} display, {len(JEWELL_ANIM)} anim")
    if TREELINE_AMMO:   print(f"  Treeline Ammo:   {TREELINE_AMMO}")
    if TREELINE_JEWELL: print(f"  Treeline Jewell: {TREELINE_JEWELL}")
    if GEM_POOL:        print(f"  Gem Pool:        {GEM_POOL}")


HEAD_POSITIONS = {
    "Summit":        {"lat": 44.27057, "lon": -71.30328, "elev_m": 1917},
    "Pinkham Notch": {"lat": 44.25764, "lon": -71.25291, "elev_m":  609},
    "Alpine Garden": {"lat": 44.26780, "lon": -71.29220, "elev_m": 1640},
}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fspl_db(d_km: float) -> float:
    return 32.44 + 20 * math.log10(max(d_km, 0.001)) + 20 * math.log10(FREQ_MHZ)


def pred_rssi(d_km: float, extra_loss_db: float = 0.0) -> float:
    return RX_POWER_REF_DBM - fspl_db(d_km) - extra_loss_db


def rssi_to_color(rssi: float) -> str:
    if rssi >= -90:  return "#00C853"
    if rssi >= -105: return "#FFD600"
    if rssi >= -120: return "#FF6D00"
    return "#B71C1C"


def rssi_to_label(rssi: float) -> str:
    if rssi >= -90:  return "Strong"
    if rssi >= -105: return "Good"
    if rssi >= -120: return "Marginal"
    return "Out of range"


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass_label(b: float) -> str:
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((b + 11.25) // 22.5) % 16]


# FSPL-based hop plausibility.
# Expected direct-link RSSI = TX_EIRP + RX_GAIN - FSPL(d_km).
# If obs_rssi is more than RELAY_THRESHOLD_DB above this prediction,
# the signal cannot have traveled that distance in one hop — it was relayed.
# With our link budget (22 dBm TX, 2 dBi each end) and conservative ±20 dB
# for terrain/antenna variance, anything >20 dB above prediction is suspect;
# >40 dB is almost certainly relayed.
RELAY_THRESHOLD_LIKELY_DB  = 20   # yellow — suspicious
RELAY_THRESHOLD_CERTAIN_DB = 40   # red — almost certainly relayed


def terrain_loss_db(elev_m: float) -> int:
    if elev_m >= 1500: return 3
    if elev_m >= 1200: return 15
    return 25


def hop_plausibility(d_km: float, obs_rssi: float) -> tuple[str, str, str]:
    """Return (color, label, detail) for FSPL-vs-observed deviation."""
    expected = pred_rssi(d_km)
    delta = obs_rssi - expected  # positive = stronger than expected
    if delta > RELAY_THRESHOLD_CERTAIN_DB:
        return "#E53935", "Almost certainly relayed", f"+{delta:.0f} dB above FSPL"
    if delta > RELAY_THRESHOLD_LIKELY_DB:
        return "#FB8C00", "Possibly relayed", f"+{delta:.0f} dB above FSPL"
    return "#43A047", "Plausible direct link", f"{delta:+.0f} dB vs FSPL"


# ---------------------------------------------------------------------------
# Nodes observed from Mt. Washington (combined: 2026-05-20 + 2026-05-23 hike)
#
# obs_rssi = best (highest) RSSI observed across all sessions, dBm.
# packets  = total packet count across all sessions.
# elev_m   = None where elevation is unconfirmed.
#
# Directional coverage from summit:
#   W:   !3369ecf0
#   SW:  !0ac9f61c, !d0dbf5e0, !facda2e0, !43593b08
#   SSW: !98de985c, !9e3b15c4, !a6965348, !8ecc1813
#   S:   !de28f744, !4ad10bfa, !da63ea38, !3b46af7c, !1c496f00, !e1ccc5f2,
#        !a20a1240, !b03d38b4, !9e75f97c, !e977eda7
#   SSE: !4bb40fe5
#   SE:  !d872fb89, !bcae633e, !a2e26938
#   ESE: !3e703fd2, !c0c103db, !05b41df9, !16c3f424  ← new from 2026-05-23 hike
#
#   GAP: N / NE / E / NW — blocked by Presidential Range terrain
#
# EXCLUDED (not added):
#   !db51af80  rssi=-1 at 180 km — impossible for direct link; relayed packet
#              with sender GPS from Lowell MA but last-hop relay physically
#              adjacent to HEAD Pi. Not usable as a propagation reference.
#   unknown    no mesh_id — can't track across sessions.
# ---------------------------------------------------------------------------
KNOWN_NODES = {
    # ── West ────────────────────────────────────────────────────────────────
    "!3369ecf0": {"lat": 44.2237, "lon": -72.0110, "elev_m": 195,  "obs_rssi": -45,  "packets":  3},  # W  57 km; updated 2026-05-23
    # ── Southwest ───────────────────────────────────────────────────────────
    "!0ac9f61c": {"lat": 43.6470, "lon": -72.2731, "elev_m": None, "obs_rssi": -43,  "packets": 10},  # SW 104 km; new 2026-05-23 hike
    "!d0dbf5e0": {"lat": 43.6994, "lon": -72.0634, "elev_m": None, "obs_rssi": -60,  "packets":  1},  # SW  88 km; new 2026-05-23 hike
    "!facda2e0": {"lat": 43.6470, "lon": -71.8537, "elev_m": 662,  "obs_rssi": -91,  "packets":  1},  # SW  85 km
    "!43593b08": {"lat": 42.7287, "lon": -72.3220, "elev_m": 157,  "obs_rssi": -91,  "packets":  3},  # SW 193 km
    # ── South-southwest ─────────────────────────────────────────────────────
    "!98de985c": {"lat": 43.1227, "lon": -71.9061, "elev_m": None, "obs_rssi":  -8,  "packets":  3},  # SSW 137 km; updated 2026-05-23
    "!9e3b15c4": {"lat": 43.1227, "lon": -71.7488, "elev_m": 249,  "obs_rssi": -95,  "packets":  1},  # SSW 130 km
    "!a6965348": {"lat": 43.4373, "lon": -71.5915, "elev_m": None, "obs_rssi": -54,  "packets":  1},  # SSW  96 km; new 2026-05-23 hike
    "!8ecc1813": {"lat": 42.7557, "lon": -71.8012, "elev_m": None, "obs_rssi": -54,  "packets":  1},  # SSW 173 km; new 2026-05-23 hike
    # ── South ───────────────────────────────────────────────────────────────
    "!de28f744": {"lat": 42.9130, "lon": -71.6440, "elev_m": 289,  "obs_rssi": -17,  "packets": 12},  # S  153 km; updated 2026-05-23
    "!4ad10bfa": {"lat": 43.0113, "lon": -71.4801, "elev_m": 35,   "obs_rssi": -93,  "packets":  5},  # S  143 km
    "!e1ccc5f2": {"lat": 43.5290, "lon": -71.1328, "elev_m": None, "obs_rssi": -48,  "packets":  1},  # S   84 km; new 2026-05-23 hike
    "!da63ea38": {"lat": 42.9924, "lon": -71.4793, "elev_m": None, "obs_rssi": -42,  "packets":  2},  # S  143 km; new 2026-05-23 hike
    "!3b46af7c": {"lat": 42.9858, "lon": -71.4199, "elev_m": None, "obs_rssi": -42,  "packets":  2},  # S  143 km; new 2026-05-23 hike
    "!1c496f00": {"lat": 42.9896, "lon": -71.3368, "elev_m": None, "obs_rssi": -47,  "packets":  1},  # S  143 km; new 2026-05-23 hike
    "!a20a1240": {"lat": 42.9113, "lon": -70.8133, "elev_m": 20,   "obs_rssi": -110, "packets": 83},  # S  155 km
    "!b03d38b4": {"lat": 42.8081, "lon": -70.9100, "elev_m": 26,   "obs_rssi": -95,  "packets": 51},  # S  164 km
    "!9e75f97c": {"lat": 42.8081, "lon": -70.8575, "elev_m": None, "obs_rssi": -24,  "packets": 133}, # S  165 km (own node home)
    "!e977eda7": {"lat": 42.8016, "lon": -70.8510, "elev_m": 14,   "obs_rssi": -92,  "packets":  8},  # S  165 km
    # ── South-southeast ─────────────────────────────────────────────────────
    "!4bb40fe5": {"lat": 42.9326, "lon": -70.8116, "elev_m": 15,   "obs_rssi": -115, "packets": 11},  # SSE 154 km
    # ── Southeast ───────────────────────────────────────────────────────────
    "!d872fb89": {"lat": 43.8370, "lon": -70.8248, "elev_m": None, "obs_rssi": -61,  "packets":  2},  # SE   62 km; new 2026-05-23 hike
    "!bcae633e": {"lat": 43.7748, "lon": -70.4938, "elev_m": None, "obs_rssi": -73,  "packets":  1},  # SE   85 km; new 2026-05-23 hike
    "!a2e26938": {"lat": 43.5945, "lon": -70.2284, "elev_m": 46,   "obs_rssi": -95,  "packets":  1},  # SE  123 km
    # ── East-southeast ──────────────────────────────────────────────────────
    "!3e703fd2": {"lat": 43.9484, "lon": -70.2939, "elev_m": None, "obs_rssi":  -7,  "packets":  1},  # ESE  88 km; new 2026-05-23 hike
    "!c0c103db": {"lat": 43.9484, "lon": -70.2939, "elev_m": None, "obs_rssi":  -9,  "packets":  1},  # ESE  88 km; new 2026-05-23 hike (co-located with !3e703fd2)
    "!05b41df9": {"lat": 43.9419, "lon": -70.2874, "elev_m": None, "obs_rssi": -17,  "packets":  1},  # ESE  89 km; new 2026-05-23 hike
    "!16c3f424": {"lat": 43.6470, "lon": -70.2284, "elev_m": None, "obs_rssi":  -9,  "packets":  1},  # SE  111 km; new 2026-05-23 hike
}

SUMMIT = (44.27057, -71.30328)


# ---------------------------------------------------------------------------
# Custom control panel (replaces Folium LayerControl)
# ---------------------------------------------------------------------------

def _build_custom_control(layer_map: dict[str, str], map_var: str) -> str:
    heads = list(HEAD_POSITIONS.keys())
    terrain_labels = {
        "Alpine":     "Open / Alpine (above treeline)",
        "Sub-alpine": "Mixed / Sub-alpine",
        "Forest":     "Dense Forest (below treeline)",
    }
    first_terrain = list(terrain_labels.values())[0]

    layer_entries = ",\n".join(
        f'    "{name}": "{js_var}"'
        for name, js_var in layer_map.items()
    )

    head_btns = "\n    ".join(
        f'<button class="ctrl-btn{" active" if i == 0 else ""}" '
        f'data-head="{h}">{h}</button>'
        for i, h in enumerate(heads)
    )
    terrain_btns = "\n      ".join(
        f'<button class="ctrl-btn{" active" if i == 0 else ""}" '
        f'data-terrain="{v}">{k}</button>'
        for i, (k, v) in enumerate(terrain_labels.items())
    )

    # CSS uses plain string (no f-string) so braces don't need escaping
    css = """<style>
#map-ctrl {
  position: fixed; top: 80px; right: 16px; z-index: 9999;
  background: rgba(255,255,255,0.97); border-radius: 12px;
  border: 1px solid #ddd; padding: 14px 16px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 12px; width: 200px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  user-select: none;
}
#map-ctrl .ctrl-title {
  font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
  color: #888; text-transform: uppercase; margin: 10px 0 5px;
}
#map-ctrl .ctrl-title:first-child { margin-top: 0; }
.btn-row { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 2px; }
.ctrl-btn {
  padding: 4px 10px; border: 1.5px solid #ccc; background: #f5f5f5;
  border-radius: 20px; cursor: pointer; font-size: 11.5px; color: #444;
  transition: background 0.12s, border-color 0.12s, color 0.12s;
  white-space: nowrap; outline: none;
}
.ctrl-btn:hover { border-color: #1976D2; color: #1976D2; }
.ctrl-btn.active {
  background: #1976D2; border-color: #1976D2;
  color: #fff; font-weight: 600;
}
#terrain-sec { display: none; }
</style>"""

    panel = f"""<div id="map-ctrl">
  <div class="ctrl-title">Head Position</div>
  <div class="btn-row" id="head-btns">
    {head_btns}
  </div>
  <div class="ctrl-title">View</div>
  <div class="btn-row" id="view-btns">
    <button class="ctrl-btn active" data-view="heatmap">Heatmap</button>
    <button class="ctrl-btn" data-view="dots">Dot Grid</button>
  </div>
  <div id="terrain-sec">
    <div class="ctrl-title">Terrain</div>
    <div class="btn-row" id="terrain-btns">
      {terrain_btns}
    </div>
  </div>
</div>"""

    js = f"""<script>
(function() {{
  // Store var names as strings; Folium declares them AFTER </body>,
  // so we must look them up at load time, not at parse time.
  var MAP_VAR    = '{map_var}';
  var layerNames = {{
{layer_entries}
  }};
  var currentHead    = '{heads[0]}';
  var currentView    = 'heatmap';
  var currentTerrain = '{first_terrain}';

  var layers = {{}};   // populated on load

  function sync() {{
    var MAP = window[MAP_VAR];
    if (!MAP) return;
    Object.keys(layers).forEach(function(k) {{
      if (layers[k]) MAP.removeLayer(layers[k]);
    }});
    var key = currentView === 'heatmap'
      ? 'heatmap__' + currentHead
      : 'dots__' + currentHead + '__' + currentTerrain;
    if (layers[key]) MAP.addLayer(layers[key]);
    document.getElementById('terrain-sec').style.display =
      currentView === 'dots' ? 'block' : 'none';
  }}

  function activate(groupId, el) {{
    document.querySelectorAll('#' + groupId + ' .ctrl-btn')
      .forEach(function(b) {{ b.classList.remove('active'); }});
    el.classList.add('active');
  }}

  window.addEventListener('load', function() {{
    // Resolve layer objects now that Folium has declared them
    Object.keys(layerNames).forEach(function(k) {{
      layers[k] = window[layerNames[k]];
    }});

    document.querySelectorAll('#head-btns .ctrl-btn').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        activate('head-btns', this);
        currentHead = this.dataset.head;
        sync();
      }});
    }});
    document.querySelectorAll('#view-btns .ctrl-btn').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        activate('view-btns', this);
        currentView = this.dataset.view;
        sync();
      }});
    }});
    document.querySelectorAll('#terrain-btns .ctrl-btn').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        activate('terrain-btns', this);
        currentTerrain = this.dataset.terrain;
        sync();
      }});
    }});
    sync();
  }});
}})();
</script>"""

    return css + "\n" + panel + "\n" + js


# ---------------------------------------------------------------------------
# Folium map
# ---------------------------------------------------------------------------

def build_map(out_path: Path) -> None:  # noqa: C901
    m = folium.Map(location=[44.10, -71.45], zoom_start=9, tiles="OpenStreetMap")

    import json as _json

    # ── Static trail lines ──────────────────────────────────────────────────
    folium.PolyLine(AMMO_TRAIL,   color="#888", weight=3, opacity=0.5,
                    tooltip="Ammonoosuc Ravine Trail (ascent)").add_to(m)
    folium.PolyLine(JEWELL_TRAIL, color="#888", weight=3, opacity=0.5,
                    tooltip="Jewell Trail (descent)").add_to(m)

    if TREELINE_AMMO:
        folium.CircleMarker(TREELINE_AMMO, radius=5, color="#4CAF50", fill=True,
                            fill_color="#4CAF50", fill_opacity=0.9,
                            tooltip="Treeline (Ammo) ~1200 m — terrain changes from forest to alpine above here").add_to(m)
    if TREELINE_JEWELL:
        folium.CircleMarker(TREELINE_JEWELL, radius=5, color="#4CAF50", fill=True,
                            fill_color="#4CAF50", fill_opacity=0.9,
                            tooltip="Treeline (Jewell) ~1200 m").add_to(m)

    # ── Summit pin ──────────────────────────────────────────────────────────
    folium.Marker(
        list(SUMMIT),
        tooltip=folium.Tooltip(
            f"<b>Mt. Washington Summit — meshradiohead2 (HEAD)</b><br>"
            f"1917 m · LongFast SF11/BW250 · TX {TX_POWER_DBM:.0f} dBm · Link budget {LINK_BUDGET_DB:.1f} dB",
            sticky=False),
        icon=folium.Icon(color="blue", icon="star"),
    ).add_to(m)

    # ── Known nodes — coloured by hop plausibility ──────────────────────────
    known_fg = folium.FeatureGroup(name="OBSERVED nodes  [dot color = PREDICTED coverage]", show=True)
    hop_fg   = folium.FeatureGroup(name="OBSERVED RSSI  [HYBRID: real signal vs FSPL model]", show=False)

    for mid, n in KNOWN_NODES.items():
        d_km    = haversine_km(*SUMMIT, n["lat"], n["lon"])
        pred    = pred_rssi(d_km, extra_loss_db=3)
        fspl_direct = pred_rssi(d_km, extra_loss_db=0)
        obs     = n.get("obs_rssi")
        elev_str = f"{n['elev_m']} m" if n.get("elev_m") else "unknown"
        brg     = bearing_deg(*SUMMIT, n["lat"], n["lon"])
        cdir    = compass_label(brg)

        cov_color = rssi_to_color(pred)

        if obs is not None:
            hop_color, hop_label, hop_detail = hop_plausibility(d_km, obs)
            delta_db = obs - fspl_direct
            if delta_db > RELAY_THRESHOLD_CERTAIN_DB:
                hop_explain = (
                    f"Observed {obs} dBm is {delta_db:+.0f} dB stronger than the "
                    f"free-space prediction of {fspl_direct:.0f} dBm at {d_km:.0f} km. "
                    f"Even a high-gain antenna setup cannot account for this — the packet "
                    f"was almost certainly relayed through a physically nearby node before "
                    f"reaching the HEAD. The GPS in the packet is the original sender's "
                    f"location; the RSSI is from the last relay hop."
                )
            elif delta_db > RELAY_THRESHOLD_LIKELY_DB:
                hop_explain = (
                    f"Observed {obs} dBm is {delta_db:+.0f} dB above the free-space "
                    f"prediction of {fspl_direct:.0f} dBm at {d_km:.0f} km. This is "
                    f"suspicious — possible explanations include a high-gain antenna, "
                    f"strong terrain reflection, or a relay hop through a closer node."
                )
            else:
                hop_explain = (
                    f"Observed {obs} dBm is {delta_db:+.0f} dB vs the free-space "
                    f"prediction of {fspl_direct:.0f} dBm at {d_km:.0f} km. This "
                    f"deviation is within the expected range for a direct single-hop "
                    f"link over varied terrain (±20 dB is typical)."
                )
        else:
            hop_color, hop_label, hop_detail = "#9E9E9E", "No observed RSSI", "—"
            hop_explain = "No RSSI data recorded for this node."

        shared_popup = f"""
<div style="font-family:monospace;font-size:12px;min-width:300px">
<b style="font-size:14px">{mid}</b><br>
<span style="color:#555">Meshtastic node heard from Mt. Washington summit</span>
<hr style="margin:5px 0">
<div style="background:#E3F2FD;border-left:3px solid #1565C0;padding:3px 6px;margin:3px 0;font-size:10.5px">
  <b style="color:#1565C0">REAL DATA</b> — from actual Meshtastic packets received on 2026-05-20 / 2026-05-23
</div>
<b>Location</b><br>
&nbsp;GPS: ({n['lat']:.4f}°N, {abs(n['lon']):.4f}°W)<br>
&nbsp;Elevation: {elev_str}<br>
&nbsp;Direction from summit: {cdir} ({brg:.0f}°)<br>
&nbsp;Distance from summit: <b>{d_km:.1f} km</b>
<hr style="margin:5px 0">
<b>Observed signal (REAL)</b><br>
&nbsp;Best RSSI: <b>{obs if obs is not None else '—'} dBm</b>
  ({rssi_to_label(obs) if obs is not None else '—'})<br>
&nbsp;Total packets heard: {n['packets']}<br>
&nbsp;Sessions: 2026-05-20 home base + 2026-05-23 hike
<hr style="margin:5px 0">
<div style="background:#FFF8E1;border-left:3px solid #FF8F00;padding:3px 6px;margin:3px 0;font-size:10.5px">
  <b style="color:#FF8F00">PREDICTED</b> — FSPL model (Rappaport 2002), 915 MHz, TX {TX_POWER_DBM:.0f} dBm, dipole antenna
</div>
<b>Link prediction from summit</b><br>
&nbsp;Free-space path loss at {d_km:.0f} km: {fspl_direct:.0f} dBm<br>
&nbsp;+ Alpine terrain penalty (+3 dB): <b>{pred:.0f} dBm</b><br>
&nbsp;Summit-to-here reachable: {'<b style="color:green">YES</b>' if pred > -120 else '<b style="color:red">NO (beyond link budget)</b>'}
<hr style="margin:5px 0">
<div style="background:#F3E5F5;border-left:3px solid #7B1FA2;padding:3px 6px;margin:3px 0;font-size:10.5px">
  <b style="color:#7B1FA2">HYBRID</b> — real observed RSSI compared against FSPL model to infer hop count
</div>
<b>Hop plausibility: <span style="color:{hop_color}">{hop_label}</span></b><br>
<span style="font-size:11px;color:#333">{hop_explain}</span><br>
<span style="font-size:10px;color:#888;font-style:italic">
  Will be replaced with ground-truth hop count once hop_limit/hops_away
  fields are deployed to the collector.
</span>
</div>"""

        # ── Coverage layer ──────────────────────────────────────────────────
        cov_tip = folium.Tooltip(f"""
<div style="font-family:monospace;font-size:12px">
<b>{mid}</b> &nbsp;|&nbsp; {cdir} &nbsp;|&nbsp; {d_km:.0f} km from summit<br>
Predicted RSSI (summit→here): <b>{pred:.0f} dBm</b> ({rssi_to_label(pred)})<br>
Best observed RSSI: {obs if obs is not None else '—'} dBm &nbsp;·&nbsp; {n['packets']} packet(s)<br>
<i>Click for hop plausibility analysis</i>
</div>""", sticky=False)

        folium.CircleMarker(
            location=[n["lat"], n["lon"]], radius=10,
            color=cov_color, fill=True, fill_color=cov_color,
            fill_opacity=0.85, weight=2,
            tooltip=cov_tip,
            popup=folium.Popup(shared_popup, max_width=340),
        ).add_to(known_fg)
        folium.PolyLine(
            [list(SUMMIT), [n["lat"], n["lon"]]],
            color=cov_color, weight=1.5, opacity=0.4,
            tooltip=f"{d_km:.0f} km to {cdir}",
        ).add_to(known_fg)

        # ── Hop plausibility layer ──────────────────────────────────────────
        hop_radius = 12 if hop_color == "#E53935" else (10 if hop_color == "#FB8C00" else 8)
        hop_tip = folium.Tooltip(f"""
<div style="font-family:monospace;font-size:12px">
<b>{mid}</b> &nbsp;|&nbsp; {cdir} &nbsp;|&nbsp; {d_km:.0f} km<br>
<b style="color:{hop_color}">{hop_label}</b><br>
Observed: {obs if obs is not None else '—'} dBm &nbsp;·&nbsp;
Free-space predicted: {fspl_direct:.0f} dBm &nbsp;·&nbsp;
Deviation: {hop_detail}<br>
<i>Click for full analysis</i>
</div>""", sticky=False)

        folium.CircleMarker(
            location=[n["lat"], n["lon"]], radius=hop_radius,
            color=hop_color, fill=True, fill_color=hop_color,
            fill_opacity=0.9, weight=2,
            tooltip=hop_tip,
            popup=folium.Popup(shared_popup, max_width=340),
        ).add_to(hop_fg)
        folium.PolyLine(
            [list(SUMMIT), [n["lat"], n["lon"]]],
            color=hop_color, weight=1.5, opacity=0.5,
            tooltip=f"{d_km:.0f} km — {hop_label}",
        ).add_to(hop_fg)

    # Summit star marker (always visible)
    summit_tip = folium.Tooltip(f"""
<div style="font-family:monospace;font-size:12px">
<b>Mt. Washington Summit — HEAD Node (meshradiohead2)</b><br>
Elevation: 1917 m (6,288 ft) &nbsp;·&nbsp; GPS: 44.2703°N, 71.3033°W<br>
<hr style="margin:4px 0">
Radio assumption: Heltec V3 · 915 MHz · LongFast SF11 · BW 250 kHz<br>
TX power: {TX_POWER_DBM:.0f} dBm · Dipole antenna · RX sensitivity: {RX_SENS_DBM:.0f} dBm<br>
Link budget: {LINK_BUDGET_DB:.0f} dB (theoretical max range ~1700 km in free space)<br>
<hr style="margin:4px 0">
This node collects all Meshtastic telemetry and is the reference point
for all distance/RSSI calculations on this map.
</div>""", sticky=False)

    folium.Marker(
        list(SUMMIT),
        tooltip=summit_tip,
        popup=folium.Popup(
            f"<b>meshradiohead2 — HEAD node</b><br>"
            f"Elevation: 1917 m<br>"
            f"Freq: 915 MHz · LongFast SF11/BW250 · TX {TX_POWER_DBM:.0f} dBm<br>"
            f"Link budget: {LINK_BUDGET_DB:.0f} dB",
            max_width=240),
        icon=folium.Icon(color="blue", icon="star"),
    ).add_to(m)

    # ── Trail connectivity coloring ─────────────────────────────────────────
    # Color each trail segment by predicted mesh connectivity at that position.
    # Metric: best RSSI to any known node + count bonus (10*log10(nodes_marginal)).
    # This is a prediction (no HEAD GPS from the hike), but uses real node
    # positions from the collected data.
    if AMMO_ANIM and JEWELL_ANIM:
        conn_fg = folium.FeatureGroup(name="PREDICTED  Connectivity along route", show=False)

        def _conn_color(score: float) -> str:
            """
            Gradient: black (no signal) → red (very weak) →
            orange (weak) → yellow (ok) → green (good).
            Clean, distinct colors with no brownish mid-tones.
            """
            STOPS = [
                (-135, (0,   0,   0)),    # black  — completely isolated
                (-127, (180, 0,   0)),    # red    — super weak
                (-119, (255, 80,  0)),    # orange — weakish
                (-111, (255, 210, 0)),    # yellow — ok
                (-100, (0,   200, 60)),   # green  — great
            ]
            if score >= STOPS[-1][0]:
                r, g, b = STOPS[-1][1]
                return f"#{r:02x}{g:02x}{b:02x}"
            if score <= STOPS[0][0]:
                return "#000000"
            for i in range(len(STOPS) - 1):
                lo_s, lo_c = STOPS[i]
                hi_s, hi_c = STOPS[i + 1]
                if lo_s <= score < hi_s:
                    t = (score - lo_s) / (hi_s - lo_s)
                    r = int(lo_c[0] + t * (hi_c[0] - lo_c[0]))
                    g = int(lo_c[1] + t * (hi_c[1] - lo_c[1]))
                    b = int(lo_c[2] + t * (hi_c[2] - lo_c[2]))
                    return f"#{r:02x}{g:02x}{b:02x}"
            return "#000000"

        anim_full = AMMO_ANIM + JEWELL_ANIM
        ammo_len  = len(AMMO_ANIM)

        # Sample at step=4 — ~580 segments, fast render, still smooth
        step = 4
        pts = anim_full[::step]
        # Always include the last point so the trail ends properly
        if anim_full[-1] not in pts:
            pts = list(pts) + [anim_full[-1]]

        for i in range(len(pts) - 1):
            pt_a = pts[i]
            pt_b = pts[i + 1]
            lat  = (pt_a[0] + pt_b[0]) / 2
            lon  = (pt_a[1] + pt_b[1]) / 2
            elev = (pt_a[2] + pt_b[2]) / 2

            loss = terrain_loss_db(elev)
            node_scores = []
            for mid, nd in KNOWN_NODES.items():
                d_km = haversine_km(lat, lon, nd["lat"], nd["lon"])
                node_scores.append((mid, pred_rssi(d_km, loss)))

            node_scores.sort(key=lambda x: x[1], reverse=True)
            best_rssi  = node_scores[0][1] if node_scores else -999
            best_node  = node_scores[0][0] if node_scores else "—"
            marginal_n = sum(1 for _, r in node_scores if r >= -120)
            good_n     = sum(1 for _, r in node_scores if r >= -105)

            # Count bonus: each 10× increase in reachable nodes = +10 dB
            count_bonus = 10 * math.log10(max(1, marginal_n))
            score = best_rssi + count_bonus

            color = _conn_color(score)

            # Terrain and phase labels for tooltip
            if loss == 3:
                terrain_str = "Alpine / open (+3 dB)"
            elif loss == 15:
                terrain_str = "Sub-alpine / sparse trees (+15 dB)"
            else:
                terrain_str = "Dense forest (+25 dB)"

            phase = "Ascending Ammonoosuc" if (i * step) < ammo_len else "Descending Jewell"

            tip = (
                f"<b>Phase:</b> {phase}<br>"
                f"<b>Elevation:</b> {elev:.0f} m &nbsp;|&nbsp; {terrain_str}<br>"
                f"<b>Best predicted RSSI:</b> {best_rssi:.0f} dBm → {best_node}<br>"
                f"<b>Nodes ≥−105 dBm (Good):</b> {good_n}<br>"
                f"<b>Nodes ≥−120 dBm (Marginal):</b> {marginal_n}<br>"
                f"<b>Score (RSSI + count bonus):</b> {score:.1f}"
            )

            folium.PolyLine(
                [pt_a[:2], pt_b[:2]],
                color=color, weight=7, opacity=0.88,
                tooltip=folium.Tooltip(tip, sticky=True),
            ).add_to(conn_fg)

        conn_fg.add_to(m)

    # ── Relay node predictions ──────────────────────────────────────────────
    # Two fixed relay nodes at each treeline crossing.  These are the minimum
    # set that gives complete Good-quality trail coverage regardless of where
    # the HEAD node is on the trail.
    if TREELINE_AMMO and TREELINE_JEWELL and AMMO_ANIM and JEWELL_ANIM:
        relay_fg = folium.FeatureGroup(name="PREDICTED  Proposed relay nodes", show=False)
        cov_fg   = folium.FeatureGroup(name="PREDICTED  Trail coverage with relays", show=False)

        anim_combined = AMMO_ANIM + JEWELL_ANIM  # [(lat, lon, elev_m), ...]

        # Trailhead = first Ammo point; Jewell bottom = last Jewell anim point
        ammo_trailhead  = (AMMO_ANIM[0][0],    AMMO_ANIM[0][1])
        jewell_trailhead= (JEWELL_ANIM[-1][0],  JEWELL_ANIM[-1][1])

        PROPOSED = [
            {
                "lat": TREELINE_AMMO[0],   "lon": TREELINE_AMMO[1],   "elev_m": 1205,
                "name": "Relay A — Ammo Treeline",
                "trail_side": "Ammonoosuc Ravine Trail",
                "km_info": "~4.0 km from Ammo trailhead",
                "forest_anchor": ammo_trailhead,
                "forest_anchor_label": "Ammo trailhead (762 m)",
            },
            {
                "lat": TREELINE_JEWELL[0], "lon": TREELINE_JEWELL[1], "elev_m": 1199,
                "name": "Relay B — Jewell Treeline",
                "trail_side": "Jewell Trail",
                "km_info": "~3.9 km from Jewell trailhead",
                "forest_anchor": jewell_trailhead,
                "forest_anchor_label": "Jewell trailhead (~750 m)",
            },
        ]

        relay_latlons = [(r["lat"], r["lon"], r["elev_m"]) for r in PROPOSED]

        for rly in PROPOSED:
            d_sum = haversine_km(rly["lat"], rly["lon"], *SUMMIT)
            d_fst = haversine_km(rly["lat"], rly["lon"], *rly["forest_anchor"])
            rssi_up   = pred_rssi(d_sum, 3)    # relay→summit: open alpine on both sides
            rssi_down = pred_rssi(d_fst, 25)   # forest→relay: forest loss (worst side)
            two_hop   = min(rssi_up, rssi_down)

            # Baseline: direct forest trailhead → summit with no relay
            d_direct    = haversine_km(*rly["forest_anchor"], *SUMMIT)
            rssi_direct = pred_rssi(d_direct, 25)
            gain_db     = two_hop - rssi_direct

            popup_html = f"""
<div style="font-family:monospace;font-size:12px;min-width:320px">
<b style="font-size:14px">{rly['name']}</b><br>
<span style="color:#7B1FA2">&#9679; Proposed fixed relay node</span>
<hr style="margin:5px 0">
<b>Location</b><br>
&nbsp;GPS: ({rly['lat']:.4f}°N, {abs(rly['lon']):.4f}°W)<br>
&nbsp;Elevation: ~{rly['elev_m']} m (treeline crossing)<br>
&nbsp;Trail position: {rly['km_info']} on {rly['trail_side']}
<hr style="margin:5px 0">
<b>Why here?</b><br>
The treeline (~1200 m) is the single best relay location because it sits
exactly at the terrain transition. Dense forest below (+25 dB loss) limits
range to ~5 km. Open alpine above (+3 dB) gives ~68 km range. A node here
bridges both regimes with the shortest possible hop on each side.
<hr style="margin:5px 0">
<b>Link quality (both hops of the relay path)</b><br>
&nbsp;Hop 1 &mdash; {rly['forest_anchor_label']} &rarr; this relay:<br>
&nbsp;&nbsp;&nbsp;<b style="color:{rssi_to_color(rssi_down)}">{rssi_down:.0f} dBm</b>
  &nbsp;{rssi_to_label(rssi_down)} &nbsp;({d_fst:.1f} km, +25 dB forest)
<br>
&nbsp;Hop 2 &mdash; This relay &rarr; Summit (1917 m):<br>
&nbsp;&nbsp;&nbsp;<b style="color:{rssi_to_color(rssi_up)}">{rssi_up:.0f} dBm</b>
  &nbsp;{rssi_to_label(rssi_up)} &nbsp;({d_sum:.1f} km, +3 dB alpine)
<br>
&nbsp;Two-hop weakest link: <b style="color:{rssi_to_color(two_hop)}">{two_hop:.0f} dBm</b><br>
&nbsp;Direct trailhead&rarr;summit (no relay): <b style="color:{rssi_to_color(rssi_direct)}">{rssi_direct:.0f} dBm</b><br>
&nbsp;Relay improvement: <b>+{gain_db:.0f} dB</b>
<hr style="margin:5px 0">
<b>Hardware</b><br>
Same Heltec V3 as HEAD node. No GPS required (position is fixed and recorded).
Weatherproof case + large LiPo or small solar panel. Place at the treeline
before the hike; collect on the way down.
</div>"""

            folium.CircleMarker(
                location=[rly["lat"], rly["lon"]],
                radius=13, color="#6A1B9A", fill=True,
                fill_color="#CE93D8", fill_opacity=0.92, weight=3,
                tooltip=folium.Tooltip(
                    f"<b>{rly['name']}</b><br>"
                    f"Proposed fixed relay &mdash; click for link analysis",
                    sticky=False),
                popup=folium.Popup(popup_html, max_width=370),
            ).add_to(relay_fg)

            # Dashed line: this relay → summit (alpine hop)
            folium.PolyLine(
                [[rly["lat"], rly["lon"]], list(SUMMIT)],
                color=rssi_to_color(rssi_up), weight=2.5, opacity=0.8,
                dash_array="10 5",
                tooltip=(
                    f"{rly['name']} → Summit: {rssi_up:.0f} dBm "
                    f"({rssi_to_label(rssi_up)}) — {d_sum:.1f} km, alpine (+3 dB)"
                ),
            ).add_to(relay_fg)

            # Dashed line: relay → forest trailhead (forest hop)
            folium.PolyLine(
                [[rly["lat"], rly["lon"]], list(rly["forest_anchor"])],
                color=rssi_to_color(rssi_down), weight=2.5, opacity=0.8,
                dash_array="10 5",
                tooltip=(
                    f"Trailhead → {rly['name']}: {rssi_down:.0f} dBm "
                    f"({rssi_to_label(rssi_down)}) — {d_fst:.1f} km, forest (+25 dB)"
                ),
            ).add_to(relay_fg)

        # ── Trail segment coloring by relay coverage ────────────────────────
        # Color each trail segment by the best RSSI it gets from any fixed relay
        # (independent of HEAD position — shows where relays alone keep the
        # mesh connected even when the HEAD is elsewhere on the trail).
        step = max(1, len(anim_combined) // 120)
        sampled = anim_combined[::step]

        prev_seg_color = None
        seg_pts: list = []

        def flush_seg(pts, color):
            if len(pts) >= 2:
                folium.PolyLine(
                    [p[:2] for p in pts],
                    color=color, weight=5, opacity=0.75,
                ).add_to(cov_fg)

        for i, pt in enumerate(sampled):
            lat, lon, elev = pt
            # Best RSSI from any proposed relay to this point
            best = max(
                pred_rssi(
                    haversine_km(lat, lon, r[0], r[1]),
                    max(terrain_loss_db(elev), terrain_loss_db(r[2])),
                )
                for r in relay_latlons
            )
            if best >= -90:
                seg_color = "#00C853"   # strong — well within relay range
            elif best >= -105:
                seg_color = "#FFD600"   # good — usable relay link
            elif best >= -120:
                seg_color = "#FF6D00"   # marginal
            else:
                seg_color = "#B71C1C"   # below sensitivity — relay gap

            if seg_color != prev_seg_color:
                flush_seg(seg_pts, prev_seg_color or seg_color)
                seg_pts = [pt]
                prev_seg_color = seg_color
            else:
                seg_pts.append(pt)

        flush_seg(seg_pts, prev_seg_color or "#888")

        relay_fg.add_to(m)
        cov_fg.add_to(m)

    known_fg.add_to(m)
    hop_fg.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    # ── Build animation data ────────────────────────────────────────────────
    # Combined trail: Ammo ascent → Jewell descent (with elevation for terrain model)
    anim_trail = AMMO_ANIM + JEWELL_ANIM  # [(lat, lon, elev_m), ...]

    # Serialise nodes for JS — include hop plausibility metadata
    nodes_js = {}
    for mid, n in KNOWN_NODES.items():
        d_sum  = haversine_km(*SUMMIT, n["lat"], n["lon"])
        obs    = n.get("obs_rssi")
        brg    = bearing_deg(*SUMMIT, n["lat"], n["lon"])
        cdir   = compass_label(brg)
        if obs is not None:
            _, hop_label, _ = hop_plausibility(d_sum, obs)
        else:
            hop_label = "No data"
        nodes_js[mid] = {
            "lat": n["lat"], "lon": n["lon"],
            "packets": n["packets"],
            "obs_rssi": obs,
            "dist_summit_km": round(d_sum, 1),
            "bearing": round(brg, 0),
            "compass": cdir,
            "hop_label": hop_label,
            "elev_m": n.get("elev_m"),
        }

    trail_js = [[round(lat, 6), round(lon, 6), round(elev, 0)]
                for lat, lon, elev in anim_trail]

    nodes_json = _json.dumps(nodes_js)
    trail_json = _json.dumps(trail_js)

    # ── Save base map then inject animation JS ──────────────────────────────
    tmp_path = out_path.with_suffix(".tmp.html")
    m.save(str(tmp_path))
    html = tmp_path.read_text(encoding="utf-8")
    tmp_path.unlink()

    match = re.search(r"var (map_[a-f0-9]+)\s*=\s*L\.map\(", html)
    map_var = match.group(1) if match else "map_unknown"

    anim_js = f"""
<style>
#anim-panel {{
  position: fixed;
  bottom: 20px; right: 20px;
  z-index: 1000;
  background: rgba(255,255,255,0.97);
  border: 1px solid #bbb;
  border-radius: 10px;
  padding: 14px 16px;
  font-family: sans-serif;
  font-size: 12px;
  width: 310px;
  box-shadow: 2px 2px 8px rgba(0,0,0,0.18);
}}
#anim-panel h3 {{ margin: 0 0 8px; font-size: 13px; }}
#anim-controls {{ display: flex; gap: 6px; align-items: center; margin: 8px 0; flex-wrap: wrap; }}
#anim-controls button {{
  padding: 5px 12px; border: none; border-radius: 5px; cursor: pointer;
  font-size: 12px; font-weight: bold;
}}
#btn-play  {{ background: #1565C0; color: white; }}
#btn-reset {{ background: #546E7A; color: white; }}
#speed-label {{ font-size: 11px; color: #555; }}
#progress-wrap {{
  height: 6px; background: #e0e0e0; border-radius: 3px;
  margin: 6px 0; cursor: pointer;
}}
#progress-bar {{ height: 100%; background: #1565C0; border-radius: 3px; width: 0%; transition: width 0.05s; }}
#anim-stats {{
  font-size: 11px; line-height: 1.6; color: #333;
  border-top: 1px solid #eee; padding-top: 6px; margin-top: 4px;
}}
#node-list {{ max-height: 140px; overflow-y: auto; margin-top: 4px; }}
#node-list table {{ width: 100%; border-collapse: collapse; font-size: 10.5px; }}
#node-list td {{ padding: 1px 4px; }}
.nl-hdr {{ font-weight: bold; background: #f5f5f5; }}
#legend-box {{
  position: fixed; bottom: 20px; left: 20px; z-index: 1000;
  background: rgba(255,255,255,0.96); border: 1px solid #bbb; border-radius: 10px;
  padding: 12px 14px; font-family: sans-serif; font-size: 11px;
  max-width: 260px; box-shadow: 2px 2px 6px rgba(0,0,0,0.14);
}}
#data-toggle-btn {{
  position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
  z-index: 9999; padding: 6px 16px; border-radius: 20px; border: none;
  font-family: sans-serif; font-size: 12px; font-weight: bold;
  cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
  background: #1565C0; color: white; letter-spacing: 0.04em;
}}
#data-toggle-btn:hover {{ background: #0d47a1; }}
#data-source-panel {{
  display: none; position: fixed; top: 115px; left: 50%; transform: translateX(-50%);
  z-index: 9998; background: rgba(255,255,255,0.98);
  border: 1.5px solid #1565C0; border-radius: 10px;
  padding: 14px 16px; font-family: sans-serif; font-size: 11.5px;
  max-width: 520px; width: 90vw; box-shadow: 0 4px 16px rgba(0,0,0,0.2);
}}
#data-source-panel h4 {{ margin: 0 0 8px; font-size: 13px; }}
#data-source-panel table {{ width: 100%; border-collapse: collapse; }}
#data-source-panel td {{ padding: 4px 8px; vertical-align: top; }}
#data-source-panel tr:not(:last-child) td {{ border-bottom: 1px solid #eee; }}
.ds-real {{ color: #1565C0; font-weight: bold; white-space: nowrap; }}
.ds-pred {{ color: #E65100; font-weight: bold; white-space: nowrap; }}
.ds-hybrid {{ color: #6A1B9A; font-weight: bold; white-space: nowrap; }}
</style>

<button id="data-toggle-btn">&#128202; Data Sources</button>

<div id="data-source-panel">
  <h4>&#128202; What is real data vs. model prediction?</h4>
  <table>
    <tr>
      <td class="ds-real">&#9679; REAL</td>
      <td>Node GPS positions — from actual Meshtastic packet headers (2026-05-20 + 2026-05-23)</td>
    </tr>
    <tr>
      <td class="ds-real">&#9679; REAL</td>
      <td>Observed RSSI — signal strength actually measured by the HEAD radio at the summit</td>
    </tr>
    <tr>
      <td class="ds-real">&#9679; REAL</td>
      <td>Packet counts — total transmissions heard per node across all sessions</td>
    </tr>
    <tr>
      <td class="ds-real">&#9679; REAL</td>
      <td>Trail route — AllTrails GPX recording of Ammo ascent / Jewell descent</td>
    </tr>
    <tr>
      <td class="ds-pred">&#9632; PREDICTED</td>
      <td>Animation lines — color/weight = FSPL model estimate, <b>not measured</b>. HEAD had no GPS during the hike; trail position is approximate.</td>
    </tr>
    <tr>
      <td class="ds-pred">&#9632; PREDICTED</td>
      <td>Connectivity gradient (colored trail) — FSPL + terrain loss at each elevation. Predicted, not recorded.</td>
    </tr>
    <tr>
      <td class="ds-pred">&#9632; PREDICTED</td>
      <td>Proposed relay nodes + their link quality — model estimates for hardware not yet deployed</td>
    </tr>
    <tr>
      <td class="ds-pred">&#9632; PREDICTED</td>
      <td>Node dot color in coverage layer — predicted RSSI from summit via FSPL, not observed signal</td>
    </tr>
    <tr>
      <td class="ds-hybrid">&#9670; HYBRID</td>
      <td>Hop plausibility — <b>real observed RSSI</b> compared against FSPL model math to infer whether a packet was relayed. The signal is real; the hop-count inference is a model estimate.</td>
    </tr>
  </table>
  <div style="margin-top:8px;font-size:10.5px;color:#888">
    Layer names in the control (top-right) are prefixed REAL / PREDICTED / HYBRID accordingly.
    Node popups show colored banners for each section.
  </div>
</div>

<div id="anim-panel">
  <h3>&#128247; Hike Playback — LoRa Link Quality
    <span style="font-size:9px;background:#E65100;color:white;padding:2px 6px;
                 border-radius:10px;vertical-align:middle;margin-left:6px;
                 font-weight:normal;letter-spacing:0.05em">PREDICTED</span>
  </h3>
  <div style="font-size:10.5px;color:#555;margin-bottom:6px;">
    Press Play to simulate the HEAD node moving along the trail.
    Lines show <b>FSPL-predicted link quality</b> — not recorded measurements.
    HEAD had no GPS during the hike; node positions are real observed data.
  </div>
  <div id="anim-controls">
    <button id="btn-play">&#9654; Play</button>
    <button id="btn-reset">&#8635; Reset</button>
    <label id="speed-label">Speed:
      <select id="speed-select" style="font-size:11px">
        <option value="200">Slow</option>
        <option value="100" selected>Normal</option>
        <option value="40">Fast</option>
        <option value="15">Max</option>
      </select>
    </label>
  </div>
  <div id="progress-wrap"><div id="progress-bar"></div></div>
  <div id="anim-stats">
    <b>Position:</b> <span id="stat-phase">Trailhead (start)</span><br>
    <b>Elevation:</b> <span id="stat-elev">—</span> &nbsp;|&nbsp;
    <b>Terrain:</b> <span id="stat-terrain">—</span><br>
    <b>Step:</b> <span id="stat-step">0</span> / <span id="stat-total">—</span><br>
    <b>Nodes in range (&ge;&minus;120 dBm):</b> <span id="stat-in-range">—</span>
    &nbsp; <b>Strong (&ge;&minus;90):</b> <span id="stat-strong">—</span>
    <div id="node-list">
      <table>
        <tr class="nl-hdr"><td>Node</td><td>Dir</td><td>km</td><td>Pred RSSI</td><td>Quality</td></tr>
      </table>
    </div>
  </div>
</div>

<div id="legend-box">
  <b style="font-size:12px">Resilient Emergency MANET</b><br>
  <span style="color:#555">915 MHz LoRa · LongFast SF11/BW250 · TX 22 dBm · Dipole</span>
  <hr style="margin:5px 0">
  <span style="font-size:10px">
    <span style="background:#E3F2FD;color:#1565C0;padding:1px 5px;border-radius:8px;font-weight:bold">REAL</span>
    Node GPS &amp; RSSI &nbsp;
    <span style="background:#FFF8E1;color:#E65100;padding:1px 5px;border-radius:8px;font-weight:bold">PRED</span>
    Lines &amp; gradients &nbsp;
    <span style="background:#F3E5F5;color:#6A1B9A;padding:1px 5px;border-radius:8px;font-weight:bold">HYBRID</span>
    Hop inference
  </span>
  <hr style="margin:5px 0">
  <b>Line color = <span style="color:#E65100">PREDICTED</span> RSSI</b><br>
  <span style="color:#00C853">&#9644;</span> &ge;&#8722;90 dBm &nbsp; <b>Strong</b><br>
  <span style="color:#FFD600">&#9644;</span> &ge;&#8722;105 &nbsp; <b>Good</b><br>
  <span style="color:#FF6D00">&#9644;</span> &ge;&#8722;120 &nbsp; <b>Marginal</b><br>
  <span style="color:#B71C1C">&#9644;</span> &lt;&#8722;120 &nbsp; <b>Out of range</b><br>
  <hr style="margin:5px 0">
  <b>Node dot = hop plausibility (<span style="color:#6A1B9A">HYBRID</span>)</b><br>
  <span style="color:#43A047">&#9679;</span> Plausible direct<br>
  <span style="color:#FB8C00">&#9679;</span> Possibly relayed<br>
  <span style="color:#E53935">&#9679;</span> Almost certainly relayed<br>
  <hr style="margin:5px 0">
  <span style="color:#555;font-size:10px">
    Gray lines = trail route (real GPX).<br>
    Green dots = treeline crossings (~1200 m, real elevation).<br>
    FSPL model: Rappaport (2002). Terrain: &gt;1500 m = +3 dB,
    1200&#8211;1500 m = +15 dB, &lt;1200 m = +25 dB.
  </span>
</div>

<script>
window.addEventListener('load', function() {{
  const RX_POWER_REF_DBM = {RX_POWER_REF_DBM};
  const FREQ_MHZ   = {FREQ_MHZ};
  const RX_SENS    = {RX_SENS_DBM};

  const TRAIL   = {trail_json};
  const NODES   = {nodes_json};
  const MAP_VAR = {map_var};

  function haversineKm(lat1, lon1, lat2, lon2) {{
    const R = 6371.0, dLat = (lat2-lat1)*Math.PI/180,
          dLon = (lon2-lon1)*Math.PI/180;
    const a = Math.sin(dLat/2)**2
            + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }}
  function fsplDb(dKm) {{
    return 32.44 + 20*Math.log10(Math.max(dKm, 0.001)) + 20*Math.log10(FREQ_MHZ);
  }}
  function predRssi(dKm, extraDb) {{
    return RX_POWER_REF_DBM - fsplDb(dKm) - extraDb;
  }}
  function terrainLoss(elevM) {{
    if (elevM >= 1500) return 3;
    if (elevM >= 1200) return 15;
    return 25;
  }}
  function terrainLabel(elevM) {{
    if (elevM >= 1500) return 'Alpine (open, above treeline)';
    if (elevM >= 1200) return 'Sub-alpine (sparse trees)';
    return 'Dense forest (below treeline)';
  }}
  function hikePhase(idx) {{
    const ammoLen = {len(AMMO_ANIM)};
    if (idx < ammoLen) return 'Ascending — Ammonoosuc Ravine Trail';
    return 'Descending — Jewell Trail';
  }}
  function rssiColor(r) {{
    if (r >= -90)  return '#00C853';
    if (r >= -105) return '#FFD600';
    if (r >= -120) return '#FF6D00';
    return '#B71C1C';
  }}
  function rssiWeight(r) {{
    if (r >= -90)  return 3.5;
    if (r >= -105) return 2.5;
    if (r >= -120) return 1.5;
    return 0.8;
  }}
  function rssiOpacity(r) {{
    if (r >= -90)  return 0.92;
    if (r >= -105) return 0.78;
    if (r >= -120) return 0.55;
    return 0.18;
  }}
  function rssiLabel(r) {{
    if (r >= -90)  return 'Strong';
    if (r >= -105) return 'Good';
    if (r >= -120) return 'Marginal';
    return 'Out of range';
  }}

  // HEAD marker — blue pulsing circle
  const headIcon = L.divIcon({{
    html: '<div style="width:16px;height:16px;border-radius:50%;'
        + 'background:#1E88E5;border:3px solid white;'
        + 'box-shadow:0 0 8px rgba(30,136,229,0.8)"></div>',
    iconSize: [16,16], iconAnchor: [8,8], className: ''
  }});
  const headMarker = L.marker([TRAIL[0][0], TRAIL[0][1]], {{icon: headIcon}})
    .bindTooltip('HEAD node (meshradiohead2)', {{sticky:false}})
    .addTo(MAP_VAR);

  // Connection lines — one per known node
  const lines = {{}};
  Object.entries(NODES).forEach(([id, nd]) => {{
    lines[id] = L.polyline(
      [[TRAIL[0][0], TRAIL[0][1]], [nd.lat, nd.lon]],
      {{color: '#B71C1C', weight: 0.8, opacity: 0.18}}
    ).addTo(MAP_VAR);
  }});

  // Animation state
  let frame = 0, playing = false, timer = null;

  function renderFrame(f) {{
    const pt = TRAIL[f];
    const lat = pt[0], lon = pt[1], elev = pt[2];
    const loss = terrainLoss(elev);

    headMarker.setLatLng([lat, lon]);
    headMarker.setTooltipContent(
      'HEAD — ' + Math.round(elev) + ' m — ' + terrainLabel(elev)
    );

    let inRange = 0, strong = 0;
    const rows = [];
    Object.entries(NODES).forEach(([id, nd]) => {{
      const dKm = haversineKm(lat, lon, nd.lat, nd.lon);
      const rssi = predRssi(dKm, loss);
      const col  = rssiColor(rssi);
      lines[id].setLatLngs([[lat, lon], [nd.lat, nd.lon]]);
      lines[id].setStyle({{color: col, weight: rssiWeight(rssi), opacity: rssiOpacity(rssi)}});
      lines[id].setTooltipContent(
        '<b>' + id + '</b> | ' + nd.compass + ' | ' + dKm.toFixed(0) + ' km<br>'
        + 'Predicted RSSI: <b>' + rssi.toFixed(0) + ' dBm</b> (' + rssiLabel(rssi) + ')<br>'
        + 'Terrain at HEAD: ' + terrainLabel(elev) + ' (+' + loss + ' dB)<br>'
        + 'Observed best: ' + (nd.obs_rssi !== null ? nd.obs_rssi + ' dBm' : '—') + '<br>'
        + 'Hop assessment: ' + nd.hop_label
      );
      if (rssi >= -120) inRange++;
      if (rssi >= -90)  strong++;
      rows.push([id, nd.compass, dKm, rssi]);
    }});

    // Sort by RSSI descending
    rows.sort((a,b) => b[3]-a[3]);
    let tableHtml = '<table><tr class="nl-hdr"><td>Node</td><td>Dir</td>'
                  + '<td>km</td><td>RSSI</td><td>Quality</td></tr>';
    rows.forEach(r => {{
      const col = rssiColor(r[3]);
      tableHtml += '<tr>'
        + '<td style="color:' + col + ';font-weight:bold">' + r[0] + '</td>'
        + '<td>' + r[1] + '</td>'
        + '<td>' + r[2].toFixed(0) + '</td>'
        + '<td style="color:' + col + '">' + r[3].toFixed(0) + '</td>'
        + '<td style="color:' + col + '">' + rssiLabel(r[3]) + '</td>'
        + '</tr>';
    }});
    tableHtml += '</table>';

    document.getElementById('stat-phase').textContent   = hikePhase(f);
    document.getElementById('stat-elev').textContent    = Math.round(elev) + ' m';
    document.getElementById('stat-terrain').textContent = terrainLabel(elev);
    document.getElementById('stat-step').textContent    = f + 1;
    document.getElementById('stat-total').textContent   = TRAIL.length;
    document.getElementById('stat-in-range').textContent = inRange;
    document.getElementById('stat-strong').textContent   = strong;
    document.getElementById('node-list').innerHTML       = tableHtml;
    document.getElementById('progress-bar').style.width
      = ((f / (TRAIL.length-1)) * 100) + '%';
  }}

  function play() {{
    if (frame >= TRAIL.length-1) frame = 0;
    playing = true;
    document.getElementById('btn-play').innerHTML = '&#9646;&#9646; Pause';
    const ms = parseInt(document.getElementById('speed-select').value);
    timer = setInterval(() => {{
      if (frame >= TRAIL.length-1) {{ pause(); return; }}
      frame++;
      renderFrame(frame);
    }}, ms);
  }}
  function pause() {{
    playing = false;
    clearInterval(timer);
    document.getElementById('btn-play').innerHTML = '&#9654; Play';
  }}

  document.getElementById('btn-play').addEventListener('click', () => {{
    if (playing) pause(); else play();
  }});
  document.getElementById('btn-reset').addEventListener('click', () => {{
    pause(); frame = 0; renderFrame(0);
  }});
  document.getElementById('speed-select').addEventListener('change', () => {{
    if (playing) {{ pause(); play(); }}
  }});
  document.getElementById('progress-wrap').addEventListener('click', function(e) {{
    const rect = this.getBoundingClientRect();
    const pct  = (e.clientX - rect.left) / rect.width;
    frame = Math.round(pct * (TRAIL.length-1));
    renderFrame(frame);
  }});

  // Wire tooltips on lines
  Object.values(lines).forEach(l => l.bindTooltip('', {{sticky: true}}));

  // Data Sources toggle
  document.getElementById('data-toggle-btn').addEventListener('click', function() {{
    const panel = document.getElementById('data-source-panel');
    const open  = panel.style.display === 'block';
    panel.style.display = open ? 'none' : 'block';
    this.style.background = open ? '#1565C0' : '#0d47a1';
    this.textContent = open ? '\U0001F4CA Data Sources' : '\U0001F4CA Data Sources ✕';
  }});

  renderFrame(0);
}});
</script>"""

    html = html.replace("</body>", anim_js + "\n</body>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  map  → {out_path}")


# ---------------------------------------------------------------------------
# Seaborn RSSI vs distance plot
# ---------------------------------------------------------------------------

def build_distance_plot(out_path: Path) -> None:
    # Use Matplotlib's bundled style instead of requiring a plotting package
    # solely for global cosmetics.
    plt.style.use("seaborn-v0_8-darkgrid")
    fig, ax = plt.subplots(figsize=(12, 7))

    # Extend range to cover all known nodes
    max_d = max((haversine_km(*SUMMIT, n["lat"], n["lon"]) for n in KNOWN_NODES.values()), default=25)
    max_d = max(max_d * 1.08, 25)
    distances = np.linspace(0.05, max_d, 800)

    # FSPL baseline (free-space, no terrain penalty)
    fspl_rssi = [pred_rssi(d, 0) for d in distances]
    ax.plot(distances, fspl_rssi, color="#546E7A", linewidth=2, linestyle="-",
            label="FSPL baseline (free space)", zorder=3)

    # Terrain curves (showing typical trail penalties)
    for terrain_label, extra_loss in TERRAIN_LOSS.items():
        rssi_vals = [pred_rssi(d, extra_loss) for d in distances]
        ax.plot(distances, rssi_vals, linestyle="--",
                label=f"{terrain_label} (+{extra_loss} dB loss)",
                color=TERRAIN_COLORS[terrain_label], linewidth=1.5, alpha=0.7)

    # Reference lines
    ax.axhline(-90,  color="#00C853", linestyle=":", linewidth=1.0, alpha=0.7, label="–90 dBm strong")
    ax.axhline(-105, color="#FFD600", linestyle=":", linewidth=1.0, alpha=0.7, label="–105 dBm marginal")
    ax.axhline(-120, color="#B71C1C", linestyle=":", linewidth=1.0, alpha=0.7, label="–120 dBm RX floor")

    # Known nodes — scatter coloured by hop plausibility
    for mid, n in KNOWN_NODES.items():
        obs = n.get("obs_rssi")
        if obs is None:
            continue
        d_km = haversine_km(*SUMMIT, n["lat"], n["lon"])
        color, label, detail = hop_plausibility(d_km, obs)
        ax.scatter(d_km, obs, color=color, s=60, zorder=5,
                   edgecolors="white", linewidths=0.6)
        ax.annotate(
            mid.replace("!", ""),
            xy=(d_km, obs), xytext=(4, 3),
            textcoords="offset points",
            fontsize=6.5, color=color, alpha=0.9,
        )

    # Legend entries for plausibility colours
    from matplotlib.lines import Line2D
    legend_extra = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#43A047", markersize=8,
               label="● Plausible direct link (obs within 20 dB of FSPL)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#FB8C00", markersize=8,
               label="● Possibly relayed (obs 20–40 dB above FSPL)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#E53935", markersize=8,
               label="● Almost certainly relayed (obs >40 dB above FSPL)"),
    ]

    ax.set_xlabel("Distance from Mt. Washington Summit (km)", fontsize=12)
    ax.set_ylabel("Observed / Predicted RSSI (dBm)", fontsize=12)
    ax.set_title(
        "Mt. Washington — Observed RSSI vs FSPL Prediction  (hop plausibility validation)\n"
        f"915 MHz · TX {TX_POWER_DBM:.0f} dBm · Dipoles each end · LongFast SF11/BW250 · RX sens {RX_SENS_DBM:.0f} dBm",
        fontsize=11,
    )
    ax.set_xlim(0, max_d)
    ax.set_ylim(-140, -50)

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles + legend_extra, labels + [e.get_label() for e in legend_extra],
              loc="upper right", fontsize=8, framealpha=0.9)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150)
    plt.close()
    print(f"  plot → {out_path}")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--mapdata", default=str(Path(__file__).resolve().parents[2] / "MapData"),
                    help="Directory containing the AllTrails GPX files")
    ap.add_argument("--grid-step", type=float, default=0.008,
                    help="Grid spacing in degrees (~0.008° ≈ 600m; finer = slower)")
    args = ap.parse_args()

    root    = Path(args.root)
    out_dir = root / "artifacts/coverage_prediction"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\nLoading trails from GPX...")
    load_trails(Path(args.mapdata))
    print("\nBuilding pre-trial coverage prediction...")
    print(f"  Link budget: {LINK_BUDGET_DB:.1f} dB  "
          f"({TX_POWER_DBM} dBm conducted + {TX_ANT_GAIN_DBI:.2f} dBi TX antenna "
          f"+ {RX_ANT_GAIN_DBI:.2f} dBi RX antenna − {RX_SENS_DBM} dBm sensitivity; "
          f"TX EIRP {TX_EIRP_DBM:.2f} dBm)")

    build_map(out_dir / "coverage_map.html")
    build_distance_plot(out_dir / "rssi_vs_distance.png")

    print("\nDone. Open in browser:")
    print(f"  open {out_dir}/coverage_map.html")
    print(f"  open {out_dir}/rssi_vs_distance.png\n")


if __name__ == "__main__":
    main()

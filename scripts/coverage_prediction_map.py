#!/usr/bin/env python3
"""Pre-trial coverage prediction map for Mt. Washington.

No field data required — uses FSPL at 915 MHz plus terrain-class loss estimates.
Outputs:
  artifacts/coverage_prediction/coverage_map.html     — interactive Folium map
  artifacts/coverage_prediction/rssi_vs_distance.png  — seaborn range curves
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
import seaborn as sns

# ---------------------------------------------------------------------------
# Radio parameters (Heltec V3 + LoRa @ 915 MHz, Meshtastic defaults)
# ---------------------------------------------------------------------------
FREQ_MHZ       = 915.0
TX_POWER_DBM   = 22.0
ANT_GAIN_DBI   = 2.15
RX_SENS_DBM    = -130.0

LINK_BUDGET_DB = TX_POWER_DBM + 2 * ANT_GAIN_DBI - RX_SENS_DBM

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

AMMO_TRAIL:      list[tuple] = []
JEWELL_TRAIL:    list[tuple] = []
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
    global AMMO_TRAIL, JEWELL_TRAIL, TREELINE_AMMO, TREELINE_JEWELL, GEM_POOL

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

    step_a = max(1, len(ammo_ascent)   // 60)
    step_j = max(1, len(jewell_ascent) // 60)
    AMMO_TRAIL[:]   = [(lat, lon) for lat, lon, _ in ammo_ascent[::step_a]]
    JEWELL_TRAIL[:] = [(lat, lon) for lat, lon, _ in reversed(jewell_ascent[::step_j])]

    tl_a = first_crossing(ammo_ascent, 1200)
    tl_j = first_crossing(jewell_ascent, 1200)
    gp   = first_crossing(ammo_ascent, 1068)

    TREELINE_AMMO   = (tl_a[0], tl_a[1]) if tl_a else None
    TREELINE_JEWELL = (tl_j[0], tl_j[1]) if tl_j else None
    GEM_POOL        = (gp[0],   gp[1])   if gp   else None

    print(f"  Ammo:   {len(ammo_ascent)} ascent pts → {len(AMMO_TRAIL)} plotted")
    print(f"  Jewell: {len(jewell_ascent)} ascent pts → {len(JEWELL_TRAIL)} plotted")
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
    return TX_POWER_DBM + 2 * ANT_GAIN_DBI - fspl_db(d_km) - extra_loss_db


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


# FSPL-based hop plausibility.
# Expected direct-link RSSI = TX_POWER + 2*ANT_GAIN - FSPL(d_km).
# If obs_rssi is more than RELAY_THRESHOLD_DB above this prediction,
# the signal cannot have traveled that distance in one hop — it was relayed.
# With our link budget (22 dBm TX, 2 dBi each end) and conservative ±20 dB
# for terrain/antenna variance, anything >20 dB above prediction is suspect;
# >40 dB is almost certainly relayed.
RELAY_THRESHOLD_LIKELY_DB  = 20   # yellow — suspicious
RELAY_THRESHOLD_CERTAIN_DB = 40   # red — almost certainly relayed


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

def build_map(out_path: Path, grid_step_deg: float = 0.008) -> None:
    m = folium.Map(location=[43.6, -71.5], zoom_start=8, tiles="OpenStreetMap")

    # Key location markers (always visible)
    for label, (lat, lon) in LOCATIONS.items():
        folium.Marker([lat, lon], tooltip=label,
                      icon=folium.Icon(color="gray", icon="info-sign")).add_to(m)

    # Known nodes — predicted coverage layer (coloured by summit predicted RSSI)
    known_fg = folium.FeatureGroup(name="Known nodes — predicted coverage", show=True)
    # Known nodes — hop plausibility layer (coloured by FSPL vs observed RSSI)
    hop_fg = folium.FeatureGroup(name="Known nodes — hop plausibility", show=False)

    for mid, n in KNOWN_NODES.items():
        d_km  = haversine_km(*SUMMIT, n["lat"], n["lon"])
        pred  = pred_rssi(d_km, extra_loss_db=3)
        obs   = n.get("obs_rssi")
        elev_str = f"{n['elev_m']}m" if n.get("elev_m") else "elev unknown"

        # Coverage layer colour (based on predicted RSSI from summit)
        cov_color = rssi_to_color(pred)

        # Hop plausibility: compare obs_rssi to FSPL expectation at this distance
        if obs is not None:
            hop_color, hop_label, hop_detail = hop_plausibility(d_km, obs)
        else:
            hop_color, hop_label, hop_detail = "#9E9E9E", "No obs RSSI", "—"

        popup_html = (
            f"<b>{mid}</b><br>"
            f"Elevation: {elev_str}<br>"
            f"Packets heard: {n['packets']}<br>"
            f"Best observed RSSI: {obs if obs is not None else '—'} dBm<br>"
            f"<b>Distance from summit: {d_km:.1f} km</b><br>"
            f"<b>Predicted RSSI from summit: {pred:.0f} dBm</b><br>"
            f"Reachable from summit: {'✓ YES' if pred > -120 else '✗ NO'}<br>"
            f"<hr style='margin:4px 0'>"
            f"<b>Hop plausibility:</b> {hop_label}<br>"
            f"Expected direct RSSI at this dist: {pred_rssi(d_km):.0f} dBm<br>"
            f"Deviation: {hop_detail}"
        )

        # Coverage layer marker
        folium.CircleMarker(
            location=[n["lat"], n["lon"]], radius=10,
            color=cov_color, fill=True, fill_color=cov_color,
            fill_opacity=0.85, weight=2,
            tooltip=f"{mid} — {d_km:.0f} km — pred {pred:.0f} dBm",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(known_fg)
        folium.PolyLine(
            [list(SUMMIT), [n["lat"], n["lon"]]],
            color=cov_color, weight=1.5, opacity=0.4,
        ).add_to(known_fg)

        # Hop plausibility layer marker
        hop_radius = 12 if hop_color == "#E53935" else (10 if hop_color == "#FB8C00" else 8)
        folium.CircleMarker(
            location=[n["lat"], n["lon"]], radius=hop_radius,
            color=hop_color, fill=True, fill_color=hop_color,
            fill_opacity=0.9, weight=2,
            tooltip=f"{mid} — {hop_label} — obs {obs} dBm @ {d_km:.0f} km",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(hop_fg)
        folium.PolyLine(
            [list(SUMMIT), [n["lat"], n["lon"]]],
            color=hop_color, weight=1.5, opacity=0.5,
        ).add_to(hop_fg)

    known_fg.add_to(m)
    hop_fg.add_to(m)

    # Summit star marker (always visible)
    folium.Marker(
        list(SUMMIT),
        tooltip="Mt. Washington Summit — HEAD position tomorrow",
        popup="HEAD node (meshradiohead2)<br>1917 m",
        icon=folium.Icon(color="blue", icon="star"),
    ).add_to(m)

    # Trail routes + placement markers (always visible)
    trail_fg = folium.FeatureGroup(name="Tomorrow's route", show=True)
    folium.PolyLine(AMMO_TRAIL,  color="#E91E63", weight=4, opacity=0.85,
                    tooltip="Ammonoosuc Ravine Trail (ascent)").add_to(trail_fg)
    folium.PolyLine(JEWELL_TRAIL, color="#9C27B0", weight=4, opacity=0.85,
                    tooltip="Jewell Trail (descent)").add_to(trail_fg)
    for pt, label in [(TREELINE_AMMO,   "Treeline — Ammo (~1200m)"),
                      (TREELINE_JEWELL, "Treeline — Jewell (~1200m)")]:
        if pt:
            folium.CircleMarker(pt, radius=8, color="#4CAF50", fill=True,
                                fill_color="#4CAF50", fill_opacity=0.9,
                                tooltip=label).add_to(trail_fg)

    placements = [
        {"lat": 44.26689, "lon": -71.36113,
         "label": "Trailhead — dense forest", "extra_loss": 25},
        ({"lat": GEM_POOL[0], "lon": GEM_POOL[1],
          "label": "Gem Pool (~1068m)", "extra_loss": 20}
         if GEM_POOL else
         {"lat": 44.26768, "lon": -71.32647,
          "label": "Gem Pool (~1068m)", "extra_loss": 20}),
        ({"lat": TREELINE_AMMO[0], "lon": TREELINE_AMMO[1],
          "label": "Ammo treeline (~1200m)", "extra_loss": 5}
         if TREELINE_AMMO else
         {"lat": 44.26622, "lon": -71.32359,
          "label": "Ammo treeline (~1200m)", "extra_loss": 5}),
        {"lat": 44.25872, "lon": -71.31915,
         "label": "Lakes of the Clouds Hut (1528m)", "extra_loss": 3},
        ({"lat": TREELINE_JEWELL[0], "lon": TREELINE_JEWELL[1],
          "label": "Jewell treeline (~1200m)", "extra_loss": 5}
         if TREELINE_JEWELL else
         {"lat": 44.28375, "lon": -71.33587,
          "label": "Jewell treeline (~1200m)", "extra_loss": 5}),
        {"lat": 44.28259, "lon": -71.31689,
         "label": "Jewell–Gulfside Junction (1648m)", "extra_loss": 3},
    ]
    for p in placements:
        d_km = haversine_km(*SUMMIT, p["lat"], p["lon"])
        rssi  = pred_rssi(d_km, p["extra_loss"])
        popup = (f"<b>{p['label']}</b><br>"
                 f"Distance from summit: {d_km:.1f} km<br>"
                 f"Terrain loss: +{p['extra_loss']} dB<br>"
                 f"Predicted RSSI: {rssi:.0f} dBm<br>"
                 f"Quality: {rssi_to_label(rssi)}")
        folium.Marker(
            [p["lat"], p["lon"]],
            tooltip=f"{p['label']} — {rssi:.0f} dBm predicted",
            popup=folium.Popup(popup, max_width=260),
            icon=folium.Icon(color="orange" if rssi > -105 else "red",
                             icon="map-marker"),
        ).add_to(trail_fg)
    trail_fg.add_to(m)

    # Prediction layers — all show=False; custom JS control manages visibility
    lat_range = np.arange(44.220, 44.330, grid_step_deg)
    lon_range = np.arange(-71.370, -71.200, grid_step_deg)
    # Heatmap uses a finer grid — just numbers, no DOM cost
    heat_step = min(grid_step_deg / 4, 0.002)
    heat_lat  = np.arange(44.220, 44.330, heat_step)
    heat_lon  = np.arange(-71.370, -71.200, heat_step)
    heat_gradient = {
        0.0: "#B71C1C", 0.35: "#FF6D00",
        0.6: "#FFD600", 0.85: "#00C853", 1.0: "#00E676",
    }
    rssi_min, rssi_max = -130.0, -60.0
    layer_map: dict[str, str] = {}

    for head_name, head in HEAD_POSITIONS.items():

        # Dot grid — one layer per terrain class
        for terrain_label, extra_loss in TERRAIN_LOSS.items():
            key = f"dots__{head_name}__{terrain_label}"
            fg = folium.FeatureGroup(name=key, show=False)
            for lat in lat_range:
                for lon in lon_range:
                    d_km = haversine_km(head["lat"], head["lon"], lat, lon)
                    rssi = pred_rssi(d_km, extra_loss)
                    if rssi < -130:
                        continue
                    folium.CircleMarker(
                        location=[lat, lon], radius=6, weight=0,
                        color=rssi_to_color(rssi), fill=True,
                        fill_color=rssi_to_color(rssi), fill_opacity=0.55,
                        tooltip=(f"{rssi:.0f} dBm ({rssi_to_label(rssi)}) — "
                                 f"{d_km:.1f} km from {head_name}"),
                    ).add_to(fg)
            folium.Marker(
                [head["lat"], head["lon"]],
                tooltip=f"HEAD: {head_name} ({head['elev_m']} m)",
                icon=folium.Icon(color="blue", icon="tower", prefix="fa"),
            ).add_to(fg)
            fg.add_to(m)
            layer_map[key] = fg.get_name()

        # Heatmap — alpine terrain, one per HEAD
        key = f"heatmap__{head_name}"
        hm_fg = folium.FeatureGroup(name=key, show=False)
        heat_data = []
        for lat in heat_lat:
            for lon in heat_lon:
                d_km = haversine_km(head["lat"], head["lon"], lat, lon)
                rssi = pred_rssi(d_km, extra_loss_db=3)
                if rssi <= rssi_min:
                    continue
                w = max(0.0, min(1.0, (rssi - rssi_min) / (rssi_max - rssi_min)))
                heat_data.append([lat, lon, w])
        folium.plugins.HeatMap(
            heat_data, min_opacity=0.35, radius=18, blur=14,
            gradient=heat_gradient,
        ).add_to(hm_fg)
        folium.Marker(
            [head["lat"], head["lon"]],
            tooltip=f"HEAD: {head_name} ({head['elev_m']} m)",
            icon=folium.Icon(color="blue", icon="tower", prefix="fa"),
        ).add_to(hm_fg)
        hm_fg.add_to(m)
        layer_map[key] = hm_fg.get_name()

    # Legend (bottom-left, always visible)
    m.get_root().html.add_child(folium.Element("""
    <div style="position:fixed;bottom:40px;left:40px;z-index:1000;background:white;
                padding:12px;border-radius:8px;border:1px solid #ccc;font-size:13px;">
      <b>Predicted RSSI (915 MHz LoRa)</b><br>
      <span style="color:#00C853">&#9632;</span> &ge; &minus;90 dBm &nbsp; Strong<br>
      <span style="color:#FFD600">&#9632;</span> &minus;105 to &minus;90 &nbsp; Good<br>
      <span style="color:#FF6D00">&#9632;</span> &minus;120 to &minus;105 &nbsp; Marginal<br>
      <span style="color:#B71C1C">&#9632;</span> &lt; &minus;120 dBm &nbsp; Out of range<br>
      <hr style="margin:6px 0">
      <small>TX 22 dBm &bull; Dipole &bull; SF12 &bull; FSPL only<br>
      Dense forest adds ~25 dB &bull; Sub-alpine ~15 dB</small>
    </div>"""))

    # Save to temp → inject custom control → write final output
    tmp_path = out_path.with_suffix(".tmp.html")
    m.save(str(tmp_path))
    html = tmp_path.read_text(encoding="utf-8")
    tmp_path.unlink()

    match = re.search(r"var (map_[a-f0-9]+)\s*=\s*L\.map\(", html)
    map_var = match.group(1) if match else "map_unknown"

    ctrl = _build_custom_control(layer_map, map_var)
    html = html.replace("</body>", ctrl + "\n</body>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"  map  → {out_path}")


# ---------------------------------------------------------------------------
# Seaborn RSSI vs distance plot
# ---------------------------------------------------------------------------

def build_distance_plot(out_path: Path) -> None:
    sns.set_theme(style="darkgrid", palette="muted")
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
        f"915 MHz · TX {TX_POWER_DBM:.0f} dBm · Dipole · SF12 · RX sens {RX_SENS_DBM:.0f} dBm",
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
          f"({TX_POWER_DBM} dBm TX + {2*ANT_GAIN_DBI:.1f} dB antenna − {RX_SENS_DBM} dBm sens)")

    build_map(out_dir / "coverage_map.html", grid_step_deg=args.grid_step)
    build_distance_plot(out_dir / "rssi_vs_distance.png")

    print("\nDone. Open in browser:")
    print(f"  open {out_dir}/coverage_map.html")
    print(f"  open {out_dir}/rssi_vs_distance.png\n")


if __name__ == "__main__":
    main()

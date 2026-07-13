#!/usr/bin/env python3
"""Real-data hike map — 2026-05-23 Mt. Washington trial.

Observed telemetry and the Garmin receiver track are shown separately from an
explicitly labelled, historical FSPL screening overlay for proposed relays.

Shows:
  • Full GPS route colored by signal quality (active collection segments)
  • Gap segment clearly marked
  • Animated HEAD marker following real GPS track
  • All received mesh nodes colored by RSSI
  • Live rolling 30-min node counter

Outputs:
  artifacts/coverage_prediction/hike_data_map.html
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import folium

from radio_link_budget import (
    RX_ANTENNA_GAIN_DBI,
    RX_POWER_REFERENCE_DBM,
    RX_SENSITIVITY_DBM,
    TX_ANTENNA_GAIN_DBI,
    TX_CONDUCTED_DBM,
    TX_EIRP_DBM,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EDT = timedelta(hours=-4)
HIKE_DATE        = "2026-05-23"
ACTIVE_START_UTC = "2026-05-23T16:24"   # collector came back online
GAP_START_UTC    = "2026-05-23T13:36"   # 09:36 EDT
GAP_END_UTC      = "2026-05-23T16:24"   # 12:24 EDT

ADJACENT_RELAY_ID = "!db51af80"
HEAD_NODE_ID      = "!9e75f97c"

GAP_START_EDT_MIN = 9 * 60 + 36
GAP_END_EDT_MIN   = 12 * 60 + 24


# ---------------------------------------------------------------------------
# RSSI coloring
# ---------------------------------------------------------------------------
_STOPS = [
    (-130, (0,   0,   0  )),
    (-120, (180, 0,   0  )),
    (-110, (255, 80,  0  )),
    (-100, (255, 210, 0  )),
    (-88,  (0,   200, 60 )),
]

def rssi_color(rssi: float) -> str:
    if rssi <= _STOPS[0][0]:
        r, g, b = _STOPS[0][1]; return f"#{r:02x}{g:02x}{b:02x}"
    if rssi >= _STOPS[-1][0]:
        r, g, b = _STOPS[-1][1]; return f"#{r:02x}{g:02x}{b:02x}"
    for i in range(len(_STOPS) - 1):
        v0, c0 = _STOPS[i]; v1, c1 = _STOPS[i + 1]
        if v0 <= rssi <= v1:
            t = (rssi - v0) / (v1 - v0)
            return "#{:02x}{:02x}{:02x}".format(
                int(c0[0] + t*(c1[0]-c0[0])),
                int(c0[1] + t*(c1[1]-c0[1])),
                int(c0[2] + t*(c1[2]-c0[2])),
            )
    return "#888888"

def rssi_label(rssi: float | None) -> str:
    if rssi is None:    return "No data"
    if rssi >= -88:     return "Strong"
    if rssi >= -100:    return "Good"
    if rssi >= -110:    return "Marginal"
    if rssi >= -120:    return "Weak"
    return "Barely detectable"


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------
def utc_to_epoch_ms(utc_ts: str) -> int:
    dt = datetime.fromisoformat(utc_ts.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)

def to_edt_min(utc_ts: str) -> int:
    dt = datetime.fromisoformat(utc_ts.replace("Z", "+00:00"))
    edt = dt + EDT
    return edt.hour * 60 + edt.minute

def epoch_ms_to_edt_hhmm(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc) + EDT
    return f"{dt.hour:02d}:{dt.minute:02d} EDT"

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))


# ---------------------------------------------------------------------------
# Proposed infrastructure terminal assumptions.
# LongFast preset = SF11 / BW 250 kHz / CR 4/5 (NOT SF12/BW125 — that is the
# deprecated LongSlow). Sensitivity per Meshtastic link-budget table / SX1262.
# Predictions here are FSPL + flat elevation-class loss: NO line-of-sight test,
# NO diffraction. Screening estimates only — see trial1_report "Model limitation".
# ---------------------------------------------------------------------------
FREQ_MHZ  = 915.0
TX_DBM    = TX_CONDUCTED_DBM
TX_ANT_GAIN = TX_ANTENNA_GAIN_DBI
RX_ANT_GAIN = RX_ANTENNA_GAIN_DBI
TX_EIRP   = TX_EIRP_DBM
RX_POWER_REF = RX_POWER_REFERENCE_DBM
RX_SENS   = RX_SENSITIVITY_DBM
LINK_BUDGET_DB = RX_POWER_REF - RX_SENS  # 157.3 dB

PROPOSED_NODES = [
    {
        "id":    "ammo_relay",
        "label": "Ammo Trail Relay",
        "lat":   44.26616, "lon": -71.32348, "ele": 1201,
        "type":  "relay",
        "note":  "Treeline crossing — Ammo Trail (ascending 10:19 EDT)",
    },
    {
        "id":    "jewell_relay",
        "label": "Jewell Trail Relay",
        "lat":   44.28376, "lon": -71.33583, "ele": 1199,
        "type":  "relay",
        "note":  "Treeline crossing — Jewell Trail (descending 17:02 EDT)",
    },
    {
        "id":    "trailhead_gw",
        "label": "Trailhead Gateway (Starlink)",
        "lat":   44.26700, "lon": -71.36083, "ele": 764,
        "type":  "gateway",
        "note":  "Base Rd parking area — Starlink uplink to SAR dispatch",
    },
]

def fspl_db(d_km: float) -> float:
    if d_km <= 0: return 0.0
    return 32.44 + 20 * math.log10(d_km) + 20 * math.log10(FREQ_MHZ)

def terrain_loss_db(elev_m: float) -> float:
    if elev_m >= 1500: return 3.0
    if elev_m >= 1200: return 15.0
    return 25.0

def predicted_rssi(d_km: float, elev_m: float) -> float:
    return RX_POWER_REF - fspl_db(d_km) - terrain_loss_db(elev_m)

def best_relay_rssi(lat: float, lon: float, ele: float) -> float:
    """Predicted RSSI from the closest relay node."""
    best = -999.0
    for node in PROPOSED_NODES:
        d = haversine_km(lat, lon, node["lat"], node["lon"])
        r = predicted_rssi(d, ele)
        if r > best:
            best = r
    return best


# ---------------------------------------------------------------------------
# Garmin GPX loader — returns list of (lat, lon, ele_m, epoch_ms)
# ---------------------------------------------------------------------------
def load_garmin_gpx(path: Path) -> list[tuple[float, float, float, int]]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    pts = root.findall(f".//{prefix}trkpt")
    result = []
    for p in pts:
        lat = float(p.get("lat"))
        lon = float(p.get("lon"))
        ele_el = p.find(f"{prefix}ele")
        ele = float(ele_el.text) if ele_el is not None else 0.0
        time_el = p.find(f"{prefix}time")
        if time_el is None:
            continue
        ts_ms = utc_to_epoch_ms(time_el.text)
        result.append((lat, lon, ele, ts_ms))
    return result


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
def load_hike_records(jsonl_path: Path) -> list[dict]:
    records = []
    with jsonl_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("timestamp_utc", "")
            if ts.startswith(HIKE_DATE) and ts >= ACTIVE_START_UTC:
                records.append(r)
    return records

def build_node_stats(records: list[dict]) -> dict:
    stats: dict[str, dict] = {}
    for r in records:
        mid = r.get("from_mesh_id")
        if not mid: continue
        if mid not in stats:
            stats[mid] = {
                "rssi": [], "lat": None, "lon": None, "elev": None,
                "portnum_counts": defaultdict(int), "timestamps": [],
                "best_rssi_ts": None, "best_rssi_val": None,
            }
        s = stats[mid]
        s["timestamps"].append(r["timestamp_utc"])
        s["portnum_counts"][r.get("portnum", "?")] += 1
        rssi = r.get("rssi_dbm")
        if rssi is not None:
            s["rssi"].append(rssi)
            if s["best_rssi_val"] is None or rssi > s["best_rssi_val"]:
                s["best_rssi_val"] = rssi
                s["best_rssi_ts"]  = r["timestamp_utc"]
        if (r.get("portnum") == "POSITION_APP"
                and r.get("lat") and abs(r["lat"]) > 0.01):
            s["lat"] = r["lat"]; s["lon"] = r["lon"]; s["elev"] = r.get("elev_m")
    return stats

def build_packet_events(records: list[dict], node_stats: dict) -> list[dict]:
    events = []
    for r in records:
        mid = r.get("from_mesh_id")
        if not mid or r.get("rssi_dbm") is None: continue
        events.append({
            "ts":  utc_to_epoch_ms(r["timestamp_utc"]),
            "mid": mid,
            "rssi": r["rssi_dbm"],
            "has_gps": node_stats.get(mid, {}).get("lat") is not None,
            "is_adj": mid == ADJACENT_RELAY_ID,
        })
    events.sort(key=lambda e: e["ts"])
    return events


# ---------------------------------------------------------------------------
# Build GPS animation lookup: sorted list of (epoch_ms, lat, lon)
# thinned to ~600 pts so JS interpolation stays fast
# ---------------------------------------------------------------------------
def build_gps_anim(gps_track: list[tuple], max_pts: int = 600) -> list[list]:
    step = max(1, len(gps_track) // max_pts)
    return [[t[3], t[0], t[1]] for t in gps_track[::step]]


def head_pos_at(gps_track: list[tuple], epoch_ms: int) -> tuple[float, float]:
    """Interpolate HEAD lat/lon from Garmin track at a given epoch_ms."""
    if epoch_ms <= gps_track[0][3]:
        return gps_track[0][0], gps_track[0][1]
    if epoch_ms >= gps_track[-1][3]:
        return gps_track[-1][0], gps_track[-1][1]
    lo, hi = 0, len(gps_track) - 2
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if gps_track[mid][3] <= epoch_ms: lo = mid
        else: hi = mid - 1
    p0, p1 = gps_track[lo], gps_track[lo + 1]
    t = (epoch_ms - p0[3]) / (p1[3] - p0[3])
    return p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------
def build_map(jsonl_path: Path, garmin_gpx: Path, out_path: Path) -> None:

    print(f"Loading GPS track: {garmin_gpx}")
    gps_track = load_garmin_gpx(garmin_gpx)
    print(f"  {len(gps_track)} GPS points, "
          f"{epoch_ms_to_edt_hhmm(gps_track[0][3])} – "
          f"{epoch_ms_to_edt_hhmm(gps_track[-1][3])}")

    summit_pt  = max(gps_track, key=lambda p: p[2])
    summit_lat, summit_lon = summit_pt[0], summit_pt[1]
    summit_ms  = summit_pt[3]
    print(f"  Summit: {epoch_ms_to_edt_hhmm(summit_ms)} at {summit_pt[2]:.0f}m "
          f"({summit_lat:.5f}, {summit_lon:.5f})")

    print(f"Loading telemetry: {jsonl_path}")
    hike_records = load_hike_records(jsonl_path)
    print(f"  Active records: {len(hike_records)}")

    node_stats    = build_node_stats(hike_records)
    packet_events = build_packet_events(hike_records, node_stats)
    print(f"  Unique source nodes: {len(node_stats)}, events w/ RSSI: {len(packet_events)}")
    ingest_sha256 = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
    if hike_records:
        source_badge = "OBSERVED LOG (WITH KNOWN GAPS)"
        source_line = (
            f"OBSERVED RECEIVER LOG + GARMIN TRACK — {HIKE_DATE}"
        )
        evidence_summary_html = (
            f"The selected receiver export contains {len(hike_records):,} records "
            f"in the active time window and {len(node_stats)} unique source IDs. "
            "Decoded IDs are not equivalent to study participants: many reported "
            "positions are implausibly distant and may belong to third-party meshes. "
            "Only records with independently usable geometry can support propagation "
            "analysis.<br><br>"
            "<b>The 2h48m collector outage is missing data.</b> It cannot distinguish "
            "a software outage from an RF outage and cannot prove coverage. No relay, "
            "multi-hop, gateway, dispatch, or end-to-end SOS path was field-tested."
        )
    else:
        source_badge = "GARMIN TRACK ONLY — TELEMETRY MISSING"
        source_line = f"GARMIN TRACK ONLY — NO {HIKE_DATE} RECEIVER RECORDS IN SOURCE"
        evidence_summary_html = (
            "<b>The selected export contains no receiver records in the May 23 active "
            "window.</b> This build therefore shows the Garmin track only. Packet, "
            "node-count, RSSI, and coverage conclusions are withheld. Supply the "
            "original May 23 receiver JSONL to reproduce the observed-data layer."
        )

    # -----------------------------------------------------------------------
    # Split GPS track into three display segments
    # -----------------------------------------------------------------------
    gap_start_ms = utc_to_epoch_ms(GAP_START_UTC + ":00+00:00")
    gap_end_ms   = utc_to_epoch_ms(GAP_END_UTC   + ":00+00:00")
    hike_end_ms  = gps_track[-1][3]

    seg_pre_gap  = [(p[0], p[1]) for p in gps_track if p[3] < gap_start_ms]
    seg_gap      = [(p[0], p[1]) for p in gps_track if gap_start_ms <= p[3] <= gap_end_ms]
    seg_active   = [p for p in gps_track if p[3] > gap_end_ms]

    # -----------------------------------------------------------------------
    # Color active GPS segments by 5-min RSSI window
    # -----------------------------------------------------------------------
    WIN_MS = 5 * 60 * 1000

    # Build {bucket_ms: [rssi, ...]} — exclude adjacent device and HEAD self-packets
    # so trail color reflects real mesh connectivity, not the device in your bag
    rssi_bins: dict[int, list[int]] = defaultdict(list)
    for r in hike_records:
        if r.get("rssi_dbm") is None: continue
        if r.get("from_mesh_id") in (ADJACENT_RELAY_ID, HEAD_NODE_ID): continue
        t_ms = utc_to_epoch_ms(r["timestamp_utc"])
        bucket = (t_ms // WIN_MS) * WIN_MS
        rssi_bins[bucket].append(r["rssi_dbm"])

    def seg_color(t_ms: int) -> str:
        bucket = (t_ms // WIN_MS) * WIN_MS
        vals = rssi_bins.get(bucket)
        return rssi_color(max(vals)) if vals else "#aaaaaa"

    def seg_tip(t_ms: int) -> str:
        bucket = (t_ms // WIN_MS) * WIN_MS
        vals = rssi_bins.get(bucket)
        t_str = epoch_ms_to_edt_hhmm(t_ms)
        if vals:
            best = max(vals)
            return (f"{t_str}<br>"
                    f"Max RSSI: {best} dBm ({rssi_label(best)})<br>"
                    f"Packets: {len(vals)}")
        return f"{t_str}<br>No packets in this 5-min window"

    # -----------------------------------------------------------------------
    # Folium map
    # -----------------------------------------------------------------------
    m = folium.Map(location=[44.10, -71.45], zoom_start=9, tiles="OpenStreetMap")

    # -- Pre-gap segment (gray solid — collector offline) --
    if len(seg_pre_gap) >= 2:
        folium.PolyLine(
            seg_pre_gap, color="#aaaaaa", weight=3, opacity=0.6,
            tooltip="Ammo ascent — collector offline",
        ).add_to(m)

    # -- Gap segment (dashed red/gray) --
    if len(seg_gap) >= 2:
        folium.PolyLine(
            seg_gap, color="#c0392b", weight=3, opacity=0.5,
            dash_array="8 6",
            tooltip="Collector offline — 09:36–12:24 EDT",
        ).add_to(m)
        mid_idx = len(seg_gap) // 2
        folium.Marker(
            location=seg_gap[mid_idx],
            icon=folium.DivIcon(
                html=(
                    '<div style="background:#c0392b;color:#fff;padding:4px 10px;'
                    'border-radius:5px;font-size:11px;font-weight:bold;'
                    'white-space:nowrap;box-shadow:0 2px 4px rgba(0,0,0,0.3);">'
                    'Collector offline<br>09:36 – 12:24 EDT  (2 h 48 m)</div>'
                ),
                icon_size=(195, 42), icon_anchor=(98, 21),
            ),
        ).add_to(m)

    # -- Active collection: colored polyline in 5-min windows --
    if seg_active:
        # Group consecutive GPS points by 5-min bin
        current_bucket = (seg_active[0][3] // WIN_MS) * WIN_MS
        current_seg: list[tuple[float, float]] = [(seg_active[0][0], seg_active[0][1])]

        for p in seg_active[1:]:
            bucket = (p[3] // WIN_MS) * WIN_MS
            if bucket != current_bucket:
                if len(current_seg) >= 2:
                    color = seg_color(current_bucket)
                    tip   = seg_tip(current_bucket)
                    folium.PolyLine(
                        current_seg, color=color, weight=5, opacity=0.88,
                        tooltip=tip,
                    ).add_to(m)
                current_seg    = [current_seg[-1]]  # overlap by one point for continuity
                current_bucket = bucket
            current_seg.append((p[0], p[1]))

        # Final segment
        if len(current_seg) >= 2:
            folium.PolyLine(
                current_seg, color=seg_color(current_bucket),
                weight=5, opacity=0.88, tooltip=seg_tip(current_bucket),
            ).add_to(m)

    # -- Summit pin --
    folium.Marker(
        location=(summit_lat, summit_lon),
        popup=folium.Popup(
            f"<b>Mt. Washington Summit ({summit_pt[2]:.0f} m)</b><br>"
            f"Reached: <b>{epoch_ms_to_edt_hhmm(summit_ms)}</b><br>"
            "Collection was active from 12:24 EDT",
            max_width=250,
        ),
        icon=folium.Icon(color="blue", icon="star", prefix="fa"),
        tooltip=f"Summit — {epoch_ms_to_edt_hhmm(summit_ms)}",
    ).add_to(m)

    # -- Node markers --
    gps_fg   = folium.FeatureGroup(name="REAL — Mesh Nodes (known location)", show=True)
    no_gps_list: list[dict] = []

    for mid, s in sorted(node_stats.items(),
                         key=lambda x: max(x[1]["rssi"]) if x[1]["rssi"] else -999,
                         reverse=True):
        if mid == HEAD_NODE_ID: continue
        rssi_vals = s["rssi"]
        max_rssi  = max(rssi_vals) if rssi_vals else None
        min_rssi  = min(rssi_vals) if rssi_vals else None
        pkt_count = sum(s["portnum_counts"].values())
        lat, lon  = s["lat"], s["lon"]
        is_adj    = mid == ADJACENT_RELAY_ID

        fe = to_edt_min(min(s["timestamps"]))
        le = to_edt_min(max(s["timestamps"]))

        if lat is None or lon is None:
            no_gps_list.append({"mid": mid, "max_rssi": max_rssi,
                                 "count": pkt_count, "is_adj": is_adj})
            continue

        # HEAD position at the moment of best contact with this node
        best_ts   = s.get("best_rssi_ts")
        head_contact = head_pos_at(gps_track, utc_to_epoch_ms(best_ts)) if best_ts else (summit_lat, summit_lon)
        dist_km   = haversine_km(head_contact[0], head_contact[1], lat, lon)
        color     = rssi_color(max_rssi) if max_rssi is not None else "#999"
        radius    = 9 if is_adj else (7 if pkt_count > 5 else 5)

        adj_banner = (
            '<div style="background:#e67e22;color:#fff;padding:3px 8px;'
            'border-radius:3px;margin-bottom:5px;font-size:11px;">'
            'ADJACENT DEVICE — carried with HEAD</div>'
        ) if is_adj else ""

        portnum_str = ", ".join(
            f"{p}×{c}" for p, c in
            sorted(s["portnum_counts"].items(), key=lambda x: -x[1])
        )

        popup_html = (
            f'<div style="font-family:monospace;font-size:12px;min-width:230px">'
            f'{adj_banner}<b>{mid}</b><br>'
            f'<span style="color:{color};font-weight:bold;">'
            f'Max RSSI: {max_rssi} dBm ({rssi_label(max_rssi)})</span><br>'
            f'Min RSSI: {min_rssi} dBm<br>'
            f'Packets: {pkt_count}<br>'
            f'Distance at best contact: {dist_km:.1f} km<br>'
            f'GPS: {lat:.4f}°N, {abs(lon):.4f}°W'
            + (f', {s["elev"]}m' if s["elev"] else "")
            + f'<br>Ports: {portnum_str}<br>'
            f'Active: {fe//60:02d}:{fe%60:02d}–{le//60:02d}:{le%60:02d} EDT'
            f'</div>'
        )

        folium.CircleMarker(
            location=(lat, lon), radius=radius,
            color=color, fill=True, fill_color=color, fill_opacity=0.8, weight=2,
            popup=folium.Popup(popup_html, max_width=310),
            tooltip=f"{mid} | {max_rssi} dBm | {dist_km:.0f} km",
        ).add_to(gps_fg)

        folium.PolyLine(
            [head_contact, (lat, lon)],
            color=color, weight=1.5, opacity=0.3,
            dash_array="4 8" if is_adj else None,
        ).add_to(gps_fg)

    gps_fg.add_to(m)

    # -----------------------------------------------------------------------
    # Proposed: Coverage if Deployed — full trail colored by best-relay RSSI
    # -----------------------------------------------------------------------
    cov_fg = folium.FeatureGroup(
        name="SUPERSEDED — historical FSPL coverage screen", show=False
    )

    all_track = gps_track  # full route (ascending + gap + descending)
    if len(all_track) >= 2:
        # Group into 5-min windows, color by predicted best-relay RSSI at midpoint
        WIN_MS2 = 5 * 60 * 1000
        curr_b2 = (all_track[0][3] // WIN_MS2) * WIN_MS2
        curr_seg2: list[tuple[float, float]] = [(all_track[0][0], all_track[0][1])]
        mid_ele2: list[float] = [all_track[0][2]]
        mid_lat2  = all_track[0][0]; mid_lon2 = all_track[0][1]

        def flush_seg2(seg, lats_lons_eles, bucket_ms):
            if len(seg) < 2: return
            avg_lat = sum(p[0] for p in lats_lons_eles) / len(lats_lons_eles)
            avg_lon = sum(p[1] for p in lats_lons_eles) / len(lats_lons_eles)
            avg_ele = sum(p[2] for p in lats_lons_eles) / len(lats_lons_eles)
            pr = best_relay_rssi(avg_lat, avg_lon, avg_ele)
            color = rssi_color(pr)
            t_str = epoch_ms_to_edt_hhmm(bucket_ms)
            tip = (f"{t_str} (superseded FSPL screen)<br>"
                   f"Historical estimate: {pr:.1f} dBm ({rssi_label(pr)})<br>"
                   f"<i>Not an ITM or field-validated coverage result</i>")
            folium.PolyLine(seg, color=color, weight=4, opacity=0.75,
                            dash_array="6 3", tooltip=tip).add_to(cov_fg)

        seg2_pts: list[tuple[float, float]] = [(all_track[0][0], all_track[0][1])]
        seg2_mid: list[tuple[float, float, float]] = [(all_track[0][0], all_track[0][1], all_track[0][2])]

        for pt in all_track[1:]:
            b = (pt[3] // WIN_MS2) * WIN_MS2
            if b != curr_b2:
                flush_seg2(seg2_pts, seg2_mid, curr_b2)
                seg2_pts = [seg2_pts[-1]]
                seg2_mid = [(pt[0], pt[1], pt[2])]
                curr_b2  = b
            seg2_pts.append((pt[0], pt[1]))
            seg2_mid.append((pt[0], pt[1], pt[2]))
        flush_seg2(seg2_pts, seg2_mid, curr_b2)

    cov_fg.add_to(m)

    # -----------------------------------------------------------------------
    # Proposed: Relay Infrastructure — markers at the three node positions
    # -----------------------------------------------------------------------
    infra_fg = folium.FeatureGroup(
        name="CANDIDATE — unapproved relay locations", show=False
    )

    relay_links: list[tuple] = []
    for node in PROPOSED_NODES:
        is_gw = node["type"] == "gateway"
        color  = "#8e44ad" if is_gw else "#e67e22"
        icon   = "wifi" if is_gw else "rss"

        # Link budget table rows for this node
        link_rows = ""
        for other in PROPOSED_NODES:
            if other["id"] == node["id"]: continue
            d = haversine_km(node["lat"], node["lon"], other["lat"], other["lon"])
            pr = predicted_rssi(d, min(node["ele"], other["ele"]))
            lbl = rssi_label(pr)
            link_rows += (
                f"<tr><td>{other['label']}</td>"
                f"<td style='text-align:right'>{d:.2f} km</td>"
                f"<td style='text-align:right;color:{rssi_color(pr)};font-weight:bold'>"
                f"{pr:.1f} dBm</td>"
                f"<td>{lbl}</td></tr>"
            )

        hw_spec = (
            "Heltec LoRa32 V3 + 5W solar + IP67 enclosure<br>"
            "<b>Est. cost: ~$120</b>"
        ) if not is_gw else (
            "Raspberry Pi + Heltec V3 + Starlink Mini<br>"
            "<b>Est. cost: ~$450 + Starlink service</b>"
        )

        popup_html = f"""
<div style="font-family:monospace;font-size:12px;min-width:280px;">
  <div style="background:{color};color:#fff;padding:4px 10px;border-radius:4px 4px 0 0;
              font-weight:bold;font-size:13px;margin-bottom:6px;">
    {'&#x1F4F6; GATEWAY' if is_gw else '&#x1F4E1; RELAY'} &mdash; {node['label']}
  </div>
  <div style="padding:0 4px;">
    <div><b>Position:</b> {node['lat']:.5f}°N, {abs(node['lon']):.5f}°W, {node['ele']}m</div>
    <div style="margin-top:4px;font-size:11px;color:#555;">{node['note']}</div>
    <div style="margin-top:6px;font-size:11px;">{hw_spec}</div>
    <div style="margin-top:8px;font-size:11px;font-weight:bold;">Link budget (TX EIRP {TX_EIRP:.2f}dBm + RX gain {RX_ANT_GAIN:.2f}dBi, 915MHz LongFast SF11/BW250):</div>
    <div style="font-size:10px;color:#a33;"><b>SUPERSEDED:</b> historical FSPL
    + terrain-class estimate. Later ITM/3DEP analysis reverses the summit-link
    conclusion; do not use this table for deployment.</div>
    <table style="width:100%;margin-top:4px;font-size:10px;border-collapse:collapse;">
      <tr style="background:#f0f0f0;">
        <th style="text-align:left;padding:2px 4px;">Link to</th>
        <th>Dist</th><th>RSSI</th><th>Quality</th>
      </tr>
      {link_rows}
    </table>
    <div style="margin-top:6px;font-size:10px;color:#888;">
      Terrain loss: alpine ≥1500m=3dB, sub-alpine 1200–1500m=15dB, forest &lt;1200m=25dB
    </div>
  </div>
</div>"""

        folium.Marker(
            location=(node["lat"], node["lon"]),
            popup=folium.Popup(popup_html, max_width=340),
            tooltip=f"UNAPPROVED CANDIDATE: {node['label']}",
            icon=folium.Icon(color="purple" if is_gw else "orange",
                             icon=icon, prefix="fa"),
        ).add_to(infra_fg)

        # Store for link lines
        relay_links.append((node["lat"], node["lon"], node["label"], color))

    # Draw link lines between relay nodes and gateway
    gw = PROPOSED_NODES[-1]
    for node in PROPOSED_NODES[:-1]:
        d = haversine_km(node["lat"], node["lon"], gw["lat"], gw["lon"])
        pr = predicted_rssi(d, min(node["ele"], gw["ele"]))
        folium.PolyLine(
            [(node["lat"], node["lon"]), (gw["lat"], gw["lon"])],
            color="#8e44ad", weight=2, opacity=0.6, dash_array="8 5",
            tooltip=(f"Relay→Gateway: {d:.2f} km, superseded FSPL screen "
                     f"{pr:.1f} dBm"),
        ).add_to(infra_fg)

    # Relay-to-relay link (both relays → summit coverage zone circle)
    summit_lat2, summit_lon2 = summit_lat, summit_lon
    for node in PROPOSED_NODES[:-1]:
        d = haversine_km(node["lat"], node["lon"], summit_lat2, summit_lon2)
        pr = predicted_rssi(d, 1917)
        folium.PolyLine(
            [(node["lat"], node["lon"]), (summit_lat2, summit_lon2)],
            color="#e67e22", weight=2, opacity=0.5, dash_array="6 4",
            tooltip=(f"Relay→Summit: {d:.2f} km, superseded FSPL screen "
                     f"{pr:.1f} dBm"),
        ).add_to(infra_fg)

    infra_fg.add_to(m)

    folium.LayerControl(collapsed=True, position="bottomright").add_to(m)

    # -----------------------------------------------------------------------
    # Prepare JS data
    # -----------------------------------------------------------------------
    gps_anim  = build_gps_anim(gps_track)   # [[epoch_ms, lat, lon], ...]
    hike_start_ms = gps_track[0][3]
    hike_end_ms   = gps_track[-1][3]
    active_start_ms = utc_to_epoch_ms(ACTIVE_START_UTC + ":00+00:00")

    # Rolling 30-min node counter at 1-min intervals
    ROLLING_WIN_MS = 30 * 60 * 1000
    STEP_MS        = 60 * 1000
    rolling_series: list[list] = []
    t_ms = active_start_ms
    while t_ms <= hike_end_ms + STEP_MS:
        lo = t_ms - ROLLING_WIN_MS
        unique = len({ev["mid"] for ev in packet_events if lo <= ev["ts"] <= t_ms})
        rolling_series.append([t_ms, unique])
        t_ms += STEP_MS

    total_unique_nodes = len({ev["mid"] for ev in packet_events})

    # Timeline chart (5-min EDT bins)
    timeline_bins: dict[int, int] = defaultdict(int)
    for r in hike_records:
        timeline_bins[to_edt_min(r["timestamp_utc"]) // 5] += 1
    min_bin = min(timeline_bins) if timeline_bins else 0
    max_bin = max(timeline_bins) if timeline_bins else 0
    chart_labels = []
    chart_values = []
    for b in range(min_bin, max_bin + 1):
        h = (b * 5) // 60; mi = (b * 5) % 60
        chart_labels.append(f"{h:02d}:{mi:02d}")
        chart_values.append(timeline_bins.get(b, 0))

    no_gps_rows = ""
    for n in sorted(no_gps_list, key=lambda x: x["max_rssi"] or -999, reverse=True):
        rssi_str = str(n["max_rssi"]) if n["max_rssi"] is not None else "—"
        color = rssi_color(n["max_rssi"]) if n["max_rssi"] is not None else "#888"
        adj   = " †" if n["is_adj"] else ""
        no_gps_rows += (
            f"<tr><td style='font-size:11px;'>{n['mid']}{adj}</td>"
            f"<td style='color:{color};font-weight:bold;text-align:center;'>{rssi_str}</td>"
            f"<td style='text-align:center;'>{n['count']}</td></tr>"
        )

    gps_count = sum(1 for s in node_stats.values() if s["lat"] is not None)

    events_json        = json.dumps(packet_events)
    gps_anim_json      = json.dumps(gps_anim)
    rolling_json       = json.dumps(rolling_series)
    chart_labels_json  = json.dumps(chart_labels)
    chart_values_json  = json.dumps(chart_values)

    # -----------------------------------------------------------------------
    # Inject HTML + JS
    # -----------------------------------------------------------------------
    extra = f"""
<style>
  #hike-panel {{
    position:fixed; top:10px; right:10px; width:300px;
    background:rgba(255,255,255,0.95); border:1px solid #ccc; border-radius:8px;
    color:#222; font-family:monospace; font-size:12px; z-index:9999;
    max-height:90vh; overflow-y:auto; box-shadow:0 2px 8px rgba(0,0,0,0.15);
  }}
  #hike-panel .ph {{
    padding:10px 14px; border-bottom:1px solid #e0e0e0;
    background:#f8f8f8; border-radius:8px 8px 0 0;
  }}
  #hike-panel h3 {{ margin:0 0 4px 0; font-size:13px; color:#1a4a8a; }}
  .real-badge {{
    display:inline-block; background:#1a6633; color:#fff;
    padding:2px 8px; border-radius:3px; font-size:10px;
    font-weight:bold; letter-spacing:1px; margin-bottom:6px;
  }}
  #hike-panel .stat {{ color:#444; margin:2px 0; }}
  #hike-panel .stat b {{ color:#111; }}
  #hike-panel .sec-hdr {{
    padding:5px 14px; background:#f0f0f0; font-size:10px;
    color:#666; letter-spacing:1px; text-transform:uppercase;
    border-bottom:1px solid #ddd;
  }}
  #hike-panel table {{ width:100%; border-collapse:collapse; }}
  #hike-panel td {{ padding:3px 10px; border-bottom:1px solid #eee; color:#333; }}
  #hike-panel th {{
    padding:4px 10px; background:#f0f4f8; color:#555;
    font-size:10px; text-align:left;
  }}

  #anim-panel {{
    position:fixed; bottom:10px; left:50%; transform:translateX(-50%);
    width:680px; max-width:96vw;
    background:rgba(255,255,255,0.97); border:1px solid #ccc; border-radius:8px;
    padding:10px 16px 8px; z-index:9998; box-shadow:0 2px 8px rgba(0,0,0,0.18);
    font-family:monospace;
  }}
  #anim-panel .ap-header {{
    display:flex; align-items:center; gap:10px; margin-bottom:8px;
  }}
  #anim-panel h4 {{ margin:0; font-size:12px; color:#1a4a8a; flex:1; }}
  #play-btn {{
    background:#1a4a8a; color:#fff; border:none; border-radius:4px;
    padding:4px 14px; font-size:12px; cursor:pointer; font-family:monospace;
  }}
  #play-btn:hover {{ background:#2563b0; }}
  #speed-sel {{
    font-size:11px; padding:3px 6px; border:1px solid #ccc;
    border-radius:4px; font-family:monospace;
  }}
  #time-display {{
    font-size:12px; color:#333; min-width:80px; text-align:center;
  }}
  #time-slider {{ width:100%; margin:4px 0; }}
  #anim-canvas {{ display:block; width:100%; }}

  #node-counter-box {{
    position:fixed; top:10px; left:50%; transform:translateX(-50%);
    background:rgba(255,255,255,0.97); border:1px solid #ccc; border-radius:8px;
    padding:8px 20px; z-index:9999; font-family:monospace; text-align:center;
    box-shadow:0 2px 6px rgba(0,0,0,0.15); pointer-events:none;
  }}
  .nc-label {{ font-size:10px; color:#888; text-transform:uppercase; letter-spacing:1px; }}
  #nc-current {{
    font-size:32px; font-weight:bold; color:#1a4a8a; line-height:1.1; display:block;
  }}
  .nc-sub {{ font-size:10px; color:#888; }}

  #rssi-legend {{
    position:fixed; bottom:200px; left:10px;
    background:rgba(255,255,255,0.95); border:1px solid #ccc; border-radius:8px;
    padding:10px 14px; z-index:9997; font-family:monospace; font-size:11px;
    box-shadow:0 2px 6px rgba(0,0,0,0.12);
  }}
  #rssi-legend h4 {{ margin:0 0 6px 0; font-size:11px; color:#1a4a8a; }}
  .lrow {{ display:flex; align-items:center; gap:8px; margin:3px 0; color:#333; }}
  .lswatch {{ width:14px; height:14px; border-radius:3px; flex-shrink:0; border:1px solid #ccc; }}

  #map-title {{
    position:fixed; top:10px; left:10px;
    background:rgba(255,255,255,0.95); border:1px solid #ccc; border-radius:8px;
    padding:8px 14px; z-index:9999; font-family:monospace;
    box-shadow:0 2px 6px rgba(0,0,0,0.12);
  }}
  #map-title .mt {{ font-size:13px; font-weight:bold; color:#1a4a8a; }}
  #map-title .ms {{ font-size:10px; color:#1a6633; font-weight:bold; letter-spacing:1px; }}
  #map-title .mn {{ font-size:10px; color:#888; margin-top:2px; }}

  /* Push Leaflet layer control above the animation panel */
  .leaflet-bottom.leaflet-right {{
    bottom: 160px !important;
  }}
  .leaflet-control-layers {{
    font-family: monospace;
    font-size: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.18) !important;
  }}
  .leaflet-control-layers-toggle {{
    background-color: #1a4a8a !important;
  }}

  #proposal-panel {{
    position:fixed; top:10px; right:320px;
    width:310px; max-height:90vh; overflow-y:auto;
    background:rgba(255,255,255,0.97); border:2px solid #8e44ad;
    border-radius:8px; font-family:monospace; font-size:11px;
    color:#222; z-index:9998;
    box-shadow:0 2px 10px rgba(142,68,173,0.25);
    display:none;
  }}
  #proposal-panel.visible {{ display:block; }}
  #proposal-panel .pp-hdr {{
    background:#8e44ad; color:#fff; padding:8px 14px;
    border-radius:6px 6px 0 0; font-weight:bold; font-size:12px;
  }}
  #proposal-panel .pp-body {{ padding:10px 14px; }}
  #proposal-panel .pp-sec {{
    font-size:10px; font-weight:bold; letter-spacing:1px;
    text-transform:uppercase; color:#8e44ad; margin:10px 0 4px 0;
    border-bottom:1px solid #e0c8f0; padding-bottom:2px;
  }}
  #proposal-panel .pp-row {{ margin:3px 0; color:#444; }}
  #proposal-panel .pp-row b {{ color:#111; }}
  #proposal-panel .math-box {{
    background:#f8f0ff; border:1px solid #d0a8e8; border-radius:4px;
    padding:6px 10px; margin:6px 0; font-size:10px; line-height:1.6;
    color:#333;
  }}
  #proposal-panel .chain-box {{
    background:#f0f8f0; border:1px solid #a0d0a0; border-radius:4px;
    padding:6px 10px; margin:6px 0; font-size:10px; line-height:1.7;
    color:#333;
  }}
  #proposal-panel table {{ width:100%; border-collapse:collapse; margin:4px 0; }}
  #proposal-panel td, #proposal-panel th {{
    padding:3px 6px; border-bottom:1px solid #ece4f4; font-size:10px;
  }}
  #proposal-panel th {{ background:#f0e8f8; color:#555; text-align:left; }}
  #toggle-proposal {{
    position:fixed; top:10px; right:320px;
    background:#8e44ad; color:#fff; border:none; border-radius:6px;
    padding:6px 14px; font-size:11px; font-family:monospace;
    cursor:pointer; z-index:10000; box-shadow:0 2px 6px rgba(0,0,0,0.2);
  }}
  #toggle-proposal:hover {{ background:#6c3483; }}

</style>

<button id="toggle-proposal" onclick="(function(){{
  var p=document.getElementById('proposal-panel');
  var b=document.getElementById('toggle-proposal');
  var show=p.classList.toggle('visible');
  b.textContent = show ? '✕ Close Proposal' : '📋 The Proposal';
}})()">&#x1F4CB; The Proposal</button>

<div id="proposal-panel">
  <div class="pp-hdr">&#x1F4E1; Proposed MANET Infrastructure<br>
    <span style="font-size:10px;font-weight:normal;opacity:0.85;">
      NH State Forest Emergency Communications
    </span>
  </div>
  <div class="pp-body">

    <div class="pp-sec">What this shows</div>
    <div class="pp-row">Optional layers (off by default) preserve the original
      proposal for auditability:
      <ul style="margin:4px 0 0 14px;line-height:1.7;">
        <li>3 unapproved candidate nodes at terrain breakpoints</li>
        <li>A historical FSPL + terrain-class overlay (dashed)</li>
        <li><b>Superseded:</b> it cannot establish coverage during the 2h48m
        collector outage</li>
      </ul>
    </div>

    <div class="pp-sec">Node Placement</div>
    <table>
      <tr><th>Node</th><th>Location</th><th>Elev</th><th>Cost</th></tr>
      <tr><td>Ammo Relay</td><td>Treeline crossing</td><td>1201 m</td><td>~$120</td></tr>
      <tr><td>Jewell Relay</td><td>Treeline crossing</td><td>1199 m</td><td>~$120</td></tr>
      <tr><td>Gateway</td><td>Trailhead / Base Rd</td><td>764 m</td><td>~$450</td></tr>
    </table>
    <div style="color:#888;font-size:10px;margin-top:2px;">
      Draft hardware concept only; site permission, mounting, power, backhaul,
      exact radio configuration, and legal authorization remain unverified.
    </div>

    <div class="pp-sec">Historical Link-Budget Screen (superseded)</div>
    <div class="math-box">
      TX power:          22 dBm (Heltec V3 max)<br>
      TX antenna gain: +{TX_ANT_GAIN:.2f} dBi (TX EIRP {TX_EIRP:.2f} dBm)<br>
      RX antenna gain: +{RX_ANT_GAIN:.2f} dBi<br>
      RX sensitivity: −131 dBm (LongFast SF11 BW250 CR4/5)<br>
      ────────────────────────────<br>
      <b>Link budget:  157.3 dB total</b><br>
      FSPL (915 MHz): 32.44 + 20·log₁₀(d_km) + 59.2<br>
      Terrain loss: alpine=3 dB, sub-alpine=15 dB, forest=25 dB<br>
      Predicted RSSI = TX EIRP + RX gain − FSPL − terrain_loss<br>
      <span style="color:#a33;">Preserved to explain the optional historical
      overlay. It omitted line-of-sight and diffraction; the ITM/3DEP result
      below supersedes it.</span>
    </div>

    <div class="pp-sec">Corrected Terrain-Model Screen</div>
    <table>
      <tr><th>Link</th><th>Historical FSPL</th><th>ITM q90</th><th>Status</th></tr>
      <tr><td>Ammo→Summit</td><td>−72.9 dBm</td>
          <td style="color:#a33;font-weight:bold">−132.3 dBm</td>
          <td>below sensitivity</td></tr>
      <tr><td>Jewell→Summit</td><td>−77.9 dBm</td>
          <td style="color:#a33;font-weight:bold">−118.7 dBm</td>
          <td>below planning threshold</td></tr>
      <tr><td>Ammo→Gateway</td><td>−99.8 dBm</td>
          <td style="color:#2e7d32;font-weight:bold">−76.6 dBm</td>
          <td>modeled only</td></tr>
      <tr><td>Jewell→Gateway</td><td>−99.1 dBm</td>
          <td style="color:#2e7d32;font-weight:bold">−74.1 dBm</td>
          <td>modeled only</td></tr>
    </table>
    <div style="color:#888;font-size:10px;margin-top:2px;">
      ITM values are terrain-model predictions, not measurements. The summit
      paths fail the −100 dBm engineering screen and need field testing.
    </div>

    <div class="pp-sec">Target Architecture (not implemented end-to-end)</div>
    <div class="chain-box">
      <b>Hiker triggers SOS</b> (Meshtastic button or app)<br>
      ↓ LoRa mesh hop to nearest relay node<br>
      ↓ Relay forwards to Gateway Pi at trailhead<br>
      ↓ Gateway Pi → independently verified WAN link<br>
      ↓ Authorized bridge to an agreed dispatch interface<br>
      ↓ <b>Delivery to an approved operational recipient</b><br>
      ↓ Payload: node ID, last GPS fix, RSSI, timestamp<br>
      <span style="color:#a33;font-weight:bold;">
        End-to-end latency and delivery are unmeasured
      </span>
    </div>

    <div class="pp-sec">Historical Cost Sketch (not a quote)</div>
    <div class="pp-row">
      2× relay nodes: <b>~$240</b><br>
      1× gateway Pi + Heltec: <b>~$150</b><br>
      Starlink Mini: <b>~$300 hardware</b><br>
      Service, mounts, batteries, permitting, spares, labor, and maintenance:
      <b>not costed</b><br>
      <b style="font-size:12px;color:#8e44ad;">Original ~$690 subtotal is
      incomplete and must not be used as a deployment budget.</b>
    </div>

    <div class="pp-sec">What the observed log can support</div>
    <div class="pp-row" style="line-height:1.6;">
      {evidence_summary_html}
      <br><br><span style="font-size:9px;color:#777;">Receiver source SHA-256:
      {ingest_sha256}</span>
    </div>

  </div>
</div>

<div id="node-counter-box">
  <div class="nc-label">Nodes in contact</div>
  <span id="nc-current">0</span>
  <div class="nc-sub">last 30 min &bull; {total_unique_nodes} heard total</div>
</div>

<div id="map-title">
  <div class="mt">Mt. Washington Mesh Trial</div>
  <div class="ms">{source_line}</div>
  <div class="mn">Optional historical proposal overlays are modeled and superseded</div>
</div>

<div id="rssi-legend">
  <h4>Signal Strength (RSSI)</h4>
  <div class="lrow"><div class="lswatch" style="background:#00c83c;"></div>&gt;&minus;88 dBm &mdash; Strong</div>
  <div class="lrow"><div class="lswatch" style="background:#ffd200;"></div>&minus;100 dBm &mdash; Good</div>
  <div class="lrow"><div class="lswatch" style="background:#ff5000;"></div>&minus;110 dBm &mdash; Marginal</div>
  <div class="lrow"><div class="lswatch" style="background:#b40000;"></div>&minus;120 dBm &mdash; Weak</div>
  <div class="lrow"><div class="lswatch" style="background:#000;border:1px solid #aaa;"></div>Below &minus;120 &mdash; Barely detectable</div>
  <div style="margin-top:7px;color:#888;font-size:10px;line-height:1.5;">
    Colored trail = active collection (5-min windows)<br>
    Gray = before collector came online<br>
    <span style="color:#c0392b;">Red dashed</span> = collector offline<br>
    Circles = mesh nodes with known location<br>
    Lines = RF links observed from summit
  </div>
</div>

<div id="hike-panel">
  <div class="ph">
    <div class="real-badge">{source_badge}</div>
    <h3>Mt. Washington &mdash; 2026-05-23</h3>
    <div class="stat">GPS track: <b>08:06 &ndash; 18:40 EDT</b></div>
    <div class="stat">Active collection: <b>12:24 &ndash; 18:33 EDT</b></div>
    <div class="stat">Summit: <b>{epoch_ms_to_edt_hhmm(summit_ms)}</b></div>
    <div class="stat">Packets received: <b>{len(hike_records)}</b></div>
    <div class="stat">Unique source nodes: <b>{len(node_stats)}</b></div>
    <div class="stat">Nodes with known location: <b>{gps_count}</b></div>
    <div class="stat" style="color:#c0392b;margin-top:6px;">
      Collector offline: <b>09:36 &ndash; 12:24 EDT</b>
      <div style="font-size:10px;color:#888;margin-top:2px;">2 h 48 m</div>
    </div>
  </div>
  <div class="sec-hdr">Unknown-location nodes ({len(no_gps_list)})</div>
  <table>
    <tr><th>Node ID</th><th>Max RSSI</th><th>Pkts</th></tr>
    {no_gps_rows}
  </table>
  <div style="font-size:10px;color:#888;padding:4px 10px;">
    &dagger; = adjacent device (carried with HEAD)
  </div>
</div>

<div id="anim-panel">
  <div class="ap-header">
    <h4>
      Hike Replay &amp; Packet Timeline
      <span style="font-size:10px;color:#888;font-weight:normal;">&mdash; 5-min bins EDT</span>
      <span style="background:#c0392b;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;margin-left:4px;">
        OFFLINE 09:36&ndash;12:24
      </span>
    </h4>
    <select id="speed-sel">
      <option value="120">120x</option>
      <option value="240" selected>240x</option>
      <option value="480">480x</option>
      <option value="960">960x</option>
    </select>
    <span id="time-display">08:06 EDT</span>
    <button id="play-btn">&#9654; Play</button>
  </div>
  <input type="range" id="time-slider" min="0" max="1000" value="0">
  <canvas id="anim-canvas" height="55"></canvas>
</div>

<script>
(function() {{

  var EVENTS        = {events_json};
  var GPS_ANIM      = {gps_anim_json};
  var ROLLING       = {rolling_json};
  var HIKE_START    = {hike_start_ms};
  var HIKE_END      = {hike_end_ms};
  var ACT_START     = {active_start_ms};
  var GAP_START_MIN = {GAP_START_EDT_MIN};
  var GAP_END_MIN   = {GAP_END_EDT_MIN};
  var CHART_LABELS  = {chart_labels_json};
  var CHART_VALUES  = {chart_values_json};
  var MIN_BIN       = {min_bin};

  var currentMs = HIKE_START;
  var playing   = false;
  var rafId     = null;
  var lastWall  = null;
  var headMarker = null;
  var leafMap    = null;

  // ── GPS interpolation (binary search) ─────────────────────────────────────
  function gpsAt(ms) {{
    if (!GPS_ANIM.length) return null;
    if (ms <= GPS_ANIM[0][0])  return [GPS_ANIM[0][1], GPS_ANIM[0][2]];
    if (ms >= GPS_ANIM[GPS_ANIM.length-1][0]) {{
      var last = GPS_ANIM[GPS_ANIM.length-1];
      return [last[1], last[2]];
    }}
    var lo = 0, hi = GPS_ANIM.length - 2;
    while (lo < hi) {{
      var mid = (lo + hi + 1) >> 1;
      if (GPS_ANIM[mid][0] <= ms) lo = mid; else hi = mid - 1;
    }}
    var p0 = GPS_ANIM[lo], p1 = GPS_ANIM[lo+1];
    var t  = (ms - p0[0]) / (p1[0] - p0[0]);
    return [p0[1] + t*(p1[1]-p0[1]), p0[2] + t*(p1[2]-p0[2])];
  }}

  // ── Rolling node count (binary search) ────────────────────────────────────
  function nodeCountAt(ms) {{
    if (!ROLLING.length || ms < ROLLING[0][0]) return 0;
    var lo = 0, hi = ROLLING.length - 1;
    while (lo < hi) {{
      var mid = (lo + hi + 1) >> 1;
      if (ROLLING[mid][0] <= ms) lo = mid; else hi = mid - 1;
    }}
    return ROLLING[lo][1];
  }}

  // ── Time display ──────────────────────────────────────────────────────────
  function msToEdtStr(ms) {{
    var d  = new Date(ms);
    var utcH = d.getUTCHours(), utcM = d.getUTCMinutes();
    var edtH = (utcH - 4 + 24) % 24;
    return String(edtH).padStart(2,'0') + ':' + String(utcM).padStart(2,'0') + ' EDT';
  }}

  // ── Set time ─────────────────────────────────────────────────────────────
  function setTime(ms) {{
    currentMs = Math.max(HIKE_START, Math.min(HIKE_END, ms));
    document.getElementById('time-display').textContent = msToEdtStr(currentMs);
    var frac = (currentMs - HIKE_START) / (HIKE_END - HIKE_START);
    document.getElementById('time-slider').value = Math.round(frac * 1000);

    var pos = gpsAt(currentMs);
    if (headMarker && pos) headMarker.setLatLng(pos);

    var cnt = (currentMs >= ACT_START) ? nodeCountAt(currentMs) : 0;
    document.getElementById('nc-current').textContent = cnt;

    drawChartCursor(frac);
  }}

  // ── Animation loop ────────────────────────────────────────────────────────
  function step(wallMs) {{
    if (!playing) return;
    if (lastWall === null) lastWall = wallMs;
    var delta = (wallMs - lastWall) * parseInt(document.getElementById('speed-sel').value);
    lastWall = wallMs;
    var next = currentMs + delta;
    if (next >= HIKE_END) {{
      setTime(HIKE_END);
      playing = false;
      document.getElementById('play-btn').textContent = '▶ Play';
      lastWall = null;
      return;
    }}
    setTime(next);
    rafId = requestAnimationFrame(step);
  }}

  function play() {{
    if (currentMs >= HIKE_END) setTime(HIKE_START);
    playing = true; lastWall = null;
    document.getElementById('play-btn').textContent = '⏸ Pause';
    rafId = requestAnimationFrame(step);
  }}
  function pause() {{
    playing = false;
    if (rafId) cancelAnimationFrame(rafId);
    lastWall = null;
    document.getElementById('play-btn').textContent = '▶ Play';
  }}

  // ── Chart ─────────────────────────────────────────────────────────────────
  var chartCanvas, chartCtx, chartW, chartH;

  function initChart() {{
    chartCanvas = document.getElementById('anim-canvas');
    chartCtx    = chartCanvas.getContext('2d');
    chartW      = chartCanvas.parentElement.offsetWidth - 32;
    chartCanvas.width = chartW;
    chartH      = chartCanvas.height;
    drawChart();
  }}

  function drawChart() {{
    var ctx = chartCtx, W = chartW, H = chartH, n = CHART_VALUES.length;
    if (!n) return;
    var barW = W / n;
    var maxV = Math.max.apply(null, CHART_VALUES) || 1;
    ctx.clearRect(0, 0, W, H);

    // Gap shading
    var gapX0 = Math.max(0, ((GAP_START_MIN/5 - MIN_BIN) / n) * W);
    var gapX1 = Math.min(W, ((GAP_END_MIN/5   - MIN_BIN) / n) * W);
    ctx.fillStyle = 'rgba(192,57,43,0.12)';
    ctx.fillRect(gapX0, 0, gapX1-gapX0, H-14);
    if (gapX1 > gapX0 + 20) {{
      ctx.fillStyle = '#c0392b'; ctx.font = '9px monospace';
      ctx.fillText('OFFLINE', gapX0+3, 10);
    }}

    // Bars
    for (var i = 0; i < n; i++) {{
      var bh = (CHART_VALUES[i] / maxV) * (H-18);
      ctx.fillStyle = '#3a7cc4';
      ctx.fillRect(i*barW+1, H-14-bh, barW-2, bh);
    }}

    // Hour labels
    ctx.fillStyle = '#888'; ctx.font = '9px monospace';
    for (var i = 0; i < n; i += 12)
      if (CHART_LABELS[i]) ctx.fillText(CHART_LABELS[i], i*barW, H-2);

    ctx.strokeStyle = '#ccc';
    ctx.beginPath(); ctx.moveTo(0, H-14); ctx.lineTo(W, H-14); ctx.stroke();
  }}

  function drawChartCursor(frac) {{
    drawChart();
    var x = frac * chartW;
    chartCtx.strokeStyle = '#c0392b'; chartCtx.lineWidth = 1.5;
    chartCtx.beginPath(); chartCtx.moveTo(x, 0); chartCtx.lineTo(x, chartH-14);
    chartCtx.stroke();
  }}

  // ── Init ──────────────────────────────────────────────────────────────────
  window.addEventListener('load', function() {{
    var mapEl = document.querySelector('.folium-map');
    if (!mapEl) return;
    for (var k in window) {{
      if (window[k] && typeof window[k].addLayer === 'function' &&
          typeof window[k].setView === 'function') {{
        leafMap = window[k]; break;
      }}
    }}
    if (!leafMap) return;

    var HeadIcon = L.divIcon({{
      html: '<div style="width:14px;height:14px;background:#1a4a8a;border:3px solid #fff;border-radius:50%;box-shadow:0 0 8px rgba(26,74,138,0.8);"></div>',
      iconSize: [14, 14], iconAnchor: [7, 7],
    }});
    var startPos = GPS_ANIM.length ? [GPS_ANIM[0][1], GPS_ANIM[0][2]] : [44.27, -71.30];
    headMarker = L.marker(startPos, {{
      icon: HeadIcon, zIndexOffset: 2000,
    }}).addTo(leafMap);
    headMarker.bindTooltip('HEAD position', {{permanent: false}});

    document.getElementById('play-btn').addEventListener('click', function() {{
      if (playing) pause(); else play();
    }});
    document.getElementById('time-slider').addEventListener('input', function() {{
      setTime(HIKE_START + (this.value/1000) * (HIKE_END - HIKE_START));
      if (playing) pause();
    }});

    initChart();
    setTime(HIKE_START);

  }});

}})();
</script>
"""

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = tmp.name
    m.save(tmp_path)
    html = Path(tmp_path).read_text(encoding="utf-8")
    os.unlink(tmp_path)
    html = html.replace("</body>", extra + "</body>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ingest",
        required=True,
        help="receiver JSONL export; its SHA-256 is embedded in the map",
    )
    ap.add_argument("--garmin-gpx",
        default=str(Path(__file__).parent.parent.parent / "activity_22989412258.gpx"))
    ap.add_argument("--out",
        default="artifacts/coverage_prediction/hike_data_map.html")
    args = ap.parse_args()

    repo_root = Path(__file__).parent.parent
    out_path  = (repo_root / args.out
                 if not Path(args.out).is_absolute() else Path(args.out))

    build_map(
        jsonl_path=Path(args.ingest),
        garmin_gpx=Path(args.garmin_gpx),
        out_path=out_path,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

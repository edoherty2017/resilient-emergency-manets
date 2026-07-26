#!/usr/bin/env python3
"""Trial 2 Monadnock field day — predicted vs observed connectivity, side by side.

Left pane: ITM-predicted receive power along the frozen White Dot ascent from
each live public Meshtastic station (registered pre-hike in
artifacts/trial2/monadnock_livemesh_predictions_20260723.json and
monadnock_airmap_data.json). Right pane: observed RSSI from the Pi's packet
log — empty placeholder until the rig comes home, then regenerated with
--observed.

Node toggling: each station is its own overlay layer (route re-colored by that
station alone), plus combined "best available" layers at ITM q50 (median) and
q90 (rough-day) confidence. Same RSSI color ramp as hike_data_map.py.

Usage:
  .venv/bin/python scripts/monadnock_prediction_map.py
  .venv/bin/python scripts/monadnock_prediction_map.py --observed obs.json

Outputs:
  artifacts/trial2/monadnock_prediction_vs_observed.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import folium
from folium.plugins import DualMap

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "artifacts/trial2/monadnock_airmap_data.json"
OUT = ROOT / "artifacts/trial2/monadnock_prediction_vs_observed.html"

# Same ramp as hike_data_map.py (Trial 1 map) for visual continuity.
_STOPS = [
    (-130, (0, 0, 0)),
    (-120, (180, 0, 0)),
    (-110, (255, 80, 0)),
    (-100, (255, 210, 0)),
    (-88, (0, 200, 60)),
]


def rssi_color(rssi: float | None) -> str:
    if rssi is None:
        return "#666666"
    if rssi <= _STOPS[0][0]:
        r, g, b = _STOPS[0][1]
        return f"#{r:02x}{g:02x}{b:02x}"
    if rssi >= _STOPS[-1][0]:
        r, g, b = _STOPS[-1][1]
        return f"#{r:02x}{g:02x}{b:02x}"
    for (x0, c0), (x1, c1) in zip(_STOPS, _STOPS[1:]):
        if x0 <= rssi <= x1:
            t = (rssi - x0) / (x1 - x0)
            r, g, b = (round(a + (b_ - a) * t) for a, b_ in zip(c0, c1))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#666666"


def rx_series(d: dict, node_ids: list[str], q: str) -> list[float | None]:
    """Best predicted RX (dBm) at each route point across node_ids."""
    out = []
    for i in range(len(d["route"])):
        best = None
        for nid in node_ids:
            cell = d["matrix"][nid][i]
            if cell.get(q) is None:
                continue
            rx = d["eirp"] - cell[q]
            if best is None or rx > best:
                best = rx
        out.append(best)
    return out


def add_route_layer(fmap, d, name, series, show, points_popup=False):
    fg = folium.FeatureGroup(name=name, show=show)
    rte = d["route"]
    for i in range(1, len(rte)):
        folium.PolyLine(
            [(rte[i - 1]["lat"], rte[i - 1]["lon"]), (rte[i]["lat"], rte[i]["lon"])],
            color=rssi_color(series[i]),
            weight=6,
            opacity=0.95,
        ).add_to(fg)
    for i, p in enumerate(rte):
        popup = None
        if points_popup:
            rows = "".join(
                f"<tr><td>{n['name']}</td>"
                f"<td align=right>{d['matrix'][n['id']][i]['km']:.1f} km</td>"
                f"<td align=right><b>{d['eirp'] - d['matrix'][n['id']][i]['q50']:.0f}</b></td>"
                f"<td align=right>{d['eirp'] - d['matrix'][n['id']][i]['q90']:.0f}</td></tr>"
                for n in d["nodes"]
                if d["matrix"][n["id"]][i].get("q50") is not None
            )
            popup = folium.Popup(
                f"<b>Point {i + 1}/{len(rte)}</b> — {p['d_m'] / 1000:.2f} km up, "
                f"{p['elev']:.0f} m<br>predicted RX (dBm) per station:"
                f"<table style='font-size:11px'><tr><th>station</th><th>dist</th>"
                f"<th>q50</th><th>q90</th></tr>{rows}</table>",
                max_width=340,
            )
        folium.CircleMarker(
            (p["lat"], p["lon"]),
            radius=5 if series[i] is not None else 4,
            color="#ffffff",
            weight=1,
            fill=True,
            fill_color=rssi_color(series[i]),
            fill_opacity=1.0,
            popup=popup,
        ).add_to(fg)
    fg.add_to(fmap)
    return fg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observed", help="JSON of observed per-point RSSI (built tonight)")
    args = ap.parse_args()

    d = json.loads(DATA.read_text())
    rte = d["route"]
    summit = rte[d["summit_idx"]]
    public = [n["id"] for n in d["nodes"] if n["kind"] == "public"]

    m = DualMap(location=(summit["lat"], summit["lon"]), zoom_start=14, tiles=None)
    for child in (m.m1, m.m2):
        folium.TileLayer("OpenStreetMap", name="street map").add_to(child)
        folium.TileLayer(
            "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            name="topo (OpenTopoMap)",
            attr="© OpenStreetMap, SRTM | © OpenTopoMap (CC-BY-SA)",
        ).add_to(child)

    # ---- LEFT: prediction layers -------------------------------------------
    add_route_layer(
        m.m1, d, "PREDICTED · best of live stations (median)",
        rx_series(d, public, "q50"), show=True, points_popup=True,
    )
    add_route_layer(
        m.m1, d, "PREDICTED · rough day (ITM q90)",
        rx_series(d, public, "q90"), show=False,
    )
    for n in d["nodes"]:
        tag = "own beacon (Plan A)" if n["kind"] == "own" else n["name"]
        add_route_layer(
            m.m1, d, f"only: {tag}",
            rx_series(d, [n["id"]], "q50"), show=False,
        )

    # ---- RIGHT: observed ----------------------------------------------------
    if args.observed:
        obs = json.loads(Path(args.observed).read_text())
        add_route_layer(m.m2, d, "OBSERVED · best real RSSI", obs["best_rssi"], show=True,
                        points_popup=False)
    else:
        fg = folium.FeatureGroup(name="OBSERVED · awaiting field data", show=True)
        folium.PolyLine(
            [(p["lat"], p["lon"]) for p in rte], color="#888888", weight=5,
            opacity=0.7, dash_array="6 8",
        ).add_to(fg)
        folium.Marker(
            (summit["lat"], summit["lon"]),
            icon=folium.DivIcon(html=(
                "<div style='background:#fff;border:2px dashed #888;border-radius:6px;"
                "padding:6px 10px;font:12px monospace;width:190px'>AWAITING FIELD DATA"
                "<br>regenerates tonight from the Pi's JSONL</div>")),
        ).add_to(fg)
        fg.add_to(m.m2)

    # ---- stations + landmarks on both panes --------------------------------
    for child in (m.m1, m.m2):
        for n in d["nodes"]:
            summit_cell = d["matrix"][n["id"]][d["summit_idx"]]
            rx50 = d["eirp"] - summit_cell["q50"]
            folium.Marker(
                (n["lat"], n["lon"]),
                icon=folium.Icon(
                    color="orange" if n["kind"] == "own" else
                    ("green" if rx50 >= -100 else "blue" if rx50 >= -134 else "gray"),
                    icon="tower-cell" if n["kind"] == "public" else "flag", prefix="fa",
                ),
                popup=folium.Popup(
                    f"<b>{n['name']}</b><br>{summit_cell['km']:.1f} km from summit<br>"
                    f"predicted at summit: <b>{rx50:.0f} dBm</b> (q50) / "
                    f"{d['eirp'] - summit_cell['q90']:.0f} (q90)<br>"
                    f"<i>toggle this station's route view in the layer control</i>",
                    max_width=260,
                ),
                tooltip=n["name"],
            ).add_to(child)
        folium.Marker(
            (summit["lat"], summit["lon"]), tooltip="Monadnock summit (965 m)",
            icon=folium.Icon(color="red", icon="mountain", prefix="fa"),
        ).add_to(child)
        folium.Marker(
            (rte[0]["lat"], rte[0]["lon"]), tooltip="State Park HQ — White Dot trailhead",
            icon=folium.Icon(color="darkgreen", icon="car", prefix="fa"),
        ).add_to(child)
        folium.LayerControl(collapsed=False).add_to(child)

    # ---- header + legend -----------------------------------------------------
    legend_rows = "".join(
        f"<span style='background:{rssi_color(v)};width:26px;display:inline-block'>&nbsp;</span>"
        for v in range(-132, -85, 3)
    )
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:9999;
      background:#fff;border:2px solid #333;border-radius:6px;padding:7px 14px;
      font:12px/1.5 monospace;box-shadow:0 1px 6px rgba(0,0,0,.3)">
      <b>MONADNOCK · WHITE DOT · PREDICTED (left) vs OBSERVED (right)</b><br>
      ITM q50 · EIRP ref {d['eirp']} dBm · frozen 2026-07-23 · public stations are
      non-calibration-grade (unknown TX EIRP)<br>
      {legend_rows}<br>
      <span style="letter-spacing:.35em">−130&nbsp;&nbsp;−120&nbsp;&nbsp;−110&nbsp;&nbsp;−100&nbsp;&nbsp;−88 dBm</span>
    </div>"""))

    m.save(str(OUT))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

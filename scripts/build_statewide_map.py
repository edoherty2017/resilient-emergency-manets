#!/usr/bin/env python3
"""Statewide SAR mesh proposal map (static, publication-grade).

One figure for the NH F&G pack: DEM hillshade, every audited site colored by
category (gateway ★ / hut / shelter / ridge / valley), usable links drawn
(fine-DEM rescues dashed), rental trails overlaid, region labels. Reads the
audit so the caption can state the PASS verdict honestly.

Run: .venv/bin/python scripts/build_statewide_map.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CAT_STYLE = {
    "gateway": {"c": "#d62728", "m": "*", "s": 200, "label": "MQTT gateway (grid/backhaul)"},
    "hut":     {"c": "#9467bd", "m": "s", "s": 46,  "label": "Staffed hut/cabin"},
    "shelter": {"c": "#8c564b", "m": "D", "s": 36,  "label": "Caretaker shelter"},
    "ridge":   {"c": "#2ca02c", "m": "^", "s": 46,  "label": "Ridge relay (solar pyramid)"},
    "valley":  {"c": "#1f77b4", "m": "o", "s": 36,  "label": "Trailhead node"},
    "portable": {"c": "#ff7f0e", "m": "P", "s": 60,
                 "label": "SAR-deployed portable (Wilderness interior)"},
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Statewide proposal map")
    ap.add_argument("--suffix", default="_statewide")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    ap.add_argument("--out", default="artifacts/sim/statewide_proposal_map.png")
    args = ap.parse_args()

    topo = json.loads((ROOT / f"artifacts/sim/topology{args.suffix}.json").read_text())
    audit = json.loads((ROOT / f"artifacts/sim/coverage_audit{args.suffix}.json").read_text())
    routes = json.loads((ROOT / f"artifacts/sim/routes{args.suffix}.json").read_text())
    dem = np.load(ROOT / args.dem_npz)
    sites = topo["sites"]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    z = dem["dem"]
    la, lo = dem["lat_axis"], dem["lon_axis"]
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(z, vert_exag=0.00002)

    fig, ax = plt.subplots(figsize=(11, 16))
    ax.imshow(hs, extent=[lo.min(), lo.max(), la.min(), la.max()],
              origin="lower", cmap="gray", alpha=0.65, aspect="auto")

    # NH state boundary: everything outside is Vermont / Maine / Massachusetts
    # / ocean — correctly empty, and now visibly so.
    nh_p = ROOT / "artifacts/osm/nh_boundary.json"
    if nh_p.exists():
        g = json.loads(nh_p.read_text())
        rings = ([g["coordinates"][0]] if g["type"] == "Polygon"
                 else [poly[0] for poly in g["coordinates"]])
        from matplotlib.patches import Polygon as _BPoly
        from matplotlib.path import Path as _MPath
        import matplotlib.patches as _mpatches
        for ring in rings:
            xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
            ax.plot(xs, ys, color="#111", lw=2.0, zorder=5)
        # dim everything outside NH
        ring = rings[0]
        frame = [(lo.min(), la.min()), (lo.max(), la.min()),
                 (lo.max(), la.max()), (lo.min(), la.max()), (lo.min(), la.min())]
        verts = frame + [(c[0], c[1]) for c in ring] + [ring[0][:2]]
        codes = ([_MPath.MOVETO] + [_MPath.LINETO] * 3 + [_MPath.CLOSEPOLY]
                 + [_MPath.MOVETO] + [_MPath.LINETO] * (len(ring) - 1)
                 + [_MPath.CLOSEPOLY])
        ax.add_patch(_mpatches.PathPatch(_MPath(verts, codes), facecolor="white",
                                         alpha=0.55, edgecolor="none", zorder=4))
        ax.annotate("VERMONT", xy=(-72.35, 44.35), fontsize=13, color="#666",
                    rotation=78, zorder=6)
        ax.annotate("MAINE", xy=(-70.92, 44.75), fontsize=13, color="#666",
                    rotation=-78, zorder=6)

    # coverage blanket: terrain-clipped service polygons where computed
    # (coverage_field.py); the audit, not the shading, is the coverage claim
    import math as _m
    from matplotlib.patches import Circle, Polygon as MplPolygon
    sa_p = ROOT / "artifacts/sim/service_areas.json"
    if sa_p.exists():
        sa = json.loads(sa_p.read_text())["sites"]
        for n, sv in sa.items():
            mlat = 111320.0
            mlon = 111320.0 * _m.cos(_m.radians(sv["lat"]))
            pts = []
            nr = len(sv["range_m"])
            for k, r in enumerate(sv["range_m"]):
                az = k * 2 * _m.pi / nr
                r = max(r, 40.0)
                pts.append((sv["lon"] + r * _m.sin(az) / mlon,
                            sv["lat"] + r * _m.cos(az) / mlat))
            ax.add_patch(MplPolygon(pts, closed=True, facecolor="#2ca02c",
                                    alpha=0.12, edgecolor="none", zorder=1))
    else:
        for s in sites.values():
            r_deg = 2500.0 / 111320.0
            ax.add_patch(Circle((s["lon"], s["lat"]),
                                r_deg / _m.cos(_m.radians(s["lat"])) * 0.85,
                                facecolor="#2ca02c", alpha=0.10,
                                edgecolor="none", zorder=1))
    # uncovered trail segments in red (trail_coverage.json gaps)
    tc_p = ROOT / "artifacts/sim/trail_coverage.json"
    if tc_p.exists():
        tc = json.loads(tc_p.read_text())
        for g in tc.get("gap_segments", []):
            ax.plot(g["lon"], g["lat"], "x", color="red", ms=9, mew=2.2, zorder=6)

    # usable links
    for key, l in topo["links"].items():
        a, b = key.split("|")
        rssi90 = 26.3 - l["loss_db_q90"]
        if rssi90 < -131.0:
            continue
        sa, sb = sites[a], sites[b]
        fine = l.get("model") == "short_link_fspl" or l.get("dem") == "fine_3dep"
        ax.plot([sa["lon"], sb["lon"]], [sa["lat"], sb["lat"]],
                color="#2a4d14" if not fine else "#b8860b",
                lw=1.4 if rssi90 >= -100 else 0.7,
                ls="-" if not fine else (0, (3, 2)),
                alpha=0.8 if rssi90 >= -100 else 0.45, zorder=2)

    # rental trails
    for rname, r in routes["routes"].items():
        ax.plot(r["lon"], r["lat"], color="#0a58ff", lw=1.6, alpha=0.75, zorder=3)

    # sites by category
    for cat, st in CAT_STYLE.items():
        xs = [s["lon"] for s in sites.values() if s.get("category") == cat]
        ys = [s["lat"] for s in sites.values() if s.get("category") == cat]
        ax.scatter(xs, ys, c=st["c"], marker=st["m"], s=st["s"],
                   edgecolor="black", linewidth=0.5, label=st["label"], zorder=4)

    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles += [
        Line2D([0], [0], color="#2a4d14", lw=1.6, label="Usable link (ITM q90 ≥ −131 dBm)"),
        Line2D([0], [0], color="#b8860b", lw=1.6, ls=(0, (3, 2)),
               label="Short-link policy / fine-DEM link"),
        Line2D([0], [0], color="#0a58ff", lw=1.8, label="Rental route (real OSM trail)"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.93)

    n_gw = sum(1 for s in sites.values() if s.get("mqtt_uplink"))
    ax.set_title(
        f"NH SAR Mesh — statewide proposal topology\n"
        f"{len(sites)} sites · {n_gw} gateways · coverage audit: "
        f"{audit['verdict']} ({len(audit['stranded_sites'])} stranded, "
        f"{sum(1 for t in audit['trail_coverage'] if t['ok'])}/"
        f"{len(audit['trail_coverage'])} routes covered)",
        fontsize=13)
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_xlim(lo.min(), lo.max()); ax.set_ylim(la.min(), la.max())

    # ── region site-count annotations (the statewide view fuses the dense
    #    clusters into single blobs; label what each blob contains) ───────────
    REGION_BOXES = {
        "White Mtns core": (43.95, 44.45, -71.75, -71.00),
        "Moosilauke": (43.95, 44.06, -71.92, -71.76),
        "Cardigan": (43.60, 43.70, -71.95, -71.84),
        "Squam/Rumney": (43.72, 43.90, -71.85, -71.44),
        "Belknaps/Ossipee": (43.45, 43.80, -71.45, -71.02),
        "Kearsarge/Ragged": (43.33, 43.53, -71.95, -71.80),
        "Sunapee/Greenway": (43.15, 43.35, -72.12, -72.00),
        "Monadnock/Wapack": (42.80, 43.02, -72.15, -71.84),
        "Pisgah": (42.82, 42.88, -72.48, -72.40),
        "Kilkenny/N Country": (44.40, 45.15, -71.50, -71.10),
    }
    for label, (a0, a1, b0, b1) in REGION_BOXES.items():
        n = sum(1 for s in sites.values()
                if a0 <= s["lat"] <= a1 and b0 <= s["lon"] <= b1)
        if n:
            ax.annotate(f"{label}: {n}", xy=(b1, a1), fontsize=8, color="#222",
                        ha="left", va="bottom",
                        bbox=dict(boxstyle="round,pad=0.15", fc="white",
                                  ec="#888", alpha=0.85))

    # ── inset: the White Mountains core at readable zoom ─────────────────────
    axin = ax.inset_axes([0.005, 0.60, 0.44, 0.395])
    a0, a1, b0, b1 = 44.00, 44.42, -71.75, -71.02
    ila = (la >= a0) & (la <= a1)
    ilo = (lo >= b0) & (lo <= b1)
    axin.imshow(hs[np.ix_(ila, ilo)], extent=[b0, b1, a0, a1], origin="lower",
                cmap="gray", alpha=0.6, aspect="auto")
    if sa_p.exists():
        sa2 = json.loads(sa_p.read_text())["sites"]
        for n, sv in sa2.items():
            if not (a0 <= sv["lat"] <= a1 and b0 <= sv["lon"] <= b1):
                continue
            mlat = 111320.0
            mlon = 111320.0 * _m.cos(_m.radians(sv["lat"]))
            pts = [(sv["lon"] + max(r, 40) * _m.sin(k * 2 * _m.pi / len(sv["range_m"])) / mlon,
                    sv["lat"] + max(r, 40) * _m.cos(k * 2 * _m.pi / len(sv["range_m"])) / mlat)
                   for k, r in enumerate(sv["range_m"])]
            axin.add_patch(MplPolygon(pts, closed=True, facecolor="#2ca02c",
                                      alpha=0.14, edgecolor="none"))
    for rname, r in routes["routes"].items():
        axin.plot(r["lon"], r["lat"], color="#0a58ff", lw=1.0, alpha=0.7)
    for cat, st in CAT_STYLE.items():
        xs = [s["lon"] for s in sites.values() if s.get("category") == cat
              and a0 <= s["lat"] <= a1 and b0 <= s["lon"] <= b1]
        ys = [s["lat"] for s in sites.values() if s.get("category") == cat
              and a0 <= s["lat"] <= a1 and b0 <= s["lon"] <= b1]
        axin.scatter(xs, ys, c=st["c"], marker=st["m"], s=st["s"] * 0.6,
                     edgecolor="black", linewidth=0.4)
    n_core = sum(1 for s in sites.values()
                 if a0 <= s["lat"] <= a1 and b0 <= s["lon"] <= b1)
    axin.set_title(f"White Mountains core — {n_core} sites", fontsize=9)
    axin.set_xlim(b0, b1); axin.set_ylim(a0, a1)
    axin.set_xticks([]); axin.set_yticks([])
    ax.indicate_inset_zoom(axin, edgecolor="black")
    fig.tight_layout()
    out = ROOT / args.out
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

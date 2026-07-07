#!/usr/bin/env python3
"""Predictive-vs-actual coverage heatmap (proposal deliverable #4 figure).

Computes an ITM-predicted received-signal grid from a transmitter site over the
real DEM, renders it as a terrain-aware heatmap, and overlays observed RF points
colored by their actual measured signal — so predicted and actual coverage can be
compared at a glance. Also emits a residual (actual − predicted) summary.

Usage:
  python3 scripts/build_coverage_heatmap.py \
      --dem-npz artifacts/dem/cache/usgs_3dep_mtwashington.npz \
      --tx-lat 44.26616 --tx-lon -71.32348 \
      --observations artifacts/airmap/live_trial/predictions_postcalibration.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, itm_p2p_loss, EIRP_DBM, RX_SENS_DBM, PLANNING_DBM  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="ITM predicted-vs-actual coverage heatmap")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_mtwashington.npz")
    ap.add_argument("--tx-lat", type=float, default=44.26616, help="Transmitter latitude (default Ammo relay)")
    ap.add_argument("--tx-lon", type=float, default=-71.32348)
    ap.add_argument("--tx-h", type=float, default=3.0)
    ap.add_argument("--rx-h", type=float, default=1.5)
    ap.add_argument("--freq-mhz", type=float, default=915.0)
    ap.add_argument("--grid-size", type=int, default=45)
    ap.add_argument("--observations", default=None, help="Parquet with lat/lon + observed signal to overlay")
    ap.add_argument("--obs-col", default="obs_target_dbm")
    ap.add_argument("--out-png", default="artifacts/itm/coverage_heatmap.png")
    ap.add_argument("--out-json", default="artifacts/itm/coverage_heatmap_summary.json")
    ap.add_argument("--route-gpx", default=str(Path.home() / "MANET/activity_22989412258.gpx"),
                    help="GPX track to draw over the coverage overlay (set '' to skip)")
    ap.add_argument("--out-html", default="artifacts/itm/coverage_map.html",
                    help="Interactive coverage overlay on a real basemap with the route")
    ap.add_argument("--no-html", action="store_true")
    args = ap.parse_args()

    dem_path = ROOT / args.dem_npz if not Path(args.dem_npz).is_absolute() else Path(args.dem_npz)
    if not dem_path.exists():
        raise SystemExit(f"DEM cache not found: {dem_path}; run dem_3dep.py / dem_copernicus.py")
    dem = Dem(dem_path)

    # Grid bounds: a window around the transmitter clipped to the DEM extent.
    lat_pad, lon_pad = 0.03, 0.04
    lat_lo = max(args.tx_lat - lat_pad, float(dem.lat.min()))
    lat_hi = min(args.tx_lat + lat_pad, float(dem.lat.max()))
    lon_lo = max(args.tx_lon - lon_pad, float(dem.lon.min()))
    lon_hi = min(args.tx_lon + lon_pad, float(dem.lon.max()))
    lats = np.linspace(lat_lo, lat_hi, args.grid_size)
    lons = np.linspace(lon_lo, lon_hi, args.grid_size)

    print(f"computing ITM grid {args.grid_size}x{args.grid_size} from "
          f"({args.tx_lat:.5f},{args.tx_lon:.5f}) ...")
    pred = np.full((args.grid_size, args.grid_size), np.nan)
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            d_m, prof = dem.profile(args.tx_lat, args.tx_lon, la, lo)
            if d_m < 30.0:
                pred[i, j] = EIRP_DBM
                continue
            try:
                itm = itm_p2p_loss(d_m / 1000.0, prof, (args.tx_h, args.rx_h), freq_mhz=args.freq_mhz)
                pred[i, j] = EIRP_DBM - itm["loss_db_q50"]
            except Exception:
                pred[i, j] = np.nan

    ground = dem.sample(
        np.repeat(lats, args.grid_size),
        np.tile(lons, args.grid_size),
    ).reshape(args.grid_size, args.grid_size)

    # ── Render ────────────────────────────────────────────────────────────────
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    fig, ax = plt.subplots(figsize=(9, 8))
    extent = [lon_lo, lon_hi, lat_lo, lat_hi]
    # terrain hillshade backdrop
    ax.imshow(ground, extent=extent, origin="lower", cmap="gray", alpha=0.35, aspect="auto")
    norm = TwoSlopeNorm(vmin=-140, vcenter=PLANNING_DBM, vmax=-60)
    im = ax.imshow(pred, extent=extent, origin="lower", cmap="RdYlGn", norm=norm,
                   alpha=0.65, aspect="auto")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Predicted RSSI (dBm) — ITM q50")
    ax.plot(args.tx_lon, args.tx_lat, marker="^", color="black", markersize=13,
            markeredgecolor="white", label="Transmitter")

    residual_summary = None
    if args.observations:
        obs_path = ROOT / args.observations if not Path(args.observations).is_absolute() else Path(args.observations)
        if obs_path.exists():
            obs = pd.read_parquet(obs_path)
            obs = obs.dropna(subset=["lat", "lon", args.obs_col])
            if len(obs):
                sc = ax.scatter(obs["lon"], obs["lat"], c=obs[args.obs_col], cmap="RdYlGn",
                                norm=norm, edgecolor="black", s=28, linewidth=0.4,
                                label="Observed")
                # residual at each observed point: actual − predicted(grid nearest)
                gi = np.clip(np.searchsorted(lats, obs["lat"]) - 0, 0, args.grid_size - 1)
                gj = np.clip(np.searchsorted(lons, obs["lon"]) - 0, 0, args.grid_size - 1)
                pred_at = pred[gi, gj]
                resid = obs[args.obs_col].to_numpy() - pred_at
                resid = resid[~np.isnan(resid)]
                if len(resid):
                    residual_summary = {
                        "n": int(len(resid)),
                        "mean_db": float(np.mean(resid)),
                        "rmse_db": float(np.sqrt(np.mean(resid ** 2))),
                        "p50_db": float(np.median(resid)),
                    }

    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_title("ITM Predicted Coverage vs Observed RF\n(transmitter → receiver, real 3DEP terrain)")
    ax.legend(loc="upper right")
    out_png = ROOT / args.out_png if not Path(args.out_png).is_absolute() else Path(args.out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)

    # ── Interactive overlay: coverage raster on a real basemap + the route ────
    out_html_rel = None
    if not args.no_html:
        out_html = _build_html_overlay(
            pred, lats, lons, lat_lo, lat_hi, lon_lo, lon_hi, norm,
            args.tx_lat, args.tx_lon, args.route_gpx, args.out_html,
        )
        out_html_rel = str(out_html.relative_to(ROOT)) if out_html.is_relative_to(ROOT) else str(out_html)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "transmitter": {"lat": args.tx_lat, "lon": args.tx_lon, "tx_h_m": args.tx_h},
        "freq_mhz": args.freq_mhz,
        "grid_size": args.grid_size,
        "predicted_rssi_dbm": {
            "min": float(np.nanmin(pred)), "max": float(np.nanmax(pred)),
            "pct_above_planning_threshold": float(100.0 * np.nanmean(pred >= PLANNING_DBM)),
            "pct_above_sensitivity": float(100.0 * np.nanmean(pred >= RX_SENS_DBM)),
        },
        "residual_actual_minus_predicted": residual_summary,
        "out_png": str(out_png.relative_to(ROOT)) if out_png.is_relative_to(ROOT) else str(out_png),
        "out_html": out_html_rel,
    }
    out_json = ROOT / args.out_json if not Path(args.out_json).is_absolute() else Path(args.out_json)
    out_json.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def _load_gpx(path: Path) -> list[tuple[float, float]]:
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.findall(f".//{prefix}trkpt")]


def _build_html_overlay(pred, lats, lons, lat_lo, lat_hi, lon_lo, lon_hi, norm,
                        tx_lat, tx_lon, route_gpx, out_html):
    """Render the coverage grid as a semi-transparent raster on a real basemap,
    with the GPS route drawn on top so coverage can be read along the trail."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.cm as cm
    import matplotlib.pyplot as plt
    import folium
    import branca.colormap as bcm

    # RGBA overlay image; row 0 must be NORTH for folium ImageOverlay.
    rgba = cm.RdYlGn(norm(pred))
    rgba[..., 3] = np.where(np.isnan(pred), 0.0, 0.6)  # transparent where no prediction
    rgba_img = np.flipud(rgba)  # lats ascending -> flip so top row = north
    overlay_png = (ROOT / "artifacts/itm/_coverage_overlay_rgba.png")
    plt.imsave(overlay_png, rgba_img)

    clat = (lat_lo + lat_hi) / 2
    clon = (lon_lo + lon_hi) / 2
    m = folium.Map(location=[clat, clon], zoom_start=13, tiles=None)
    folium.TileLayer("OpenStreetMap", name="Street").add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite",
    ).add_to(m)
    folium.TileLayer(
        "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap", name="Topo", show=True,
    ).add_to(m)

    folium.raster_layers.ImageOverlay(
        image=str(overlay_png),
        bounds=[[lat_lo, lon_lo], [lat_hi, lon_hi]],
        opacity=0.6, name="ITM predicted RSSI",
    ).add_to(m)

    if route_gpx and Path(route_gpx).exists():
        pts = _load_gpx(Path(route_gpx))
        if pts:
            folium.PolyLine(pts, color="#1020ff", weight=3, opacity=0.9,
                            tooltip="Route").add_to(m)
            folium.Marker(pts[0], tooltip="Start",
                          icon=folium.Icon(color="green", icon="play")).add_to(m)
            folium.Marker(pts[-1], tooltip="End",
                          icon=folium.Icon(color="red", icon="stop")).add_to(m)

    folium.Marker([tx_lat, tx_lon], tooltip="Transmitter (proposed relay)",
                  icon=folium.Icon(color="black", icon="tower-broadcast", prefix="fa")).add_to(m)

    legend = bcm.LinearColormap(
        [cm.RdYlGn(x) for x in (0.0, 0.25, 0.5, 0.75, 1.0)],
        vmin=-140, vmax=-60, caption="Predicted RSSI (dBm) — green=strong, red=no link",
    )
    legend.add_to(m)
    folium.LayerControl().add_to(m)

    out = ROOT / out_html if not Path(out_html).is_absolute() else Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(out))
    return out


if __name__ == "__main__":
    raise SystemExit(main())

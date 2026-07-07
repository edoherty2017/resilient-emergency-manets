#!/usr/bin/env python3
"""Fetch real USGS 3DEP elevation for the trial AOI and cache it for the pipeline.

Replaces the synthetic pseudo-DEM (review P2 item 11). Source: USGS 3DEP
ImageServer (https://elevation.nationalmap.gov), public domain. The export is
saved as GeoTIFF plus an .npz cache (lat_axis, lon_axis, dem) in the format
consumed by dem_transformer.py and itm_relay_links.py.

Default AOI covers the Ammonoosuc/Jewell trail system, the proposed relay and
gateway sites, and the Mt. Washington summit.

Run from the repo root inside .venv:
    python scripts/dem_3dep.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SERVICE_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch USGS 3DEP DEM for the trial AOI")
    ap.add_argument("--lat-min", type=float, default=44.235)
    ap.add_argument("--lat-max", type=float, default=44.325)
    ap.add_argument("--lon-min", type=float, default=-71.420)
    ap.add_argument("--lon-max", type=float, default=-71.255)
    ap.add_argument("--width", type=int, default=1800, help="Export width in pixels")
    ap.add_argument("--out-dir", default="artifacts/dem/cache")
    ap.add_argument("--name", default="usgs_3dep_mtwashington")
    args = ap.parse_args()

    import requests
    import rasterio

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tif_path = out_dir / f"{args.name}.tif"
    npz_path = out_dir / f"{args.name}.npz"

    # Pixel aspect: keep ~square pixels in meters
    lat_span = args.lat_max - args.lat_min
    lon_span = args.lon_max - args.lon_min
    lat_c = (args.lat_min + args.lat_max) / 2
    meters_lon = lon_span * 111_320.0 * np.cos(np.radians(lat_c))
    meters_lat = lat_span * 111_320.0
    height = int(round(args.width * meters_lat / meters_lon))

    params = {
        "bbox": f"{args.lon_min},{args.lat_min},{args.lon_max},{args.lat_max}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{args.width},{height}",
        "format": "tiff",
        "pixelType": "F32",
        "noDataInterpretation": "esriNoDataMatchAny",
        "interpolation": "RSP_BilinearInterpolation",
        "f": "image",
    }
    print(f"fetching 3DEP export {args.width}x{height} px "
          f"(~{meters_lon / args.width:.1f} m/px) from elevation.nationalmap.gov ...")
    r = requests.get(SERVICE_URL, params=params, timeout=300)
    r.raise_for_status()
    if not r.content[:4] in (b"II*\x00", b"MM\x00*"):
        raise SystemExit(f"service did not return a TIFF (got {r.content[:80]!r})")
    tif_path.write_bytes(r.content)

    with rasterio.open(tif_path) as src:
        dem = src.read(1).astype(np.float64)
        bounds = src.bounds
        nodata = src.nodata
    if nodata is not None:
        dem = np.where(dem == nodata, np.nan, dem)
    # Row 0 of the raster is the NORTH edge; flip so lat_axis is ascending.
    dem = np.flipud(dem)
    lat_axis = np.linspace(bounds.bottom, bounds.top, dem.shape[0])
    lon_axis = np.linspace(bounds.left, bounds.right, dem.shape[1])

    np.savez_compressed(npz_path, lat_axis=lat_axis, lon_axis=lon_axis, dem=dem)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "usgs-3dep-imageserver",
        "service_url": SERVICE_URL,
        "request_params": {k: v for k, v in params.items() if k != "f"},
        "crs": "EPSG:4326",
        "vertical_datum": "NAVD88 (3DEP native)",
        "resolution_m_approx": round(meters_lon / args.width, 2),
        "elev_range_m": [float(np.nanmin(dem)), float(np.nanmax(dem))],
        "nan_fraction": float(np.isnan(dem).mean()),
        "outputs": {"geotiff": str(tif_path), "npz": str(npz_path)},
        "checksums_sha256": {
            str(tif_path): file_sha256(tif_path),
            str(npz_path): file_sha256(npz_path),
        },
    }
    manifest_path = out_dir / f"{args.name}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))

    # Sanity anchor: Mt. Washington summit is 1916.6 m (NAVD88). Warn loudly if
    # the fetched surface disagrees — wrong tile/units would poison everything.
    si = int(np.abs(lat_axis - 44.2706).argmin())
    sj = int(np.abs(lon_axis - (-71.3033)).argmin())
    window = dem[max(si - 3, 0):si + 4, max(sj - 3, 0):sj + 4]
    summit = float(np.nanmax(window))
    print(f"sanity: max elevation within ~30m of summit coords = {summit:.1f} m (expect ~1916)")
    if not (1890.0 <= summit <= 1940.0):
        print("WARNING: summit elevation check failed — inspect the export before use")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

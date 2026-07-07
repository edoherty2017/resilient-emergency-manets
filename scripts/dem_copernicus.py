#!/usr/bin/env python3
"""Fetch Copernicus GLO-30 elevation for a non-US AOI (Brenta Dolomites default).

USGS 3DEP covers only the US; for the Brenta trial extension this pulls the
ESA Copernicus DSM (30 m, open data, AWS Open Data bucket `copernicus-dem-30m`)
and caches the AOI crop in the same npz format consumed by itm_relay_links.py
and dem_transformer.py.

Note: GLO-30 is a *surface* model (DSM — includes buildings/vegetation). Above
treeline in the Brenta this is effectively bare-earth; below treeline it adds
canopy height, which is conservative (more obstruction) for link planning.

Run inside .venv:
    python scripts/dem_copernicus.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BUCKET = "https://copernicus-dem-30m.s3.amazonaws.com"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Copernicus GLO-30 DEM crop for an AOI")
    # Default AOI: Brenta Dolomites trek (Madonna di Campiglio .. Molveno)
    ap.add_argument("--lat-min", type=float, default=46.10)
    ap.add_argument("--lat-max", type=float, default=46.26)
    ap.add_argument("--lon-min", type=float, default=10.78)
    ap.add_argument("--lon-max", type=float, default=11.00)
    ap.add_argument("--out-dir", default="artifacts/dem/cache")
    ap.add_argument("--name", default="copernicus_glo30_brenta")
    args = ap.parse_args()

    import rasterio
    from rasterio.windows import from_bounds

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / f"{args.name}.npz"

    # Collect the 1-degree tiles covering the AOI
    tiles = sorted({
        (int(math.floor(lat)), int(math.floor(lon)))
        for lat in (args.lat_min, args.lat_max - 1e-9)
        for lon in (args.lon_min, args.lon_max - 1e-9)
    })

    parts = []
    tile_urls = []
    for tlat, tlon in tiles:
        name = tile_name(tlat, tlon)
        url = f"{BUCKET}/{name}/{name}.tif"
        tile_urls.append(url)
        print(f"reading {url}")
        with rasterio.open(url) as src:
            win = from_bounds(
                max(args.lon_min, tlon), max(args.lat_min, tlat),
                min(args.lon_max, tlon + 1), min(args.lat_max, tlat + 1),
                src.transform,
            )
            data = src.read(1, window=win).astype(np.float64)
            bounds = rasterio.windows.bounds(win, src.transform)
            if src.nodata is not None:
                data = np.where(data == src.nodata, np.nan, data)
            parts.append({"data": np.flipud(data), "bounds": bounds})

    if len(parts) == 1:
        dem = parts[0]["data"]
        b = parts[0]["bounds"]
        lat_axis = np.linspace(b[1], b[3], dem.shape[0])
        lon_axis = np.linspace(b[0], b[2], dem.shape[1])
    else:
        raise SystemExit(
            "multi-tile mosaic not implemented; shrink the AOI to one 1-degree tile "
            f"or extend this script (tiles needed: {tiles})"
        )

    np.savez_compressed(npz_path, lat_axis=lat_axis, lon_axis=lon_axis, dem=dem)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "copernicus-glo30-dsm",
        "license": "ESA Copernicus open data (free use with attribution)",
        "tiles": tile_urls,
        "crs": "EPSG:4326",
        "vertical_datum": "EGM2008 (Copernicus native)",
        "model_type": "DSM (surface model: includes canopy/buildings)",
        "resolution_m_approx": 30,
        "aoi": {"lat_min": args.lat_min, "lat_max": args.lat_max,
                "lon_min": args.lon_min, "lon_max": args.lon_max},
        "elev_range_m": [float(np.nanmin(dem)), float(np.nanmax(dem))],
        "nan_fraction": float(np.isnan(dem).mean()),
        "outputs": {"npz": str(npz_path)},
        "checksums_sha256": {str(npz_path): file_sha256(npz_path)},
    }
    (out_dir / f"{args.name}_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))

    # Sanity anchors: Cima Tosa (~3136 m) is the Brenta high point; Rifugio
    # Alimonta sits at ~2580 m per hut listings.
    for label, la, lo, expect in [
        ("Cima Tosa area max", 46.155, 10.872, (3000, 3180)),
        ("Rifugio Alimonta", 46.17393, 10.89201, (2500, 2650)),
    ]:
        i = int(np.abs(lat_axis - la).argmin())
        j = int(np.abs(lon_axis - lo).argmin())
        window = dem[max(i - 5, 0):i + 6, max(j - 5, 0):j + 6]
        v = float(np.nanmax(window))
        ok = expect[0] <= v <= expect[1]
        print(f"sanity {label}: {v:.0f} m (expect {expect[0]}-{expect[1]}) {'OK' if ok else 'FAIL'}")
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

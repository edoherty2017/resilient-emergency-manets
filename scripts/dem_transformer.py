#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def read_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def synthetic_dem(lat_grid: np.ndarray, lon_grid: np.ndarray) -> np.ndarray:
    """Deterministic pseudo-DEM in meters from lat/lon for reproducible dry/live flows.

    WARNING: this is fabricated sine-wave terrain, not real elevation data. It exists
    only to validate the pipeline command path. Every consumer of these features must
    treat them as synthetic until real USGS 3DEP ingestion replaces this function
    (config/airmap/dem-sources.yaml has the source config; see review P2 item 11).
    """
    lat_r = np.radians(lat_grid)
    lon_r = np.radians(lon_grid)
    ridge = 1150 + 350 * np.sin(lat_r * 17.0) * np.cos(lon_r * 19.0)
    valley = 220 * np.sin(lat_r * 41.0 + lon_r * 13.0)
    trend = 180 * (lat_grid - lat_grid.min())
    return ridge + valley + trend


def build_dem_window(df: pd.DataFrame, pad_deg: float, grid_size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lat_min = float(df["lat"].min()) - pad_deg
    lat_max = float(df["lat"].max()) + pad_deg
    lon_min = float(df["lon"].min()) - pad_deg
    lon_max = float(df["lon"].max()) + pad_deg

    lat_axis = np.linspace(lat_min, lat_max, grid_size)
    lon_axis = np.linspace(lon_min, lon_max, grid_size)
    lon_grid, lat_grid = np.meshgrid(lon_axis, lat_axis)
    dem = synthetic_dem(lat_grid, lon_grid)
    return lat_axis, lon_axis, dem


def nearest_idx(arr: np.ndarray, value: float) -> int:
    return int(np.abs(arr - value).argmin())


def slope_aspect(dem: np.ndarray, dlat_m: float, dlon_m: float) -> tuple[np.ndarray, np.ndarray]:
    gy, gx = np.gradient(dem, dlat_m, dlon_m)
    slope = np.degrees(np.arctan(np.sqrt(gx**2 + gy**2)))
    aspect = (np.degrees(np.arctan2(-gx, gy)) + 360.0) % 360.0
    return slope, aspect


def normalize_variants(values: pd.Series) -> dict[str, pd.Series]:
    arr = values.astype(float)
    vmin, vmax = float(arr.min()), float(arr.max())
    mean, std = float(arr.mean()), float(arr.std(ddof=0))
    std = std if std > 1e-9 else 1.0

    minmax = (arr - vmin) / max(vmax - vmin, 1e-9)
    z = (arr - mean) / std
    logn = np.log1p(np.clip(arr - vmin, 0, None))
    atan = np.arctan(arr / max(np.percentile(arr, 95), 1e-9))
    gamma = np.power(np.clip(minmax, 0, 1), 0.7)

    return {
        "elev_norm_minmax": minmax,
        "elev_norm_zscore": z,
        "elev_norm_log": logn,
        "elev_norm_arctan": atan,
        "elev_norm_gamma": gamma,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build DEM window + topographic route features")
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--out-dir", default="artifacts/dem")
    ap.add_argument("--pad-deg", type=float, default=0.01)
    ap.add_argument("--grid-size", type=int, default=512)
    ap.add_argument("--sample-limit", type=int, default=20000)
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--node-ids", default="meshradiohead2,meshhikernode1,meshradiohead",
                    help="Comma-separated node dirs under --ingest-root to read")
    # AOI bounds: White Mountains / Presidential Range trial area. GPS rows outside
    # these bounds are far-field mesh strangers or corrupted fixes; including them
    # once blew the DEM window up to a third of the planet (lon +114 = East Asia).
    ap.add_argument("--aoi-lat-min", type=float, default=43.8)
    ap.add_argument("--aoi-lat-max", type=float, default=44.8)
    ap.add_argument("--aoi-lon-min", type=float, default=-72.0)
    ap.add_argument("--aoi-lon-max", type=float, default=-70.8)
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_mtwashington.npz",
                    help="Real USGS 3DEP cache produced by scripts/dem_3dep.py")
    ap.add_argument("--allow-synthetic", action="store_true",
                    help="Fall back to the synthetic pseudo-DEM if the real cache is missing (dry runs only)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    cache_dir = out_dir / "cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for node_id in [s.strip() for s in args.node_ids.split(",") if s.strip()]:
        frames.append(read_jsonl(Path(args.ingest_root) / f"{node_id}/jsonl/telemetry_stream.jsonl"))
    df = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if df.empty:
        raise SystemExit("no telemetry rows found")

    if args.trial_id and "trial_id" in df.columns:
        dff = df[df["trial_id"] == args.trial_id].copy()
        if not dff.empty:
            df = dff

    df = df.dropna(subset=["lat", "lon"]).copy()
    if df.empty:
        raise SystemExit("no rows with lat/lon available for DEM window")

    in_aoi = (
        df["lat"].between(args.aoi_lat_min, args.aoi_lat_max)
        & df["lon"].between(args.aoi_lon_min, args.aoi_lon_max)
    )
    excluded_outside_aoi = int((~in_aoi).sum())
    df = df[in_aoi].copy()
    if df.empty:
        raise SystemExit("no rows inside AOI bounds for DEM window")

    if len(df) > args.sample_limit:
        df = df.iloc[-args.sample_limit :].copy()

    dem_npz = Path(args.dem_npz)
    if dem_npz.exists():
        cached = np.load(dem_npz)
        lat_axis, lon_axis, dem = cached["lat_axis"], cached["lon_axis"], cached["dem"]
        dem_source = "usgs-3dep-imageserver"
        # Points outside the real DEM footprint get no terrain features.
        in_dem = (
            df["lat"].between(float(lat_axis.min()), float(lat_axis.max()))
            & df["lon"].between(float(lon_axis.min()), float(lon_axis.max()))
        )
        dropped_outside_dem = int((~in_dem).sum())
        df = df[in_dem].copy()
        if df.empty:
            raise SystemExit("no rows inside the real DEM footprint")
        if dropped_outside_dem:
            print(f"[dem] dropped {dropped_outside_dem} rows outside the 3DEP footprint")
    elif args.allow_synthetic:
        lat_axis, lon_axis, dem = build_dem_window(df, args.pad_deg, args.grid_size)
        dem_source = "synthetic-dem-deterministic"
    else:
        raise SystemExit(
            f"real DEM cache not found at {dem_npz}; run `python scripts/dem_3dep.py` "
            "first, or pass --allow-synthetic for a pipeline dry run"
        )

    lat_center = float((lat_axis.min() + lat_axis.max()) / 2)
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * max(math.cos(math.radians(lat_center)), 1e-6)
    dlat_m = float((lat_axis[1] - lat_axis[0]) * meters_per_deg_lat)
    dlon_m = float((lon_axis[1] - lon_axis[0]) * meters_per_deg_lon)

    slope_grid, aspect_grid = slope_aspect(dem, dlat_m, dlon_m)

    # Route extraction: map each row to nearest DEM cell
    lat_idx = df["lat"].apply(lambda v: nearest_idx(lat_axis, float(v))).astype(int)
    lon_idx = df["lon"].apply(lambda v: nearest_idx(lon_axis, float(v))).astype(int)

    features = df[[c for c in ["timestamp_utc", "trial_id", "node_id", "head_id", "lat", "lon", "rssi_dbm", "snr_db"] if c in df.columns]].copy()
    features["dem_elev_m"] = [float(dem[i, j]) for i, j in zip(lat_idx, lon_idx)]
    features["dem_slope_deg"] = [float(slope_grid[i, j]) for i, j in zip(lat_idx, lon_idx)]
    features["dem_aspect_deg"] = [float(aspect_grid[i, j]) for i, j in zip(lat_idx, lon_idx)]
    features["dem_cell_i"] = lat_idx.to_numpy()
    features["dem_cell_j"] = lon_idx.to_numpy()

    features = features.sort_values("timestamp_utc") if "timestamp_utc" in features.columns else features
    features["dem_elev_delta_m"] = features["dem_elev_m"].diff().fillna(0.0)

    norm = normalize_variants(features["dem_elev_m"])
    for k, v in norm.items():
        features[k] = v

    csv_path = out_dir / "route_topography_features.csv"
    parquet_path = out_dir / "route_topography_features.parquet"
    features.to_csv(csv_path, index=False)
    features.to_parquet(parquet_path, index=False)

    tile_id = hashlib.sha256(
        f"{float(lat_axis.min()):.6f},{float(lat_axis.max()):.6f},{float(lon_axis.min()):.6f},{float(lon_axis.max()):.6f},{args.grid_size}".encode()
    ).hexdigest()[:16]
    tile_path = cache_dir / f"dem_tile_{tile_id}.npz"
    np.savez_compressed(tile_path, lat_axis=lat_axis, lon_axis=lon_axis, dem=dem)

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "recipe_version": "dem-topography-v3",
        "source": dem_source,
        "trial_id": args.trial_id,
        "aoi_bounds": {
            "lat_min": args.aoi_lat_min,
            "lat_max": args.aoi_lat_max,
            "lon_min": args.aoi_lon_min,
            "lon_max": args.aoi_lon_max,
        },
        "rows_excluded_outside_aoi": excluded_outside_aoi,
        **(
            {
                "WARNING": (
                    "SYNTHETIC pseudo-DEM (sine-wave terrain) for pipeline validation "
                    "only. NOT real elevation data — do not cite any derived feature "
                    "as terrain analysis."
                )
            }
            if dem_source == "synthetic-dem-deterministic"
            else {}
        ),
        "window": {
            "lat_min": float(lat_axis.min()),
            "lat_max": float(lat_axis.max()),
            "lon_min": float(lon_axis.min()),
            "lon_max": float(lon_axis.max()),
            "grid_size": int(args.grid_size),
            "pad_deg": float(args.pad_deg),
            "crs": "EPSG:4326",
            "vertical_datum": "relative-meters",
        },
        "normalization_variants": ["minmax", "zscore", "log", "arctan", "gamma"],
        "outputs": {
            "tile_cache": str(tile_path),
            "route_csv": str(csv_path),
            "route_parquet": str(parquet_path),
        },
        "checksums_sha256": {
            str(tile_path): file_sha256(tile_path),
            str(csv_path): file_sha256(csv_path),
            str(parquet_path): file_sha256(parquet_path),
        },
    }

    manifest_path = out_dir / "feature_provenance_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "rows": int(len(features)),
        "tile_id": tile_id,
        "manifest": str(manifest_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

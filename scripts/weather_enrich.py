#!/usr/bin/env python3
"""Attach field-log or pinned reanalysis weather tags to telemetry.

Replaces the synthetic weather defaults that previously stamped every row with a
single tag (see docs/academic-rigor-review-2026-06-12.md). Fetches hourly
historical gridded estimates for the trial AOI and date range, maps each observation to its
nearest hour, and derives a per-row `weather_tag` used by the stratified metrics.
Open-Meteo/ERA5 values are reanalysis estimates, not measurements at the radio
or Mt. Washington Observatory. A contemporaneous field log takes precedence.

Open-Meteo archive (https://archive-api.open-meteo.com) is free and key-less.
For offline use, --field-log accepts a CSV of manually recorded conditions
(start_utc,end_utc,weather_tag) that takes precedence over the API.

Usage:
  python3 scripts/weather_enrich.py \
      --input artifacts/airmap/live_trial/predictions_postcalibration.parquet \
      --output artifacts/weather/telemetry_weather_enriched.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# WMO weather interpretation codes -> coarse tag for stratification.
WMO_TAG = {
    range(0, 1): "clear", range(1, 4): "cloudy", range(45, 49): "fog",
    range(51, 68): "rain", range(71, 78): "snow", range(80, 83): "rain",
    range(85, 87): "snow", range(95, 100): "thunderstorm",
}


def wmo_to_tag(code) -> str:
    if pd.isna(code):
        return "unknown"
    c = int(code)
    for rng, tag in WMO_TAG.items():
        if c in rng:
            return tag
    return "cloudy"


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in (".csv",):
        return pd.read_csv(path)
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return pd.DataFrame(rows)


def fetch_hourly(lat: float, lon: float, elevation_m: float, start: str, end: str,
                 model: str) -> tuple[pd.DataFrame, dict]:
    import requests
    params = {
        "latitude": round(lat, 3), "longitude": round(lon, 3),
        "elevation": round(elevation_m, 1),
        "start_date": start, "end_date": end,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,visibility,weather_code",
        "timezone": "UTC",
        "models": model,
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    h = payload["hourly"]
    required = ("temperature_2m", "precipitation", "wind_speed_10m", "weather_code")
    missing = {name: sum(value is None for value in h[name]) for name in required}
    missing = {name: count for name, count in missing.items() if count}
    if missing:
        raise ValueError(
            f"model {model!r} returned missing required hourly values: {missing}"
        )
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df, {
        "kind": "reanalysis" if model != "best_match" else "model_blend",
        "provider": "Open-Meteo Historical Weather API",
        "model_requested": model,
        "request_url": r.url,
        "response_sha256": hashlib.sha256(r.content).hexdigest(),
        "api_elevation_m": payload.get("elevation"),
        "hourly_units": payload.get("hourly_units"),
        "not_station_measurements": True,
    }


def derive_tag(row) -> str:
    base = wmo_to_tag(row.get("weather_code"))
    wind = row.get("wind_speed_10m")
    vis = row.get("visibility")
    # Wind/visibility overrides for SAR-relevant stratification.
    if base in ("clear", "cloudy") and wind is not None and not pd.isna(wind) and wind >= 12 * 3.6:
        return "windy"  # wind_speed_10m is km/h from the archive
    if base == "clear" and vis is not None and not pd.isna(vis) and vis < 1000:
        return "fog"
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrich telemetry with field-log/reanalysis tags")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="artifacts/weather/telemetry_weather_enriched.parquet")
    ap.add_argument("--field-log", default=None, help="CSV start_utc,end_utc,weather_tag (offline override)")
    ap.add_argument("--lat-col", default="lat")
    ap.add_argument("--lon-col", default="lon")
    ap.add_argument("--elev-col", default="elev_m")
    ap.add_argument("--model", default="era5",
                    choices=["era5", "era5_land", "best_match"])
    args = ap.parse_args()

    df = load_table(Path(args.input))
    if df.empty:
        raise SystemExit("empty input")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp_utc"]).copy()

    source = None
    if args.field_log:
        log = pd.read_csv(args.field_log)
        log["start_utc"] = pd.to_datetime(log["start_utc"], utc=True)
        log["end_utc"] = pd.to_datetime(log["end_utc"], utc=True)
        df["weather_tag"] = "unknown"
        for _, seg in log.iterrows():
            m = (df["timestamp_utc"] >= seg["start_utc"]) & (df["timestamp_utc"] <= seg["end_utc"])
            df.loc[m, "weather_tag"] = seg["weather_tag"]
        source = f"field_log:{args.field_log}"
        df["weather_source"] = source
    else:
        lat = pd.to_numeric(
            df[args.lat_col] if args.lat_col in df else pd.Series(np.nan, index=df.index),
            errors="coerce",
        )
        lon = pd.to_numeric(
            df[args.lon_col] if args.lon_col in df else pd.Series(np.nan, index=df.index),
            errors="coerce",
        )
        if lat.notna().sum() == 0:
            raise SystemExit("no lat/lon to locate weather; provide --field-log instead")
        clat, clon = float(lat.median()), float(lon.median())
        elev = pd.to_numeric(
            df[args.elev_col] if args.elev_col in df else pd.Series(np.nan, index=df.index),
            errors="coerce",
        )
        celev = float(elev.median()) if elev.notna().any() else 1917.0
        start = df["timestamp_utc"].min().strftime("%Y-%m-%d")
        end = df["timestamp_utc"].max().strftime("%Y-%m-%d")
        print(f"fetching Open-Meteo {args.model} for "
              f"({clat:.3f},{clon:.3f},{celev:.0f} m) {start}..{end}")
        wx, source = fetch_hourly(clat, clon, celev, start, end, args.model)
        wx["weather_tag"] = wx.apply(derive_tag, axis=1)
        merged = pd.merge_asof(
            df.sort_values("timestamp_utc"),
            wx[["time", "weather_tag", "temperature_2m", "precipitation",
                "wind_speed_10m", "visibility", "weather_code"]].sort_values("time"),
            left_on="timestamp_utc", right_on="time", direction="nearest",
            tolerance=pd.Timedelta(minutes=60),
        )
        df = merged
        df["weather_tag"] = df["weather_tag"].fillna("unknown")
        df["weather_source"] = (
            f"open_meteo:{args.model}:reanalysis_estimate"
            if args.model != "best_match" else "open_meteo:best_match:model_blend"
        )
        source["requested_location"] = {
            "lat": clat, "lon": clon, "elevation_m": celev,
        }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)

    counts = df["weather_tag"].value_counts(dropna=False).to_dict()
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "rows": int(len(df)),
        "weather_tag_counts": {str(k): int(v) for k, v in counts.items()},
        "output": str(out_path),
    }
    (out_path.parent / "weather_enrich_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

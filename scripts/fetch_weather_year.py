#!/usr/bin/env python3
"""Fetch a pinned reanalysis year from the Open-Meteo historical API.

The request names a model explicitly. Open-Meteo's default "Best Match" may
blend/reselect models over time and must not be labelled ERA5. The default here
is ERA5 reanalysis. ERA5-Land does not expose every requested variable through
this endpoint and is rejected if values are missing. Reanalysis is a
model/data-assimilation product, not a
measurement at the Mt. Washington Observatory.

Variables:
  shortwave_radiation_sum  — reanalysis estimate of surface solar energy
                             (MJ/m²/day). Dividing by this project's Haurwitz
                             clear-sky estimate yields a derived daily kt proxy.
  snowfall_sum             — daily snowfall (cm). Fresh snow blankets the
                             panels; the pyramid's steep faces shed it, so:
                             snow_factor = 0.25 the day of ≥1 cm snowfall,
                             0.6 the day after ≥5 cm, else 1.0.
  cloud_cover_mean, temperature_2m_mean — kept for reference/ML features.

Output: artifacts/sim/weather_year.json {start_date, location, days: [...]}.

Run: .venv/bin/python scripts/fetch_weather_year.py --start 2025-07-01 --end 2026-06-30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import solar_model  # noqa: E402

API = "https://archive-api.open-meteo.com/v1/archive"


def archive_url(*, lat: float, lon: float, elevation_m: float, start: str,
                end: str, model: str) -> str:
    """Build an explicit, reviewable Open-Meteo request URL."""

    q = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "elevation": elevation_m,
        "start_date": start,
        "end_date": end,
        "daily": "shortwave_radiation_sum,snowfall_sum,cloud_cover_mean,temperature_2m_mean",
        "timezone": "UTC",
        "models": model,
    })
    return f"{API}?{q}"


def clear_sky_day_mj(lat: float, lon: float, date: datetime) -> float:
    """Clear-sky daily horizontal total (MJ/m²) from our Haurwitz model."""
    wh = solar_model.daily_solar_wh(lat, lon, date, kt=1.0,
                                    horizon=np.zeros(8),
                                    solar_cfg={"panel_w_nominal": 1000.0,
                                               "system_efficiency": 1.0},
                                    step_s=900)
    return wh * 3600.0 / 1e6  # Wh/m² -> J/m² -> MJ/m²


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a pinned reanalysis weather year")
    ap.add_argument("--lat", type=float, default=44.2706, help="Mt. Washington area")
    ap.add_argument("--lon", type=float, default=-71.3033)
    ap.add_argument("--elevation-m", type=float, default=1917.0,
                    help="Requested site elevation for API downscaling metadata")
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--model", default="era5",
                    choices=["era5_land", "era5", "best_match"],
                    help="Explicit API model; best_match is not an ERA5-only dataset")
    ap.add_argument("--out", default="artifacts/sim/weather_year.json")
    args = ap.parse_args()

    url = archive_url(lat=args.lat, lon=args.lon, elevation_m=args.elevation_m,
                      start=args.start, end=args.end, model=args.model)
    with urllib.request.urlopen(url, timeout=60) as r:
        raw = r.read()
    data = json.loads(raw)
    d = data["daily"]
    dates = d["time"]
    sw = d["shortwave_radiation_sum"]
    snow = d["snowfall_sum"]
    cloud = d["cloud_cover_mean"]
    temp = d["temperature_2m_mean"]

    required = {
        "shortwave_radiation_sum": sw,
        "snowfall_sum": snow,
        "cloud_cover_mean": cloud,
        "temperature_2m_mean": temp,
    }
    missing = {name: sum(value is None for value in values)
               for name, values in required.items()}
    missing = {name: count for name, count in missing.items() if count}
    if missing:
        raise SystemExit(
            f"model {args.model!r} returned missing required daily values: {missing}; "
            "refusing to turn missing data into zero-weather simulation input"
        )

    days = []
    prev_snow = 0.0
    for i, ds in enumerate(dates):
        date = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
        cs = clear_sky_day_mj(args.lat, args.lon, date)
        sw_i = sw[i]
        kt = float(np.clip(sw_i / cs, 0.03, 0.95)) if cs > 0 else 0.03
        sn = snow[i]
        if sn >= 1.0:
            sf = 0.25
        elif prev_snow >= 5.0:
            sf = 0.6
        else:
            sf = 1.0
        prev_snow = sn
        days.append({"date": ds, "kt": round(kt, 3),
                     "snowfall_cm": round(sn, 1), "snow_factor": sf,
                     "cloud_pct": cloud[i], "temp_c": temp[i]})

    out = {"source": "Open-Meteo Historical Weather API",
           "source_kind": "reanalysis" if args.model != "best_match" else "model_blend",
           "model_requested": args.model,
           "not_station_measurements": True,
           "request_url": url,
           "api_response_sha256": hashlib.sha256(raw).hexdigest(),
           "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
           "location": {"lat": args.lat, "lon": args.lon,
                        "requested_elevation_m": args.elevation_m,
                        "api_elevation_m": data.get("elevation")},
           "start_date": args.start, "end_date": args.end,
           "kt_definition": "shortwave_radiation_sum / project Haurwitz clear-sky estimate; clipped to [0.03, 0.95]",
           "snow_factor_definition": "unvalidated engineering heuristic: 0.25 on >=1 cm snowfall day; 0.6 after >=5 cm; otherwise 1.0",
           "n_days": len(days), "days": days}
    p = ROOT / args.out
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))

    kts = [x["kt"] for x in days]
    snow_days = sum(1 for x in days if x["snowfall_cm"] >= 1.0)
    print(f"{len(days)} days {args.start}..{args.end}  "
          f"kt mean {np.mean(kts):.2f} p10 {np.quantile(kts,0.1):.2f} "
          f"p90 {np.quantile(kts,0.9):.2f}  snow days (≥1cm): {snow_days}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

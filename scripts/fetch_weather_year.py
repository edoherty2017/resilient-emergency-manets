#!/usr/bin/env python3
"""Fetch a real year of daily weather for the sim from the Open-Meteo archive.

Variables (ERA5-blended reanalysis, same source as weather_enrich.py):
  shortwave_radiation_sum  — actual solar energy that reached the ground
                             (MJ/m²/day). Divided by our clear-sky model's
                             same-day total this gives a *measured* daily
                             clearness index kt: real cloud cover, not a
                             statistical guess.
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


def clear_sky_day_mj(lat: float, lon: float, date: datetime) -> float:
    """Clear-sky daily horizontal total (MJ/m²) from our Haurwitz model."""
    wh = solar_model.daily_solar_wh(lat, lon, date, kt=1.0,
                                    horizon=np.zeros(8),
                                    solar_cfg={"panel_w_nominal": 1000.0,
                                               "system_efficiency": 1.0},
                                    step_s=900)
    return wh * 3600.0 / 1e6  # Wh/m² -> J/m² -> MJ/m²


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a real weather year (Open-Meteo archive)")
    ap.add_argument("--lat", type=float, default=44.2706, help="Mt. Washington area")
    ap.add_argument("--lon", type=float, default=-71.3033)
    ap.add_argument("--start", default="2025-07-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--out", default="artifacts/sim/weather_year.json")
    args = ap.parse_args()

    q = urllib.parse.urlencode({
        "latitude": args.lat, "longitude": args.lon,
        "start_date": args.start, "end_date": args.end,
        "daily": "shortwave_radiation_sum,snowfall_sum,cloud_cover_mean,temperature_2m_mean",
        "timezone": "UTC",
    })
    with urllib.request.urlopen(f"{API}?{q}", timeout=60) as r:
        data = json.loads(r.read())
    d = data["daily"]
    dates = d["time"]
    sw = d["shortwave_radiation_sum"]
    snow = d["snowfall_sum"]
    cloud = d["cloud_cover_mean"]
    temp = d["temperature_2m_mean"]

    days = []
    prev_snow = 0.0
    for i, ds in enumerate(dates):
        date = datetime.fromisoformat(ds).replace(tzinfo=timezone.utc)
        cs = clear_sky_day_mj(args.lat, args.lon, date)
        sw_i = sw[i] if sw[i] is not None else 0.0
        kt = float(np.clip(sw_i / cs, 0.03, 0.95)) if cs > 0 else 0.03
        sn = snow[i] or 0.0
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

    out = {"source": "open-meteo.com ERA5 archive",
           "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
           "location": {"lat": args.lat, "lon": args.lon},
           "start_date": args.start, "n_days": len(days), "days": days}
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

#!/usr/bin/env python3
"""Per-node solar charge model over real terrain.

Expected daily solar energy for a node at (lat, lon) on the DEM:
  1. Sun position (NOAA approximation: declination + equation of time).
  2. Clear-sky GHI via Haurwitz: 1098*cos(z)*exp(-0.057/cos(z)) W/m^2.
  3. Terrain shading: horizon elevation angle at N azimuths, ray-marched over
     the DEM — direct beam is blocked whenever solar elevation is below the
     horizon mask (this is why ravine nodes charge far less than ridge nodes).
  4. Daily clearness index kt (Beta-distributed around the monthly mean from
     config/sim/wmnf_sim.yaml) scales clear-sky down for cloud; when shaded,
     a diffuse floor (30% of kt-scaled GHI) still reaches the panel.
  5. Panel: P = panel_w_nominal * (GHI_eff / 1000) * system_efficiency.

CLI demo: .venv/bin/python scripts/solar_model.py --date 2026-07-10
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, haversine_m  # noqa: E402

def diffuse_fraction(kt: float) -> float:
    """Diffuse share of GHI vs clearness (Erbs-style, linearized): overcast
    days are nearly all diffuse, clear days ~15%."""
    return float(np.clip(1.02 - 1.1 * kt, 0.15, 0.98))


def solar_position(lat_deg: float, lon_deg: float, when_utc: datetime):
    """NOAA-approximation solar elevation and azimuth (degrees)."""
    doy = when_utc.timetuple().tm_yday
    frac_year = 2.0 * math.pi / 365.0 * (doy - 1 + (when_utc.hour - 12) / 24.0)
    decl = (0.006918 - 0.399912 * math.cos(frac_year) + 0.070257 * math.sin(frac_year)
            - 0.006758 * math.cos(2 * frac_year) + 0.000907 * math.sin(2 * frac_year)
            - 0.002697 * math.cos(3 * frac_year) + 0.00148 * math.sin(3 * frac_year))
    eqtime_min = 229.18 * (0.000075 + 0.001868 * math.cos(frac_year)
                           - 0.032077 * math.sin(frac_year)
                           - 0.014615 * math.cos(2 * frac_year)
                           - 0.040849 * math.sin(2 * frac_year))
    tst_min = (when_utc.hour * 60 + when_utc.minute + when_utc.second / 60.0
               + eqtime_min + 4.0 * lon_deg)
    ha_deg = tst_min / 4.0 - 180.0
    lat = math.radians(lat_deg)
    ha = math.radians(ha_deg)
    cos_z = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    cos_z = max(-1.0, min(1.0, cos_z))
    elev = 90.0 - math.degrees(math.acos(cos_z))
    az = math.degrees(math.atan2(
        -math.sin(ha),
        math.tan(decl) * math.cos(lat) - math.sin(lat) * math.cos(ha),
    )) % 360.0
    return elev, az


def clear_sky_ghi(elev_deg: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance (W/m^2)."""
    if elev_deg <= 0:
        return 0.0
    cos_z = math.cos(math.radians(90.0 - elev_deg))
    return 1098.0 * cos_z * math.exp(-0.057 / cos_z)


def horizon_mask(dem: Dem, lat: float, lon: float, n_azimuths: int = 48,
                 max_range_m: float = 12000.0, step_m: float = 60.0) -> np.ndarray:
    """Horizon elevation angle (deg) at each azimuth, ray-marched over the DEM.

    Rays are clipped to the DEM extent; beyond it the terrain is assumed not
    to rise above the last in-bounds sample (fine for this AOI: the Presidentials
    are the local high ground).
    """
    z0 = float(dem.sample(np.array([lat]), np.array([lon]))[0]) + 1.0  # panel ~1 m up
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat))
    dists = np.arange(step_m, max_range_m + step_m, step_m)
    angles = np.zeros(n_azimuths)
    for k in range(n_azimuths):
        az = math.radians(k * 360.0 / n_azimuths)
        lats = lat + (dists * math.cos(az)) / m_per_deg_lat
        lons = lon + (dists * math.sin(az)) / m_per_deg_lon
        ok = ((lats >= dem.lat.min()) & (lats <= dem.lat.max())
              & (lons >= dem.lon.min()) & (lons <= dem.lon.max()))
        if not ok.any():
            continue
        z = dem.sample(lats[ok], lons[ok])
        angles[k] = max(0.0, float(np.max(np.degrees(np.arctan2(z - z0, dists[ok])))))
    return angles


def sample_daily_kt(month: int, rng: np.random.Generator, solar_cfg: dict) -> float:
    mean = float(solar_cfg["monthly_kt_mean"][month - 1])
    c = float(solar_cfg["kt_daily_beta_concentration"])
    return float(rng.beta(mean * c, (1.0 - mean) * c))


def solar_power_w(lat: float, lon: float, when_utc: datetime, kt: float,
                  horizon: np.ndarray, solar_cfg: dict,
                  site_solar: dict | None = None) -> float:
    """Instantaneous panel output in watts.

    Physics: GHI = clear-sky × kt, split into direct beam + diffuse sky
    (diffuse_fraction). Terrain horizon blocks only the beam (sky stays).
    Optional site_solar dict models the mounting:
      canopy_tau  — forest canopy transmittance for a node hoisted into the
                    mid-canopy (~16 ft on a branch): both beam and sky light
                    are filtered by leaves above it. Northern-hardwood
                    full-leaf mid-canopy ≈ 0.10–0.25.
      geometry    — "flat" (default) or "pyramid": four faces at tilt_deg
                    facing N/E/S/W (quarter of rated W each). The beam lands
                    on the best-facing slab; every slab sees sky diffuse
                    weighted by (1+cosβ)/2.
    """
    elev, az = solar_position(lat, lon, when_utc)
    ghi = clear_sky_ghi(elev) * kt
    if ghi <= 0.0:
        return 0.0
    fd = diffuse_fraction(kt)
    diffuse_h = ghi * fd
    direct_h = ghi - diffuse_h
    idx = int(round(az / 360.0 * len(horizon))) % len(horizon)
    if elev < horizon[idx]:
        direct_h = 0.0                       # ridge blocks the beam only
    ss = site_solar or {}
    tau = float(ss.get("canopy_tau", 1.0))
    direct_h *= tau
    diffuse_h *= tau
    if ss.get("geometry") == "pyramid":
        beta = math.radians(float(ss.get("tilt_deg", 35.0)))
        sin_e = math.sin(math.radians(max(elev, 5.0)))
        dni = direct_h / sin_e
        plane = 0.0
        for face_az in (0.0, 90.0, 180.0, 270.0):
            cos_inc = (math.sin(math.radians(elev)) * math.cos(beta)
                       + math.cos(math.radians(elev)) * math.sin(beta)
                       * math.cos(math.radians(az - face_az)))
            plane += 0.25 * (dni * max(cos_inc, 0.0)
                             + diffuse_h * (1.0 + math.cos(beta)) / 2.0)
    else:
        plane = direct_h + diffuse_h
    return (float(solar_cfg["panel_w_nominal"]) * (plane / 1000.0)
            * float(solar_cfg["system_efficiency"]))


def daily_solar_wh(lat: float, lon: float, date_utc: datetime, kt: float,
                   horizon: np.ndarray, solar_cfg: dict, step_s: int = 300,
                   site_solar: dict | None = None) -> float:
    day0 = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    total_w = 0.0
    n = 86400 // step_s
    for i in range(n):
        total_w += solar_power_w(lat, lon, day0 + timedelta(seconds=i * step_s),
                                 kt, horizon, solar_cfg, site_solar)
    return total_w * step_s / 3600.0


def main() -> int:
    import yaml
    ap = argparse.ArgumentParser(description="Daily solar-gain demo per topology site")
    ap.add_argument("--config", default="config/sim/wmnf_sim.yaml")
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_presidentials_wide.npz")
    ap.add_argument("--date", default="2026-07-10")
    ap.add_argument("--kt", type=float, default=None, help="Override clearness index")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text())
    dem = Dem(ROOT / args.dem_npz)
    topo = json.loads((ROOT / args.topology).read_text())
    date = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    rng = np.random.default_rng(cfg["sim"]["seed"])
    kt = args.kt if args.kt is not None else sample_daily_kt(date.month, rng, cfg["solar"])

    print(f"date {args.date}  kt={kt:.2f}  panel {cfg['solar']['panel_w_nominal']} W")
    for name, s in topo["sites"].items():
        hz = horizon_mask(dem, s["lat"], s["lon"],
                          cfg["solar"]["horizon_azimuths"], cfg["solar"]["horizon_max_range_m"])
        wh = daily_solar_wh(s["lat"], s["lon"], date, kt, hz, cfg["solar"])
        print(f"  {name:22s} elev {s['elev_m']:7.1f} m  horizon mean {hz.mean():5.2f}° "
              f"max {hz.max():5.2f}°  -> {wh:6.2f} Wh/day")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

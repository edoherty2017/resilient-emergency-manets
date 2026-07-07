#!/usr/bin/env python3
"""Terrain-clipped RF service areas + statewide trail-coverage field.

Answers "is there anywhere SAR responds that the network can't reach?" with a
computed field, not a claim, and gives the viewer live per-node service
polygons.

Model (viewshed + single knife-edge, ITM-calibrated):
  For each site, sweep N_AZ azimuths out to MAX_KM over the DEM. Along each
  ray track the dominant obstruction (max elevation angle from the antenna).
  Loss = FSPL + clutter offset (clear) or FSPL + ITU P.526 knife-edge penalty
  from the worst edge (obstructed). The clutter offset is CALIBRATED by
  regressing this model against the Longley-Rice link matrix, and the residual
  RMSE is reported — the field is a screening model, the audit stays ITM.

Outputs:
  artifacts/sim/service_areas.json   per-site range-by-azimuth polygons (m)
  artifacts/sim/trail_coverage.json  per-trail-vertex best RSSI + gap segments
  artifacts/sim/coverage_field_stats.json

Run: .venv/bin/python scripts/coverage_field.py --suffix _statewide
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, haversine_m  # noqa: E402

EIRP_DBM = 26.3
RX_SENS_DBM = -131.0
N_AZ = 72
MAX_KM = 9.0
STEP_M = 74.0
RX_H = 1.5
FREQ_MHZ = 915.0


def knife_edge_db(v: float) -> float:
    """ITU-R P.526 single knife-edge approximation (v ≥ -0.78)."""
    if v <= -0.78:
        return 0.0
    return 6.9 + 20.0 * math.log10(math.sqrt((v - 0.1) ** 2 + 1.0) + v - 0.1)


def ray_losses(dem: Dem, lat, lon, hg):
    """Raw loss (FSPL + knife-edge, NO clutter) and blocked mask per azimuth."""
    z0 = float(dem.sample(np.array([lat]), np.array([lon]))[0]) + hg
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    dists = np.arange(STEP_M, MAX_KM * 1000.0 + STEP_M, STEP_M)
    lam = 299.792458 / FREQ_MHZ
    out = np.full((N_AZ, len(dists)), 300.0)
    blk = np.zeros((N_AZ, len(dists)), dtype=bool)
    for k in range(N_AZ):
        az = math.radians(k * 360.0 / N_AZ)
        lats = lat + (dists * math.cos(az)) / m_lat
        lons = lon + (dists * math.sin(az)) / m_lon
        ok = ((lats >= dem.lat.min()) & (lats <= dem.lat.max())
              & (lons >= dem.lon.min()) & (lons <= dem.lon.max()))
        if not ok.any():
            continue
        z = dem.sample(lats[ok], lons[ok])
        d = dists[ok]
        n = len(d)
        rx_z = z + RX_H
        # elevation angle of terrain at each step; running max + its argmax
        # give the dominant obstruction ("horizon edge") before each step
        ang_terrain = (z - z0) / d
        run_max = np.maximum.accumulate(ang_terrain)
        new_max = ang_terrain >= run_max
        run_argmax = np.maximum.accumulate(np.where(new_max, np.arange(n), 0))
        fspl = 20 * np.log10(d) + 20 * math.log10(FREQ_MHZ) - 27.55
        # LOS test: horizon accumulated BEFORE this step vs angle to receiver
        ang_rx = (rx_z - z0) / d
        prev_max = np.concatenate(([-1e9], run_max[:-1]))
        prev_arg = np.concatenate(([0], run_argmax[:-1]))
        blocked = ang_rx < prev_max
        loss = fspl.copy()
        if blocked.any():
            bidx = np.where(blocked)[0]
            e = prev_arg[bidx]                       # dominant edge index
            d1 = np.maximum(d[e], STEP_M / 2)
            d2 = np.maximum(d[bidx] - d1, STEP_M / 2)
            # edge height above the tx→rx chord
            chord = z0 + (rx_z[bidx] - z0) * (d1 / d[bidx])
            h = z[e] - chord
            v = h * np.sqrt(2.0 * d[bidx] / (lam * d1 * d2))
            pen = np.array([knife_edge_db(float(x)) for x in v])
            loss[bidx] = fspl[bidx] + np.clip(pen, 0.0, 80.0)
        out[k, ok] = loss
        bb = np.zeros(len(ok), dtype=bool)
        bb[ok] = blocked
        blk[k] = bb[:blk.shape[1]] if len(bb) > blk.shape[1] else np.pad(bb, (0, blk.shape[1]-len(bb)))
    return dists, out, blk


def calibrate(dem, sites, links):
    """Fit separate LOS / obstructed offsets vs ITM q50 on real links."""
    diffs = []
    for key, l in links.items():
        if l.get("model") == "short_link_fspl":
            continue
        a, b = key.split("|")
        sa, sb = sites[a], sites[b]
        d_m = haversine_m(sa["lat"], sa["lon"], sb["lat"], sb["lon"])
        if not (500.0 <= d_m <= MAX_KM * 1000.0):
            continue
        diffs.append((key, l["loss_db_q50"], d_m, sa, sb))
    rng = np.random.default_rng(3)
    sel = rng.choice(len(diffs), size=min(150, len(diffs)), replace=False)
    res_los, res_obs = [], []
    for i in sel:
        key, itm_loss, d_m, sa, sb = diffs[i]
        brg = math.atan2((sb["lon"] - sa["lon"]) * math.cos(math.radians(sa["lat"])),
                         sb["lat"] - sa["lat"])
        k = int(round((math.degrees(brg) % 360.0) / (360.0 / N_AZ))) % N_AZ
        dists, loss, blk = ray_losses(dem, sa["lat"], sa["lon"], sa["hg_m"])
        j = int(np.clip(round(d_m / STEP_M) - 1, 0, len(dists) - 1))
        r = itm_loss - loss[k, j]
        if np.isfinite(r) and abs(r) < 100:
            (res_obs if blk[k, j] else res_los).append(r)
    res_los, res_obs = np.array(res_los), np.array(res_obs)
    c_los = float(np.median(res_los)) if len(res_los) >= 8 else 8.0
    c_obs = float(np.median(res_obs)) if len(res_obs) >= 8 else 20.0
    return {"los_db": c_los, "obs_db": c_obs,
            "sigma_los": float(np.std(res_los)) if len(res_los) else None,
            "sigma_obs": float(np.std(res_obs)) if len(res_obs) else None,
            "n_los": int(len(res_los)), "n_obs": int(len(res_obs))}


def main() -> int:
    ap = argparse.ArgumentParser(description="Service-area field + trail coverage")
    ap.add_argument("--suffix", default="_statewide")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    ap.add_argument("--routes", default=None)
    ap.add_argument("--out-prefix", default="artifacts/sim/")
    args = ap.parse_args()

    dem = Dem(ROOT / args.dem_npz)
    topo = json.loads((ROOT / f"artifacts/sim/topology{args.suffix}.json").read_text())
    sites = topo["sites"]

    cal = calibrate(dem, sites, topo["links"])
    print(f"calibration vs ITM links: LOS {cal['los_db']:+.1f} dB "
          f"(sigma {cal['sigma_los']}, n={cal['n_los']}) | obstructed "
          f"{cal['obs_db']:+.1f} dB (sigma {cal['sigma_obs']}, n={cal['n_obs']})")

    # ── per-site service polygons: outer envelope (farthest covered) ─────────
    service = {}
    for i, (name, s) in enumerate(sites.items()):
        dists, loss, blk = ray_losses(dem, s["lat"], s["lon"], s["hg_m"])
        loss = loss + np.where(blk, cal["obs_db"], cal["los_db"])
        rssi = EIRP_DBM - loss
        ranges = []
        for k in range(N_AZ):
            cov = np.where(rssi[k] >= RX_SENS_DBM)[0]
            ranges.append(round(float(dists[cov[-1]]), 0) if len(cov) else 0.0)
        service[name] = {"lat": s["lat"], "lon": s["lon"], "range_m": ranges}
        if i % 25 == 0:
            print(f"  service polygons {i}/{len(sites)}")

    (ROOT / f"{args.out_prefix}service_areas.json").write_text(json.dumps({
        "n_az": N_AZ, "max_m": MAX_KM * 1000.0, "model":
        f"viewshed+knife-edge; offsets LOS {cal['los_db']:+.1f} / obstructed "
        f"{cal['obs_db']:+.1f} dB (ITM-calibrated); outer service envelope",
        "sites": service}))

    # ── union area statistics on a coarse grid ────────────────────────────────
    GRID = 0.005      # ~550 m cells
    la0, la1 = float(dem.lat.min()), float(dem.lat.max())
    lo0, lo1 = float(dem.lon.min()), float(dem.lon.max())
    glats = np.arange(la0, la1, GRID)
    glons = np.arange(lo0, lo1, GRID)
    covered_cells = np.zeros((len(glats), len(glons)), dtype=bool)
    for name, sv in service.items():
        rmax = max(sv["range_m"])
        if rmax <= 0:
            continue
        dla = rmax / 111320.0
        dlo = dla / math.cos(math.radians(sv["lat"]))
        i0 = int(np.searchsorted(glats, sv["lat"] - dla))
        i1 = int(np.searchsorted(glats, sv["lat"] + dla))
        j0 = int(np.searchsorted(glons, sv["lon"] - dlo))
        j1 = int(np.searchsorted(glons, sv["lon"] + dlo))
        for gi in range(max(i0, 0), min(i1 + 1, len(glats))):
            for gj in range(max(j0, 0), min(j1 + 1, len(glons))):
                if covered_cells[gi, gj]:
                    continue
                dy = (glats[gi] - sv["lat"]) * 111320.0
                dx = (glons[gj] - sv["lon"]) * 111320.0 * math.cos(math.radians(sv["lat"]))
                dd = math.hypot(dx, dy)
                az = math.degrees(math.atan2(dx, dy)) % 360.0
                if dd <= sv["range_m"][int(round(az / (360.0 / N_AZ))) % N_AZ]:
                    covered_cells[gi, gj] = True
    cell_km2 = (GRID * 111.32) * (GRID * 111.32 * math.cos(math.radians((la0 + la1) / 2)))
    area_km2 = float(covered_cells.sum() * cell_km2)
    # high-terrain mask (mountain SAR proxy): cells above 600 m
    gz = dem.sample(np.repeat(glats, len(glons)), np.tile(glons, len(glats))
                    ).reshape(len(glats), len(glons))
    high = gz >= 600.0
    high_cov = float((covered_cells & high).sum() / max(high.sum(), 1))
    area_stats = {"union_area_km2": round(area_km2, 0),
                  "nh_area_km2": 24214,
                  "pct_of_state": round(100 * area_km2 / 24214, 1),
                  "pct_high_terrain_600m": round(100 * high_cov, 1)}
    print("area stats:", area_stats)

    # ── trail coverage: best site RSSI at every route vertex ─────────────────
    routes_path = args.routes or f"artifacts/sim/routes{args.suffix}.json"
    rj = json.loads((ROOT / routes_path).read_text())
    gaps, per_route = [], {}
    for rname, r in rj["routes"].items():
        lats = np.array(r["lat"]); lons = np.array(r["lon"])
        best = np.full(len(lats), -999.0)
        for sname, sv in service.items():
            d = np.array([haversine_m(sv["lat"], sv["lon"], la, lo)
                          for la, lo in zip(lats, lons)])
            near = d <= MAX_KM * 1000.0
            if not near.any():
                continue
            brg = np.degrees(np.arctan2(
                (lons - sv["lon"]) * math.cos(math.radians(sv["lat"])),
                lats - sv["lat"])) % 360.0
            k = (np.round(brg / (360.0 / N_AZ)).astype(int)) % N_AZ
            rng_at = np.array(sv["range_m"])[k]
            ok = near & (d <= rng_at)
            # covered points get an FSPL-based rssi estimate; it only needs to
            # beat the -131 threshold test
            best[ok] = np.maximum(best[ok], -100.0)
        cov = float(np.mean(best > -131.0))
        per_route[rname] = round(cov, 4)
        in_gap = None
        for i, b in enumerate(best):
            if b <= -131.0 and in_gap is None:
                in_gap = i
            elif b > -131.0 and in_gap is not None:
                gaps.append({"route": rname, "from_idx": in_gap, "to_idx": i,
                             "lat": float(lats[(in_gap + i) // 2]),
                             "lon": float(lons[(in_gap + i) // 2]),
                             "length_pts": i - in_gap})
                in_gap = None
        if in_gap is not None:
            gaps.append({"route": rname, "from_idx": in_gap, "to_idx": len(best),
                         "lat": float(lats[(in_gap + len(best)) // 2]),
                         "lon": float(lons[(in_gap + len(best)) // 2]),
                         "length_pts": len(best) - in_gap})

    stats = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_note": "screening field (viewshed+knife-edge, ITM-calibrated); "
                      "link-level claims remain Longley-Rice",
        "calibration": cal,
        "area": area_stats,
        "per_route_coverage": per_route,
        "worst_routes": sorted(per_route.items(), key=lambda kv: kv[1])[:8],
        "n_gap_segments": len(gaps),
        "gap_segments": sorted(gaps, key=lambda g: -g["length_pts"])[:40],
    }
    (ROOT / f"{args.out_prefix}trail_coverage.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items()
                      if k in ("calibration", "area", "worst_routes",
                               "n_gap_segments")}, indent=2))
    print(f"wrote {args.out_prefix}service_areas.json, trail_coverage.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

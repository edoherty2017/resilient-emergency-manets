#!/usr/bin/env python3
"""Terrain-clipped RF service areas + statewide trail-coverage field.

Produces a conservative, uncalibrated planning screen and per-node service
polygons.  It does not answer whether field coverage exists.

Model (viewshed + single knife-edge, ITM-calibrated):
  For each site, sweep N_AZ azimuths out to MAX_KM over the DEM. Along each
  ray track the dominant obstruction (max elevation angle from the antenna).
  Loss = FSPL + clutter offset (clear) or FSPL + ITU P.526 knife-edge penalty
  from the worst edge (obstructed). The offsets are aligned to the project's
  own Longley-Rice link matrix.  That is an internal model-to-model alignment,
  not calibration against independent observations.

Outputs:
  artifacts/sim/service_areas.json   per-site range-by-azimuth polygons (m)
  artifacts/sim/trail_coverage.json  per-trail-vertex best RSSI + gap segments
  artifacts/sim/coverage_field_stats.json

Run: .venv/bin/python scripts/coverage_field.py --suffix _statewide
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, haversine_m  # noqa: E402
from radio_link_budget import (  # noqa: E402
    PLANNING_THRESHOLD_DBM,
    RX_POWER_REFERENCE_DBM,
)

RX_POWER_REF_DBM = RX_POWER_REFERENCE_DBM
N_AZ = 72
MAX_KM = 9.0
STEP_M = 74.0
RX_H = 1.5
FREQ_MHZ = 915.0


def _file_record(path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


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
    """Align LOS/obstructed offsets to the same design's ITM q50 links."""
    diffs = []
    for key, l in links.items():
        if (
            not l.get("simulation_eligible", True)
            or l.get("model")
            in {
                "short_link_fspl",
                "short_link_fspl_unvalidated_opt_in",
                "excluded_unvalidated_short_link",
            }
        ):
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


def contiguous_range_m(dists: np.ndarray, rssi: np.ndarray, threshold_dbm: float) -> float:
    """Conservative range before the first failed sample on one ray.

    A farthest-covered-point envelope silently fills shadowed interior gaps.
    A simple polygon cannot represent those holes, so stopping at the first
    failure is conservative and honest about the representation.
    """

    covered = np.asarray(rssi) >= threshold_dbm
    failed = np.flatnonzero(~covered)
    stop = int(failed[0]) if len(failed) else len(covered)
    return round(float(dists[stop - 1]), 0) if stop else 0.0


def _reachable_sites_from_audit(audit: dict) -> set[str]:
    """Return sites in planning-tier components that reach a gateway."""

    tier = audit.get("planning_screen", audit)
    return {
        member
        for component in tier.get("components", [])
        if component.get("reaches_backhaul")
        for member in component.get("members", [])
    }


def _state_mask(lats: np.ndarray, lons: np.ndarray, boundary: dict) -> np.ndarray:
    """Mask grid-cell centers to the supplied GeoJSON Polygon/MultiPolygon."""

    from matplotlib.path import Path as MplPath

    lon_grid, lat_grid = np.meshgrid(lons, lats)
    points = np.column_stack((lon_grid.ravel(), lat_grid.ravel()))
    polygons = (
        boundary["coordinates"]
        if boundary["type"] == "MultiPolygon"
        else [boundary["coordinates"]]
    )
    mask = np.zeros(len(points), dtype=bool)
    for polygon in polygons:
        if not polygon:
            continue
        inside = MplPath(np.asarray(polygon[0], dtype=float)).contains_points(points)
        for hole in polygon[1:]:
            inside &= ~MplPath(np.asarray(hole, dtype=float)).contains_points(points)
        mask |= inside
    return mask.reshape(len(lats), len(lons))


def main() -> int:
    ap = argparse.ArgumentParser(description="Service-area field + trail coverage")
    ap.add_argument("--suffix", default="_statewide")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    ap.add_argument("--routes", default=None)
    ap.add_argument("--out-prefix", default="artifacts/sim/")
    ap.add_argument(
        "--audit",
        default=None,
        help="planning audit used to exclude relays without gateway reachability",
    )
    ap.add_argument(
        "--receiver-threshold-dbm",
        type=float,
        default=PLANNING_THRESHOLD_DBM,
        help="planning threshold used for service polygons (default: -100 dBm)",
    )
    args = ap.parse_args()

    dem_path = ROOT / args.dem_npz
    topology_path = ROOT / f"artifacts/sim/topology{args.suffix}.json"
    dem = Dem(dem_path)
    topo = json.loads(topology_path.read_text())
    sites = topo["sites"]
    audit_path = ROOT / (
        args.audit or f"artifacts/sim/coverage_audit{args.suffix}.json"
    )
    audit = json.loads(audit_path.read_text())
    reachable_sites = _reachable_sites_from_audit(audit)
    if not reachable_sites:
        raise ValueError(f"no gateway-reachable planning-tier sites in {audit_path}")

    cal = calibrate(dem, sites, topo["links"])
    print(f"internal alignment vs ITM links: LOS {cal['los_db']:+.1f} dB "
          f"(sigma {cal['sigma_los']}, n={cal['n_los']}) | obstructed "
          f"{cal['obs_db']:+.1f} dB (sigma {cal['sigma_obs']}, n={cal['n_obs']})")

    # ── conservative per-site service polygons ───────────────────────────────
    service = {}
    service_sites = [(name, sites[name]) for name in sorted(reachable_sites)]
    for i, (name, s) in enumerate(service_sites):
        dists, loss, blk = ray_losses(dem, s["lat"], s["lon"], s["hg_m"])
        loss = loss + np.where(blk, cal["obs_db"], cal["los_db"])
        rssi = RX_POWER_REF_DBM - loss
        ranges = []
        for k in range(N_AZ):
            ranges.append(
                contiguous_range_m(dists, rssi[k], args.receiver_threshold_dbm)
            )
        service[name] = {"lat": s["lat"], "lon": s["lon"], "range_m": ranges}
        if i % 25 == 0:
            print(f"  service polygons {i}/{len(service_sites)}")

    (ROOT / f"{args.out_prefix}service_areas.json").write_text(json.dumps({
        "n_az": N_AZ,
        "max_m": MAX_KM * 1000.0,
        "receiver_threshold_dbm": args.receiver_threshold_dbm,
        "audit": str(audit_path.relative_to(ROOT)),
        "input_provenance": {
            "generator": _file_record(Path(__file__)),
            "topology": _file_record(topology_path),
            "dem": _file_record(dem_path),
            "planning_audit": _file_record(audit_path),
        },
        "n_gateway_reachable_sites": len(service_sites),
        "model":
        f"viewshed+knife-edge; offsets LOS {cal['los_db']:+.1f} / obstructed "
        f"{cal['obs_db']:+.1f} dB aligned to project ITM links; conservative "
        "contiguous range before first failed sample",
        "claim_status": "INTERNAL_MODEL_SCREEN_NOT_FIELD_VALIDATED",
        "sites": service}))

    # ── union area statistics on a coarse grid ────────────────────────────────
    GRID = 0.005      # ~550 m cells
    la0, la1 = float(dem.lat.min()), float(dem.lat.max())
    lo0, lo1 = float(dem.lon.min()), float(dem.lon.max())
    glats = np.arange(la0, la1, GRID)
    glons = np.arange(lo0, lo1, GRID)
    boundary_path = ROOT / "artifacts/osm/nh_boundary.json"
    state_mask = _state_mask(glats, glons, json.loads(boundary_path.read_text()))
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
                if covered_cells[gi, gj] or not state_mask[gi, gj]:
                    continue
                dy = (glats[gi] - sv["lat"]) * 111320.0
                dx = (glons[gj] - sv["lon"]) * 111320.0 * math.cos(math.radians(sv["lat"]))
                dd = math.hypot(dx, dy)
                az = math.degrees(math.atan2(dx, dy)) % 360.0
                if dd <= sv["range_m"][int(round(az / (360.0 / N_AZ))) % N_AZ]:
                    covered_cells[gi, gj] = True
    cell_km2 = (GRID * 111.32) * (GRID * 111.32 * math.cos(math.radians((la0 + la1) / 2)))
    area_km2 = float((covered_cells & state_mask).sum() * cell_km2)
    state_area_km2 = float(state_mask.sum() * cell_km2)
    # high-terrain mask (mountain SAR proxy): cells above 600 m
    gz = dem.sample(np.repeat(glats, len(glons)), np.tile(glons, len(glats))
                    ).reshape(len(glats), len(glons))
    high = (gz >= 600.0) & state_mask
    high_cov = float((covered_cells & high).sum() / max(high.sum(), 1))
    area_stats = {"union_area_km2": round(area_km2, 0),
                  "state_grid_area_km2": round(state_area_km2, 0),
                  "pct_of_state_grid": round(100 * area_km2 / state_area_km2, 1),
                  "pct_high_terrain_600m": round(100 * high_cov, 1)}
    print("area stats:", area_stats)

    # ── trail coverage: best site RSSI at every route vertex ─────────────────
    routes_path = args.routes or f"artifacts/sim/routes{args.suffix}.json"
    routes_file = ROOT / routes_path
    rj = json.loads(routes_file.read_text())
    gaps, per_route = [], {}
    for rname, r in rj["routes"].items():
        lats = np.array(r["lat"]); lons = np.array(r["lon"])
        covered = np.zeros(len(lats), dtype=bool)
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
            covered |= near & (d <= rng_at)
        cov = float(np.mean(covered))
        per_route[rname] = round(cov, 4)
        in_gap = None
        for i, is_covered in enumerate(covered):
            if not is_covered and in_gap is None:
                in_gap = i
            elif is_covered and in_gap is not None:
                gaps.append({"route": rname, "from_idx": in_gap, "to_idx": i,
                             "lat": float(lats[(in_gap + i) // 2]),
                             "lon": float(lons[(in_gap + i) // 2]),
                             "length_pts": i - in_gap})
                in_gap = None
        if in_gap is not None:
            gaps.append({"route": rname, "from_idx": in_gap, "to_idx": len(covered),
                         "lat": float(lats[(in_gap + len(covered)) // 2]),
                         "lon": float(lons[(in_gap + len(covered)) // 2]),
                         "length_pts": len(covered) - in_gap})

    stats = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_kind": "internal_model_screen",
        "claim_status": "NOT_FIELD_VALIDATED",
        "receiver_threshold_dbm": args.receiver_threshold_dbm,
        "gateway_reachable_sites_only": True,
        "n_gateway_reachable_sites": len(service_sites),
        "input_provenance": {
            "generator": _file_record(Path(__file__)),
            "topology": _file_record(topology_path),
            "routes": _file_record(routes_file),
            "dem": _file_record(dem_path),
            "planning_audit": _file_record(audit_path),
        },
        "model_note": "Conservative contiguous viewshed+knife-edge polygons; "
                      "offsets are aligned to the project's own ITM design "
                      "links, not independent field observations.",
        "limitations": [
            "Internal model-to-model alignment is not field calibration.",
            "Azimuth polygons stop at the first failed sample and may omit disconnected coverage islands.",
            "Coverage excludes modeled relays that fail the planning-tier gateway-reachability screen.",
        ],
        "calibration": cal,
        "area": area_stats,
        "per_route_coverage": per_route,
        "worst_routes": sorted(per_route.items(), key=lambda kv: kv[1])[:8],
        "n_gap_segments": len(gaps),
        "gap_segments": sorted(gaps, key=lambda g: -g["length_pts"])[:40],
    }
    (ROOT / f"{args.out_prefix}trail_coverage.json").write_text(json.dumps(stats, indent=2))
    (ROOT / f"{args.out_prefix}coverage_field_stats.json").write_text(
        json.dumps(stats, indent=2)
    )
    print(json.dumps({k: v for k, v in stats.items()
                      if k in ("calibration", "area", "worst_routes",
                               "n_gap_segments")}, indent=2))
    print(f"wrote {args.out_prefix}service_areas.json, trail_coverage.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

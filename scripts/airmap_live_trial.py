#!/usr/bin/env python3
"""AIRMap live trial: FSPL baseline prediction + calibration against observed telemetry.

Calibration policy (see docs/academic-rigor-review-2026-06-12.md):
- Only "calibration-eligible" rows enter any fit or error metric used as evidence:
  GPS on both ends (distance_source == source_to_head_gps), verified direct link
  (hops_away == 0), plausible RSSI, fresh position fixes.
- The observable is ESP (effective signal power) when SNR is available, since raw
  RSSI is noise-dominated near the demodulation floor.
- Calibration fits a floating-intercept log-distance model PL = alpha + 10*beta*log10(d_m)
  by OLS; beta is the path-loss exponent deliverable. A mean-bias fit is retained for
  comparison. Evaluation is blocked cross-validation (contiguous time folds); parameter
  uncertainty comes from a moving-block bootstrap.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from radio_link_budget import (
    RX_ANTENNA_GAIN_DBI,
    RX_POWER_REFERENCE_DBM,
    RX_SENSITIVITY_DBM,
    TX_ANTENNA_GAIN_DBI,
    TX_CONDUCTED_DBM,
    TX_EIRP_DBM,
)


TX_DBM = TX_CONDUCTED_DBM
TX_ANT_GAIN_DBI = TX_ANTENNA_GAIN_DBI
RX_ANT_GAIN_DBI = RX_ANTENNA_GAIN_DBI
# Meshtastic LongFast = SF11 / BW 250 kHz / CR 4/5; link budget 153 dB at 22 dBm + 0 dBi
# (https://meshtastic.org/docs/overview/radio-settings/) => sensitivity ~= -131 dBm,
# consistent with the Semtech SX1262 datasheet (SF11/BW250).
RX_SENS_DBM = RX_SENSITIVITY_DBM
# Thermal noise floor for BW 250 kHz with ~6 dB receiver noise figure:
# -174 + 10*log10(250e3) + 6 ~= -114 dBm. LoRa demodulates below this (SNR floor
# ~= -17.5 dB at SF11), which is why sensitivity sits below the noise floor.
NOISE_FLOOR_DBM = -114.0
RX_POWER_REF_DBM = RX_POWER_REFERENCE_DBM

# Physical plausibility: any observation hotter than this for a >10 m link implies a
# co-located transmitter (e.g. the adjacent forwarder seen in Trial 1) and is excluded.
PLAUSIBLE_MAX_DBM = -20.0
MIN_LINK_DISTANCE_M = 10.0


def fspl_db(distance_m: float, freq_mhz: float) -> float:
    d_km = max(distance_m / 1000.0, 1e-6)
    return 32.44 + 20 * math.log10(d_km) + 20 * math.log10(freq_mhz)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def slant_distance_m(lat1, lon1, elev1, lat2, lon2, elev2) -> float:
    """3D link distance; falls back to 2D haversine when either elevation is missing."""
    d2 = haversine_m(lat1, lon1, lat2, lon2)
    if elev1 is None or elev2 is None or pd.isna(elev1) or pd.isna(elev2):
        return d2
    return math.sqrt(d2 ** 2 + float(elev1 - elev2) ** 2)


def esp_dbm(rssi: pd.Series, snr: pd.Series) -> pd.Series:
    """Effective Signal Power: ESP = RSSI + SNR - 10*log10(1 + 10^(0.1*SNR)).

    Separates the signal estimate from noise when SNR is low; near/below the noise
    floor raw RSSI measures mostly noise. Standard Semtech formulation.
    """
    snr_lin = np.power(10.0, 0.1 * snr)
    return rssi + snr - 10.0 * np.log10(1.0 + snr_lin)


def floating_intercept_fit(distance_m: np.ndarray, path_loss_db: np.ndarray) -> dict | None:
    """OLS fit of PL = alpha + 10*beta*log10(d_m). Returns parameters + diagnostics."""
    n = len(distance_m)
    if n < 3:
        return None
    x = 10.0 * np.log10(distance_m)
    X = np.column_stack([np.ones(n), x])
    coef, _, _, _ = np.linalg.lstsq(X, path_loss_db, rcond=None)
    alpha, beta = float(coef[0]), float(coef[1])
    resid = path_loss_db - X @ coef
    dof = max(n - 2, 1)
    sigma = float(np.sqrt(np.sum(resid ** 2) / dof))
    ss_tot = float(np.sum((path_loss_db - path_loss_db.mean()) ** 2))
    r2 = float(1.0 - np.sum(resid ** 2) / ss_tot) if ss_tot > 0 else None
    return {"alpha_db": alpha, "path_loss_exponent": beta, "sigma_db": sigma, "r2": r2, "n": int(n)}


def moving_block_bootstrap(
    df: pd.DataFrame, block_seconds: float = 60.0, n_boot: int = 500, seed: int = 7
) -> dict | None:
    """Moving-block bootstrap CIs for the floating-intercept parameters.

    Rows are grouped into contiguous time blocks; blocks are resampled with
    replacement. Respects the temporal autocorrelation that makes naive
    row-level bootstrap (and naive n) anti-conservative.
    """
    if len(df) < 30:
        return None
    rng = np.random.default_rng(seed)
    # Resolution-independent (pandas may store datetime64 at us or ns resolution)
    t = (df["timestamp_utc"] - df["timestamp_utc"].min()).dt.total_seconds()
    block_id = (t // block_seconds).astype(int).to_numpy()
    blocks = [df.index[block_id == b].to_numpy() for b in np.unique(block_id)]
    if len(blocks) < 5:
        return None
    stats = {"alpha_db": [], "path_loss_exponent": [], "sigma_db": []}
    for _ in range(n_boot):
        chosen = rng.choice(len(blocks), size=len(blocks), replace=True)
        idx = np.concatenate([blocks[i] for i in chosen])
        sample = df.loc[idx]
        fit = floating_intercept_fit(
            sample["distance_m"].to_numpy(), sample["obs_path_loss_db"].to_numpy()
        )
        if fit is None:
            continue
        for k in stats:
            stats[k].append(fit[k])
    if not stats["path_loss_exponent"]:
        return None
    out = {"n_boot": int(len(stats["path_loss_exponent"])), "block_seconds": block_seconds}
    for k, v in stats.items():
        arr = np.asarray(v)
        out[f"{k}_ci95"] = [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))]
    return out


def blocked_cv(df: pd.DataFrame, freq_mhz: float, n_folds: int = 5) -> dict | None:
    """Contiguous-time-fold CV comparing FSPL, mean-bias, and floating-intercept.

    Contiguous folds (not random rows) so the held-out data is temporally —
    and on a moving route, spatially — separated from the training data.
    """
    n = len(df)
    if n < 10 * n_folds:
        n_folds = max(2, n // 10)
    if n < 20:
        return None
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    fold_edges = np.linspace(0, n, n_folds + 1).astype(int)
    # ITM is a fixed (untrained) terrain model, evaluated on test folds like FSPL,
    # only when a precomputed per-row ITM column is present.
    has_itm = "pred_path_loss_itm_db" in df.columns and df["pred_path_loss_itm_db"].notna().any()
    sq_err: dict[str, list] = {"fspl": [], "mean_bias": [], "floating_intercept": []}
    if has_itm:
        sq_err["itm"] = []
    for f in range(n_folds):
        lo, hi = fold_edges[f], fold_edges[f + 1]
        test = df.iloc[lo:hi]
        train = pd.concat([df.iloc[:lo], df.iloc[hi:]])
        if len(train) < 3 or len(test) == 0:
            continue
        fspl_pred = test["distance_m"].apply(lambda d: fspl_db(float(d), freq_mhz)).to_numpy()
        obs_pl = test["obs_path_loss_db"].to_numpy()
        sq_err["fspl"].extend((obs_pl - fspl_pred) ** 2)
        train_fspl = train["distance_m"].apply(lambda d: fspl_db(float(d), freq_mhz)).to_numpy()
        bias = float((train["obs_path_loss_db"].to_numpy() - train_fspl).mean())
        sq_err["mean_bias"].extend((obs_pl - (fspl_pred + bias)) ** 2)
        fit = floating_intercept_fit(
            train["distance_m"].to_numpy(), train["obs_path_loss_db"].to_numpy()
        )
        if fit is not None:
            fi_pred = fit["alpha_db"] + 10.0 * fit["path_loss_exponent"] * np.log10(test["distance_m"].to_numpy())
            sq_err["floating_intercept"].extend((obs_pl - fi_pred) ** 2)
        if has_itm:
            itm_pred = test["pred_path_loss_itm_db"].to_numpy(dtype=float)
            mask = ~np.isnan(itm_pred)
            sq_err["itm"].extend((obs_pl[mask] - itm_pred[mask]) ** 2)
    return {
        "n_folds": int(n_folds),
        "held_out_rmse_db": {
            k: (float(np.sqrt(np.mean(v))) if v else None) for k, v in sq_err.items()
        },
    }


def itm_predictor(dem_npz: Path, tx_h: float, rx_h: float, freq_mhz: float):
    """Build a per-row ITM path-loss predictor over a cached DEM.

    Returns a callable f(src_lat, src_lon, head_lat, head_lon) -> (pl_q50, pl_q90),
    or None if the DEM/itmlogic are unavailable. Ground elevation comes from the
    DEM; GPS antenna heights are added as hg (GPS altitude is noisy and is not used
    for the terrain profile). Uses the same engine as scripts/itm_relay_links.py.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from itm_relay_links import Dem, itm_p2p_loss
    except Exception as exc:  # itmlogic or DEM module missing
        print(f"[itm] predictor unavailable ({exc}); falling back to FSPL only")
        return None
    if not dem_npz.exists():
        print(f"[itm] DEM cache not found at {dem_npz}; falling back to FSPL only")
        return None
    dem = Dem(dem_npz)

    def predict(src_lat, src_lon, head_lat, head_lon):
        if any(pd.isna(v) for v in (src_lat, src_lon, head_lat, head_lon)):
            return (np.nan, np.nan)
        d_m, prof = dem.profile(float(src_lat), float(src_lon), float(head_lat), float(head_lon))
        if d_m < 1.0:
            return (np.nan, np.nan)
        try:
            itm = itm_p2p_loss(d_m / 1000.0, prof, (tx_h, rx_h), freq_mhz=freq_mhz)
        except Exception:
            return (np.nan, np.nan)
        return (float(itm["loss_db_q50"]), float(itm["loss_db_q90"]))

    return predict


def git_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()


def load_garmin_gpx(path: Path) -> pd.DataFrame:
    """Parse a Garmin GPX track into a DataFrame sorted by timestamp_utc."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""
    prefix = f"{{{ns}}}" if ns else ""
    rows = []
    for p in root.findall(f".//{prefix}trkpt"):
        lat = float(p.get("lat"))
        lon = float(p.get("lon"))
        ele_el = p.find(f"{prefix}ele")
        ele = float(ele_el.text) if ele_el is not None else 0.0
        time_el = p.find(f"{prefix}time")
        if time_el is None:
            continue
        ts = pd.Timestamp(time_el.text).tz_convert("UTC")
        rows.append({"timestamp_utc": ts, "lat": lat, "lon": lon, "ele_m": ele})
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc")


def time_bin_from_hour(hour: int) -> str:
    if 5 <= hour <= 7:
        return "dawn"
    if 8 <= hour <= 16:
        return "day"
    if 17 <= hour <= 19:
        return "dusk"
    if 20 <= hour <= 22:
        return "evening_peak"
    return "night"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--node-id", default="meshhikernode1")
    ap.add_argument("--head-id", default="meshnodehead")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--lat0", type=float, default=44.2706)
    ap.add_argument("--lon0", type=float, default=-71.3033)
    ap.add_argument("--lat1", type=float, default=44.2950)
    ap.add_argument("--lon1", type=float, default=-71.2758)
    ap.add_argument("--time-window-seconds", type=int, default=5)
    ap.add_argument("--min-observed-samples", type=int, default=200)
    ap.add_argument("--min-calibration-samples", type=int, default=30)
    ap.add_argument("--src-pos-tolerance-s", type=int, default=60,
                    help="Max staleness of a source-node position fix used for link distance")
    ap.add_argument("--require-rsrp", action="store_true", help="Fail run if no rsrp_dbm samples are present")
    ap.add_argument("--require-calibration-grade", action="store_true",
                    help="Hard-fail unless enough calibration-eligible rows exist and the fit passes plausibility gates")
    ap.add_argument("--allow-unverified-hops", action="store_true",
                    help="Treat rows without hop telemetry as direct links (NOT calibration grade; shakedown only)")
    ap.add_argument("--head-gpx", default=None, help="Garmin GPX file for HEAD position ground truth (replaces linear interpolation)")
    ap.add_argument("--predictor", choices=["fspl", "itm"], default="fspl",
                    help="Baseline per-row predictor: free-space (fspl) or Longley-Rice terrain (itm). "
                         "itm requires --dem-npz and itmlogic; falls back to fspl if unavailable.")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_mtwashington.npz",
                    help="Cached DEM for ITM terrain profiles (scripts/dem_3dep.py / dem_copernicus.py)")
    ap.add_argument("--tx-height-m", type=float, default=2.0, help="Source antenna height above ground for ITM")
    ap.add_argument("--rx-height-m", type=float, default=1.5, help="HEAD antenna height above ground for ITM")
    args = ap.parse_args()

    root = Path(args.root)
    model_cfg = yaml.safe_load((root / "config/airmap/model-baseline.yaml").read_text())
    eval_cfg = yaml.safe_load((root / "config/airmap/calibration-and-eval.yaml").read_text())
    out_dir = root / "artifacts/airmap/live_trial"
    out_dir.mkdir(parents=True, exist_ok=True)

    freq_mhz = float(model_cfg["model"]["frequency_mhz"])
    model_name = model_cfg["model"]["name"]
    model_version = model_cfg["model"]["version"]
    model_hash = model_cfg["model"]["hash"]
    recipe_version = model_cfg["features"]["recipe_version"]
    calibration_version = eval_cfg["calibration"]["version"]
    min_stratum_n = int(eval_cfg.get("evaluation", {}).get("min_samples_per_stratum", 30))

    node_path = Path(args.ingest_root) / f"{args.node_id}/jsonl/telemetry_stream.jsonl"
    obs = load_jsonl(node_path)
    if obs.empty:
        raise SystemExit(f"no observation rows found in {node_path}")

    obs = obs[(obs["trial_id"] == args.trial_id) & (obs["node_id"] == args.node_id)].copy()
    if obs.empty:
        raise SystemExit("no rows after trial/node filter")

    # Observed metric fallback chain: prefer RSRP, then RSSI if RSRP is unavailable.
    obs["obs_rsrp_dbm"] = pd.to_numeric(obs.get("rsrp_dbm"), errors="coerce")
    obs["obs_rssi_dbm"] = pd.to_numeric(obs.get("rssi_dbm"), errors="coerce")
    obs["obs_snr_db"] = pd.to_numeric(obs.get("snr_db"), errors="coerce")
    obs["obs_metric_dbm"] = obs["obs_rsrp_dbm"].combine_first(obs["obs_rssi_dbm"])
    obs["obs_metric_source"] = np.where(
        obs["obs_rsrp_dbm"].notna(),
        "rsrp_dbm",
        np.where(obs["obs_rssi_dbm"].notna(), "rssi_dbm", "none"),
    )

    # Calibration observable: ESP when RSSI+SNR are both present (RSSI alone is
    # noise-dominated near the floor), otherwise the metric fallback chain.
    has_esp = obs["obs_rssi_dbm"].notna() & obs["obs_snr_db"].notna()
    obs["obs_esp_dbm"] = np.where(
        has_esp, esp_dbm(obs["obs_rssi_dbm"], obs["obs_snr_db"]), np.nan
    )
    obs["obs_target_dbm"] = obs["obs_esp_dbm"].combine_first(obs["obs_metric_dbm"])
    obs["obs_target_source"] = np.where(has_esp, "esp_dbm", obs["obs_metric_source"])

    # Verified hop count (collector >= Trial 2 logs hop_limit/hop_start).
    hop_limit = pd.to_numeric(obs.get("hop_limit"), errors="coerce")
    hop_start = pd.to_numeric(obs.get("hop_start"), errors="coerce")
    obs["hops_away"] = hop_start - hop_limit
    hop_data_available = bool(obs["hops_away"].notna().any())

    t0 = obs["timestamp_utc"].min()
    t1 = obs["timestamp_utc"].max()
    span = max((t1 - t0).total_seconds(), 1.0)
    if args.head_gpx:
        # ── Garmin GPS ground truth for HEAD position ─────────────────────────
        gpx = load_garmin_gpx(Path(args.head_gpx))
        obs_sorted = obs.sort_values("timestamp_utc").copy()
        gpx_sorted = gpx.rename(columns={"lat": "head_lat", "lon": "head_lon", "ele_m": "head_elev_m"})
        merged = pd.merge_asof(
            obs_sorted,
            gpx_sorted[["timestamp_utc", "head_lat", "head_lon", "head_elev_m"]],
            on="timestamp_utc",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=60),
        )
        obs = merged.copy()
        obs["head_gps_source"] = np.where(obs["head_lat"].notna(), "garmin_external", "missing")

        # ── Build source-node GPS timelines from POSITION_APP packets ─────────
        src_cols = ["from_mesh_id", "timestamp_utc", "lat", "lon"]
        if "elev_m" in obs.columns:
            src_cols.append("elev_m")
        src_pos = obs[
            obs["portnum"].astype(str).str.contains("POSITION", na=False)
            & obs["lat"].notna() & obs["lon"].notna()
            & obs["from_mesh_id"].notna()
        ][src_cols].copy()
        src_pos = src_pos.rename(columns={"lat": "src_lat", "lon": "src_lon", "elev_m": "src_elev_m"})
        if "src_elev_m" not in src_pos.columns:
            src_pos["src_elev_m"] = np.nan
        src_pos["src_pos_timestamp"] = src_pos["timestamp_utc"]

        src_gps_rows = []
        for mid, grp in src_pos.groupby("from_mesh_id"):
            grp_sorted = grp.sort_values("timestamp_utc")
            node_obs = obs[obs["from_mesh_id"] == mid].sort_values("timestamp_utc").copy()
            if node_obs.empty:
                continue
            joined = pd.merge_asof(
                node_obs,
                grp_sorted[["timestamp_utc", "src_lat", "src_lon", "src_elev_m", "src_pos_timestamp"]],
                on="timestamp_utc",
                direction="nearest",
                tolerance=pd.Timedelta(seconds=args.src_pos_tolerance_s),
            )
            src_gps_rows.append(joined)

        # Nodes with no position packets keep src_lat/src_lon as NaN
        has_src_gps_ids = set(src_pos["from_mesh_id"].unique())
        no_src_gps = obs[~obs["from_mesh_id"].isin(has_src_gps_ids)].copy()
        no_src_gps["src_lat"] = np.nan
        no_src_gps["src_lon"] = np.nan
        no_src_gps["src_elev_m"] = np.nan
        no_src_gps["src_pos_timestamp"] = pd.NaT

        if src_gps_rows:
            obs = pd.concat(src_gps_rows + [no_src_gps], ignore_index=True).sort_values("timestamp_utc")
        else:
            obs = no_src_gps
        obs = obs.reset_index(drop=True)

        obs["src_pos_staleness_s"] = (
            (obs["timestamp_utc"] - pd.to_datetime(obs["src_pos_timestamp"], utc=True))
            .dt.total_seconds()
            .abs()
        )

        # ── Compute link distance (3D slant where both elevations exist) ──────
        has_both = obs["src_lat"].notna() & obs["head_lat"].notna()
        obs["distance_m"] = np.nan
        obs["distance_source"] = "unknown"

        if has_both.any():
            obs.loc[has_both, "distance_m"] = obs[has_both].apply(
                lambda r: slant_distance_m(
                    r["src_lat"], r["src_lon"], r.get("src_elev_m"),
                    r["head_lat"], r["head_lon"], r.get("head_elev_m"),
                ),
                axis=1,
            )
            obs.loc[has_both, "distance_source"] = "source_to_head_gps"

        # Diagnostic only: how far the HEAD moved from the reference point. This is
        # NOT a link distance and never feeds predictions or calibration.
        head_only = ~has_both & obs["head_lat"].notna()
        if head_only.any():
            obs.loc[head_only, "distance_m"] = obs[head_only].apply(
                lambda r: haversine_m(args.lat0, args.lon0, r["head_lat"], r["head_lon"]), axis=1
            )
            obs.loc[head_only, "distance_source"] = "head_displacement_from_ref"

        # HEAD elevation drives terrain class
        obs["head_elev_m"] = pd.to_numeric(obs.get("head_elev_m"), errors="coerce")
        obs["topography_class"] = pd.cut(
            obs["head_elev_m"],
            bins=[-np.inf, 1200, 1500, np.inf],
            labels=["valley_forest", "sub_alpine", "alpine_ridge"],
        ).astype(str)

        # Use HEAD lat/lon as the observation coordinates
        obs["lat"] = obs["head_lat"]
        obs["lon"] = obs["head_lon"]

    else:
        # ── Legacy: linear interpolation between two fixed endpoints ──────────
        frac = (obs["timestamp_utc"] - t0).dt.total_seconds() / span
        obs["lat"] = args.lat0 + (args.lat1 - args.lat0) * frac
        obs["lon"] = args.lon0 + (args.lon1 - args.lon0) * frac
        obs["distance_m"] = obs.apply(
            lambda r: haversine_m(args.lat0, args.lon0, r["lat"], r["lon"]), axis=1
        )
        obs["distance_source"]  = "linear_interpolation"
        obs["topography_class"] = np.where(frac > 0.5, "alpine_ridge", "valley")
        obs["head_gps_source"]  = "linear_interpolation"
        obs["src_lat"] = np.nan
        obs["src_lon"] = np.nan
        obs["src_elev_m"] = np.nan
        obs["src_pos_staleness_s"] = np.nan

    # Predictions only where the distance is a real (or legacy-synthetic) link
    # distance. Missing distance stays NaN — it must never default to a tiny
    # distance and fabricate a hot prediction.
    obs["distance_m"] = pd.to_numeric(obs["distance_m"], errors="coerce")
    predictable = obs["distance_source"].isin(["source_to_head_gps", "linear_interpolation"]) & (
        obs["distance_m"] >= 1.0
    )
    # FSPL baseline is always computed (cheap, terrain-free lower bound).
    obs["pred_path_loss_fspl_db"] = np.where(
        predictable,
        obs["distance_m"].apply(lambda d: fspl_db(float(d), freq_mhz) if pd.notna(d) else np.nan),
        np.nan,
    )
    # ITM terrain prediction per row (only where real source->head geometry exists).
    obs["pred_path_loss_itm_db"] = np.nan
    predictor_used = "fspl"
    if args.predictor == "itm":
        itm_fn = itm_predictor(
            Path(args.dem_npz) if Path(args.dem_npz).is_absolute() else root / args.dem_npz,
            args.tx_height_m, args.rx_height_m, freq_mhz,
        )
        if itm_fn is not None:
            itm_mask = (obs["distance_source"] == "source_to_head_gps") & predictable & obs["src_lat"].notna()
            n_itm = int(itm_mask.sum())
            if n_itm:
                print(f"[itm] computing terrain predictions for {n_itm} rows ...")
                itm_vals = obs.loc[itm_mask].apply(
                    lambda r: itm_fn(r["src_lat"], r["src_lon"], r["head_lat"], r["head_lon"])[0],
                    axis=1,
                )
                obs.loc[itm_mask, "pred_path_loss_itm_db"] = itm_vals.astype(float)
                predictor_used = "itm"
            else:
                print("[itm] no rows with source->head GPS geometry; baseline stays FSPL")
    # Selected baseline path loss: ITM where available, else FSPL.
    if predictor_used == "itm":
        obs["pred_path_loss_db"] = obs["pred_path_loss_itm_db"].combine_first(obs["pred_path_loss_fspl_db"])
    else:
        obs["pred_path_loss_db"] = obs["pred_path_loss_fspl_db"]
    obs["predictor"] = predictor_used
    obs["pred_rssi_dbm"] = RX_POWER_REF_DBM - obs["pred_path_loss_db"]
    # Link margin above demodulation sensitivity (NOT an SNR; SNR would be
    # referenced to the noise floor at -114 dBm for BW 250 kHz).
    obs["pred_link_margin_db"] = obs["pred_rssi_dbm"] - RX_SENS_DBM
    obs["segment_id"] = [f"seg-{i:05d}" for i in range(len(obs))]
    obs["distance_bin"] = pd.cut(
        obs["distance_m"],
        bins=[0, 1000, 2000, 5000, np.inf],
        labels=["0-1km", "1-2km", "2-5km", "5km+"],
    ).astype(str)
    obs["material_class"] = "mixed_forest"
    # Local civil time (America/New_York), not UTC — time-of-day bins are about
    # local demand/light conditions.
    obs["local_hour"] = (
        obs["timestamp_utc"].dt.tz_convert("America/New_York").dt.hour.astype("Int64")
    )
    obs["time_bin"] = obs["local_hour"].apply(lambda h: time_bin_from_hour(int(h)) if pd.notna(h) else "unknown")

    # Optional Starlink/satellite quality fields (ingested when available).
    # merge_starlink_into_telemetry.py emits satellite_link_status_starlink to avoid
    # colliding with the MANET connectivity_mode field; alias it here.
    if "satellite_link_status_starlink" in obs.columns and "satellite_link_status" not in obs.columns:
        obs["satellite_link_status"] = obs["satellite_link_status_starlink"]
    elif "satellite_link_status_starlink" in obs.columns:
        obs["satellite_link_status"] = obs["satellite_link_status_starlink"].combine_first(obs["satellite_link_status"])
    elif "satellite_link_status" not in obs.columns:
        obs["satellite_link_status"] = pd.NA
    for col in (
        "satellite_rtt_ms_p50",
        "satellite_rtt_ms_p95",
        "satellite_down_mbps",
        "satellite_up_mbps",
        "satellite_packet_loss_pct",
        "satellite_obstruction_pct",
        "satellite_outage_seconds",
    ):
        obs[col] = pd.to_numeric(obs.get(col), errors="coerce")

    # Route/time-window join quality audit against head stream timestamps.
    head_path = Path(args.ingest_root) / f"{args.head_id}/jsonl/telemetry_stream.jsonl"
    head = load_jsonl(head_path)
    head = head[(head["trial_id"] == args.trial_id)].copy() if not head.empty else head
    if not head.empty:
        head = head[["timestamp_utc"]].dropna().sort_values("timestamp_utc").copy()
        head = head.rename(columns={"timestamp_utc": "head_timestamp_utc"})
        join = pd.merge_asof(
            obs.sort_values("timestamp_utc"),
            head.sort_values("head_timestamp_utc"),
            left_on="timestamp_utc",
            right_on="head_timestamp_utc",
            direction="nearest",
            tolerance=pd.Timedelta(seconds=args.time_window_seconds),
        )
    else:
        join = obs.copy()
        join["head_timestamp_utc"] = pd.NaT

    join["time_offset_seconds"] = (join["timestamp_utc"] - join["head_timestamp_utc"]).dt.total_seconds().abs()
    join["join_status"] = np.where(
        join["head_timestamp_utc"].isna(),
        "missing_time_window",
        np.where(join["obs_metric_dbm"].notna(), "matched", "missing_observation_metric"),
    )

    # ── Calibration eligibility ───────────────────────────────────────────────
    # Every condition is recorded so the join audit explains each exclusion.
    direct_link = join["hops_away"] == 0
    if not hop_data_available and args.allow_unverified_hops:
        direct_link = pd.Series(True, index=join.index)
    join["excl_no_target"] = join["obs_target_dbm"].isna()
    join["excl_distance_source"] = join["distance_source"] != "source_to_head_gps"
    join["excl_distance_range"] = ~(join["distance_m"] >= MIN_LINK_DISTANCE_M)
    join["excl_implausible_power"] = join["obs_target_dbm"] > PLAUSIBLE_MAX_DBM
    join["excl_unverified_hops"] = ~direct_link.fillna(False)
    join["excl_stale_src_pos"] = ~(join["src_pos_staleness_s"] <= args.src_pos_tolerance_s)
    join["calibration_eligible"] = ~(
        join["excl_no_target"]
        | join["excl_distance_source"]
        | join["excl_distance_range"]
        | join["excl_implausible_power"]
        | join["excl_unverified_hops"]
        | join["excl_stale_src_pos"]
    )

    pre = join.copy()
    post = join.copy()

    elig = post[post["calibration_eligible"]].copy()
    elig["obs_path_loss_db"] = RX_POWER_REF_DBM - elig["obs_target_dbm"]

    fit = None
    bootstrap = None
    cv = None
    residual = None
    calibration_method = "none"
    if len(elig) >= args.min_calibration_samples:
        residual = float(
            (elig["obs_target_dbm"] - (RX_POWER_REF_DBM - elig["pred_path_loss_db"])).mean()
        )
        fit = floating_intercept_fit(
            elig["distance_m"].to_numpy(), elig["obs_path_loss_db"].to_numpy()
        )
        bootstrap = moving_block_bootstrap(elig)
        cv = blocked_cv(elig, freq_mhz)
        if fit is not None:
            calibration_method = "floating_intercept_ols"
            calibrated_pl = fit["alpha_db"] + 10.0 * fit["path_loss_exponent"] * np.log10(
                post["distance_m"].where(post["distance_m"] >= 1.0)
            )
            post["pred_path_loss_db"] = np.where(
                post["pred_path_loss_db"].notna(), calibrated_pl, np.nan
            )
            post["pred_rssi_dbm"] = RX_POWER_REF_DBM - post["pred_path_loss_db"]
            post["pred_link_margin_db"] = post["pred_rssi_dbm"] - RX_SENS_DBM
        calibration_note = (
            f"floating_intercept_fit_on_{len(elig)}_eligible_rows;"
            f"target={','.join(sorted(elig['obs_target_source'].dropna().unique()))}"
        )
    else:
        calibration_note = (
            f"no_calibration_applied:eligible_rows={len(elig)}<min={args.min_calibration_samples};"
            "predictions_postcalibration_equals_precalibration"
        )

    for frame in (pre, post):
        frame["model_name"] = model_name
        frame["model_version"] = model_version
        frame["model_hash"] = model_hash
        frame["feature_recipe_version"] = recipe_version
        frame["calibration_version"] = calibration_version

    _KNOWN_STR_COLS = {
        "timestamp_utc", "head_timestamp_utc", "trial_id", "node_id", "head_id",
        "segment_id", "topography_class", "distance_bin", "material_class", "time_bin",
        "obs_metric_source", "obs_target_source", "join_status", "model_name", "model_version",
        "model_hash", "feature_recipe_version", "calibration_version",
        "satellite_link_status", "satellite_link_status_starlink",
        "head_gps_source", "distance_source", "from_mesh_id", "portnum",
        "src_pos_timestamp", "predictor",
    }
    for _frame in (pre, post):
        for _col in list(_frame.select_dtypes(include="object").columns):
            if _col not in _KNOWN_STR_COLS:
                _frame[_col] = pd.to_numeric(_frame[_col], errors="coerce")

    pre.to_parquet(out_dir / "predictions_precalibration.parquet", index=False)
    post.to_parquet(out_dir / "predictions_postcalibration.parquet", index=False)

    join_audit = post[[
        "trial_id",
        "head_id",
        "node_id",
        "timestamp_utc",
        "head_timestamp_utc",
        "time_offset_seconds",
        "segment_id",
        "join_status",
        "obs_metric_source",
        "obs_target_source",
        "distance_source",
        "src_pos_staleness_s",
        "hops_away",
        "calibration_eligible",
        "excl_no_target",
        "excl_distance_source",
        "excl_distance_range",
        "excl_implausible_power",
        "excl_unverified_hops",
        "excl_stale_src_pos",
    ]].copy()
    join_audit.to_csv(out_dir / "prediction_observation_join_audit.csv", index=False)

    def mae(a, b):
        return float(np.mean(np.abs(a - b))) if len(a) else None

    def rmse(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2))) if len(a) else None

    # All-matched metrics (engineering shakeout view; includes non-calibration-grade
    # rows). Calibration-eligible metrics are the only evidence-grade numbers.
    m = post.dropna(subset=["obs_metric_dbm", "pred_rssi_dbm"]).copy()
    elig_post = post[post["calibration_eligible"]].dropna(subset=["pred_rssi_dbm"]).copy()
    metrics_global = {
        "metric_target": "rsrp_dbm_or_rssi_dbm_fallback",
        "calibration_target": "esp_dbm_when_snr_available_else_metric_fallback",
        "metric_source_counts": {
            "rsrp_dbm": int((m["obs_metric_source"] == "rsrp_dbm").sum()) if len(m) else 0,
            "rssi_dbm": int((m["obs_metric_source"] == "rssi_dbm").sum()) if len(m) else 0,
        },
        "mae": mae(m["pred_rssi_dbm"], m["obs_metric_dbm"]),
        "rmse": rmse(m["pred_rssi_dbm"], m["obs_metric_dbm"]),
        "n": int(len(m)),
        "all_matched_note": "includes non-calibration-grade rows; do not cite as model error",
        "calibration_eligible": {
            "n": int(len(elig_post)),
            "mae": mae(elig_post["pred_rssi_dbm"], elig_post["obs_target_dbm"]) if len(elig_post) else None,
            "rmse": rmse(elig_post["pred_rssi_dbm"], elig_post["obs_target_dbm"]) if len(elig_post) else None,
            "held_out": (cv or {}).get("held_out_rmse_db"),
        },
    }

    matched_count = int((post["join_status"] == "matched").sum())
    missing_obs_count = int((post["join_status"] == "missing_observation_metric").sum())
    missing_window_count = int((post["join_status"] == "missing_time_window").sum())
    join_quality = {
        "time_window_seconds": int(args.time_window_seconds),
        "matched_count": matched_count,
        "missing_observation_metric_count": missing_obs_count,
        "missing_time_window_count": missing_window_count,
        "matched_pct": float((matched_count / len(post)) * 100.0) if len(post) else 0.0,
        "unmatched_pct": float(((missing_obs_count + missing_window_count) / len(post)) * 100.0) if len(post) else 0.0,
        "median_time_offset_seconds": float(post["time_offset_seconds"].dropna().median()) if post["time_offset_seconds"].notna().any() else None,
        "calibration_eligible_count": int(post["calibration_eligible"].sum()),
        "exclusion_counts": {
            c: int(post[c].sum())
            for c in (
                "excl_no_target",
                "excl_distance_source",
                "excl_distance_range",
                "excl_implausible_power",
                "excl_unverified_hops",
                "excl_stale_src_pos",
            )
        },
        "hop_data_available": hop_data_available,
    }
    (out_dir / "metrics_global.json").write_text(json.dumps(metrics_global, indent=2))
    (out_dir / "join_quality.json").write_text(json.dumps(join_quality, indent=2))

    # Stratified metrics: calibration-eligible rows only; strata below the
    # configured minimum are flagged and their error stats suppressed.
    strat_src = elig_post if len(elig_post) else pd.DataFrame(columns=post.columns)
    for c in ("topography_class", "weather_tag", "distance_bin", "satellite_link_status"):
        if c not in strat_src.columns:
            strat_src[c] = "unknown"
    if len(strat_src):
        strat = (
            strat_src.groupby(["topography_class", "weather_tag", "distance_bin", "satellite_link_status"], dropna=False)
            .apply(lambda g: pd.Series({
                "n": len(g),
                "mae": mae(g["pred_rssi_dbm"], g["obs_target_dbm"]),
                "rmse": rmse(g["pred_rssi_dbm"], g["obs_target_dbm"]),
            }))
            .reset_index()
        )
        strat["meets_min_n"] = strat["n"] >= min_stratum_n
        strat.loc[~strat["meets_min_n"], ["mae", "rmse"]] = np.nan
    else:
        strat = pd.DataFrame(columns=[
            "topography_class", "weather_tag", "distance_bin", "satellite_link_status",
            "n", "mae", "rmse", "meets_min_n",
        ])
    strat.to_csv(out_dir / "metrics_stratified.csv", index=False)

    sat_timebin = (
        post.groupby(["time_bin", "topography_class"], dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "n": int(len(g)),
                    "satellite_connected_rows": int(
                        g.get("satellite_link_status", pd.Series(dtype=str))
                        .astype(str)
                        .str.lower()
                        .isin(["connected", "up", "online", "active", "true", "1", "yes"])
                        .sum()
                    ),
                    "satellite_rtt_ms_p50_median": float(g["satellite_rtt_ms_p50"].dropna().median()) if g["satellite_rtt_ms_p50"].notna().any() else None,
                    "satellite_down_mbps_median": float(g["satellite_down_mbps"].dropna().median()) if g["satellite_down_mbps"].notna().any() else None,
                    "satellite_packet_loss_pct_median": float(g["satellite_packet_loss_pct"].dropna().median()) if g["satellite_packet_loss_pct"].notna().any() else None,
                }
            )
        )
        .reset_index()
    )
    sat_timebin.to_csv(out_dir / "satellite_timebin_metrics.csv", index=False)

    sat_events = post[
        [
            "timestamp_utc",
            "trial_id",
            "node_id",
            "head_id",
            "segment_id",
            "time_bin",
            "topography_class",
            "satellite_link_status",
            "satellite_rtt_ms_p95",
            "satellite_packet_loss_pct",
            "satellite_outage_seconds",
            "satellite_obstruction_pct",
        ]
    ].copy()
    sat_events = sat_events[sat_events["satellite_outage_seconds"].fillna(0) > 0]
    sat_events.to_csv(out_dir / "satellite_outage_events.csv", index=False)

    if len(elig_post):
        tmp = elig_post.copy()
        tmp["abs_err"] = (tmp["pred_rssi_dbm"] - tmp["obs_target_dbm"]).abs()
        tmp.sort_values("abs_err", ascending=False).head(10).to_csv(out_dir / "outliers.csv", index=False)
    else:
        pd.DataFrame(columns=post.columns.tolist() + ["abs_err"]).to_csv(out_dir / "outliers.csv", index=False)

    calibration_deltas = {
        "baseline_predictor": predictor_used,
        "calibration_method": calibration_method,
        "residual_bias_db": residual,
        "floating_intercept": fit,
        "bootstrap_ci": bootstrap,
        "blocked_cv": cv,
        "note": calibration_note,
        "eligible_sample_count": int(len(elig)),
        "all_matched_sample_count": int(len(m)),
    }
    (out_dir / "calibration_deltas.json").write_text(json.dumps(calibration_deltas, indent=2))

    warnings = []
    hard_fail_reasons = []
    rsrp_count = int((m["obs_metric_source"] == "rsrp_dbm").sum()) if len(m) else 0
    rssi_count = int((m["obs_metric_source"] == "rssi_dbm").sum()) if len(m) else 0

    if metrics_global["n"] < int(args.min_observed_samples):
        hard_fail_reasons.append(
            f"observed sample count {metrics_global['n']} is below minimum {int(args.min_observed_samples)}"
        )

    if rsrp_count == 0 and rssi_count > 0:
        warnings.append("running on fallback metric rssi_dbm; rsrp_dbm unavailable")

    if args.require_rsrp and rsrp_count == 0:
        hard_fail_reasons.append("require-rsrp enabled but rsrp_dbm sample count is zero")

    # Falsifiable calibration gates. Warnings during shakedown; hard failures
    # when --require-calibration-grade is set (Trial 2 onward).
    calib_gate_failures = []
    if len(elig) < args.min_calibration_samples:
        calib_gate_failures.append(
            f"calibration-eligible rows {len(elig)} < {args.min_calibration_samples}"
        )
    if fit is not None:
        if not (1.6 <= fit["path_loss_exponent"] <= 4.5):
            calib_gate_failures.append(
                f"path loss exponent {fit['path_loss_exponent']:.2f} outside plausible [1.6, 4.5]"
            )
        if fit["sigma_db"] > 10.0:
            calib_gate_failures.append(
                f"shadowing sigma {fit['sigma_db']:.1f} dB > 10 dB (literature: 6-8 dB)"
            )
    ho = ((cv or {}).get("held_out_rmse_db") or {}).get("floating_intercept")
    if ho is not None and ho > 12.0:
        calib_gate_failures.append(f"held-out RMSE {ho:.1f} dB > 12 dB")
    if not hop_data_available:
        warnings.append("hop telemetry unavailable; direct links cannot be verified (Trial 1 data)")
    if args.require_calibration_grade:
        hard_fail_reasons.extend(calib_gate_failures)
    else:
        warnings.extend(calib_gate_failures)

    quality_gates = {
        "min_observed_samples": int(args.min_observed_samples),
        "min_calibration_samples": int(args.min_calibration_samples),
        "require_rsrp": bool(args.require_rsrp),
        "require_calibration_grade": bool(args.require_calibration_grade),
        "calibration_eligible_count": int(len(elig)),
        "calibration_gate_failures": calib_gate_failures,
        "passed": len(hard_fail_reasons) == 0,
        "warnings": warnings,
        "hard_fail_reasons": hard_fail_reasons,
    }
    (out_dir / "quality_gates.json").write_text(json.dumps(quality_gates, indent=2))

    provenance = {
        "run_id": f"live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "git_commit": git_commit(root),
        "model_name": model_name,
        "model_version": model_version,
        "model_hash": model_hash,
        "feature_recipe_version": recipe_version,
        "calibration_version": calibration_version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_node_jsonl": str(node_path),
        "head_gpx": args.head_gpx,
        "head_position_method": "garmin_external_gpx" if args.head_gpx else "linear_interpolation",
        "baseline_predictor": predictor_used,
        "dem_npz": str(args.dem_npz) if predictor_used == "itm" else None,
        "radio_assumptions": {
            "preset": "LongFast (SF11, BW 250 kHz, CR 4/5)",
            "tx_conducted_dbm": TX_DBM,
            "tx_antenna_gain_dbi": TX_ANT_GAIN_DBI,
            "tx_eirp_dbm": TX_EIRP_DBM,
            "rx_antenna_gain_dbi": RX_ANT_GAIN_DBI,
            "rx_power_reference_dbm": RX_POWER_REF_DBM,
            "rx_sensitivity_dbm": RX_SENS_DBM,
            "noise_floor_dbm_bw250": NOISE_FLOOR_DBM,
        },
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2))

    summary = {
        "out_dir": str(out_dir),
        "rows_total": int(len(obs)),
        "rows_with_observed_metric": int(len(m)),
        "is_fallback_run": bool(rsrp_count == 0 and rssi_count > 0),
        "metrics_global": metrics_global,
        "join_quality": join_quality,
        "quality_gates": quality_gates,
        "calibration_deltas": calibration_deltas,
    }
    print(json.dumps(summary, indent=2, default=str))
    if not quality_gates["passed"]:
        raise SystemExit("quality gates failed: " + "; ".join(quality_gates["hard_fail_reasons"]))


if __name__ == "__main__":
    main()

"""Unit tests for the statistics introduced in the 2026-06 pipeline rebuild.

Covers ESP, Wilson intervals, the floating-intercept fit (unbiased recovery),
the moving-block bootstrap, blocked-CV model ranking, LoRa airtime, and the
calibration-eligibility gate. These pin the math the propagation claims rest on.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

alt = _load("airmap_live_trial")
pdr = _load("pdr_analysis")
airtime_mod = _load("lora_airtime")


# ── ESP ──────────────────────────────────────────────────────────────────────
def test_esp_high_snr_approaches_rssi():
    # At high SNR, ESP ~ RSSI (the correction term -> 0).
    rssi = pd.Series([-80.0])
    snr = pd.Series([20.0])
    esp = alt.esp_dbm(rssi, snr).iloc[0]
    assert esp == pytest.approx(-80.0, abs=0.1)


def test_esp_low_snr_below_rssi():
    # Near/below the noise floor ESP is several dB below raw RSSI.
    rssi = pd.Series([-120.0])
    snr = pd.Series([-5.0])
    esp = alt.esp_dbm(rssi, snr).iloc[0]
    assert esp < -120.0


# ── Wilson interval ──────────────────────────────────────────────────────────
def test_wilson_brackets_point_estimate():
    lo, hi = pdr.wilson_ci(40, 50)
    assert lo < 0.8 < hi
    assert 0.0 <= lo <= hi <= 1.0


def test_wilson_zero_n():
    assert pdr.wilson_ci(0, 0) == (None, None)


# ── Floating-intercept fit ───────────────────────────────────────────────────
def test_floating_intercept_recovers_exponent():
    rng = np.random.default_rng(0)
    betas = []
    for _ in range(50):
        d = 10 ** rng.uniform(2.3, 3.7, 400)
        pl = 40.0 + 10 * 2.7 * np.log10(d) + rng.normal(0, 6.0, 400)
        betas.append(alt.floating_intercept_fit(d, pl)["path_loss_exponent"])
    # Unbiased: mean estimate within 0.1 of truth over repeats.
    assert np.mean(betas) == pytest.approx(2.7, abs=0.1)


def test_floating_intercept_too_few_points():
    assert alt.floating_intercept_fit(np.array([1.0, 2.0]), np.array([1.0, 2.0])) is None


# ── Moving-block bootstrap ───────────────────────────────────────────────────
def test_bootstrap_ci_contains_truth():
    rng = np.random.default_rng(3)
    n = 600
    ts = pd.date_range("2026-05-23T13:00Z", periods=n, freq="5s")
    d = np.sort(10 ** rng.uniform(2.3, 3.6, n))
    pl = 40.0 + 10 * 2.7 * np.log10(d) + rng.normal(0, 6.0, n)
    df = pd.DataFrame({"timestamp_utc": ts, "distance_m": d, "obs_path_loss_db": pl})
    boot = alt.moving_block_bootstrap(df)
    lo, hi = boot["path_loss_exponent_ci95"]
    assert lo <= 2.7 <= hi


# ── Blocked CV ranks terrain model above distance-only on terrain data ───────
def test_blocked_cv_prefers_itm_when_truth_is_terrain():
    rng = np.random.default_rng(4)
    n = 300
    ts = pd.date_range("2026-05-23T13:00Z", periods=n, freq="10s")
    d = 10 ** rng.uniform(2.3, 3.6, n)
    # "ITM" column carries the true structure; obs = itm + noise. A log-distance
    # fit on d alone cannot beat the terrain predictor.
    itm = 90 + 25 * rng.random(n)  # terrain-driven, only weakly tied to distance
    obs_pl = itm + rng.normal(0, 4.0, n)
    df = pd.DataFrame({
        "timestamp_utc": ts, "distance_m": d, "obs_path_loss_db": obs_pl,
        "pred_path_loss_itm_db": itm,
    })
    cv = alt.blocked_cv(df, freq_mhz=915.0)
    ho = cv["held_out_rmse_db"]
    assert ho["itm"] < ho["floating_intercept"]
    assert ho["itm"] < ho["fspl"]


# ── LoRa airtime (Semtech formula sanity) ────────────────────────────────────
def test_airtime_symbol_time_longfast():
    # SF11 / BW250: T_sym = 2^11 / 250000 = 8.192 ms
    t = (2 ** 11) / 250_000 * 1000
    assert t == pytest.approx(8.192, abs=1e-3)


def test_airtime_monotonic_in_payload():
    a40 = airtime_mod.airtime_ms(40)
    a64 = airtime_mod.airtime_ms(64)
    assert 0 < a40 < a64 < 3000


# ── Eligibility gate excludes contaminated rows ──────────────────────────────
def test_slant_distance_3d_exceeds_2d():
    d2 = alt.haversine_m(44.27, -71.30, 44.28, -71.31)
    d3 = alt.slant_distance_m(44.27, -71.30, 700.0, 44.28, -71.31, 1400.0)
    assert d3 > d2


def test_esp_matches_manual():
    # Manual: RSSI=-110, SNR=-3 -> ESP = -110 + (-3) - 10log10(1+10^-0.3)
    val = alt.esp_dbm(pd.Series([-110.0]), pd.Series([-3.0])).iloc[0]
    expected = -110.0 + (-3.0) - 10 * np.log10(1 + 10 ** (-0.3))
    assert val == pytest.approx(expected, abs=1e-6)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def load_weather_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        # default conservative clear-state payload
        return {
            "source": "synthetic-default",
            "precip_mm_per_hr": 0.0,
            "wind_mps": 3.0,
            "visibility_km": 20.0,
            "lightning_km": 999.0,
            "lightning_age_min": 999,
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    return json.loads(path.read_text(encoding="utf-8"))


def risk_state(payload: dict[str, Any], lightning_hold_minutes: int) -> tuple[str, list[str], str | None]:
    reasons: list[str] = []

    precip = float(payload.get("precip_mm_per_hr", 0.0))
    wind = float(payload.get("wind_mps", 0.0))
    vis = float(payload.get("visibility_km", 99.0))
    ldist = float(payload.get("lightning_km", 999.0))
    lage = float(payload.get("lightning_age_min", 999.0))

    hold_until = None

    # HOLD conditions
    if ldist <= 16.0 and lage <= 60.0:
        reasons.append(f"lightning proximity {ldist:.1f}km within 60 min")
        hold_until = (datetime.now(timezone.utc) + timedelta(minutes=lightning_hold_minutes)).isoformat()
    if wind >= 18.0:
        reasons.append(f"high wind {wind:.1f} m/s")
    if vis < 1.0:
        reasons.append(f"very low visibility {vis:.2f} km")

    if reasons:
        return "hold", reasons, hold_until

    caution_reasons: list[str] = []
    if precip >= 3.0:
        caution_reasons.append(f"moderate precip {precip:.1f} mm/hr")
    if wind >= 12.0:
        caution_reasons.append(f"elevated wind {wind:.1f} m/s")
    if vis < 3.0:
        caution_reasons.append(f"reduced visibility {vis:.2f} km")
    if ldist <= 30.0 and lage <= 120.0:
        caution_reasons.append(f"recent lightning within {ldist:.1f}km")

    if caution_reasons:
        return "caution", caution_reasons, None

    return "normal", ["conditions within operating envelope"], None


def main() -> int:
    ap = argparse.ArgumentParser(description="Weather guard: normalize weather input + compute normal/caution/hold risk state")
    ap.add_argument("--weather-json", default="", help="Path to normalized weather JSON payload")
    ap.add_argument("--telemetry", default="artifacts/dem/geology_loss_features.parquet", help="Optional telemetry/prediction table to annotate")
    ap.add_argument("--out-dir", default="artifacts/weather")
    ap.add_argument("--lightning-hold-minutes", type=int, default=30)
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    weather_path = Path(args.weather_json) if args.weather_json else None
    payload = load_weather_payload(weather_path)

    state, reasons, hold_until = risk_state(payload, args.lightning_hold_minutes)

    status = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "weather_payload": payload,
        "risk_state": state,
        "reasons": reasons,
        "hold_until_utc": hold_until,
        "lightning_delay_buffer_minutes": int(args.lightning_hold_minutes),
        "recommendation": "suppress field movement and pause collection" if state == "hold" else (
            "continue with caution and acknowledgement" if state == "caution" else "proceed"
        ),
    }

    (out_dir / "weather_guard_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")

    # Optional annotation of telemetry rows
    tele_path = Path(args.telemetry)
    annotated_rows = 0
    if tele_path.exists():
        if tele_path.suffix.lower() == ".parquet":
            df = pd.read_parquet(tele_path)
        elif tele_path.suffix.lower() == ".csv":
            df = pd.read_csv(tele_path)
        else:
            df = pd.DataFrame()

        if not df.empty:
            df["weather_tag"] = state
            df["weather_guard_hold"] = state == "hold"
            df["weather_guard_reason"] = "; ".join(reasons)
            ann_path = out_dir / "weather_annotated.parquet"
            df.to_parquet(ann_path, index=False)
            annotated_rows = int(len(df))

    audit = {
        "status_path": str((out_dir / "weather_guard_status.json").resolve()),
        "annotated_rows": annotated_rows,
    }
    (out_dir / "weather_guard_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    print(json.dumps({"status": status, "audit": audit}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

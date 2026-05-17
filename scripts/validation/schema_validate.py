#!/usr/bin/env python3
"""Validate JSONL telemetry records against canonical schema rules.

Usage:
  python3 scripts/validation/schema_validate.py \
      --input /path/to/telemetry_stream.jsonl \
      --output artifacts/reports/schema_validation.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def is_iso8601_utc(value: str) -> bool:
    try:
        # supports trailing Z and offset forms
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


REQUIRED = ["timestamp_utc", "trial_id", "node_id", "head_id", "line"]

RANGES: dict[str, tuple[float, float]] = {
    "battery_mv": (0, 20000),
    "battery_pct": (0, 100),
    "usb_power": (0, 1),
    "is_charging": (0, 1),
    "rssi_dbm": (-200, 50),
    "rsrp_dbm": (-200, 50),
    "snr_db": (-40, 40),
    "lat": (-90, 90),
    "lon": (-180, 180),
    "elev_m": (-1000, 12000),
    "checksum_ok": (0, 1),
    "checksum_bad": (0, 1),
    "malformed_frame": (0, 1),
}

INT_FIELDS = {"battery_mv", "battery_pct", "usb_power", "is_charging", "rssi_dbm", "checksum_ok", "checksum_bad", "malformed_frame"}


def validate_record(rec: dict[str, Any], line_no: int) -> list[str]:
    errs: list[str] = []

    for field in REQUIRED:
        if field not in rec:
            errs.append(f"missing_required:{field}")
        elif isinstance(rec[field], str) and not rec[field].strip():
            errs.append(f"empty_required:{field}")

    ts = rec.get("timestamp_utc")
    if ts is not None and (not isinstance(ts, str) or not is_iso8601_utc(ts)):
        errs.append("invalid_timestamp_utc")

    for field, (lo, hi) in RANGES.items():
        if field not in rec:
            continue
        val = rec[field]
        if val is None:
            continue
        if not isinstance(val, (int, float)):
            errs.append(f"type_error:{field}")
            continue
        if field in INT_FIELDS and not isinstance(val, int):
            errs.append(f"int_required:{field}")
        if val < lo or val > hi:
            errs.append(f"range_error:{field}:{val}")

    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to telemetry JSONL")
    ap.add_argument("--output", required=True, help="Path to JSON validation report")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    valid = 0
    invalid = 0
    error_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    if not in_path.exists():
        report = {
            "ok": False,
            "error": "input_not_found",
            "input": str(in_path),
        }
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 2

    with in_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            total += 1
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                invalid += 1
                key = "json_decode_error"
                error_counts[key] = error_counts.get(key, 0) + 1
                if len(samples) < 20:
                    samples.append({"line": line_no, "errors": [key]})
                continue

            errs = validate_record(rec, line_no)
            if errs:
                invalid += 1
                for e in errs:
                    error_counts[e] = error_counts.get(e, 0) + 1
                if len(samples) < 20:
                    samples.append({"line": line_no, "errors": errs})
            else:
                valid += 1

    pass_rate = (valid / total) if total else 0.0
    report = {
        "ok": invalid == 0,
        "input": str(in_path),
        "total_records": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "pass_rate": round(pass_rate, 6),
        "error_counts": error_counts,
        "sample_errors": samples,
    }

    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if invalid == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

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
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_iso8601_utc(value: str) -> bool:
    try:
        if not (value.endswith("Z") or value.endswith("+00:00")):
            return False
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
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
    "hop_limit": (0, 7),
    "hop_start": (0, 7),
    "hops_away": (0, 7),
    "gps_pdop": (0, 100),
    "channel_util_pct": (0, 100),
    "air_util_tx_pct": (0, 100),
    "satellite_rtt_ms_p50": (0, 100000),
    "satellite_rtt_ms_p95": (0, 100000),
    "satellite_down_mbps": (0, 10000),
    "satellite_up_mbps": (0, 10000),
    "satellite_packet_loss_pct": (0, 100),
    "satellite_obstruction_pct": (0, 100),
    "satellite_outage_seconds": (0, 86400),
}

INT_FIELDS = {"battery_mv", "battery_pct", "usb_power", "is_charging", "rssi_dbm", "checksum_ok", "checksum_bad", "malformed_frame", "hop_limit", "hop_start", "hops_away"}
NON_NULLABLE_NUMERIC_FIELDS = {"checksum_ok", "checksum_bad", "malformed_frame"}

STRING_FIELDS = {
    "timestamp_utc",
    "trial_id",
    "node_id",
    "head_id",
    "line",
    "satellite_link_status",
    "weather_tag",
}


def write_report(path: Path, report: dict[str, Any]) -> None:
    rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if path == Path("/dev/null"):
        path.write_text(rendered, encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def validate_record(rec: Any, line_no: int = 0) -> list[str]:
    errs: list[str] = []

    if not isinstance(rec, dict):
        return ["record_not_object"]

    for field in REQUIRED:
        if field not in rec:
            errs.append(f"missing_required:{field}")
        elif not isinstance(rec[field], str):
            errs.append(f"type_error:{field}")
        elif not rec[field].strip():
            errs.append(f"empty_required:{field}")

    ts = rec.get("timestamp_utc")
    if ts is not None and (not isinstance(ts, str) or not is_iso8601_utc(ts)):
        errs.append("invalid_timestamp_utc")

    for field, (lo, hi) in RANGES.items():
        if field not in rec:
            continue
        val = rec[field]
        if val is None:
            if field in NON_NULLABLE_NUMERIC_FIELDS:
                errs.append(f"type_error:{field}")
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            errs.append(f"type_error:{field}")
            continue
        if isinstance(val, float) and not math.isfinite(val):
            errs.append(f"nonfinite:{field}")
            continue
        if field in INT_FIELDS and not isinstance(val, int):
            errs.append(f"int_required:{field}")
        if val < lo or val > hi:
            errs.append(f"range_error:{field}:{val}")

    for field in STRING_FIELDS - set(REQUIRED):
        val = rec.get(field)
        if val is not None and not isinstance(val, str):
            errs.append(f"type_error:{field}")

    status = rec.get("satellite_link_status")
    if isinstance(status, str) and status not in {"connected", "degraded", "disconnected", "unknown"}:
        errs.append(f"enum_error:satellite_link_status:{status}")

    own_node = rec.get("is_own_node")
    if own_node is not None and not isinstance(own_node, bool):
        errs.append("type_error:is_own_node")

    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to telemetry JSONL")
    ap.add_argument("--output", required=True, help="Path to JSON validation report")
    ap.add_argument(
        "--allow-truncated-final-line",
        action="store_true",
        help="Ignore one malformed final record only when the file does not end in a newline",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    total = 0
    valid = 0
    parse_errors = 0
    ignored_truncated_final = 0
    data_invalid = 0
    error_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    if not in_path.exists():
        report = {
            "ok": False,
            "error": "input_not_found",
            "input": str(in_path),
        }
        write_report(out_path, report)
        print(json.dumps(report, indent=2))
        return 2

    initial_stat = in_path.stat()
    file_size = initial_stat.st_size
    with in_path.open("rb") as f:
        for line_no, raw_bytes in enumerate(f, start=1):
            ends_with_newline = raw_bytes.endswith(b"\n")
            is_physical_final = f.tell() == file_size
            raw_bytes = raw_bytes.strip()
            if not raw_bytes:
                continue
            total += 1
            try:
                raw = raw_bytes.decode("utf-8", errors="strict")
                rec = json.loads(raw, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                if args.allow_truncated_final_line and is_physical_final and not ends_with_newline:
                    ignored_truncated_final += 1
                    continue
                parse_errors += 1
                key = "json_decode_error"
                error_counts[key] = error_counts.get(key, 0) + 1
                if len(samples) < 20:
                    samples.append({"line": line_no, "errors": [key]})
                continue

            errs = validate_record(rec, line_no)
            if errs:
                data_invalid += 1
                for e in errs:
                    error_counts[e] = error_counts.get(e, 0) + 1
                if len(samples) < 20:
                    samples.append({"line": line_no, "errors": errs})
            else:
                valid += 1

    final_stat = in_path.stat()
    input_changed = (
        final_stat.st_dev != initial_stat.st_dev
        or final_stat.st_ino != initial_stat.st_ino
        or final_stat.st_size != initial_stat.st_size
        or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
    )
    if input_changed:
        error_counts["input_changed_during_validation"] = 1

    invalid = data_invalid + parse_errors
    evaluated = total - ignored_truncated_final
    pass_rate = (valid / evaluated) if evaluated else 0.0
    ok = evaluated > 0 and invalid == 0 and not input_changed
    report = {
        "ok": ok,
        "input": str(in_path),
        "total_records": total,
        "valid_records": valid,
        "invalid_records": invalid,
        "data_invalid_records": data_invalid,
        "parse_error_records": parse_errors,
        "ignored_truncated_final_records": ignored_truncated_final,
        "input_changed_during_validation": input_changed,
        "pass_rate": round(pass_rate, 6),
        "error_counts": error_counts,
        "sample_errors": samples,
    }

    write_report(out_path, report)
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

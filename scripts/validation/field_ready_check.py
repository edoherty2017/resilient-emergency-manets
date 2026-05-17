#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter


def detect_devices() -> list[str]:
    candidates = []
    for pattern in ["/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*", "/dev/lora_radio"]:
        candidates.extend(sorted(glob.glob(pattern)))
    unique = []
    seen = set()
    for d in candidates:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def jsonl_population(path: str, sample_limit: int = 10000) -> dict:
    total = 0
    nonnull = Counter()
    if not os.path.exists(path):
        return {"exists": False}

    # Use a tail-biased window so we validate current live schema, not historic rows.
    from collections import deque

    tail = deque(maxlen=sample_limit)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tail.append(line)

    for line in tail:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        total += 1
        for k, v in rec.items():
            if v is not None:
                nonnull[k] += 1

    fields = [
        "timestamp_utc",
        "trial_id",
        "node_id",
        "head_id",
        "line",
        "battery_mv",
        "battery_pct",
        "rssi_dbm",
        "snr_db",
        "lat",
        "lon",
        "elev_m",
        "checksum_ok",
        "checksum_bad",
        "malformed_frame",
    ]
    pop = {}
    for k in fields:
        cnt = nonnull.get(k, 0)
        pop[k] = {"nonnull": cnt, "rate": (cnt / total) if total else 0.0}

    return {"exists": True, "records_sampled": total, "population": pop}


def row(name: str, passed: bool, detail: str) -> dict:
    return {"check": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Field-ready validation: device detect + telemetry population + parser integrity + PASS/FAIL matrix"
    )
    ap.add_argument("--jsonl", required=True, help="Path to telemetry JSONL stream")
    ap.add_argument("--min-records", type=int, default=100, help="Minimum sampled records for PASS")
    ap.add_argument("--sample-limit", type=int, default=10000, help="Tail window size for population checks")
    ap.add_argument("--min-core-rate", type=float, default=0.99, help="Min non-null rate for required core fields")
    ap.add_argument("--min-rf-rate", type=float, default=0.01, help="Min non-null rate for RF fields (rssi/snr)")
    ap.add_argument("--min-gps-rate", type=float, default=0.0, help="Min non-null rate for GPS fields (lat/lon)")
    ap.add_argument("--require-gps", action="store_true", help="If set, fail when gps rates are below --min-gps-rate")
    ap.add_argument("--skip-device-check", action="store_true", help="Skip local /dev detection gate")
    args = ap.parse_args()

    matrix = []

    devices = detect_devices()
    if args.skip_device_check:
        matrix.append(row("device_detected", True, f"skipped; detected={len(devices)}"))
    else:
        matrix.append(row("device_detected", len(devices) > 0, f"detected={len(devices)}"))

    pop = jsonl_population(args.jsonl, sample_limit=args.sample_limit)
    if not pop.get("exists"):
        matrix.append(row("jsonl_exists", False, args.jsonl))
        result = {"ok": False, "devices": devices, "population": pop, "matrix": matrix}
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    sampled = int(pop["records_sampled"])
    matrix.append(row("record_volume", sampled >= args.min_records, f"sampled={sampled}, min={args.min_records}"))

    p = pop["population"]

    core_fields = ["timestamp_utc", "trial_id", "node_id", "head_id", "line"]
    core_fails = []
    for f in core_fields:
        rate = float(p.get(f, {}).get("rate", 0.0))
        if rate < args.min_core_rate:
            core_fails.append(f"{f}:{rate:.3f}")
    matrix.append(
        row(
            "core_population",
            len(core_fails) == 0,
            "all >= min_core_rate" if not core_fails else ", ".join(core_fails),
        )
    )

    rf_fields = ["rssi_dbm", "snr_db"]
    rf_fails = []
    for f in rf_fields:
        rate = float(p.get(f, {}).get("rate", 0.0))
        if rate < args.min_rf_rate:
            rf_fails.append(f"{f}:{rate:.3f}")
    matrix.append(row("rf_population", len(rf_fails) == 0, "all >= min_rf_rate" if not rf_fails else ", ".join(rf_fails)))

    gps_fields = ["lat", "lon"]
    gps_fails = []
    for f in gps_fields:
        rate = float(p.get(f, {}).get("rate", 0.0))
        if rate < args.min_gps_rate:
            gps_fails.append(f"{f}:{rate:.3f}")
    gps_ok = len(gps_fails) == 0
    if args.require_gps:
        matrix.append(row("gps_population", gps_ok, "all >= min_gps_rate" if gps_ok else ", ".join(gps_fails)))
    else:
        matrix.append(row("gps_population", True, "advisory-only: " + ("ok" if gps_ok else ", ".join(gps_fails))))

    integrity_fields = ["checksum_ok", "checksum_bad", "malformed_frame"]
    integ_fails = []
    for f in integrity_fields:
        rate = float(p.get(f, {}).get("rate", 0.0))
        if rate < args.min_core_rate:
            integ_fails.append(f"{f}:{rate:.3f}")
    matrix.append(
        row(
            "parser_integrity_fields_present",
            len(integ_fails) == 0,
            "all >= min_core_rate" if not integ_fails else ", ".join(integ_fails),
        )
    )

    ok = all(r["status"] == "PASS" for r in matrix)
    result = {
        "ok": ok,
        "devices": devices,
        "population": pop,
        "matrix": matrix,
        "parameters": {
            "min_records": args.min_records,
            "sample_limit": args.sample_limit,
            "min_core_rate": args.min_core_rate,
            "min_rf_rate": args.min_rf_rate,
            "min_gps_rate": args.min_gps_rate,
            "require_gps": args.require_gps,
            "skip_device_check": args.skip_device_check,
        },
    }
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

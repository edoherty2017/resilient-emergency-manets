#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def parse_ts(s: str) -> datetime | None:
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def tail_lines(path: Path, n: int = 200) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        block = 8192
        data = b""
        while end > 0 and data.count(b"\n") <= n:
            read = min(block, end)
            end -= read
            f.seek(end)
            data = f.read(read) + data
        return data.decode("utf-8", errors="ignore").splitlines()[-n:]


def last_jsonl_timestamp(path: Path) -> datetime | None:
    for line in reversed(tail_lines(path, 1000)):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_ts(str(obj.get("timestamp_utc", "")))
        if ts:
            return ts
    return None


def last_pull_timestamp(path: Path) -> datetime | None:
    pattern = re.compile(r"^(\S+)\s+pull ok")
    last = None
    for line in tail_lines(path, 1000):
        m = pattern.search(line)
        if not m:
            continue
        ts = parse_ts(m.group(1))
        if ts:
            last = ts
    return last


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    c = 0
    with path.open("rb") as f:
        for _ in f:
            c += 1
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--stale-minutes", type=int, default=10)
    ap.add_argument("--state-file", default="/home/doher/projects/manet/resilient-emergency-manets/artifacts/health/ingest_state.json")
    args = ap.parse_args()

    ingest_root = Path(args.ingest_root)
    hiker_jsonl = ingest_root / "meshhikernode1/jsonl/telemetry_stream.jsonl"
    pull_log = ingest_root / "pull_from_head.log"

    now = datetime.now(timezone.utc)
    last_hiker_sync = last_jsonl_timestamp(hiker_jsonl)
    last_doher_pull = last_pull_timestamp(pull_log)

    current = {
        "timestamp_utc": now.isoformat(),
        "hiker_jsonl_bytes": hiker_jsonl.stat().st_size if hiker_jsonl.exists() else 0,
        "hiker_jsonl_lines": count_lines(hiker_jsonl),
        "pull_log_bytes": pull_log.stat().st_size if pull_log.exists() else 0,
        "pull_log_lines": count_lines(pull_log),
    }

    state_path = Path(args.state_file)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    previous = {}
    if state_path.exists():
        previous = json.loads(state_path.read_text())

    backlog_growth = {
        "hiker_jsonl_bytes_delta": current["hiker_jsonl_bytes"] - int(previous.get("hiker_jsonl_bytes", 0)),
        "hiker_jsonl_lines_delta": current["hiker_jsonl_lines"] - int(previous.get("hiker_jsonl_lines", 0)),
        "pull_log_bytes_delta": current["pull_log_bytes"] - int(previous.get("pull_log_bytes", 0)),
        "pull_log_lines_delta": current["pull_log_lines"] - int(previous.get("pull_log_lines", 0)),
    }

    stale_seconds = args.stale_minutes * 60
    alerts = []
    if last_hiker_sync and (now - last_hiker_sync).total_seconds() > stale_seconds:
        alerts.append(f"hiker sync stale > {args.stale_minutes}m")
    if last_doher_pull and (now - last_doher_pull).total_seconds() > stale_seconds:
        alerts.append(f"doher pull stale > {args.stale_minutes}m")
    if not last_hiker_sync:
        alerts.append("no hiker sync timestamp found")
    if not last_doher_pull:
        alerts.append("no doher pull timestamp found")

    report = {
        "generated_at_utc": now.isoformat(),
        "last_successful_hiker_sync_timestamp": last_hiker_sync.isoformat() if last_hiker_sync else None,
        "last_successful_doher_pull_timestamp": last_doher_pull.isoformat() if last_doher_pull else None,
        "backlog_growth": backlog_growth,
        "stale_threshold_minutes": args.stale_minutes,
        "alerts": alerts,
        "status": "ALERT" if alerts else "OK",
    }

    state_path.write_text(json.dumps(current, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

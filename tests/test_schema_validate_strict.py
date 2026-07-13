from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validation" / "schema_validate.py"


def valid_record() -> dict:
    return {
        "timestamp_utc": "2026-07-13T12:00:00Z",
        "trial_id": "trial-live",
        "node_id": "meshnode1",
        "head_id": "meshradiohead2",
        "line": "decoded protobuf",
    }


def run_validator(tmp_path: Path, payload: bytes, *extra: str):
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "report.json"
    input_path.write_bytes(payload)
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--input", str(input_path), "--output", str(output_path), *extra],
        capture_output=True,
        text=True,
    )
    return result, json.loads(output_path.read_text())


def test_empty_stream_fails(tmp_path):
    result, report = run_validator(tmp_path, b"")
    assert result.returncode == 1
    assert report["ok"] is False
    assert report["total_records"] == 0


def test_corrupt_and_non_utf8_records_fail(tmp_path):
    good = json.dumps(valid_record()).encode() + b"\n"
    result, report = run_validator(tmp_path, good + b"not-json\n\xff\n")
    assert result.returncode == 1
    assert report["parse_error_records"] == 2


def test_nan_and_infinity_fail_json_parsing(tmp_path):
    record = valid_record()
    prefix = json.dumps(record)[:-1]
    payload = (prefix + ',"snr_db":NaN}\n' + prefix + ',"snr_db":Infinity}\n').encode()
    result, report = run_validator(tmp_path, payload)
    assert result.returncode == 1
    assert report["parse_error_records"] == 2


def test_battery_sentinels_outside_schema_fail(tmp_path):
    records = []
    for value in (-1, 101):
        record = valid_record()
        record["battery_pct"] = value
        records.append(json.dumps(record))
    result, report = run_validator(tmp_path, ("\n".join(records) + "\n").encode())
    assert result.returncode == 1
    assert report["data_invalid_records"] == 2


def test_timestamp_must_be_utc(tmp_path):
    record = valid_record()
    record["timestamp_utc"] = "2026-07-13T13:00:00+01:00"
    result, report = run_validator(tmp_path, (json.dumps(record) + "\n").encode())
    assert result.returncode == 1
    assert report["error_counts"]["invalid_timestamp_utc"] == 1


def test_timestamp_must_use_canonical_utc_suffix(tmp_path):
    record = valid_record()
    record["timestamp_utc"] = "2026-07-13T12:00:00-00:00"
    result, report = run_validator(tmp_path, (json.dumps(record) + "\n").encode())

    assert result.returncode == 1
    assert report["error_counts"]["invalid_timestamp_utc"] == 1


def test_partial_final_record_requires_explicit_opt_in(tmp_path):
    good = (json.dumps(valid_record()) + "\n").encode()
    payload = good + b'{"timestamp_utc":'
    strict_result, strict_report = run_validator(tmp_path, payload)
    allowed_result, allowed_report = run_validator(tmp_path, payload, "--allow-truncated-final-line")
    assert strict_result.returncode == 1
    assert strict_report["parse_error_records"] == 1
    assert allowed_result.returncode == 0
    assert allowed_report["ignored_truncated_final_records"] == 1


def test_satellite_status_and_metrics_are_validated(tmp_path):
    record = valid_record()
    record["satellite_link_status"] = "RPC_FAILED_BUT_CALL_IT_DISCONNECTED"
    record["satellite_packet_loss_pct"] = 150
    result, report = run_validator(tmp_path, (json.dumps(record) + "\n").encode())

    assert result.returncode == 1
    assert any(key.startswith("enum_error:satellite_link_status") for key in report["error_counts"])
    assert any(key.startswith("range_error:satellite_packet_loss_pct") for key in report["error_counts"])


def test_nonnullable_integrity_flags_reject_null(tmp_path):
    record = valid_record()
    record["checksum_ok"] = None
    result, report = run_validator(tmp_path, (json.dumps(record) + "\n").encode())

    assert result.returncode == 1
    assert report["error_counts"]["type_error:checksum_ok"] == 1

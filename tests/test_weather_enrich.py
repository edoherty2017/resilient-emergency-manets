from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from weather_enrich import fetch_hourly  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.content = json.dumps(payload, sort_keys=True).encode()
        self.url = "https://archive-api.open-meteo.com/pinned-request"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def payload(required_value_missing: bool = False) -> dict:
    missing = None if required_value_missing else 0.0
    return {
        "elevation": 1917.0,
        "hourly_units": {"wind_speed_10m": "km/h"},
        "hourly": {
            "time": ["2026-05-23T00:00"],
            "temperature_2m": [4.0],
            "precipitation": [missing],
            "wind_speed_10m": [8.0],
            "visibility": [None],
            "weather_code": [0],
        },
    }


def test_fetch_hourly_records_pinned_model_and_provenance(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse(payload()))
    frame, source = fetch_hourly(44.27, -71.30, 1917.0, "2026-05-23", "2026-05-23", "era5")
    assert len(frame) == 1
    assert source["model_requested"] == "era5"
    assert source["kind"] == "reanalysis"
    assert source["not_station_measurements"] is True
    assert len(source["response_sha256"]) == 64


def test_fetch_hourly_rejects_missing_required_values(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload(required_value_missing=True)),
    )
    with pytest.raises(ValueError, match="missing required hourly values"):
        fetch_hourly(44.27, -71.30, 1917.0, "2026-05-23", "2026-05-23", "era5_land")

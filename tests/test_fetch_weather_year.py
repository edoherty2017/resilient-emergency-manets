from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_weather_year import archive_url  # noqa: E402


def test_archive_request_pins_model_and_elevation():
    url = archive_url(
        lat=44.2706,
        lon=-71.3033,
        elevation_m=1917.0,
        start="2025-07-01",
        end="2026-06-30",
        model="era5",
    )
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["models"] == ["era5"]
    assert query["elevation"] == ["1917.0"]
    assert query["timezone"] == ["UTC"]

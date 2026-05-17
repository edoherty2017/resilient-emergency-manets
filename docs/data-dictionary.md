# Data Dictionary (Canonical v1)

This document defines the canonical telemetry contract for MANET ingest records.

## Required fields

| Field | Type | Unit/Format | Notes |
|---|---|---|---|
| `timestamp_utc` | string | ISO-8601 UTC datetime | Record timestamp |
| `trial_id` | string | identifier | Trial/run grouping |
| `node_id` | string | identifier | Emitting node |
| `head_id` | string | identifier | Head aggregation target |
| `line` | string | raw text | Raw decoded source line |

## Optional numeric telemetry fields

| Field | Type | Range | Purpose |
|---|---|---|---|
| `battery_mv` | int | 0..20000 | Battery millivolts |
| `battery_pct` | int | 0..100 | Battery percentage |
| `usb_power` | int | 0 or 1 | USB power present |
| `is_charging` | int | 0 or 1 | Charging state |
| `rssi_dbm` | int | -200..50 | Received signal strength |
| `rsrp_dbm` | float | -200..50 | Preferred path metric when available |
| `snr_db` | float | -40..40 | Signal-to-noise ratio |
| `lat` | float | -90..90 | Latitude decimal degrees |
| `lon` | float | -180..180 | Longitude decimal degrees |
| `elev_m` | float | -1000..12000 | Elevation meters (from `elev/alt/msl`) |
| `satellite_link_status` | string | enum-ish | Satellite link state when available |
| `weather_tag` | string | enum-ish | Weather state tag for risk stratification |

## Parser integrity fields (Priority 1)

| Field | Type | Range | Purpose |
|---|---|---|---|
| `checksum_ok` | int | 0 or 1 | NMEA checksum passed for parsed sentence |
| `checksum_bad` | int | 0 or 1 | NMEA checksum failed |
| `malformed_frame` | int | 0 or 1 | Input line/frame malformed |

## Nullability policy

- Required fields must never be null or empty.
- Optional fields may be absent when not observable from the source line.
- If present, optional fields must satisfy declared ranges.
- `rssi_dbm` fallback usage must be explicitly labeled in downstream artifacts.

## Canonical schema file

Machine-readable source of truth:

- `schemas/telemetry.schema.json`

Validation CLI:

- `scripts/validation/schema_validate.py`

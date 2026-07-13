# Data Dictionary (Canonical v1)

This document defines the canonical telemetry contract for MANET ingest records.

## Required fields

| Field | Type | Unit/Format | Notes |
|---|---|---|---|
| `timestamp_utc` | string | ISO-8601 UTC datetime | Record timestamp |
| `trial_id` | string | identifier | Trial/run grouping |
| `node_id` | string | identifier | Collector/ingest-source node that wrote the record (not necessarily the RF packet origin) |
| `head_id` | string | identifier | Head aggregation target |
| `line` | string | text | Human-readable summary of the decoded Meshtastic protobuf packet; not raw serial evidence |

When available, the optional `from_mesh_id` field identifies the RF packet
origin, while `is_own_node` states whether that origin matches the collector's
own Meshtastic identity.

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
| `elev_m` | float | -1000..12000 | Meshtastic position altitude (HAE when supplied, otherwise device altitude) |
| `gps_pdop` | float | 0..100 | Position dilution-of-precision value; collector divides Meshtastic's 1/100-unit integer by 100 |
| `channel_util_pct` | float | 0..100 | Meshtastic channel utilization |
| `air_util_tx_pct` | float | 0..100 | Meshtastic transmit airtime utilization |
| `hop_limit` | int | 0..7 | Remaining Meshtastic hop limit |
| `hop_start` | int | 0..7 | Original hop limit when firmware supplies it |
| `hops_away` | int | 0..7 | Derived relays traversed (`hop_start - hop_limit`) |
| `satellite_link_status` | string | `connected`, `degraded`, `disconnected`, `unknown` | Observed/aggregated satellite state; RPC errors use `unknown` |
| `satellite_rtt_ms_p50` | float | 0..100000 ms | Median valid Starlink RTT in the aggregation window |
| `satellite_rtt_ms_p95` | float | 0..100000 ms | Nearest-rank p95 RTT, null when insufficient samples |
| `satellite_down_mbps` | float | 0..10000 Mbps | Mean reported downlink throughput |
| `satellite_up_mbps` | float | 0..10000 Mbps | Mean reported uplink throughput |
| `satellite_packet_loss_pct` | float | 0..100 | Mean per-sample Starlink drop fraction × 100 |
| `satellite_obstruction_pct` | float | 0..100 | Mean reported obstruction fraction × 100 |
| `satellite_outage_seconds` | float | 0..86400 s | Observed outage seconds in the aggregation window |
| `weather_tag` | string | enum-ish | Weather state tag for risk stratification |

## Parser integrity fields (Priority 1)

| Field | Type | Range | Purpose |
|---|---|---|---|
| `checksum_ok` | int | 0 or 1 | Compatibility flag: Meshtastic delivered a successfully decoded protobuf packet |
| `checksum_bad` | int | 0 or 1 | Compatibility flag; raw serial checksum failures are not exposed by the Meshtastic callback API |
| `malformed_frame` | int | 0 or 1 | Input record was malformed before normalization |

## Nullability policy

- Required fields must never be null or empty.
- Optional fields may be absent when not observable from the source line.
- If present, optional fields must satisfy declared ranges.
- Meshtastic reports `batteryLevel=101` while on external power. Collectors normalize
  that sentinel to `battery_pct=null` and `usb_power=1`; `101` is never a percentage.
- `rssi_dbm` fallback usage must be explicitly labeled in downstream artifacts.

## Canonical schema file

Machine-readable source of truth:

- `schemas/telemetry.schema.json`

Validation CLI:

- `scripts/validation/schema_validate.py`

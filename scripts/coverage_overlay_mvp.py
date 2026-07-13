#!/usr/bin/env python3
import argparse
import html
import json
import math
import numbers
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd


SAT_POSITIVE = {"connected"}
SATELLITE_STATES = {"connected", "degraded", "disconnected", "unknown"}
CONTROL_PLANE_MODES = {"IP_FULL", "IP_DEGRADED", "MESH_ONLY"}
TIME_BIN_ORDER = ["dawn", "day", "dusk", "evening_peak", "night", "unknown"]
RAVINE_NOTCH_KEYWORDS = ("ravine", "notch", "gorge", "gulch", "canyon", "col", "gap")
RAVINE_NOTCH_TOPOGRAPHY = {"valley", "ravine", "notch", "gorge", "canyon"}


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open(encoding="utf-8", errors="strict") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSON in {path} line {line_no}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"non-object record in {path} line {line_no}")
            rows.append(record)
    df = pd.DataFrame(rows)
    if not df.empty:
        if "timestamp_utc" not in df.columns:
            raise ValueError(f"missing timestamp_utc in {path}")
        raw_timestamps = df["timestamp_utc"]
        parsed = pd.to_datetime(raw_timestamps, utc=False, errors="coerce")
        invalid_utc = raw_timestamps.map(
            lambda value: not isinstance(value, str)
            or not (value.endswith("Z") or value.endswith("+00:00"))
        )
        if parsed.isna().any() or invalid_utc.any():
            raise ValueError(f"invalid/non-UTC timestamp_utc in {path}")
        df["timestamp_utc"] = pd.to_datetime(raw_timestamps, utc=True, errors="raise")
    return df


def load_residuals(live_trial_dir: Path) -> pd.DataFrame:
    p = live_trial_dir / "predictions_postcalibration.parquet"
    if not p.exists():
        return pd.DataFrame()
    pred = pd.read_parquet(p)
    required = {"timestamp_utc", "node_id", "trial_id", "obs_metric_dbm", "pred_rssi_dbm"}
    missing = required - set(pred.columns)
    if missing:
        raise ValueError(f"residual artifact missing columns: {sorted(missing)}")
    def canonical_utc(value) -> bool:
        if isinstance(value, str):
            if not (value.endswith("Z") or value.endswith("+00:00")):
                return False
        try:
            timestamp = pd.Timestamp(value)
            return (
                not pd.isna(timestamp)
                and timestamp.tzinfo is not None
                and timestamp.utcoffset().total_seconds() == 0
            )
        except Exception:
            return False

    if not pred["timestamp_utc"].map(canonical_utc).all():
        raise ValueError("residual artifact contains invalid/non-UTC timestamps")
    parsed_ts = pd.to_datetime(pred["timestamp_utc"], utc=True, errors="raise")
    pred["timestamp_utc"] = parsed_ts
    if "obs_metric_dbm" in pred.columns and "pred_rssi_dbm" in pred.columns:
        observed = pd.to_numeric(pred["obs_metric_dbm"], errors="coerce")
        predicted = pd.to_numeric(pred["pred_rssi_dbm"], errors="coerce")
        invalid_observed = pred["obs_metric_dbm"].notna() & ~pred["obs_metric_dbm"].map(
            lambda value: isinstance(value, numbers.Real) and not isinstance(value, bool)
        )
        invalid_predicted = pred["pred_rssi_dbm"].notna() & ~pred["pred_rssi_dbm"].map(
            lambda value: isinstance(value, numbers.Real) and not isinstance(value, bool)
        )
        if (
            invalid_observed.any()
            or invalid_predicted.any()
            or not observed.dropna().map(math.isfinite).all()
            or not predicted.dropna().map(math.isfinite).all()
        ):
            raise ValueError("residual artifact contains invalid metric values")
        pred["abs_error_db"] = (observed - predicted).abs()
    keep = [
        c
        for c in [
            "timestamp_utc",
            "node_id",
            "trial_id",
            "abs_error_db",
            "time_bin",
            "topography_class",
            "segment_id",
        ]
        if c in pred.columns
    ]
    out = pred[keep]
    keys = ["timestamp_utc", "node_id", "trial_id"]
    if out.duplicated(subset=keys).any():
        raise ValueError("residual artifact has duplicate timestamp/node/trial keys")
    return out


def strict_numeric_column(
    df: pd.DataFrame,
    field: str,
    minimum: float,
    maximum: float,
) -> pd.Series:
    if field not in df.columns:
        return pd.Series(float("nan"), index=df.index, dtype=float)
    original = df[field]
    converted = pd.to_numeric(original, errors="coerce")
    invalid = original.notna() & ~original.map(
        lambda value: isinstance(value, numbers.Real) and not isinstance(value, bool)
    )
    finite = converted.dropna().map(math.isfinite)
    out_of_range = converted.notna() & ~converted.between(minimum, maximum)
    if invalid.any() or not finite.all() or out_of_range.any():
        raise ValueError(f"invalid {field} values in telemetry")
    return converted


def build_coverage(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mesh_metric_dbm"] = strict_numeric_column(out, "rssi_dbm", -200, 50)
    out["mesh_snr_db"] = strict_numeric_column(out, "snr_db", -40, 40)
    out["cell_rsrp_dbm"] = strict_numeric_column(out, "rsrp_dbm", -200, 50)

    # Current merges write the canonical field. Retain the suffixed alias only
    # for explicit compatibility with previously generated ingest copies.
    if "satellite_link_status_starlink" in out.columns:
        sat = out["satellite_link_status_starlink"].combine_first(out.get("satellite_link_status", pd.Series(dtype=str)))
    else:
        sat = out.get("satellite_link_status")
    out["satellite_link_status"] = (
        sat.fillna("unknown").astype(str).str.lower()
        if sat is not None
        else pd.Series("unknown", index=out.index)
    )
    invalid_satellite_states = set(out["satellite_link_status"]) - SATELLITE_STATES
    if invalid_satellite_states:
        raise ValueError(f"invalid satellite_link_status values: {sorted(invalid_satellite_states)}")

    out["has_mesh_metric"] = out["mesh_metric_dbm"].notna() | out["mesh_snr_db"].notna()
    out["has_cell_metric"] = out["cell_rsrp_dbm"].notna()
    out["has_satellite"] = out["satellite_link_status"].isin(SAT_POSITIVE)

    def mode(row):
        if row["has_satellite"]:
            return "SATELLITE"
        if row["has_cell_metric"]:
            return "CELLULAR"
        if row["has_mesh_metric"]:
            return "MESH"
        return "NONE"

    out["coverage_mode"] = out.apply(mode, axis=1)
    return out


def error_band(abs_err):
    if pd.isna(abs_err):
        return "unknown"
    if abs_err <= 6:
        return "low"
    if abs_err <= 12:
        return "medium"
    return "high"


def normalize_time_bin(value) -> str:
    if pd.isna(value):
        return "unknown"
    v = str(value).strip().lower()
    return v if v in TIME_BIN_ORDER else "unknown"


def infer_time_bin_from_timestamp(ts, local_timezone: ZoneInfo | None = None) -> str:
    if pd.isna(ts):
        return "unknown"
    local_timezone = local_timezone or ZoneInfo("America/New_York")
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        raise ValueError("time-bin inference requires a timezone-aware timestamp")
    h = int(stamp.tz_convert(local_timezone).hour)
    if 5 <= h < 8:
        return "dawn"
    if 8 <= h < 17:
        return "day"
    if 17 <= h < 19:
        return "dusk"
    if 19 <= h < 22:
        return "evening_peak"
    return "night"


def is_ravine_notch_segment(segment_id, topography_class) -> bool:
    topo = "" if pd.isna(topography_class) else str(topography_class).strip().lower()
    seg = "" if pd.isna(segment_id) else str(segment_id).strip().lower()
    if topo in RAVINE_NOTCH_TOPOGRAPHY:
        return True
    return any(tok in seg for tok in RAVINE_NOTCH_KEYWORDS)


def enrich_overlay_features(df: pd.DataFrame, local_timezone: ZoneInfo | None = None) -> pd.DataFrame:
    out = df.copy()
    if "time_bin" not in out.columns:
        out["time_bin"] = pd.NA
    if "topography_class" not in out.columns:
        out["topography_class"] = pd.NA
    if "segment_id" not in out.columns:
        out["segment_id"] = pd.NA

    out["time_bin"] = out["time_bin"].apply(normalize_time_bin)
    unknown_mask = out["time_bin"] == "unknown"
    if unknown_mask.any() and "timestamp_utc" in out.columns:
        out.loc[unknown_mask, "time_bin"] = out.loc[unknown_mask, "timestamp_utc"].apply(
            lambda value: infer_time_bin_from_timestamp(value, local_timezone)
        )

    out["topography_class"] = out["topography_class"].fillna("unknown").astype(str)
    out["segment_id"] = out["segment_id"].fillna("").astype(str)
    out["ravine_notch_segment"] = [
        is_ravine_notch_segment(seg, topo) for seg, topo in zip(out["segment_id"], out["topography_class"])
    ]
    return out


def render_leaflet_html(df_map: pd.DataFrame, out_html: Path, title: str) -> None:
    max_points = 6000
    if len(df_map) > max_points:
        stride = max(1, math.ceil(len(df_map) / max_points))
        df_map = df_map.iloc[::stride].copy()

    points = []
    for _, r in df_map.iterrows():
        points.append(
            {
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "elev_m": None if pd.isna(r.get("elev_m")) else float(r.get("elev_m")),
                "ts": None if pd.isna(r.get("timestamp_utc")) else r.get("timestamp_utc").isoformat(),
                "node_id": html.escape(str(r.get("node_id", "")), quote=True),
                "trial_id": html.escape(str(r.get("trial_id", "")), quote=True),
                "coverage_mode": html.escape(str(r.get("coverage_mode", "NONE")), quote=True),
                "control_plane_mode": html.escape(str(r.get("control_plane_mode", "UNKNOWN")), quote=True),
                "mesh_metric_dbm": None if pd.isna(r.get("mesh_metric_dbm")) else float(r.get("mesh_metric_dbm")),
                "cell_rsrp_dbm": None if pd.isna(r.get("cell_rsrp_dbm")) else float(r.get("cell_rsrp_dbm")),
                "satellite_link_status": html.escape(str(r.get("satellite_link_status", "unknown")), quote=True),
                "abs_error_db": None if pd.isna(r.get("abs_error_db")) else float(r.get("abs_error_db")),
                "error_band": html.escape(str(r.get("error_band", "unknown")), quote=True),
                "time_bin": html.escape(str(r.get("time_bin", "unknown")), quote=True),
                "topography_class": html.escape(str(r.get("topography_class", "unknown")), quote=True),
                "segment_id": html.escape(str(r.get("segment_id", "")), quote=True),
                "ravine_notch_segment": bool(r.get("ravine_notch_segment", False)),
                "ts_epoch": int(r["timestamp_utc"].timestamp()) if not pd.isna(r.get("timestamp_utc")) else None,
            }
        )

    center_lat = float(df_map["lat"].median()) if len(df_map) else 44.26
    center_lon = float(df_map["lon"].median()) if len(df_map) else -71.29

    safe_title = html.escape(title, quote=True)
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>{safe_title}</title>
  <link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css' />
  <style>
    html, body {{ margin:0; padding:0; height:100%; font-family:Arial,sans-serif; background:#0f0f0f; color:#eee; }}
    #map {{ height:80vh; }}
    #bar {{ height:20vh; padding:10px; background:#111; color:#eee; font-size:13px; }}
    .chip {{ display:inline-block; padding:3px 8px; border-radius:999px; margin-right:8px; }}
    label {{ margin-right:8px; }}
    input[type=range] {{ width: 300px; vertical-align: middle; }}
  </style>
</head>
<body>
<div id='map'></div>
<div id='bar'>
  <strong>{safe_title}</strong><br/>
  <span class='chip' style='background:#2ecc71;color:#111'>MESH</span>
  <span class='chip' style='background:#3498db'>CELLULAR</span>
  <span class='chip' style='background:#9b59b6'>SATELLITE</span>
  <span class='chip' style='background:#7f8c8d'>NONE</span>
  <span class='chip' style='background:#f1c40f;color:#111'>ERR low</span>
  <span class='chip' style='background:#e67e22'>ERR med</span>
  <span class='chip' style='background:#e74c3c'>ERR high</span>
  <br/>
  <label>Time filter:</label>
  <input id='timeSlider' type='range' min='0' max='100' value='100' step='1'>
  <span id='timeLabel'>100%</span>
  <br/>
  <label>Time-bin layers:</label>
  <span id='timeBinToggles'></span>
  <label style='margin-left:10px;'>
    <input id='toggle-ravine-notch' type='checkbox' checked> ravine/notch highlight
  </label>
  <span id='stats' style='margin-left:12px;'></span>
</div>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<script>
const points = {json.dumps(points, allow_nan=False)};
const timeBinOrder = {json.dumps(TIME_BIN_ORDER)};
const modeColor = (mode) => ({{'MESH':'#2ecc71','CELLULAR':'#3498db','SATELLITE':'#9b59b6','NONE':'#7f8c8d'}}[mode] || '#7f8c8d');
const errFill = (band) => ({{'low':'#f1c40f','medium':'#e67e22','high':'#e74c3c','unknown':null}}[band] || null);

const map = L.map('map').setView([{center_lat}, {center_lon}], 12);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }}).addTo(map);

const layer = L.layerGroup().addTo(map);
const withTs = points.filter(p => p.ts_epoch !== null).map(p => p.ts_epoch);
const minTs = withTs.length ? Math.min(...withTs) : null;
const maxTs = withTs.length ? Math.max(...withTs) : null;

const timeBinCountsAll = {{}};
for (const p of points) {{
  const b = p.time_bin || 'unknown';
  timeBinCountsAll[b] = (timeBinCountsAll[b] || 0) + 1;
}}

const timeBinToggleHost = document.getElementById('timeBinToggles');
for (const bin of timeBinOrder) {{
  if (!timeBinCountsAll[bin]) continue;
  const id = `time-bin-${{bin}}`;
  const wrapper = document.createElement('label');
  wrapper.style.marginRight = '6px';
  wrapper.innerHTML = `<input id="${{id}}" class="time-bin-toggle" type="checkbox" value="${{bin}}" checked> ${{bin}}`;
  timeBinToggleHost.appendChild(wrapper);
}}
if (!timeBinToggleHost.children.length) {{
  timeBinToggleHost.innerHTML = "<label><input class='time-bin-toggle' type='checkbox' value='unknown' checked> unknown</label>";
}}

function selectedTimeBins() {{
  return new Set(Array.from(document.querySelectorAll('.time-bin-toggle:checked')).map(el => el.value));
}}

function render(pct) {{
  layer.clearLayers();
  let threshold = maxTs;
  if (minTs !== null && maxTs !== null) threshold = Math.round(minTs + ((maxTs - minTs) * (pct / 100)));

  const enabledBins = selectedTimeBins();
  const highlightRavineNotch = document.getElementById('toggle-ravine-notch').checked;

  let counts = {{MESH:0,CELLULAR:0,SATELLITE:0,NONE:0}};
  let shown = 0;
  let latlngs = [];
  let latlngsByNode = {{}};
  let ravineLatLngsByNode = {{}};
  let shownBinCounts = {{}};

  for (const p of points) {{
    const bin = p.time_bin || 'unknown';
    if (p.ts_epoch !== null && p.ts_epoch > threshold) continue;
    if (!enabledBins.has(bin)) continue;

    shown += 1;
    counts[p.coverage_mode] = (counts[p.coverage_mode] || 0) + 1;
    shownBinCounts[bin] = (shownBinCounts[bin] || 0) + 1;
    latlngs.push([p.lat,p.lon]);
    const nodeKey = p.node_id || 'unknown';
    if (!latlngsByNode[nodeKey]) latlngsByNode[nodeKey] = [];
    latlngsByNode[nodeKey].push([p.lat,p.lon]);

    const highlightThis = highlightRavineNotch && p.ravine_notch_segment;
    if (highlightThis) {{
      if (!ravineLatLngsByNode[nodeKey]) ravineLatLngsByNode[nodeKey] = [];
      ravineLatLngsByNode[nodeKey].push([p.lat,p.lon]);
    }}
    const fill = errFill(p.error_band);
    const marker = L.circleMarker([p.lat,p.lon], {{
      radius: highlightThis ? 6 : 4,
      color: highlightThis ? '#ff4fa3' : modeColor(p.coverage_mode),
      weight: highlightThis ? 2 : 1,
      fillColor: fill || modeColor(p.coverage_mode),
      fillOpacity: fill ? 0.95 : 0.80
    }}).addTo(layer);
    marker.bindPopup(`<b>${{p.coverage_mode}}</b><br/>ctrl_plane: ${{p.control_plane_mode || 'UNKNOWN'}}<br/>ts: ${{p.ts || 'n/a'}}<br/>time_bin: ${{bin}}<br/>topography: ${{p.topography_class || 'unknown'}}<br/>segment_id: ${{p.segment_id || 'n/a'}}<br/>ravine_notch_segment: ${{Boolean(p.ravine_notch_segment)}}<br/>node: ${{p.node_id}}<br/>elev_m: ${{p.elev_m ?? 'n/a'}}<br/>mesh_rssi: ${{p.mesh_metric_dbm ?? 'n/a'}}<br/>cell_rsrp: ${{p.cell_rsrp_dbm ?? 'n/a'}}<br/>abs_error_db: ${{p.abs_error_db ?? 'n/a'}}<br/>sat: ${{p.satellite_link_status}}`);
  }}

  if (latlngs.length > 1) {{
    for (const nodeLatLngs of Object.values(latlngsByNode)) {{
      if (nodeLatLngs.length > 1) L.polyline(nodeLatLngs, {{color:'#f39c12', weight:2, opacity:0.55}}).addTo(layer);
    }}
    map.fitBounds(L.latLngBounds(latlngs), {{padding:[20,20]}});
  }}

  if (highlightRavineNotch) {{
    for (const nodeLatLngs of Object.values(ravineLatLngsByNode)) {{
      if (nodeLatLngs.length > 1) L.polyline(nodeLatLngs, {{color:'#ff4fa3', weight:4, opacity:0.85, dashArray:'6,4'}}).addTo(layer);
    }}
  }}

  const binStats = timeBinOrder.map(bin => `${{bin}}=${{shownBinCounts[bin] || 0}}`).join(' ');
  document.getElementById('stats').textContent = `shown=${{shown}} | mesh=${{counts.MESH||0}} | cell=${{counts.CELLULAR||0}} | sat=${{counts.SATELLITE||0}} | none=${{counts.NONE||0}} | bins: ${{binStats}}`;
}}

const slider = document.getElementById('timeSlider');
slider.addEventListener('input', (e) => {{
  const pct = Number(e.target.value);
  document.getElementById('timeLabel').textContent = `${{pct}}%`;
  render(pct);
}});

document.querySelectorAll('.time-bin-toggle').forEach(el => el.addEventListener('change', () => render(Number(slider.value))));
document.getElementById('toggle-ravine-notch').addEventListener('change', () => render(Number(slider.value)));

render(100);
</script>
</body>
</html>
"""
    atomic_write_text(out_html, html_doc)


def load_connectivity_events(path: Path) -> pd.DataFrame:
    """Load connectivity_events.jsonl and return sorted by timestamp."""
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open(encoding="utf-8", errors="strict") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid connectivity JSON in {path} line {line_no}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"non-object connectivity record in {path} line {line_no}")
            rows.append(record)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    required = {"timestamp_utc", "connectivity_mode"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"connectivity evidence missing columns: {sorted(missing)}")
    raw_timestamps = df["timestamp_utc"]
    invalid_utc = raw_timestamps.map(
        lambda value: not isinstance(value, str)
        or not (value.endswith("Z") or value.endswith("+00:00"))
    )
    df["timestamp_utc"] = pd.to_datetime(raw_timestamps, utc=True, errors="coerce")
    if df["timestamp_utc"].isna().any() or invalid_utc.any():
        raise ValueError("connectivity evidence contains invalid/non-UTC timestamps")
    if df["connectivity_mode"].isna().any():
        raise ValueError("connectivity evidence contains null connectivity_mode")
    return df.sort_values("timestamp_utc").reset_index(drop=True)


def assign_control_plane_mode(
    telemetry: pd.DataFrame,
    events: pd.DataFrame,
    max_event_age_seconds: float = 300.0,
) -> pd.DataFrame:
    """Assign observed connectivity state; unobserved periods remain UNKNOWN."""
    out = telemetry.copy()
    if events.empty or "connectivity_mode" not in events.columns:
        out["control_plane_mode"] = "UNKNOWN"
        return out
    invalid_modes = set(events["connectivity_mode"].dropna().astype(str)) - CONTROL_PLANE_MODES
    if invalid_modes:
        raise ValueError(f"invalid connectivity modes: {sorted(invalid_modes)}")
    conflicts = events.groupby("timestamp_utc")["connectivity_mode"].nunique(dropna=False)
    if (conflicts > 1).any():
        raise ValueError("conflicting connectivity modes share a timestamp")
    ev = events[["timestamp_utc", "connectivity_mode"]].rename(columns={"connectivity_mode": "control_plane_mode"})
    ev = ev.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc")
    merged = pd.merge_asof(
        out.sort_values("timestamp_utc"),
        ev,
        on="timestamp_utc",
        direction="backward",
        tolerance=pd.Timedelta(seconds=max_event_age_seconds),
    )
    merged["control_plane_mode"] = merged["control_plane_mode"].fillna("UNKNOWN")
    return merged


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (in percent)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(100.0 * max(center - half, 0.0), 2), round(100.0 * min(center + half, 1.0), 2))


def transition_window_summary(
    timeline: pd.DataFrame,
    min_rows: int = 4,
    min_coverage_pct: float = 95.0,
) -> dict:
    """Emit per-mode pass/fail stats for coverage-transition windows.

    Coverage here means "an RF/satellite indicator is present on the telemetry
    record assigned to this connectivity-mode interval" — a receive-side
    presence signal, NOT an independently measured window or end-to-end delivery.
    Rows are temporally autocorrelated, so even the Wilson CI is optimistic;
    treat these as descriptive statistics.
    """
    if "control_plane_mode" not in timeline.columns:
        return {}
    result = {}
    for mode in ["IP_FULL", "IP_DEGRADED", "MESH_ONLY"]:
        sub = timeline[timeline["control_plane_mode"] == mode]
        n = int(len(sub))
        if n == 0:
            result[mode] = {
                "n_rows": 0,
                "coverage_mode_counts": {},
                "pass": False,
                "reason": "no observations for required connectivity mode",
            }
            continue
        counts = sub["coverage_mode"].value_counts(dropna=False).to_dict()
        # Gate on a declared minimum sample count and receive-side coverage
        # percentage; a token single observation cannot establish a window.
        covered = sum(v for k, v in counts.items() if k != "NONE")
        lo, hi = wilson_ci(covered, n)
        result[mode] = {
            "n_rows": n,
            "coverage_mode_counts": {str(k): int(v) for k, v in counts.items()},
            "covered_rows": covered,
            "coverage_pct": round(100.0 * covered / n, 2) if n else 0.0,
            "coverage_pct_wilson95": [lo, hi],
            "definition": "receive-side indicator presence per telemetry record in the mode interval; not an independent window or end-to-end delivery; rows autocorrelated",
            "minimum_rows": min_rows,
            "minimum_coverage_pct": min_coverage_pct,
            "pass": n >= min_rows and (100.0 * covered / n) >= min_coverage_pct,
        }
    return result


def main():
    ap = argparse.ArgumentParser(description="Generate coverage overlay V2 artifacts (CSV + interactive HTML + summary)")
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--node-id", default="meshradiohead2", help="Primary telemetry node to load")
    ap.add_argument("--hiker-id", default="", help="Optional hiker node to merge in (leave empty if not available)")
    ap.add_argument("--trial-id", default="trial-live")
    ap.add_argument("--out-dir", default="artifacts/overlay")
    ap.add_argument("--live-trial-dir", default="artifacts/airmap/live_trial")
    ap.add_argument("--gps-min-rows", type=int, default=100)
    ap.add_argument("--strict-gps", action="store_true")
    ap.add_argument("--min-transition-rows", type=int, default=4)
    ap.add_argument("--min-transition-coverage-pct", type=float, default=95.0)
    ap.add_argument("--max-connectivity-event-age-sec", type=float, default=300.0)
    ap.add_argument("--min-control-plane-evidence-pct", type=float, default=95.0)
    ap.add_argument("--local-timezone", default="America/New_York")
    ap.add_argument(
        "--allow-missing-connectivity-events",
        action="store_true",
        help="Generate a diagnostic overlay with UNKNOWN control-plane state; transition gates still fail",
    )
    args = ap.parse_args()
    if args.min_transition_rows <= 0:
        raise SystemExit("--min-transition-rows must be greater than zero")
    if not 0 <= args.min_transition_coverage_pct <= 100:
        raise SystemExit("--min-transition-coverage-pct must be between 0 and 100")
    if args.max_connectivity_event_age_sec <= 0:
        raise SystemExit("--max-connectivity-event-age-sec must be greater than zero")
    if not 0 <= args.min_control_plane_evidence_pct <= 100:
        raise SystemExit("--min-control-plane-evidence-pct must be between 0 and 100")
    if args.gps_min_rows < 0:
        raise SystemExit("--gps-min-rows cannot be negative")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.node_id) or args.node_id in {".", ".."}:
        raise SystemExit("--node-id contains unsafe characters")
    if args.hiker_id and (
        not re.fullmatch(r"[A-Za-z0-9_.-]+", args.hiker_id)
        or args.hiker_id in {".", ".."}
    ):
        raise SystemExit("--hiker-id contains unsafe characters")
    if args.hiker_id and args.hiker_id == args.node_id:
        raise SystemExit("--hiker-id must differ from --node-id")
    try:
        local_timezone = ZoneInfo(args.local_timezone)
    except ZoneInfoNotFoundError as exc:
        raise SystemExit(f"unknown --local-timezone: {args.local_timezone}") from exc

    root = Path(args.ingest_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    head = load_jsonl(root / f"{args.node_id}/jsonl/telemetry_stream.jsonl")
    if head.empty:
        raise SystemExit(f"No primary telemetry rows found for {args.node_id}")
    if (
        "node_id" not in head.columns
        or head["node_id"].isna().any()
        or set(head["node_id"].astype(str)) != {args.node_id}
    ):
        raise SystemExit(f"telemetry identity does not match ingest directory: {args.node_id}")
    head["_ingest_source_node_id"] = args.node_id
    frames = [head]
    loaded_node_ids = [args.node_id]
    if args.hiker_id:
        hiker = load_jsonl(root / f"{args.hiker_id}/jsonl/telemetry_stream.jsonl")
        if hiker.empty:
            raise SystemExit(f"No requested hiker telemetry rows found for {args.hiker_id}")
        if (
            "node_id" not in hiker.columns
            or hiker["node_id"].isna().any()
            or set(hiker["node_id"].astype(str)) != {args.hiker_id}
        ):
            raise SystemExit(f"telemetry identity does not match ingest directory: {args.hiker_id}")
        hiker["_ingest_source_node_id"] = args.hiker_id
        frames.append(hiker)
        loaded_node_ids.append(args.hiker_id)
    df = pd.concat(frames, ignore_index=True, sort=False)
    if df.empty:
        raise SystemExit("No telemetry rows found")

    # Each node gets only its own observed transition stream. Applying the HEAD
    # state to a hiker node would fabricate control-plane evidence.
    events_by_node: dict[str, pd.DataFrame] = {}
    for source_node_id in loaded_node_ids:
        events_path = root / source_node_id / "connectivity_events.jsonl"
        events = load_connectivity_events(events_path)
        if events.empty and not args.allow_missing_connectivity_events:
            raise SystemExit(f"Connectivity transition evidence missing or empty: {events_path}")
        if not events.empty and (
            "node_id" not in events.columns
            or events["node_id"].isna().any()
            or set(events["node_id"].astype(str)) != {source_node_id}
        ):
            raise SystemExit(f"connectivity identity does not match ingest directory: {source_node_id}")
        events_by_node[source_node_id] = events

    if "trial_id" not in df.columns or df["trial_id"].isna().any():
        raise SystemExit("telemetry is missing required trial_id values")
    if args.trial_id:
        filtered = df[df["trial_id"] == args.trial_id].copy()
        if filtered.empty:
            raise SystemExit(f"No telemetry rows match trial_id={args.trial_id!r}")
        df = filtered

    df = build_coverage(df).sort_values("timestamp_utc")
    mode_frames = []
    for source_node_id in loaded_node_ids:
        node_rows = df[df["_ingest_source_node_id"] == source_node_id].copy()
        mode_frames.append(
            assign_control_plane_mode(
                node_rows,
                events_by_node[source_node_id],
                max_event_age_seconds=args.max_connectivity_event_age_sec,
            )
        )
    df = pd.concat(mode_frames, ignore_index=True, sort=False).sort_values("timestamp_utc")

    # Error is owned by the exact-key residual artifact, never by an arbitrary
    # stale value carried in telemetry.
    df = df.drop(columns=["abs_error_db"], errors="ignore")
    # Merge residual/error bands from live trial outputs where available.
    residuals = load_residuals(Path(args.live_trial_dir))
    if not residuals.empty:
        merge_keys = ["timestamp_utc", "node_id", "trial_id"]
        residual_columns = merge_keys + [
            column for column in residuals.columns
            if column not in merge_keys and column not in df.columns
        ]
        df = df.merge(
            residuals[residual_columns],
            how="left",
            on=merge_keys,
            validate="many_to_one",
        )
    if "abs_error_db" not in df.columns:
        df["abs_error_db"] = pd.NA
    df["error_band"] = df["abs_error_db"].apply(error_band)
    df = enrich_overlay_features(df, local_timezone)

    timeline_cols = [
        "timestamp_utc", "trial_id", "node_id", "head_id", "lat", "lon", "elev_m",
        "coverage_mode", "control_plane_mode",
        "mesh_metric_dbm", "mesh_snr_db", "cell_rsrp_dbm", "satellite_link_status",
        "has_mesh_metric", "has_cell_metric", "has_satellite", "abs_error_db", "error_band",
        "time_bin", "topography_class", "segment_id", "ravine_notch_segment",
    ]
    for c in timeline_cols:
        if c not in df.columns:
            df[c] = pd.NA

    timeline = df[timeline_cols].copy()

    gps_any = timeline["lat"].notna() | timeline["lon"].notna()
    gps_complete = timeline["lat"].notna() & timeline["lon"].notna()
    if (gps_any & ~gps_complete).any():
        raise SystemExit(f"incomplete GPS pairs in overlay input: {int((gps_any & ~gps_complete).sum())}")
    timeline["lat"] = strict_numeric_column(timeline, "lat", -90, 90)
    timeline["lon"] = strict_numeric_column(timeline, "lon", -180, 180)
    timeline["elev_m"] = strict_numeric_column(timeline, "elev_m", -1000, 12000)
    timeline["abs_error_db"] = strict_numeric_column(timeline, "abs_error_db", 0, 10000)
    map_df = timeline[gps_complete & timeline["timestamp_utc"].notna()].copy()
    if not map_df.empty:
        invalid_gps = (
            map_df["lat"].isna()
            | map_df["lon"].isna()
            | ~map_df["lat"].map(math.isfinite)
            | ~map_df["lon"].map(math.isfinite)
            | ~map_df["lat"].between(-90, 90)
            | ~map_df["lon"].between(-180, 180)
        )
        if invalid_gps.any():
            raise SystemExit(f"invalid GPS rows in overlay input: {int(invalid_gps.sum())}")
    gps_warning = None
    if len(map_df) < args.gps_min_rows:
        gps_warning = f"gps rows below threshold: {len(map_df)} < {args.gps_min_rows}"
        if args.strict_gps:
            raise SystemExit(gps_warning)

    atomic_write_text(out_dir / "coverage_timeline.csv", timeline.to_csv(index=False))
    render_leaflet_html(map_df, out_dir / "coverage_overlay.html", "Coverage Overlay V2 (Route+Time+Error)")

    transition_summary = transition_window_summary(
        timeline,
        min_rows=args.min_transition_rows,
        min_coverage_pct=args.min_transition_coverage_pct,
    )
    observed_control_plane_rows = int(timeline["control_plane_mode"].isin(CONTROL_PLANE_MODES).sum())
    control_plane_evidence_pct = (
        100.0 * observed_control_plane_rows / len(timeline) if len(timeline) else 0.0
    )
    control_plane_evidence_pass = control_plane_evidence_pct >= args.min_control_plane_evidence_pct
    overall_transition_pass = control_plane_evidence_pass and bool(transition_summary) and all(
        v.get("pass", False) for v in transition_summary.values()
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir.resolve()),
        "loaded_node_ids": loaded_node_ids,
        "trial_id": args.trial_id,
        "local_timezone_for_inferred_time_bins": args.local_timezone,
        "max_connectivity_event_age_sec": args.max_connectivity_event_age_sec,
        "rows_total": int(len(timeline)),
        "rows_with_gps": int(len(map_df)),
        "gps_min_rows": int(args.gps_min_rows),
        "gps_gate_passed": bool(len(map_df) >= args.gps_min_rows),
        "gps_warning": gps_warning,
        "coverage_mode_counts": {str(k): int(v) for k, v in timeline["coverage_mode"].value_counts(dropna=False).items()},
        "control_plane_mode_counts": {str(k): int(v) for k, v in timeline["control_plane_mode"].value_counts(dropna=False).items()},
        "error_band_counts": {str(k): int(v) for k, v in timeline["error_band"].value_counts(dropna=False).items()},
        "transition_window_summary": transition_summary,
        "transition_window_pass": overall_transition_pass,
        "control_plane_observed_rows": observed_control_plane_rows,
        "control_plane_evidence_pct": round(control_plane_evidence_pct, 2),
        "control_plane_evidence_min_pct": args.min_control_plane_evidence_pct,
        "control_plane_evidence_pass": control_plane_evidence_pass,
        "analysis_definition": "records grouped by recently observed connectivity-mode intervals; coverage is receive-side indicator presence, not end-to-end delivery",
        "transition_gate_min_rows": args.min_transition_rows,
        "transition_gate_min_coverage_pct": args.min_transition_coverage_pct,
    }
    atomic_write_text(out_dir / "overlay_summary.json", json.dumps(summary, indent=2, allow_nan=False) + "\n")
    atomic_write_text(
        out_dir / "transition_window_summary.json",
        json.dumps(transition_summary, indent=2, allow_nan=False) + "\n",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

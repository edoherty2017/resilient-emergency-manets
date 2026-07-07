#!/usr/bin/env python3
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


SAT_POSITIVE = {"connected", "up", "online", "active", "true", "1", "yes"}
TIME_BIN_ORDER = ["dawn", "day", "dusk", "evening_peak", "night", "unknown"]
RAVINE_NOTCH_KEYWORDS = ("ravine", "notch", "gorge", "gulch", "canyon", "col", "gap")
RAVINE_NOTCH_TOPOGRAPHY = {"valley", "ravine", "notch", "gorge", "canyon"}


def load_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(rows)
    if "timestamp_utc" in df.columns:
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df


def load_residuals(live_trial_dir: Path) -> pd.DataFrame:
    p = live_trial_dir / "predictions_postcalibration.parquet"
    if not p.exists():
        return pd.DataFrame()
    pred = pd.read_parquet(p)
    if "timestamp_utc" in pred.columns:
        pred["timestamp_utc"] = pd.to_datetime(pred["timestamp_utc"], utc=True, errors="coerce")
    if "obs_metric_dbm" in pred.columns and "pred_rssi_dbm" in pred.columns:
        pred["abs_error_db"] = (pd.to_numeric(pred["obs_metric_dbm"], errors="coerce") - pd.to_numeric(pred["pred_rssi_dbm"], errors="coerce")).abs()
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
    return pred[keep].dropna(subset=["timestamp_utc"]) if keep else pd.DataFrame()


def build_coverage(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["mesh_metric_dbm"] = pd.to_numeric(out.get("rssi_dbm"), errors="coerce")
    out["mesh_snr_db"] = pd.to_numeric(out.get("snr_db"), errors="coerce")
    out["cell_rsrp_dbm"] = pd.to_numeric(out.get("rsrp_dbm"), errors="coerce")

    # merge_starlink_into_telemetry uses satellite_link_status_starlink to avoid
    # collision with the MANET connectivity_mode field; alias it here.
    if "satellite_link_status_starlink" in out.columns:
        sat = out["satellite_link_status_starlink"].combine_first(out.get("satellite_link_status", pd.Series(dtype=str)))
    else:
        sat = out.get("satellite_link_status")
    out["satellite_link_status"] = (sat.fillna("unknown").astype(str) if sat is not None else pd.Series("unknown", index=out.index))

    out["has_mesh_metric"] = out["mesh_metric_dbm"].notna() | out["mesh_snr_db"].notna()
    out["has_cell_metric"] = out["cell_rsrp_dbm"].notna()
    out["has_satellite"] = out["satellite_link_status"].str.lower().isin(SAT_POSITIVE)

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


def infer_time_bin_from_timestamp(ts) -> str:
    if pd.isna(ts):
        return "unknown"
    h = int(pd.Timestamp(ts).hour)
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


def enrich_overlay_features(df: pd.DataFrame) -> pd.DataFrame:
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
        out.loc[unknown_mask, "time_bin"] = out.loc[unknown_mask, "timestamp_utc"].apply(infer_time_bin_from_timestamp)

    out["topography_class"] = out["topography_class"].fillna("unknown").astype(str)
    out["segment_id"] = out["segment_id"].fillna("").astype(str)
    out["ravine_notch_segment"] = [
        is_ravine_notch_segment(seg, topo) for seg, topo in zip(out["segment_id"], out["topography_class"])
    ]
    return out


def render_leaflet_html(df_map: pd.DataFrame, out_html: Path, title: str) -> None:
    max_points = 6000
    if len(df_map) > max_points:
        stride = max(1, len(df_map) // max_points)
        df_map = df_map.iloc[::stride].copy()

    points = []
    for _, r in df_map.iterrows():
        points.append(
            {
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "elev_m": None if pd.isna(r.get("elev_m")) else float(r.get("elev_m")),
                "ts": None if pd.isna(r.get("timestamp_utc")) else r.get("timestamp_utc").isoformat(),
                "node_id": str(r.get("node_id", "")),
                "trial_id": str(r.get("trial_id", "")),
                "coverage_mode": str(r.get("coverage_mode", "NONE")),
                "control_plane_mode": str(r.get("control_plane_mode", "IP_FULL")),
                "mesh_metric_dbm": None if pd.isna(r.get("mesh_metric_dbm")) else float(r.get("mesh_metric_dbm")),
                "cell_rsrp_dbm": None if pd.isna(r.get("cell_rsrp_dbm")) else float(r.get("cell_rsrp_dbm")),
                "satellite_link_status": str(r.get("satellite_link_status", "unknown")),
                "abs_error_db": None if pd.isna(r.get("abs_error_db")) else float(r.get("abs_error_db")),
                "error_band": str(r.get("error_band", "unknown")),
                "time_bin": str(r.get("time_bin", "unknown")),
                "topography_class": str(r.get("topography_class", "unknown")),
                "segment_id": str(r.get("segment_id", "")),
                "ravine_notch_segment": bool(r.get("ravine_notch_segment", False)),
                "ts_epoch": int(r["timestamp_utc"].timestamp()) if not pd.isna(r.get("timestamp_utc")) else None,
            }
        )

    center_lat = float(df_map["lat"].median()) if len(df_map) else 44.26
    center_lon = float(df_map["lon"].median()) if len(df_map) else -71.29

    html = f"""<!doctype html>
<html>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>{title}</title>
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
  <strong>{title}</strong><br/>
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
const points = {json.dumps(points)};
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
  let ravineLatLngs = [];
  let shownBinCounts = {{}};

  for (const p of points) {{
    const bin = p.time_bin || 'unknown';
    if (p.ts_epoch !== null && p.ts_epoch > threshold) continue;
    if (!enabledBins.has(bin)) continue;

    shown += 1;
    counts[p.coverage_mode] = (counts[p.coverage_mode] || 0) + 1;
    shownBinCounts[bin] = (shownBinCounts[bin] || 0) + 1;
    latlngs.push([p.lat,p.lon]);

    const highlightThis = highlightRavineNotch && p.ravine_notch_segment;
    if (highlightThis) ravineLatLngs.push([p.lat,p.lon]);
    const fill = errFill(p.error_band);
    const marker = L.circleMarker([p.lat,p.lon], {{
      radius: highlightThis ? 6 : 4,
      color: highlightThis ? '#ff4fa3' : modeColor(p.coverage_mode),
      weight: highlightThis ? 2 : 1,
      fillColor: fill || modeColor(p.coverage_mode),
      fillOpacity: fill ? 0.95 : 0.80
    }}).addTo(layer);
    marker.bindPopup(`<b>${{p.coverage_mode}}</b><br/>ctrl_plane: ${{p.control_plane_mode || 'IP_FULL'}}<br/>ts: ${{p.ts || 'n/a'}}<br/>time_bin: ${{bin}}<br/>topography: ${{p.topography_class || 'unknown'}}<br/>segment_id: ${{p.segment_id || 'n/a'}}<br/>ravine_notch_segment: ${{Boolean(p.ravine_notch_segment)}}<br/>node: ${{p.node_id}}<br/>elev_m: ${{p.elev_m ?? 'n/a'}}<br/>mesh_rssi: ${{p.mesh_metric_dbm ?? 'n/a'}}<br/>cell_rsrp: ${{p.cell_rsrp_dbm ?? 'n/a'}}<br/>abs_error_db: ${{p.abs_error_db ?? 'n/a'}}<br/>sat: ${{p.satellite_link_status}}`);
  }}

  if (latlngs.length > 1) {{
    const line = L.polyline(latlngs, {{color:'#f39c12', weight:2, opacity:0.55}}).addTo(layer);
    map.fitBounds(line.getBounds(), {{padding:[20,20]}});
  }}

  if (highlightRavineNotch && ravineLatLngs.length > 1) {{
    L.polyline(ravineLatLngs, {{color:'#ff4fa3', weight:4, opacity:0.85, dashArray:'6,4'}}).addTo(layer);
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
    out_html.write_text(html)


def load_connectivity_events(path: Path) -> pd.DataFrame:
    """Load connectivity_events.jsonl and return sorted by timestamp."""
    if not path.exists():
        return pd.DataFrame()
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    return df.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)


def assign_control_plane_mode(telemetry: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """merge_asof connectivity events onto telemetry rows; default is IP_FULL."""
    out = telemetry.copy()
    if events.empty or "connectivity_mode" not in events.columns:
        out["control_plane_mode"] = "IP_FULL"
        return out
    ev = events[["timestamp_utc", "connectivity_mode"]].rename(columns={"connectivity_mode": "control_plane_mode"})
    ev = ev.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc")
    merged = pd.merge_asof(
        out.sort_values("timestamp_utc"),
        ev,
        on="timestamp_utc",
        direction="backward",
    )
    merged["control_plane_mode"] = merged["control_plane_mode"].fillna("IP_FULL")
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


def transition_window_summary(timeline: pd.DataFrame) -> dict:
    """Emit per-mode pass/fail stats for coverage-transition windows.

    Coverage here means "≥1 packet/sample of the given mode observed in the row's
    window" — a receive-side presence signal, NOT end-to-end deliverability.
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
            result[mode] = {"n_rows": 0, "coverage_mode_counts": {}, "pass": True}
            continue
        counts = sub["coverage_mode"].value_counts(dropna=False).to_dict()
        # pass = at least some connectivity (MESH or better)
        covered = sum(v for k, v in counts.items() if k != "NONE")
        lo, hi = wilson_ci(covered, n)
        result[mode] = {
            "n_rows": n,
            "coverage_mode_counts": {str(k): int(v) for k, v in counts.items()},
            "covered_rows": covered,
            "coverage_pct": round(100.0 * covered / n, 2) if n else 0.0,
            "coverage_pct_wilson95": [lo, hi],
            "definition": "receive-side presence per row window; not end-to-end deliverability; rows autocorrelated",
            "pass": covered > 0,
        }
    return result


def main():
    ap = argparse.ArgumentParser(description="Generate coverage overlay V2 artifacts (CSV + interactive HTML + summary)")
    ap.add_argument("--ingest-root", default="/home/doher/manet_ingest")
    ap.add_argument("--node-id", default="meshradiohead2", help="Primary telemetry node to load")
    ap.add_argument("--hiker-id", default="", help="Optional hiker node to merge in (leave empty if not available)")
    ap.add_argument("--trial-id", default="trial_live")
    ap.add_argument("--out-dir", default="artifacts/overlay")
    ap.add_argument("--live-trial-dir", default="artifacts/airmap/live_trial")
    ap.add_argument("--gps-min-rows", type=int, default=100)
    ap.add_argument("--strict-gps", action="store_true")
    args = ap.parse_args()

    root = Path(args.ingest_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    head = load_jsonl(root / f"{args.node_id}/jsonl/telemetry_stream.jsonl")
    frames = [head]
    if args.hiker_id:
        hiker = load_jsonl(root / f"{args.hiker_id}/jsonl/telemetry_stream.jsonl")
        if not hiker.empty:
            frames.append(hiker)
    df = pd.concat(frames, ignore_index=True, sort=False)
    if df.empty:
        raise SystemExit("No telemetry rows found")

    # Load connectivity events (one per transition, merge_asof backward → each row gets its mode).
    events_path = root / args.node_id / "connectivity_events.jsonl"
    events = load_connectivity_events(events_path)

    if "trial_id" in df.columns and args.trial_id:
        filtered = df[df["trial_id"] == args.trial_id].copy()
        if not filtered.empty:
            df = filtered

    df = build_coverage(df).sort_values("timestamp_utc")
    df = assign_control_plane_mode(df, events)

    # Merge residual/error bands from live trial outputs where available.
    residuals = load_residuals(Path(args.live_trial_dir))
    if not residuals.empty:
        merge_keys = [k for k in ["timestamp_utc", "node_id", "trial_id"] if k in df.columns and k in residuals.columns]
        if merge_keys:
            df = df.merge(residuals, how="left", on=merge_keys)
    if "abs_error_db" not in df.columns:
        df["abs_error_db"] = pd.NA
    df["error_band"] = df["abs_error_db"].apply(error_band)
    df = enrich_overlay_features(df)

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
    timeline.to_csv(out_dir / "coverage_timeline.csv", index=False)

    map_df = timeline.dropna(subset=["lat", "lon", "timestamp_utc"]).copy()
    gps_warning = None
    if len(map_df) < args.gps_min_rows:
        gps_warning = f"gps rows below threshold: {len(map_df)} < {args.gps_min_rows}"
        if args.strict_gps:
            raise SystemExit(gps_warning)

    render_leaflet_html(map_df, out_dir / "coverage_overlay.html", "Coverage Overlay V2 (Route+Time+Error)")

    transition_summary = transition_window_summary(timeline)
    overall_transition_pass = all(v.get("pass", True) for v in transition_summary.values())

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir.resolve()),
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
    }
    (out_dir / "overlay_summary.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "transition_window_summary.json").write_text(json.dumps(transition_summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

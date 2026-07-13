#!/usr/bin/env python3
"""Algorithm-comparison viewer: one map, N traced runs, live switcher.

All runs share the identical week (same seed → identical hiker movement), so
movers/trails/boundary/service areas are embedded once; per-algorithm edges,
battery series, and event logs swap live from a dropdown. A metrics strip
shows every algorithm's scoreboard with the active one highlighted — flip
between them mid-playback to see what's working and what's failing.

Run:
  .venv/bin/python scripts/render_algo_compare.py \
     --run lb_energy --run flood --run etx --run min_hop --run energy_aware
(each --run MODE expects artifacts/sim/trace_demo_MODE.jsonl + summary_demo_MODE.json)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

MAX_EDGES_PER_RUN = 10000


def digest(trace_path: Path, sites: dict, keep_movers: bool, pos_at=None):
    kind_of_pkt: dict[int, str] = {}
    edges, bat, log = [], {}, []
    edges_h = []
    kiosks: list = []            # [[t, {kiosk: [socs]}], ...]
    assigns: list = []           # [[t, walker, radio], ...]
    movers: dict[str, list] = {}
    pos_now = {n: (s["lat"], s["lon"]) for n, s in sites.items()}

    def node_pos(name, t):
        if pos_at is not None:
            q = pos_at(name, t)
            if q is not None:
                return q
        return pos_now.get(name)
    with open(trace_path) as fh:
        for line in fh:
            e = json.loads(line)
            ev, t = e["ev"], e["t"]
            if ev == "tx":
                kind_of_pkt.setdefault(e["pkt"], e["kind"] if e["kind"] != "fwd"
                                       else kind_of_pkt.get(e["pkt"], "fwd"))
            elif ev in ("rx", "col"):
                fp, tp = node_pos(e["from"], t), node_pos(e["n"], t)
                if fp and tp:
                    hk = e["from"].startswith(("rent_", "hiker_", "radio_"))
                    (edges_h if hk else edges).append(
                        [round(t, 1), fp[0], fp[1], tp[0], tp[1],
                         1 if ev == "rx" else 0,
                         kind_of_pkt.get(e["pkt"], "tel"), 1 if hk else 0])
            elif ev == "pos":
                pos_now[e["n"]] = (e["lat"], e["lon"])
                if keep_movers:
                    movers.setdefault(e["n"], []).append(
                        [round(t, 1), e["lat"], e["lon"], e.get("dk", 0)])
            elif ev == "bat":
                bat.setdefault(e["n"], []).append(
                    [round(t, 1), e["soc"], e["sw"], 1 if e["alive"] else 0])
            elif ev == "deliver":
                k = e.get("kind", "tel")
                txt = (f"🆘 SOS from {e['orig']} → SAR HQ via {e['via']}" if k == "sos"
                       else f"DM {e['orig']} → {e['via']}" if k == "msg"
                       else f"{k} {e['orig']} → {e['via']}")
                log.append([round(t, 1), "deliver", txt + f" ({e['lat_s']}s)"])
            elif ev in ("dead", "alive"):
                log.append([round(t, 1), ev, f"{e['n']} {ev}"])
            elif ev == "kiosk":
                kiosks.append([round(t, 1), e["inv"]])
            elif ev == "assign":
                assigns.append([round(t, 1), e["walker"], e["radio"]])
                log.append([round(t, 1), "rent",
                            f"{e['walker']} took {e['radio']} from {e['kiosk']} "
                            f"@ {e['soc']*100:.0f}% (best in box)"])
            elif ev == "starved":
                log.append([round(t, 1), "dead",
                            f"⚠ {e['walker']}: NO charged radio at {e['kiosk']}"])
            elif ev in ("rent", "return"):
                log.append([round(t, 1), ev, f"{e['n']} {ev} @ {e.get('kiosk','?')}"])
    half = MAX_EDGES_PER_RUN // 2
    if len(edges_h) > half:
        idx = np.linspace(0, len(edges_h) - 1, half).astype(int)
        edges_h = [edges_h[i] for i in idx]
    room = MAX_EDGES_PER_RUN - len(edges_h)
    if len(edges) > room:
        idx = np.linspace(0, len(edges) - 1, room).astype(int)
        edges = [edges[i] for i in idx]
    edges = sorted(edges + edges_h, key=lambda e: e[0])
    bat = {n: v[::4] for n, v in bat.items()}   # year-scale: ~daily
    return edges, bat, log, movers, kiosks, assigns


def build_coverage_grid(service: dict, cell_deg: float = 0.012) -> dict | None:
    """Rasterize the union of relay service-areas onto a lat/lon grid.

    Each covered cell stores the indices of every relay whose terrain-clipped
    footprint reaches it (range-by-azimuth test). At play time the browser
    colors a cell green while any covering relay is alive and red when they
    are all dead — so lost coverage is visible as red eating into green.
    """
    if not service:
        return None
    names = list(service.keys())
    lats = np.array([service[n]["lat"] for n in names])
    lons = np.array([service[n]["lon"] for n in names])
    rng = [np.asarray(service[n]["r"], dtype=float) for n in names]
    naz = len(rng[0])
    lat0, lat1 = float(lats.min()) - 0.03, float(lats.max()) + 0.03
    lon0, lon1 = float(lons.min()) - 0.03, float(lons.max()) + 0.03
    nlat = int((lat1 - lat0) / cell_deg) + 1
    nlon = int((lon1 - lon0) / cell_deg) + 1
    glat = lat0 + (np.arange(nlat) + 0.5) * cell_deg
    glon = lon0 + (np.arange(nlon) + 0.5) * cell_deg
    cov: dict[int, list[int]] = {}
    for ni, name in enumerate(names):
        nlat_, nlon_ = lats[ni], lons[ni]
        rmax = float(rng[ni].max())
        # bound the search box to this node's max reach (+1 cell margin)
        dlat_deg = rmax / 111320.0
        dlon_deg = rmax / (111320.0 * math.cos(math.radians(nlat_)))
        i0 = max(0, int((nlat_ - dlat_deg - lat0) / cell_deg))
        i1 = min(nlat, int((nlat_ + dlat_deg - lat0) / cell_deg) + 2)
        j0 = max(0, int((nlon_ - dlon_deg - lon0) / cell_deg))
        j1 = min(nlon, int((nlon_ + dlon_deg - lon0) / cell_deg) + 2)
        if i1 <= i0 or j1 <= j0:
            continue
        sub_lat = glat[i0:i1][:, None]
        sub_lon = glon[j0:j1][None, :]
        dN = (sub_lat - nlat_) * 111320.0
        dE = (sub_lon - nlon_) * 111320.0 * math.cos(math.radians(nlat_))
        dist = np.hypot(dN, dE)
        bearing = np.mod(np.arctan2(dE, dN), 2 * math.pi)
        kf = bearing / (2 * math.pi) * naz
        k0 = np.floor(kf).astype(int) % naz
        k1 = (k0 + 1) % naz
        frac = kf - np.floor(kf)
        r_at = rng[ni][k0] * (1 - frac) + rng[ni][k1] * frac
        hit = dist <= r_at
        ii, jj = np.where(hit)
        for a, b in zip(ii + i0, jj + j0):
            cov.setdefault(int(a) * nlon + int(b), []).append(ni)
    cell_km2 = (cell_deg * 111.32) * (cell_deg * 111.32 *
                                      math.cos(math.radians((lat0 + lat1) / 2)))
    return {"lat0": round(lat0, 4), "lon0": round(lon0, 4),
            "cell": cell_deg, "nlat": nlat, "nlon": nlon,
            "names": names, "cell_km2": round(cell_km2, 3),
            "cov": {str(k): v for k, v in cov.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-algorithm comparison viewer")
    ap.add_argument("--run", action="append", required=True,
                    help="mode name; expects <prefix><mode>.jsonl + summaries")
    ap.add_argument("--prefix", default="artifacts/sim/year_",
                    help="trace/summary filename prefix (year runs)")
    ap.add_argument("--topology", default="artifacts/sim/topology_statewide.json")
    ap.add_argument("--routes", default="artifacts/sim/routes_statewide.json")
    ap.add_argument("--out", default="artifacts/sim/algo_compare.html")
    ap.add_argument("--title", default="ALGORITHM ARENA — same week, same hikers, switch live")
    args = ap.parse_args()

    topo = json.loads((ROOT / args.topology).read_text())
    sites = topo["sites"]
    rjson = json.loads((ROOT / args.routes).read_text())["routes"]

    def renter_def(name):
        for pref in ("rent_", "walker_"):
            if name.startswith(pref):
                body = name[len(pref):]
                rname, _, k = body.rpartition("_")
                if rname in rjson and k.isdigit():
                    return rname, (11.5 + 1.5 * int(k)) * 3600.0
        return None

    def pos_at(name, t):
        d = renter_def(name)
        if d is None:
            return None
        rname, start_s = d
        r = rjson[rname]
        tt = min(max((t % 86400.0) - start_s, 0.0), r["duration_s"])
        return (float(np.interp(tt, r["t_s"], r["lat"])),
                float(np.interp(tt, r["t_s"], r["lon"])))

    runs, movers_shared = {}, None
    duration = 0.0
    for i, mode in enumerate(args.run):
        tp = ROOT / f"{args.prefix}trace_{mode}.jsonl"
        sp = ROOT / f"{args.prefix}summary_{mode}.json"
        if not tp.exists() or not sp.exists():
            print(f"  ({mode}: missing trace/summary — skipped)")
            continue
        s = json.loads(sp.read_text())
        # radio→walker assignment map lets radio events resolve to exact
        # trail positions in kiosk-pool runs
        radio_walker: dict = {}

        def pos_at_run(name, t):
            if name.startswith("radio_"):
                w = None
                for (ta, wa, ra) in radio_walker.get(name, ()):
                    if ta <= t:
                        w = wa
                    else:
                        break
                return pos_at(w, t) if w else None
            return pos_at(name, t)
        # pre-scan assigns for the mapping (cheap second pass avoided by
        # digesting twice would be worse; scan once here)
        with open(tp) as fh:
            for line in fh:
                if '"assign"' not in line:
                    continue
                e = json.loads(line)
                if e.get("ev") == "assign":
                    radio_walker.setdefault(e["radio"], []).append(
                        (e["t"], e["walker"], e["radio"]))
        edges, bat, log, movers, kiosks, assigns = digest(
            tp, sites, keep_movers=(movers_shared is None), pos_at=pos_at_run)
        if movers_shared is None and movers:
            movers_shared = movers
        fe = s.get("fleet_energy", {})
        rental = s.get("rental")
        runs[mode] = {
            "edges": edges, "bat": bat, "log": log,
            "kiosks": kiosks, "assigns": assigns,
            "soc6h": (fe.get("soc_series_6h") or []),
            "links": [[sites[r["a"]]["lat"], sites[r["a"]]["lon"],
                       sites[r["b"]]["lat"], sites[r["b"]]["lon"],
                       1 if r["struggling"] else 0]
                      for r in s.get("link_health", [])
                      if r["a"] in sites and r["b"] in sites],
            "stats": {"pdr": s["pdr_overall"],
                      "sos": f"{s['sos']['delivered']}/{s['sos']['sent']}",
                      "util": s["channel_utilization"],
                      "deaths": fe.get("deaths_total"),
                      "gini": fe.get("relay_energy_gini"),
                      "avail": (rental or {}).get("availability")},
        }
        # walkers exist even without trace fixes in kiosk-pool runs
        if movers_shared is None:
            movers_shared = {}
        for rname in rjson:
            for k in range(2):
                movers_shared.setdefault(f"walker_{rname}_{k}", [])
        duration = max(duration, s["days"] * 86400)
        print(f"  {mode}: {len(edges)} edges, {len(log)} log, PDR {s['pdr_overall']}")

    trails = {rn: [[round(a, 5), round(b, 5)] for a, b in
                   list(zip(r["lat"], r["lon"]))[::3]]
              for rn, r in rjson.items()}
    routegeom = {rn: {"t": [round(float(x), 1) for x in r["t_s"][::2]],
                      "lat": [round(float(x), 5) for x in r["lat"][::2]],
                      "lon": [round(float(x), 5) for x in r["lon"][::2]],
                      "dur": r["duration_s"]}
                 for rn, r in rjson.items()}
    moverdef = {}
    for n in (movers_shared or {}):
        d = renter_def(n)
        if d:
            moverdef[n] = {"route": d[0], "start": d[1]}
    # analytic movers need no trace fixes; keep only non-renter tracks
    movers_shared = {n: v for n, v in (movers_shared or {}).items()
                     if n not in moverdef}
    nh = []
    nh_p = ROOT / "artifacts/osm/nh_boundary.json"
    if nh_p.exists():
        g = json.loads(nh_p.read_text())
        ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
        nh = [[round(c[1], 4), round(c[0], 4)] for c in ring]
    service = {}
    sa_p = ROOT / "artifacts/sim/service_areas.json"
    if sa_p.exists():
        sa = json.loads(sa_p.read_text())["sites"]
        service = {n: {"lat": v["lat"], "lon": v["lon"], "r": v["range_m"]}
                   for n, v in sa.items() if n in sites}
    # per-gateway ITM coverage heatmaps (build_gateway_coverage.py)
    cov = []
    cov_p = ROOT / "artifacts/sim/coverage_overlays.json"
    if cov_p.exists():
        cov = [c for c in json.loads(cov_p.read_text()) if c["name"] in sites]
        print(f"  coverage heatmaps: {len(cov)} gateways")

    # live coverage grid: which relay service-areas cover each grid cell, so
    # the browser can paint a cell green while ≥1 covering node is alive and
    # red once they've all died — coverage loss made spatially explicit.
    covgrid = build_coverage_grid(service)
    if covgrid:
        print(f"  coverage grid: {covgrid['nlat']}x{covgrid['nlon']} cells, "
              f"{len(covgrid['cov'])} covered")

    data = {
        "title": args.title,
        "sites": {n: {"lat": s["lat"], "lon": s["lon"],
                      "mqtt": bool(s.get("mqtt_uplink"))} for n, s in sites.items()},
        "duration_s": duration, "start_utc": "2025-07-01T00:00:00Z",
        "movers": movers_shared or {}, "trails": trails, "nh": nh,
        "routegeom": routegeom, "moverdef": moverdef,
        "service": service, "cov": cov, "covgrid": covgrid, "runs": runs,
    }
    vendor = ROOT / "artifacts/vendor"
    html = (TEMPLATE
            .replace("__LEAFLET_CSS__", (vendor / "leaflet.css").read_text())
            .replace("__LEAFLET_JS__", (vendor / "leaflet.js").read_text())
            .replace("__DATA__", json.dumps(data)))
    out = ROOT / args.out
    out.write_text(html)
    print(f"compare viewer: {out} ({out.stat().st_size/1e6:.1f} MB, "
          f"{len(runs)} algorithms)")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Algorithm Arena</title>
<style>__LEAFLET_CSS__</style>
<script>__LEAFLET_JS__</script>
<script>
window.onerror=function(m,s,l,c){var d=document.createElement('div');
 d.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;background:#c00;color:#fff;padding:6px;font:13px monospace';
 d.textContent='VIEWER ERROR: '+m+' @'+l+':'+c;document.body.appendChild(d);};
</script>
<style>
 body{margin:0;font-family:-apple-system,Helvetica,sans-serif;display:flex;height:100vh}
 #map{flex:1} #panel{width:360px;background:#151a21;color:#dde;overflow-y:auto;padding:10px;font-size:12px}
 #batpanel{width:225px;background:#11151c;color:#dde;display:flex;flex-direction:column;
   font-size:11px;transition:width .2s;overflow:hidden}
 #batpanel.closed{width:30px}
 #bathead{display:flex;align-items:center;gap:6px;padding:6px;border-bottom:1px solid #2a3540;white-space:nowrap}
 #batpanel.closed #bathead b,#batpanel.closed #batcount,#batpanel.closed #batlist{display:none}
 #batcol{background:#222b36;color:#dde;border:1px solid #3a4550;border-radius:4px;cursor:pointer;padding:2px 6px}
 #batcount{color:#9ab;margin-left:auto;font-size:10px}
 #batlist{flex:1;overflow-y:auto;padding:2px 6px}
 .brow{display:flex;align-items:center;gap:5px;padding:1.5px 0;border-bottom:1px solid #1c232c;cursor:pointer}
 .brow:hover{background:#1a222c}
 .brow .bn{width:92px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#bcd}
 .brow.bdead .bn{color:#f66}
 .bbar{flex:1;height:7px;background:#222b36;border-radius:3px;overflow:hidden}
 .bfill{height:100%;background:#3c3;width:100%;border-radius:3px}
 .bpc{width:30px;text-align:right;font-variant-numeric:tabular-nums;color:#9ab}
 select#algo{font-size:15px;padding:3px;margin:4px 0;width:100%}
 table{width:100%;border-collapse:collapse;font-size:11px;margin:6px 0}
 td,th{border-bottom:1px solid #333;padding:2px 4px;text-align:right}
 th{color:#9ab} td:first-child,th:first-child{text-align:left}
 tr.active{background:#274; color:#fff}
 #controls{position:absolute;bottom:8px;left:10px;z-index:1000;background:rgba(20,25,33,.92);
   color:#dde;padding:8px 12px;border-radius:8px;display:flex;gap:8px;align-items:center}
 #scrub{width:300px} #clock{font-variant-numeric:tabular-nums;min-width:170px}
 #log{max-height:300px;overflow-y:auto;background:#0d1117;padding:6px;border-radius:6px}
 #log div{border-bottom:1px solid #222;padding:1px 0}
 .dead{color:#f66}.deliver{color:#6f6}.lg{font-size:10px;color:#9ab}
</style></head><body>
<div id="batpanel">
 <div id="bathead"><button id="batcol">◀</button> <b>relay batteries</b> <span id="batcount"></span></div>
 <div id="batlist"></div>
</div>
<div id="map"></div>
<div id="panel">
 <h2 id="ttl" style="font-size:14px"></h2>
 <select id="algo"></select>
 <label class="lg"><input type="checkbox" id="hikonly" checked> hiker traffic only
 (origins pulse at the hiker)</label>
 <div class="lg" id="layers" style="display:flex;flex-wrap:wrap;gap:2px 10px;margin:4px 0;padding:4px;background:#0d1117;border-radius:6px">
  <b style="width:100%">map layers</b>
  <label><input type="checkbox" id="ly_live" checked> <b style="color:#5c6">live coverage</b> (green=up, red=lost)</label>
  <label><input type="checkbox" id="ly_cov"> ITM signal heatmap</label>
  <label><input type="checkbox" id="ly_svc"> service-area outlines</label>
  <label><input type="checkbox" id="ly_lnk" checked> struggling links</label>
  <label><input type="checkbox" id="ly_trl" checked> trails</label>
 </div>
 <div class="lg" id="covstat" style="padding:2px 4px"></div>
 <div class="lg" style="padding:2px 4px;line-height:1.6">
  <b>node dots</b> = battery:
  <span style="color:hsl(120,82%,47%)">●</span> full
  <span style="color:hsl(60,82%,47%)">●</span> half
  <span style="color:hsl(18,82%,47%)">●</span> low (alive) ·
  <span style="color:#e01e1e">◯</span> red ring = dead<br>
  <b>coverage area</b>:
  <span style="color:#2abe5a">■</span> covered ·
  <span style="color:#eb1e1e">■</span> lost (all relays here dead)
 </div>
 <table id="stats"><tr><th>algo</th><th>PDR</th><th>SOS</th><th>util</th><th>deaths</th><th>Gini</th><th>rent%</th></tr></table>
 <canvas id="socchart" style="width:100%;height:90px;background:#0d1117;border-radius:6px"></canvas>
 <div class="lg">fleet battery through the year (p10–median band) · 📦 = charging box (count = radios docked)</div>
 <div class="lg">flash colors: <span style="color:#ff0">■</span> SOS <span style="color:#f39bff">■</span> DM
 <span style="color:#00e5ff">■</span> family <span style="color:#0cf">■</span> position <span style="color:#8f8">■</span> relay
 <span style="color:#f44">■</span> collision · switching algorithm keeps the clock</div>
 <h2 style="font-size:13px">Event log (<span id="mode"></span>)</h2><div id="log"></div>
</div>
<div id="controls">
 <button id="play">▶</button>
 <select id="speed"><option value="600">10 min/s</option>
 <option value="3600" selected>1 h/s (walking visible)</option>
 <option value="21600">6 h/s</option><option value="86400">1 d/s (days blur)</option>
 <option value="259200">3 d/s</option><option value="604800">1 wk/s (seasons)</option></select>
 <input type="range" id="scrub" min="0" max="1000" value="0"><span id="clock"></span>
</div>
<script>
const D=__DATA__;
document.getElementById('ttl').textContent=D.title;
const map=L.map('map');
L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{attribution:'OpenTopoMap'}).addTo(map);
const pts=Object.values(D.sites).map(s=>[s.lat,s.lon]);
map.fitBounds(L.latLngBounds(pts).pad(0.1));
if(D.nh.length){L.polyline(D.nh.concat([D.nh[0]]),{color:'#111',weight:2.5}).addTo(map);
 L.polygon([[[85,-180],[85,180],[-85,180],[-85,-180]],D.nh],
  {stroke:false,fillColor:'#fff',fillOpacity:0.35,interactive:false}).addTo(map);}
const trailLayer=L.layerGroup().addTo(map);
for(const line of Object.values(D.trails))
  trailLayer.addLayer(L.polyline(line,{color:'#0a58ff',weight:1.8,opacity:0.5}));
const svcLayer=L.layerGroup();
const svcPolys={};
for(const [n,sv] of Object.entries(D.service)){
  const p=[],mlat=111320,mlon=111320*Math.cos(sv.lat*Math.PI/180);
  for(let k=0;k<sv.r.length;k++){const az=k*2*Math.PI/sv.r.length,r=Math.max(sv.r[k],40);
    p.push([sv.lat+r*Math.cos(az)/mlat,sv.lon+r*Math.sin(az)/mlon]);}
  svcPolys[n]=L.polygon(p,{color:'#0a7d2c',weight:0.8,opacity:0.4,
    fillColor:'#27b04b',fillOpacity:0.07});
  svcLayer.addLayer(svcPolys[n]);
}
// ── live coverage grid: green where a relay is up, red where coverage died ──
const CG=D.covgrid;
let covImg=null, covPixels=null, covCanvas=null;
if(CG){
  covCanvas=document.createElement('canvas');
  covCanvas.width=CG.nlon; covCanvas.height=CG.nlat;
  covPixels=covCanvas.getContext('2d').createImageData(CG.nlon,CG.nlat);
  const bounds=[[CG.lat0,CG.lon0],
    [CG.lat0+CG.nlat*CG.cell,CG.lon0+CG.nlon*CG.cell]];
  covImg=L.imageOverlay('',bounds,{opacity:0.72,interactive:false,className:'covgrid'});
  if(document.getElementById('ly_live').checked)covImg.addTo(map);
}
// canvas rows run top→bottom but our grid row 0 is the SOUTH edge, so flip
function paintCoverage(){
  if(!CG||!covImg)return;
  const d=covPixels.data, nlon=CG.nlon, nlat=CG.nlat;
  let up=0, lost=0;
  d.fill(0);
  for(const [cell,nodes] of covEntries){
    const row=(cell/nlon)|0, col=cell%nlon;
    let anyAlive=false;
    for(let z=0;z<nodes.length;z++){if(aliveSet[nodes[z]]){anyAlive=true;break;}}
    anyAlive?up++:lost++;
    const y=nlat-1-row, o=(y*nlon+col)*4;
    // green = still covered (soft, lets terrain show); red = coverage LOST
    // (bold + opaque, because "where does coverage end" is the whole point)
    if(anyAlive){d[o]=42;d[o+1]=190;d[o+2]=90;d[o+3]=120;}
    else{d[o]=235;d[o+1]=30;d[o+2]=30;d[o+3]=235;}
  }
  covCanvas.getContext('2d').putImageData(covPixels,0,0);
  covImg.setUrl(covCanvas.toDataURL());
  const tot=up+lost, km2=Math.round(up*CG.cell_km2);
  document.getElementById('covstat').innerHTML=tot?
    '<b style="color:#5c6">'+Math.round(up/tot*100)+'% coverage online</b> · '+
    km2.toLocaleString()+' km² · <span style="color:#e66">'+
    Math.round(lost*CG.cell_km2).toLocaleString()+' km² lost</span>':'';
}
const covEntries=CG?Object.entries(CG.cov).map(([k,v])=>[+k,v]):[];
// aliveSet[nodeIdx] tracks each relay's current alive state for the grid
const covNameIdx={}; if(CG)CG.names.forEach((n,i)=>covNameIdx[n]=i);
const aliveSet=CG?new Uint8Array(CG.names.length).fill(1):null;
// ITM coverage heatmaps (one raster per gateway; RdYlGn centered on the
// -100 dBm planning threshold) — off by default, toggled from the panel
const covLayer=L.layerGroup();
for(const c of (D.cov||[]))
  covLayer.addLayer(L.imageOverlay(c.png,c.bounds,{opacity:0.55,interactive:false}));
function wireLayer(id,layer){const cb=document.getElementById(id);
 cb.onchange=()=>{cb.checked?layer.addTo(map):layer.remove();};}
wireLayer('ly_cov',covLayer);
wireLayer('ly_svc',svcLayer);
wireLayer('ly_trl',trailLayer);
if(covImg)document.getElementById('ly_live').onchange=e=>{
 e.target.checked?covImg.addTo(map):covImg.remove();if(e.target.checked)paintCoverage();};
// ── relay-battery sidebar: live list, worst first, collapsible ────────────
const relayNames=Object.keys(D.sites).filter(n=>!D.sites[n].mqtt).sort();
const batList=document.getElementById('batlist');
for(const n of relayNames){
  const row=document.createElement('div');row.className='brow';row.id='br_'+n;
  row.innerHTML='<span class="bn" title="'+n+'">'+n+'</span>'+
   '<div class="bbar"><div class="bfill" id="bf_'+n+'"></div></div>'+
   '<span class="bpc" id="bp_'+n+'">—</span>';
  row.onclick=()=>{const s=D.sites[n];map.setView([s.lat,s.lon],12);
    if(markers[n])markers[n].openTooltip();};
  batList.appendChild(row);
}
let lastSort=0,lastPaint=0;
function updateBatList(){
  let alive=0,dead=0,covChanged=false;
  for(const n of relayNames){
    const rec=batOf(n);if(!rec)continue;
    const f=document.getElementById('bf_'+n),p=document.getElementById('bp_'+n);
    const isAlive=rec[3]===1; isAlive?alive++:dead++;
    if(aliveSet&&n in covNameIdx){const v=isAlive?1:0;
      if(aliveSet[covNameIdx[n]]!==v){aliveSet[covNameIdx[n]]=v;covChanged=true;}}
    if(f){f.style.width=Math.round(Math.max(rec[1],0.02)*100)+'%';
      f.style.background=socColor(rec[1],isAlive);}
    if(p){p.textContent=isAlive?Math.round(rec[1]*100)+'%':'✕';
      p.style.color=isAlive?'':'#f66';}
    document.getElementById('br_'+n).classList.toggle('bdead',!isAlive);
  }
  document.getElementById('batcount').textContent=alive+' up · '+dead+' down';
  const now=performance.now();
  if(covChanged&&now-lastPaint>250){lastPaint=now;paintCoverage();}
  if(now-lastSort>600){lastSort=now;
    const order=relayNames.slice().sort((a,b)=>{
      const ra=batOf(a),rb=batOf(b);
      const ka=ra?(ra[3]===1?ra[1]:-1):2,kb=rb?(rb[3]===1?rb[1]:-1):2;
      return ka-kb;});
    for(const n of order)batList.appendChild(document.getElementById('br_'+n));}
}
document.getElementById('batcol').onclick=()=>{
  const bp=document.getElementById('batpanel');
  bp.classList.toggle('closed');
  document.getElementById('batcol').textContent=bp.classList.contains('closed')?'🔋':'◀';
  setTimeout(()=>map.invalidateSize(),250);};
const markers={};
for(const [n,s] of Object.entries(D.sites))
  markers[n]=L.circleMarker([s.lat,s.lon],{radius:s.mqtt?8:5,color:'#fff',weight:1,
    fillColor:'#3c3',fillOpacity:0.9}).addTo(map).bindTooltip(n);
const moverMarkers={};
for(const [n,tk] of Object.entries(D.movers))
  moverMarkers[n]=L.circleMarker([tk[0][1],tk[0][2]],{radius:6,color:'#123',
    weight:1.5,fillColor:'#f7b500',fillOpacity:1}).addTo(map).bindTooltip(n);
function kioskHtml(n,count,frac){
  const pct=Math.round(frac*100);
  const bar=Math.max(4,Math.round(26*frac));
  const col=frac>0.5?'#35c46a':(frac>0.2?'#e0a80f':'#d24545');
  return '<div id="kk_'+n+'" style="width:38px;font-family:-apple-system,sans-serif;'+
    'filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))">'+
    '<svg width="38" height="30" viewBox="0 0 38 30">'+
    '<rect x="1" y="1" width="36" height="22" rx="4" fill="#1b2733" stroke="#fff" stroke-width="1.5"/>'+
    '<path d="M17 5 L13 13 L17 13 L15 19 L23 10 L18 10 L21 5 Z" fill="'+col+'"/>'+
    '<text x="30" y="16" font-size="10" font-weight="700" fill="#fff" text-anchor="middle" id="kkc_'+n+'">'+count+'</text>'+
    '<rect x="5" y="25" width="28" height="4" rx="2" fill="#333"/>'+
    '<rect x="6" y="26" width="'+bar+'" height="2" rx="1" fill="'+col+'" id="kkb_'+n+'"/>'+
    '</svg></div>';
}
const kioskMarkers={}; let kioskIdx=0;
for(const [n,s] of Object.entries(D.sites)){ /* kiosk markers built lazily */ }
function ensureKiosk(n){
  if(kioskMarkers[n]||!D.sites[n])return;
  const s=D.sites[n];
  kioskMarkers[n]=L.marker([s.lat,s.lon],{icon:L.divIcon({className:'',
    html:'<div style="background:#173;color:#fff;border:2px solid #fff;border-radius:4px;padding:1px 5px;font-size:11px;font-weight:bold" id="kk_'+n+'">📦</div>',
    iconSize:null})}).addTo(map).bindTooltip('charging box '+n);
}
function applyKiosks(){
  const ks=R.kiosks||[]; if(!ks.length)return;
  while(kioskIdx<ks.length-1&&ks[kioskIdx+1][0]<=simT)kioskIdx++;
  const inv=ks[Math.min(kioskIdx,ks.length-1)][1];
  for(const n in inv)ensureKiosk(n);
  for(const n in kioskMarkers){
    const el=document.getElementById('kk_'+n); if(!el)continue;
    const socs=inv[n]||[];
    const frac=socs.length?socs.reduce((a,b)=>a+b,0)/socs.length:0;
    el.outerHTML=kioskHtml(n,socs.length,frac);
    kioskMarkers[n].setTooltipContent('box '+n+': '+socs.map(x=>Math.round(x*100)+'%').join(', '));
  }
}
let linkLayer=L.layerGroup().addTo(map);
function rebuildLinks(){
  linkLayer.remove(); linkLayer=L.layerGroup();
  if(document.getElementById('ly_lnk').checked)linkLayer.addTo(map);
  for(const l of (R.links||[]))
    if(l[4])linkLayer.addLayer(L.polyline([[l[0],l[1]],[l[2],l[3]]],
      {color:'#ff8800',weight:2,opacity:0.7,dashArray:'6 6'}));
}
document.getElementById('ly_lnk').onchange=e=>
  e.target.checked?linkLayer.addTo(map):linkLayer.remove();
// walker radio assignment: walker -> current radio (for battery fill)
let asgIdx=0; const walkerRadio={};
function applyAssigns(){
  const A=R.assigns||[];
  while(asgIdx<A.length&&A[asgIdx][0]<=simT){walkerRadio[A[asgIdx][1]]=A[asgIdx][2];asgIdx++;}
}
const moverTails={};
for(const [n,md] of Object.entries(D.moverdef||{})){
  const g=D.routegeom[md.route];
  moverMarkers[n]=L.circleMarker([g.lat[0],g.lon[0]],{radius:6,color:'#f7b500',
    weight:2.5,fillColor:'#3c3',fillOpacity:1}).addTo(map).bindTooltip(n);
  moverTails[n]=L.polyline([],{color:'#ff9500',weight:3,opacity:0.85}).addTo(map);
}
function routePos(md,t){
  const g=D.routegeom[md.route];
  let tt=(t%86400)-md.start;
  const walking=tt>=0&&tt<=g.dur;
  tt=Math.min(Math.max(tt,0),g.dur);
  // binary search along the timed polyline, then interpolate the segment
  let lo=0,hi=g.t.length-1;
  while(hi-lo>1){const m=(lo+hi)>>1; if(g.t[m]<=tt)lo=m; else hi=m;}
  const f=g.t[hi]>g.t[lo]?(tt-g.t[lo])/(g.t[hi]-g.t[lo]):0;
  return [g.lat[lo]+(g.lat[hi]-g.lat[lo])*f,
          g.lon[lo]+(g.lon[hi]-g.lon[lo])*f, walking];
}

// ── run switching ──────────────────────────────────────────────────────────
const modes=Object.keys(D.runs);
// default to a duty-cycled mode if present: those keep relays alive long
// enough that coverage loss reads as a gradual winter recession rather than
// an instant day-10 blackout (flood/always-on collapse before you can watch)
let mode=modes.find(m=>m.startsWith('duty'))||modes[0];
const sel=document.getElementById('algo');
for(const m of modes){const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);}
sel.value=mode;
const tbl=document.getElementById('stats');
for(const m of modes){
  const s=D.runs[m].stats, r=tbl.insertRow(); r.id='row_'+m;
  r.innerHTML=`<td>${m}</td><td>${(s.pdr*100).toFixed(1)}%</td><td>${s.sos}</td>`+
    `<td>${(s.util*100).toFixed(0)}%</td><td>${s.deaths??'—'}</td><td>${s.gini??'—'}</td>`+
    `<td>${s.avail!=null?(s.avail*100).toFixed(0)+'%':'—'}</td>`;
}
let R=D.runs[mode];
let simT=0,playing=false,lastReal=null,ei=0,li=0;
const mi={},bi={};
function resetCursors(){ei=R.edges.findIndex(e=>e[0]>=simT);if(ei<0)ei=R.edges.length;
 li=R.log.findIndex(l=>l[0]>=simT);if(li<0)li=R.log.length;
 for(const n in R.bat){bi[n]=0;while(bi[n]<R.bat[n].length-1&&R.bat[n][bi[n]+1][0]<=simT)bi[n]++;}
 for(const n in D.movers){mi[n]=0;while(mi[n]<D.movers[n].length-1&&D.movers[n][mi[n]+1][0]<=simT)mi[n]++;}
 for(const n in (D.moverdef||{}))applyMover(n);
 document.getElementById('log').innerHTML='';applyBat();}
function setMode(m){mode=m;R=D.runs[m];document.getElementById('mode').textContent=m;
 for(const x of modes)document.getElementById('row_'+x).className=x===m?'active':'';
 kioskIdx=0;asgIdx=0;for(const k in walkerRadio)delete walkerRadio[k];
 rebuildLinks();resetCursors();applyAssigns();applyKiosks();drawSoc();
 if(aliveSet)aliveSet.fill(1);updateBatList();paintCoverage();}
sel.onchange=e=>setMode(e.target.value);
// battery ramp stops at amber (hue 18), never pure red, so a low-but-ALIVE
// relay reads as amber — red is reserved for DEATH (dead dots get a red ring,
// dead coverage goes red) so the two never get confused
function socColor(s,alive){if(!alive)return'#3a2323';return`hsl(${Math.max(18,Math.min(120,s*120))},82%,47%)`;}
function socRing(alive){return alive?'#fff':'#e01e1e';}
function batOf(n){const b=R.bat[n];if(!b)return null;
 return b[Math.min(bi[n]??0,b.length-1)];}
function applyBat(){for(const n in R.bat){const rec=batOf(n);
 if(!rec)continue;const a=rec[3]===1;
 if(markers[n])markers[n].setStyle({fillColor:socColor(rec[1],a),
   color:socRing(a),weight:a?1:2.5});
 if(moverMarkers[n]){moverMarkers[n].setStyle({fillColor:socColor(rec[1],rec[3]===1)});
  moverMarkers[n].setTooltipContent(n+' — battery '+Math.round(rec[1]*100)+'%');}
 if(svcPolys[n])svcPolys[n].setStyle(rec[3]===1?{opacity:0.4,fillOpacity:0.07}:{opacity:0.1,fillOpacity:0,color:'#c22'});}
 // walkers wear their assigned radio's battery
 for(const w in walkerRadio){const rec=batOf(walkerRadio[w]);
  if(rec&&moverMarkers[w]){moverMarkers[w].setStyle({fillColor:socColor(rec[1],rec[3]===1)});
   moverMarkers[w].setTooltipContent(w+' ('+walkerRadio[w]+') — '+Math.round(rec[1]*100)+'%');}}
 updateBatList();}
function drawSoc(){
  const c=document.getElementById('socchart');if(!c)return;
  const w=c.clientWidth,h=c.clientHeight;
  if(c.width!==w)c.width=w; if(c.height!==h)c.height=h;
  const g=c.getContext('2d');g.clearRect(0,0,w,h);
  const S=R.soc6h||[];if(!S.length)return;
  const dur=D.duration_s/86400;
  g.strokeStyle='#4c9';g.beginPath();
  S.forEach((r,i)=>{const x=r[0]/dur*w,y=h-2-r[2]*(h-6);i?g.lineTo(x,y):g.moveTo(x,y);});
  g.stroke();
  g.strokeStyle='rgba(80,200,150,0.4)';g.beginPath();
  S.forEach((r,i)=>{const x=r[0]/dur*w,y=h-2-r[1]*(h-6);i?g.lineTo(x,y):g.moveTo(x,y);});
  g.stroke();
  g.strokeStyle='#fff';g.beginPath();
  const px=simT/D.duration_s*w;g.moveTo(px,0);g.lineTo(px,h);g.stroke();
}
function applyMover(n){
 const md=(D.moverdef||{})[n];
 if(md){const q=routePos(md,simT);
  moverMarkers[n].setLatLng([q[0],q[1]]);
  moverMarkers[n].setStyle({fillOpacity:q[2]?1:0.25});
  // breadcrumb tail: the trail actually walked in the last ~2.5 h — drawn
  // from route geometry, so switchbacks render at ANY playback speed
  const g=D.routegeom[md.route];
  if(q[2]){
    const tt=Math.min(Math.max((simT%86400)-md.start,0),g.dur), t0=Math.max(tt-9000,0);
    const pts=[];
    for(let i=0;i<g.t.length;i++){
      if(g.t[i]>=t0&&g.t[i]<=tt&&(pts.length===0||i%2===0))pts.push([g.lat[i],g.lon[i]]);
      if(g.t[i]>tt)break;
    }
    pts.push([q[0],q[1]]);
    moverTails[n].setLatLngs(pts);
  } else moverTails[n].setLatLngs([]);
  return;}
 const tk=D.movers[n],k=Math.min(mi[n],tk.length-1);
 const p0=tk[k],p1=tk[Math.min(k+1,tk.length-1)];let la=p0[1],lo=p0[2];
 if(p1[0]>p0[0]&&!p0[3]&&!p1[3]){const f=Math.max(0,Math.min(1,(simT-p0[0])/(p1[0]-p0[0])));
  la=p0[1]+(p1[1]-p0[1])*f;lo=p0[2]+(p1[2]-p0[2])*f;}
 moverMarkers[n].setLatLng([la,lo]);
 moverMarkers[n].setStyle({fillOpacity:p0[3]?0.25:1});}
const logDiv=document.getElementById('log');
const flashes=[];const flashLayer=L.layerGroup().addTo(map);
function fmt(t){const d=new Date(Date.parse(D.start_utc)+t*1000-4*3600*1000);
 return'day '+(Math.floor(t/86400)+1)+' · '+d.toISOString().substr(11,8)+' ET';}
function step(dt){simT=Math.min(simT+dt,D.duration_s);
 const hikOnly=document.getElementById('hikonly').checked;
 while(ei<R.edges.length&&R.edges[ei][0]<=simT){const e=R.edges[ei++];
  if(hikOnly&&!e[7])continue;
  if(simT-e[0]<dt+2){const col=e[5]===0?'#f44':(e[6]==='sos'?'#ff0':(e[6]==='msg'?'#f39bff':
   (e[6]==='fam'?'#00e5ff':(e[6]==='pos'?'#0cf':'#8f8'))));
   const w=e[7]?(e[6]==='sos'?5:3):1.5;
   const ln=L.polyline([[e[1],e[2]],[e[3],e[4]]],{color:col,weight:w,
     opacity:e[7]?0.95:0.5,dashArray:'2 7'});  // dashed = radio signal, not a path
   flashLayer.addLayer(ln);flashes.push({l:ln,until:performance.now()+700});
   if(e[7]){const pulse=L.circleMarker([e[1],e[2]],{radius:9,color:col,weight:3,
     fill:false,opacity:0.95});
    flashLayer.addLayer(pulse);flashes.push({l:pulse,until:performance.now()+700});}}}
 for(const n in D.movers){while(mi[n]<D.movers[n].length-1&&D.movers[n][mi[n]+1][0]<=simT)mi[n]++;applyMover(n);}
 for(const n in (D.moverdef||{}))applyMover(n);
 while(li<R.log.length&&R.log[li][0]<=simT){const l=R.log[li++];
  const e=document.createElement('div');e.className=l[1];e.textContent=fmt(l[0])+' — '+l[2];
  logDiv.prepend(e);while(logDiv.children.length>70)logDiv.lastChild.remove();}
 let dirty=false;for(const n in R.bat){while(bi[n]<R.bat[n].length-1&&R.bat[n][bi[n]+1][0]<=simT){bi[n]++;dirty=true;}}
 applyAssigns(); applyKiosks();
 if(dirty)applyBat();
 drawSoc();
 document.getElementById('clock').textContent=fmt(simT);
 document.getElementById('scrub').value=Math.round(simT/D.duration_s*1000);}
function loop(now){if(playing){const dt=lastReal?(now-lastReal)/1000:0;lastReal=now;
  step(dt*parseFloat(document.getElementById('speed').value));
  if(simT>=D.duration_s){playing=false;document.getElementById('play').textContent='▶';}}
 else lastReal=now;
 const nw=performance.now();
 for(let i=flashes.length-1;i>=0;i--)if(flashes[i].until<nw){flashLayer.removeLayer(flashes[i].l);flashes.splice(i,1);}
 requestAnimationFrame(loop);}
document.getElementById('play').onclick=()=>{playing=!playing;
 document.getElementById('play').textContent=playing?'⏸':'▶';};
document.getElementById('scrub').oninput=e=>{simT=e.target.value/1000*D.duration_s;resetCursors();};
setMode(mode);simT=11*3600;resetCursors();requestAnimationFrame(loop);
</script></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())

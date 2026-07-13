#!/usr/bin/env python3
"""Render the mesh simulation trace as an interactive HTML playback viewer.

Single self-contained HTML (Leaflet from CDN, all data embedded):
  - topo basemap with every node; fill color = live battery SOC, gateways
    starred; the hiker marker replays the real GPX
  - packet transmissions animate as flashes along links (green = received,
    red = collision); MQTT deliveries burst at the gateway
  - play/pause + speed + scrubber; sim clock in UTC and ET
  - side panel: per-node SOC bars + solar watts + event log
  - SOC strip chart across the whole run with a playhead
  - AIRMap layer: ITM predicted-coverage raster per MQTT gateway, computed
    over the real DEM (cached in artifacts/sim/), toggleable like any layer

Run: .venv/bin/python scripts/render_sim_viewer.py
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import (  # noqa: E402
    Dem,
    PLANNING_DBM,
    RX_POWER_REF_DBM,
    RX_SENS_DBM,
    itm_p2p_loss,
)


def coverage_layer(dem: Dem, name: str, lat: float, lon: float, hg: float,
                   grid: int = 60, pad: tuple[float, float] = (0.045, 0.06)) -> dict:
    """ITM predicted-RSSI raster from one transmitter → base64 PNG + bounds.
    Cached per site in artifacts/sim/coverage_<name>.npz."""
    # cache key includes grid+pad: same gateway at different extents (pilot
    # 5 km vs statewide 12 km) must not share a raster or bounds drift
    cache = ROOT / (f"artifacts/sim/coverage_{name}_{grid}"
                    f"_{pad[0]:.3f}_{pad[1]:.3f}.npz")
    lat_lo = max(lat - pad[0], float(dem.lat.min()))
    lat_hi = min(lat + pad[0], float(dem.lat.max()))
    lon_lo = max(lon - pad[1], float(dem.lon.min()))
    lon_hi = min(lon + pad[1], float(dem.lon.max()))
    if cache.exists():
        pred = np.load(cache)["pred"]
    else:
        lats = np.linspace(lat_lo, lat_hi, grid)
        lons = np.linspace(lon_lo, lon_hi, grid)
        pred = np.full((grid, grid), np.nan)
        print(f"  computing ITM coverage grid for {name} ({grid}x{grid}) ...")
        for i, la in enumerate(lats):
            for j, lo in enumerate(lons):
                d_m, prof = dem.profile(lat, lon, la, lo)
                if d_m < 30.0:
                    pred[i, j] = RX_POWER_REF_DBM
                    continue
                try:
                    itm = itm_p2p_loss(d_m / 1000.0, prof, (hg, 1.5))
                    pred[i, j] = RX_POWER_REF_DBM - itm["loss_db_q50"]
                except Exception:
                    pass
        np.savez_compressed(cache, pred=pred)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.cm as cm
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    norm = TwoSlopeNorm(vmin=-140, vcenter=PLANNING_DBM, vmax=-60)
    rgba = cm.RdYlGn(norm(pred))
    rgba[..., 3] = np.where(np.isnan(pred), 0.0, 0.55)
    tmp = ROOT / f"artifacts/sim/_cov_{name}.png"
    plt.imsave(tmp, np.flipud(rgba))
    b64 = base64.b64encode(tmp.read_bytes()).decode()
    return {"name": name, "png": f"data:image/png;base64,{b64}",
            "bounds": [[lat_lo, lon_lo], [lat_hi, lon_hi]]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive HTML viewer for mesh_sim traces")
    ap.add_argument("--trace", default="artifacts/sim/trace.jsonl")
    ap.add_argument("--summary", default="artifacts/sim/summary.json")
    ap.add_argument("--topology", default="artifacts/sim/topology.json")
    ap.add_argument("--dem-npz", default="artifacts/dem/cache/usgs_3dep_presidentials_wide.npz")
    ap.add_argument("--out", default="artifacts/sim/sim_viewer.html")
    ap.add_argument("--no-coverage", action="store_true", help="Skip AIRMap layers")
    ap.add_argument("--pos-stride", type=int, default=1,
                    help="Keep every Nth mover fix (year-scale traces)")
    ap.add_argument("--bat-stride", type=int, default=1)
    ap.add_argument("--routes", default="artifacts/sim/routes.json",
                    help="Draw these trail geometries under the movers")
    ap.add_argument("--title", default="Presidentials pilot",
                    help="Scope label shown in the viewer header")
    ap.add_argument("--service-areas", default="artifacts/sim/service_areas.json",
                    help="Terrain-clipped per-site service polygons (live layer)")
    args = ap.parse_args()

    topo = json.loads((ROOT / args.topology).read_text())
    summary = json.loads((ROOT / args.summary).read_text())
    sites = topo["sites"]

    # ── digest the trace ─────────────────────────────────────────────────────
    kind_of_pkt: dict[int, str] = {}
    edges, bat, log = [], {}, []
    edges_h = []
    kiosk_series: list = []               # [[t, {kiosk: [socs...]}], ...]
    movers: dict[str, list] = {}          # name -> [[t, lat, lon, docked], ...]
    node_pos_now = {n: (s["lat"], s["lon"]) for n, s in sites.items()}
    with open(ROOT / args.trace) as fh:
        for line in fh:
            e = json.loads(line)
            ev, t = e["ev"], e["t"]
            if ev == "tx":
                kind_of_pkt.setdefault(e["pkt"], e["kind"] if e["kind"] != "fwd" else
                                       kind_of_pkt.get(e["pkt"], "fwd"))
            elif ev in ("rx", "col"):
                frm, to = e["from"], e["n"]
                fp = node_pos_now.get(frm)
                tp = node_pos_now.get(to)
                if fp and tp:
                    hk = 1 if frm.startswith(("rent_", "hiker_", "radio_")) else 0
                    (edges_h if hk else edges).append(
                        [round(t, 1), fp[0], fp[1], tp[0], tp[1],
                         1 if ev == "rx" else 0,
                         kind_of_pkt.get(e["pkt"], "tel")])
            elif ev == "pos":
                node_pos_now[e["n"]] = (e["lat"], e["lon"])
                movers.setdefault(e["n"], []).append(
                    [round(t, 1), e["lat"], e["lon"], e.get("dk", 0)])
            elif ev == "bat":
                bat.setdefault(e["n"], []).append([round(t, 1), e["soc"], e["sw"],
                                                   1 if e["alive"] else 0])
            elif ev == "deliver":
                kind = e.get("kind", "tel")
                if kind == "sos":
                    txt = f"🆘 SOS from {e['orig']} → SAR HQ via {e['via']} ({e['lat_s']}s)"
                elif kind == "msg":
                    txt = f"DM {e['orig']} → {e['via']} delivered ({e['lat_s']}s)"
                elif kind == "fam":
                    txt = f"family msg from {e['orig']} → world via {e['via']} ({e['lat_s']}s)"
                else:
                    txt = f"{kind} from {e['orig']} → backhaul via {e['via']} ({e['lat_s']}s)"
                log.append([round(t, 1), "deliver", txt])
                p = node_pos_now.get(e["via"])
                if p:
                    edges.append([round(t, 1), p[0], p[1], p[0], p[1], 2, "mqtt"])
            elif ev == "kiosk":
                kiosk_series.append([round(t, 1), e["inv"]])
            elif ev == "assign":
                log.append([round(t, 1), "rent",
                            f"{e['walker']} took {e['radio']} from {e['kiosk']} "
                            f"@ {e['soc']*100:.0f}% (best in box)"])
            elif ev == "starved":
                log.append([round(t, 1), "dead",
                            f"⚠ {e['walker']} found NO radio at {e['kiosk']}"])
            elif ev in ("rent", "return"):
                log.append([round(t, 1), ev,
                            f"{e['n']} {'checked out of' if ev == 'rent' else 'returned to'} "
                            f"{e.get('kiosk','?')} @ {e['soc']*100:.0f}%"])
            elif ev in ("dead", "alive"):
                log.append([round(t, 1), ev, f"node {e['n']} {ev}"])

    # cap edge volume; hiker-origin lines get half the budget so relay
    # chatter can never drown out where messages actually come from
    MAX_EDGES = 24000
    half = MAX_EDGES // 2
    if len(edges_h) > half:
        idx = np.linspace(0, len(edges_h) - 1, half).astype(int)
        edges_h = [edges_h[i] for i in idx]
    room = MAX_EDGES - len(edges_h)
    if len(edges) > room:
        idx = np.linspace(0, len(edges) - 1, room).astype(int)
        edges = [edges[i] for i in idx]
    edges = sorted(edges + edges_h, key=lambda e: e[0])
    if args.pos_stride > 1:
        movers = {n: v[::args.pos_stride] for n, v in movers.items()}
    if args.bat_stride > 1:
        bat = {n: v[::args.bat_stride] for n, v in bat.items()}

    layers = []
    if not args.no_coverage:
        dem = Dem(ROOT / args.dem_npz)
        for n, s in sites.items():
            if s.get("mqtt_uplink"):
                layers.append(coverage_layer(dem, n, s["lat"], s["lon"], s["hg_m"]))

    # link-health overlay: struggling/healthy fixed links with endpoints
    links = []
    for r in summary.get("link_health", []):
        a, b = sites.get(r["a"]), sites.get(r["b"])
        if a and b:
            links.append([a["lat"], a["lon"], b["lat"], b["lon"], r["prr"],
                          r["mean_margin_db"], 1 if r["struggling"] else 0,
                          f"{r['a']}↔{r['b']} PRR {r['prr']:.2f}, margin {r['mean_margin_db']:+.1f} dB"])

    data = {
        "sites": {n: {"lat": s["lat"], "lon": s["lon"], "mqtt": bool(s.get("mqtt_uplink")),
                      "power": s.get("power", "battery"), "label": s.get("label", n)}
                  for n, s in sites.items()},
        "duration_s": summary["days"] * 86400,
        "start_utc": summary.get("start_date", "2026-07-10") + "T00:00:00Z",
        "title": args.title,
        "mode": summary["mode"],
        "pdr": summary["pdr_overall"],
        "edges": edges, "movers": movers, "bat": bat, "log": log,
        "links": links,
        "trails": {},
        "service": {},
        "nh": [],
        "kiosks": kiosk_series,
        "coverage": layers,
    }
    nh_p = ROOT / "artifacts/osm/nh_boundary.json"
    if nh_p.exists():
        g = json.loads(nh_p.read_text())
        ring = (g["coordinates"][0] if g["type"] == "Polygon"
                else g["coordinates"][0][0])
        data["nh"] = [[round(c[1], 4), round(c[0], 4)] for c in ring]
    sa_p = ROOT / args.service_areas if args.service_areas else None
    if sa_p and sa_p.exists():
        sa = json.loads(sa_p.read_text())
        for n, sv in sa["sites"].items():
            if n in sites:
                data["service"][n] = {"lat": sv["lat"], "lon": sv["lon"],
                                      "r": sv["range_m"]}
    routes_p = ROOT / args.routes if args.routes else None
    data["routegeom"], data["moverdef"] = {}, {}
    if routes_p and routes_p.exists():
        rj = json.loads(routes_p.read_text())
        for rn, r in rj["routes"].items():
            pts = list(zip(r["lat"], r["lon"]))
            data["trails"][rn] = [[round(a, 5), round(b, 5)] for a, b in pts[::3]]
            data["routegeom"][rn] = {
                "t": [round(float(x), 1) for x in r["t_s"][::2]],
                "lat": [round(float(x), 5) for x in r["lat"][::2]],
                "lon": [round(float(x), 5) for x in r["lon"][::2]],
                "dur": r["duration_s"]}
        # renters walk analytically along the exact trail; drop their fix tracks
        for n in list(movers):
            if n.startswith("rent_"):
                body = n[5:]
                rname, _, k = body.rpartition("_")
                if rname in rj["routes"] and k.isdigit():
                    data["moverdef"][n] = {"route": rname,
                                           "start": (11.5 + 1.5 * int(k)) * 3600.0}
        data["movers"] = {n: v for n, v in data["movers"].items()
                          if n not in data["moverdef"]}

    vendor = ROOT / "artifacts/vendor"
    html = (TEMPLATE
            .replace("__LEAFLET_CSS__", (vendor / "leaflet.css").read_text())
            .replace("__LEAFLET_JS__", (vendor / "leaflet.js").read_text())
            .replace("__DATA__", json.dumps(data)))
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"viewer: {out}  ({out.stat().st_size/1e6:.1f} MB, {len(edges)} edges, "
          f"{len(movers)} movers, {len(links)} links, {len(layers)} coverage layers)")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>WMNF Mesh Simulation</title>
<style>__LEAFLET_CSS__</style>
<script>__LEAFLET_JS__</script>
<script>
window.onerror=function(m,s,l,c){var d=document.createElement('div');
 d.style.cssText='position:fixed;top:0;left:0;right:0;z-index:9999;background:#c00;color:#fff;padding:6px;font:13px monospace';
 d.textContent='VIEWER ERROR: '+m+' @'+l+':'+c;document.body.appendChild(d);};
</script>
<style>
 body{margin:0;font-family:-apple-system,Helvetica,sans-serif;display:flex;height:100vh}
 #map{flex:1}
 #panel{width:330px;background:#151a21;color:#dde;overflow-y:auto;padding:10px;font-size:12px}
 #panel h2{font-size:14px;margin:4px 0}
 .bar{background:#333;height:10px;border-radius:5px;margin:2px 0 8px}
 .fill{height:10px;border-radius:5px;background:#3c3}
 #controls{position:absolute;bottom:96px;left:10px;z-index:1000;background:rgba(20,25,33,.92);
   color:#dde;padding:8px 12px;border-radius:8px;display:flex;gap:8px;align-items:center}
 #controls button{font-size:16px;width:34px;height:28px}
 #scrub{width:320px}
 #clock{font-variant-numeric:tabular-nums;font-size:13px;min-width:190px}
 #chart{position:absolute;bottom:0;left:0;right:340px;height:86px;background:rgba(20,25,33,.92);z-index:1000}
 .lg{font-size:10px;color:#9ab}
 #log{max-height:220px;overflow-y:auto;background:#0d1117;padding:6px;border-radius:6px}
 #log div{border-bottom:1px solid #222;padding:1px 0}
 .dead{color:#f66}.deliver{color:#6f6}.rent{color:#f7b500}.return{color:#c90}
</style></head><body>
<div id="map"></div>
<div id="panel">
 <h2 id="scope"></h2>
 <div class="lg"><span id="nsites"></span> fixed sites · <span id="mode"></span> · overall PDR <b id="pdr"></b> · ★ = MQTT/SAR-HQ backhaul · node color = battery</div>
 <div class="lg">flash colors: <span style="color:#ff0">■</span> SOS <span style="color:#f39bff">■</span> hiker-DM <span style="color:#00e5ff">■</span> family <span style="color:#0cf">■</span> position <span style="color:#8f8">■</span> relay <span style="color:#f44">■</span> collision</div>
 <div id="nodes"></div>
 <h2>Event log</h2><div id="log"></div>
</div>
<div id="controls">
 <button id="play">▶</button>
 <select id="speed"><option value="60">60×</option><option value="600" selected>600×</option>
  <option value="3600">1 h/s</option><option value="14400">4 h/s</option>
  <option value="21600">6 h/s</option><option value="86400">1 d/s</option>
  <option value="259200">3 d/s</option><option value="604800">1 wk/s</option></select>
 <input type="range" id="scrub" min="0" max="1000" value="0">
 <span id="clock"></span>
</div>
<canvas id="chart"></canvas>
<script>
const D = __DATA__;
const map = L.map('map');
const topoL = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{attribution:'OpenTopoMap'});
const satL = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{attribution:'Esri'});
topoL.addTo(map);
const overlays = {};
for (const c of D.coverage){
  overlays['AIRMap: '+c.name] = L.imageOverlay(c.png, c.bounds, {opacity:0.55});
}
const pts = Object.values(D.sites).map(s=>[s.lat,s.lon]);
if (D.nh && D.nh.length){
  // black state line; translucent mask outside NH (world ring + NH hole)
  L.polyline(D.nh.concat([D.nh[0]]),{color:'#111',weight:2.5,opacity:0.9}).addTo(map);
  const world=[[85,-180],[85,180],[-85,180],[-85,-180]];
  L.polygon([world, D.nh],{stroke:false,fillColor:'#ffffff',
    fillOpacity:0.35,interactive:false}).addTo(map);
}
map.fitBounds(L.latLngBounds(pts).pad(0.15));

// nodes
const markers={}, socNow={}, aliveNow={};
function socColor(s,alive){ if(!alive) return '#555';
  const h = Math.max(0,Math.min(120, s*120)); return `hsl(${h},80%,45%)`; }
for (const [n,s] of Object.entries(D.sites)){
  const m = L.circleMarker([s.lat,s.lon],{radius:s.mqtt?10:7,color:'#fff',weight:1.5,
    fillColor:'#3c3',fillOpacity:0.95}).addTo(map).bindTooltip((s.mqtt?'★ ':'')+n+' — '+s.label);
  markers[n]=m; socNow[n]=1; aliveNow[n]=true;
}
// kiosk charging boxes: live inventory count + charge list
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
const kioskMarkers={};
let ki=0;
if(D.kiosks.length){
  const names=new Set(); D.kiosks.forEach(k=>Object.keys(k[1]).forEach(n=>names.add(n)));
  for(const n of names){ const s=D.sites[n]; if(!s) continue;
    kioskMarkers[n]=L.marker([s.lat,s.lon],{icon:L.divIcon({className:'',
      html:kioskHtml(n,0,1),iconSize:null})}).addTo(map).bindTooltip('charging box: '+n);
  }
}
function applyKiosks(){
  if(!D.kiosks.length) return;
  while(ki<D.kiosks.length-1 && D.kiosks[ki+1][0]<=simT) ki++;
  const inv=D.kiosks[Math.min(ki,D.kiosks.length-1)][1];
  for(const n in kioskMarkers){
    const el=document.getElementById('kk_'+n);
    if(!el) continue;
    const socs=inv[n]||[];
    const frac=socs.length?socs.reduce((a,b)=>a+b,0)/socs.length:0;
    el.outerHTML=kioskHtml(n,socs.length,frac);
    kioskMarkers[n].setTooltipContent('box '+n+': '+socs.length+' radios ['+
      socs.map(s=>Math.round(s*100)+'%').join(', ')+']');
  }
}
// movers: hiker_alpha + every rented node
const moverMarkers={};
const moverColor=n=> n==='hiker_alpha' ? '#0cf' : '#f7b500';
for (const [n,track] of Object.entries(D.movers)){
  moverMarkers[n]=L.circleMarker([track[0][1],track[0][2]],
    {radius:n==='hiker_alpha'?7:6,color:'#123',weight:1.5,
     fillColor:moverColor(n),fillOpacity:1}).addTo(map).bindTooltip(n);
}
const moverTails={};
for (const [n,md] of Object.entries(D.moverdef||{})){
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
  let lo=0,hi=g.t.length-1;
  while(hi-lo>1){const m=(lo+hi)>>1; if(g.t[m]<=tt)lo=m; else hi=m;}
  const f=g.t[hi]>g.t[lo]?(tt-g.t[lo])/(g.t[hi]-g.t[lo]):0;
  return [g.lat[lo]+(g.lat[hi]-g.lat[lo])*f,
          g.lon[lo]+(g.lon[hi]-g.lon[lo])*f, walking, tt];
}
// real trail lines for every route (from routes.json geometry embedded below)
const routeLines = L.layerGroup().addTo(map);
for (const [rn,line] of Object.entries(D.trails||{})){
  routeLines.addLayer(L.polyline(line,{color:'#0a58ff',weight:2.5,opacity:0.55})
    .bindTooltip('trail: '+rn));
}
for (const [n,track] of Object.entries(D.movers)){
  if(n==='hiker_alpha')
    routeLines.addLayer(L.polyline(track.map(p=>[p[1],p[2]]),{color:'#08f',weight:2,opacity:0.3}));
}
// link-health overlay (struggling = orange dashed, healthy = thin green)
const linkLayer = L.layerGroup();
for (const l of D.links){
  linkLayer.addLayer(L.polyline([[l[0],l[1]],[l[2],l[3]]],
    {color:l[6]?'#ff8800':'#2a4', weight:l[6]?3:1.2, opacity:l[6]?0.9:0.35,
     dashArray:l[6]?'6 6':null}).bindTooltip(l[7]));
}
overlays['Link health (orange = struggling)']=linkLayer;
// live terrain-clipped service areas: polygon per site, hidden when the node dies
const svcLayer = L.layerGroup();
const svcPolys = {};
for (const [n,sv] of Object.entries(D.service||{})){
  const pts=[];
  const mlat=111320, mlon=111320*Math.cos(sv.lat*Math.PI/180);
  for (let k=0;k<sv.r.length;k++){
    const az=k*2*Math.PI/sv.r.length, r=Math.max(sv.r[k],40);
    pts.push([sv.lat + r*Math.cos(az)/mlat, sv.lon + r*Math.sin(az)/mlon]);
  }
  svcPolys[n]=L.polygon(pts,{color:'#0a7d2c',weight:1,opacity:0.5,
    fillColor:'#27b04b',fillOpacity:0.10}).bindTooltip(n+' service area');
  svcLayer.addLayer(svcPolys[n]);
}
overlays['Service areas (live, terrain-clipped)']=svcLayer;
svcLayer.addTo(map);
L.control.layers({'Topo':topoL,'Satellite':satL}, overlays).addTo(map);

// panel node bars
const nodesDiv = document.getElementById('nodes');
const bars={};
for (const n of Object.keys(D.sites).concat(['hiker_alpha'])){
  const s = D.sites[n];
  const row = document.createElement('div');
  row.innerHTML = `<span>${s&&s.mqtt?'★ ':''}${n} <span class="lg" id="sw_${n}"></span></span><div class="bar"><div class="fill" id="bar_${n}" style="width:100%"></div></div>`;
  nodesDiv.appendChild(row); bars[n]=document.getElementById('bar_'+n);
}
document.getElementById('mode').textContent = D.mode;
document.getElementById('pdr').textContent = (D.pdr*100).toFixed(1)+'%';
document.getElementById('scope').textContent = D.title || 'Mesh sim';
document.getElementById('nsites').textContent = Object.keys(D.sites).length;
document.title = (D.title||'Mesh sim') + ' — ' + Object.keys(D.sites).length + ' sites';

// playback engine
let simT=0, playing=false, lastReal=null;
let ei=0, li=0;                       // cursors into edges/log
const mi={}; for(const n in D.movers) mi[n]=0;   // per-mover cursor
const bi={}; for(const n in D.bat) bi[n]=0;
const flashes=[];                      // live packet flashes
const logDiv=document.getElementById('log');
function fmtClock(t){
  const d=new Date(Date.parse(D.start_utc)+t*1000);
  const et=new Date(d.getTime()-4*3600*1000);
  return 'day '+(Math.floor(t/86400)+1)+' · '+et.toISOString().substr(11,8)+' ET';
}
function applyMover(n){
  const md=(D.moverdef||{})[n];
  if(md){
    const q=routePos(md,simT), g=D.routegeom[md.route];
    moverMarkers[n].setLatLng([q[0],q[1]]);
    moverMarkers[n].setStyle({fillOpacity:q[2]?1:0.25});
    if(q[2]){
      const t0=Math.max(q[3]-9000,0), pts=[];
      for(let i=0;i<g.t.length;i++){
        if(g.t[i]>=t0&&g.t[i]<=q[3])pts.push([g.lat[i],g.lon[i]]);
        if(g.t[i]>q[3])break;
      }
      pts.push([q[0],q[1]]);
      moverTails[n].setLatLngs(pts);
    } else moverTails[n].setLatLngs([]);
    return;
  }
  // glide between fixes: linear interpolation at current simT
  const track=D.movers[n], k=Math.min(mi[n],track.length-1);
  const p0=track[k], p1=track[Math.min(k+1,track.length-1)];
  let la=p0[1], lo=p0[2];
  if(p1[0]>p0[0] && !p0[3] && !p1[3]){
    const f=Math.max(0,Math.min(1,(simT-p0[0])/(p1[0]-p0[0])));
    la=p0[1]+(p1[1]-p0[1])*f; lo=p0[2]+(p1[2]-p0[2])*f;
  }
  const m=moverMarkers[n];
  m.setLatLng([la,lo]);
  m.setStyle({fillOpacity:p0[3]?0.25:1, radius:p0[3]?3:(n==='hiker_alpha'?7:6)});
}
function seek(t){                      // jump: reset cursors, fast-forward state
  simT=t; ki=0; ei=D.edges.findIndex(e=>e[0]>=t); if(ei<0)ei=D.edges.length;
  li=D.log.findIndex(l=>l[0]>=t); if(li<0)li=D.log.length;
  logDiv.innerHTML='';
  for(const n in D.bat){ bi[n]=0; while(bi[n]<D.bat[n].length-1 && D.bat[n][bi[n]+1][0]<=t) bi[n]++; }
  for(const n in D.movers){ mi[n]=0;
    while(mi[n]<D.movers[n].length-1 && D.movers[n][mi[n]+1][0]<=t) mi[n]++;
    applyMover(n); }
  flashes.length=0; applyBat();
}
function applyBat(){
  for(const n in D.bat){
    const rec=D.bat[n][Math.min(bi[n],D.bat[n].length-1)];
    if(!rec) continue;
    socNow[n]=rec[1]; aliveNow[n]=rec[3]===1;
    if(markers[n]) markers[n].setStyle({fillColor:socColor(rec[1],rec[3]===1)});
    if(svcPolys[n]) svcPolys[n].setStyle(rec[3]===1
      ? {opacity:0.5, fillOpacity:0.10}
      : {opacity:0.15, fillOpacity:0.0, color:'#c22'});
    if(bars[n]){bars[n].style.width=(rec[1]*100)+'%';
      bars[n].style.background=socColor(rec[1],rec[3]===1);}
    const sw=document.getElementById('sw_'+n);
    if(sw) sw.textContent=(rec[3]?'':'DEAD · ')+(rec[2]>0?('☀ '+rec[2].toFixed(1)+' W · '):'')+(rec[1]*100).toFixed(0)+'%';
  }
}
function addLog(l){
  const e=document.createElement('div'); e.className=l[1];
  e.textContent=fmtClock(l[0])+' — '+l[2];
  logDiv.prepend(e); while(logDiv.children.length>80) logDiv.lastChild.remove();
}
const flashLayer = L.layerGroup().addTo(map);
function step(dt){
  simT=Math.min(simT+dt, D.duration_s);
  while(ei<D.edges.length && D.edges[ei][0]<=simT){
    const e=D.edges[ei++];
    if(simT-e[0]<dt+2){                       // only animate near-current events
      const col = e[5]===0?'#f44':(e[5]===2?'#0f0':(e[6]==='sos'?'#ff0':
        (e[6]==='msg'?'#f39bff':(e[6]==='fam'?'#00e5ff':(e[6]==='pos'?'#0cf':'#8f8')))));
      const ln = e[5]===2 ?
        L.circleMarker([e[1],e[2]],{radius:14,color:'#0f0',weight:3,fill:false}) :
        L.polyline([[e[1],e[2]],[e[3],e[4]]],{color:col,weight:e[6]==='sos'?4:2,opacity:0.9});
      flashLayer.addLayer(ln); flashes.push({l:ln,until:performance.now()+450});
    }
  }
  for(const n in D.movers){
    while(mi[n]<D.movers[n].length-1 && D.movers[n][mi[n]+1][0]<=simT){mi[n]++;}
    applyMover(n);
  }
  for(const n in (D.moverdef||{})) applyMover(n);  // exact-trail walkers
  while(li<D.log.length && D.log[li][0]<=simT){addLog(D.log[li++]);}
  let batDirty=false;
  for(const n in D.bat){ while(bi[n]<D.bat[n].length-1 && D.bat[n][bi[n]+1][0]<=simT){bi[n]++;batDirty=true;} }
  if(batDirty) applyBat();
  applyKiosks();
  document.getElementById('clock').textContent=fmtClock(simT);
  document.getElementById('scrub').value=Math.round(simT/D.duration_s*1000);
  drawChart();
}
function loop(now){
  if(playing){
    const dt=lastReal?(now-lastReal)/1000:0; lastReal=now;
    step(dt*parseFloat(document.getElementById('speed').value));
    if(simT>=D.duration_s){playing=false;document.getElementById('play').textContent='▶';}
  } else lastReal=now;
  const nw=performance.now();
  for(let i=flashes.length-1;i>=0;i--) if(flashes[i].until<nw){flashLayer.removeLayer(flashes[i].l);flashes.splice(i,1);}
  requestAnimationFrame(loop);
}
document.getElementById('play').onclick=()=>{playing=!playing;
  document.getElementById('play').textContent=playing?'⏸':'▶';};
document.getElementById('scrub').oninput=e=>{playing=false;
  document.getElementById('play').textContent='▶';
  seek(e.target.value/1000*D.duration_s);};

// SOC strip chart
const chart=document.getElementById('chart');
function drawChart(){
  const w=chart.clientWidth,h=chart.clientHeight;
  if(chart.width!==w)chart.width=w; if(chart.height!==h)chart.height=h;
  const g=chart.getContext('2d'); g.clearRect(0,0,w,h);
  g.font='9px sans-serif';
  const names=Object.keys(D.bat);
  names.forEach((n,k)=>{
    const col=`hsl(${k*360/names.length},70%,60%)`;
    g.strokeStyle=col;g.beginPath();
    const arr=D.bat[n];
    for(let i=0;i<arr.length;i+=2){
      const x=arr[i][0]/D.duration_s*w, y=h-4-arr[i][1]*(h-14);
      i===0?g.moveTo(x,y):g.lineTo(x,y);
    }
    g.stroke();
    g.fillStyle=col; g.fillText(n, 4+((k%3)*112), 10+Math.floor(k/3)*11);
  });
  g.strokeStyle='#fff';g.beginPath();
  const px=simT/D.duration_s*w; g.moveTo(px,0);g.lineTo(px,h);g.stroke();
  g.fillStyle='#9ab'; g.fillText('battery SOC (all nodes) — white line = playhead', w-260, 10);
}
seek(11*3600); requestAnimationFrame(loop);  // open at ~07:00 ET day 1: kiosks opening
</script></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())

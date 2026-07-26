#!/usr/bin/env python3
"""Monadnock field-day viewer — REAL stations, real trail, animated walk.

Zoomed-in sibling of render_year_arena.py, reusing its actual conventions:
  • real OSM-routed trail geometry from artifacts/sim/routes_statewide.json
    (routes["monadnock_white_dot"], Overpass-routed, timed with Tobler pacing)
  • walker glides by binary search + segment interpolation on the timed
    polyline (render_year_arena.routePos idiom), with a breadcrumb tail
  • strip chart with playhead under the map — here it is a per-station
    CONNECTION TIMELINE: hiker→station link status for the entire walk at a
    glance (usable / marginal / below-floor), plus the elevation profile
  • coverage_field.ray_losses viewshed+knife-edge footprints with the
    corrected 2026-07-13 calibration (LOS +0.006 dB / obstructed +37.06 dB)
  • vendored Leaflet, error banner, honest model-not-measurement banner

Every station is real (hardware models from the NHMesh telemetry snapshot);
antenna height and EIRP are ASSUMED stock and labeled as such.

Output: artifacts/trial2/monadnock_real_nodes_viewer.html
Run:    .venv/bin/python scripts/monadnock_real_nodes_viewer.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from itm_relay_links import Dem, itm_p2p_loss, haversine_m  # noqa: E402
import coverage_field as cf  # noqa: E402

OUT = ROOT / "artifacts/trial2/monadnock_real_nodes_viewer.html"
EIRP = 26.3          # project reference EIRP; station true EIRP ASSUMED equal
THRESH = -100.0      # planning threshold (usable) — matches project maps
FLOOR = -134.0       # LoRa LongFast decode floor
LOS_DB = 0.006       # corrected calibration (coverage_field_stats 2026-07-13)
OBS_DB = 37.057

STATIONS = [
    dict(id="courtst", name="Keene Court St Rooftop", lat=42.9129728, lon=-72.2731008,
         hw="LilyGo T-Beam S3 (from mesh telemetry)", hg=8.0, note="rooftop install; height ASSUMED 8 m"),
    dict(id="newmike", name="NewMikeshire", lat=42.9326336, lon=-72.2796544,
         hw="T-Echo (from mesh telemetry)", hg=3.0, note="height ASSUMED 3 m"),
    dict(id="wemo", name="NHMesh WeMo (Hopkinton)", lat=43.1357952, lon=-71.6832768,
         hw="LilyGo T-Beam S3 (mains-powered, ch-util 20% from telemetry)", hg=3.0,
         note="height ASSUMED 3 m"),
    dict(id="hh10", name="HH10 Washington Beacon", lat=43.1620096, lon=-72.155136,
         hw="RAK4631 (from mesh telemetry)", hg=3.0, note="height ASSUMED 3 m"),
]


def footprint(dem: Dem, lat: float, lon: float, hg: float) -> list[list[float]]:
    """Range-by-azimuth polygon where predicted RSSI >= THRESH (calibrated)."""
    dists, loss, blk = cf.ray_losses(dem, lat, lon, hg)
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    poly = []
    for k in range(cf.N_AZ):
        rssi = EIRP - (loss[k] + np.where(blk[k], OBS_DB, LOS_DB))
        r = max(cf.contiguous_range_m(dists, rssi, THRESH), 150.0)
        az = math.radians(k * 360.0 / cf.N_AZ)
        poly.append([round(lat + r * math.cos(az) / m_lat, 5),
                     round(lon + r * math.sin(az) / m_lon, 5)])
    return poly


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="monadnock_white_dot")
    ap.add_argument("--detail-dem", default="artifacts/dem/cache/usgs_3dep_monadnock.npz")
    ap.add_argument("--stations-json", help="override STATIONS with a JSON list")
    ap.add_argument("--title", default="MONADNOCK \u00b7 REAL STATIONS \u00b7 WHITE DOT (OSM)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    global STATIONS
    if args.stations_json:
        STATIONS = json.loads(Path(args.stations_json).read_text())
    out_path = Path(args.out)
    detail = Dem(ROOT / args.detail_dem)
    state = Dem(ROOT / "artifacts/dem/cache/usgs_3dep_nh_statewide.npz")
    rt = json.loads((ROOT / "artifacts/sim/routes_statewide.json").read_text())["routes"][args.route]
    assert rt["geometry"] == "osm", "expected OSM-routed geometry"
    lats = np.array(rt["lat"]); lons = np.array(rt["lon"]); t_s = np.array(rt["t_s"], dtype=float)
    elevs = detail.sample(lats, lons)
    n = len(lats)
    summit_idx = int(np.argmax(elevs))
    print(f"route: {n} OSM samples, {rt['distance_km']} km out-and-back, "
          f"Tobler {t_s[-1]/3600:.2f} h, summit at sample {summit_idx}")

    print("links: ITM q50 hiker→station at every sample...")
    links = {}
    for st in STATIONS:
        row = []
        for la, lo in zip(lats, lons):
            d_m = haversine_m(la, lo, st["lat"], st["lon"])
            prof = state.sample(np.linspace(la, st["lat"], 200), np.linspace(lo, st["lon"], 200))
            r = itm_p2p_loss(d_m / 1000.0, prof, (1.5, st["hg"]))
            row.append([round(EIRP - r["loss_db_q50"], 1), round(d_m / 1000.0, 2)])
        links[st["id"]] = row
        print(f'  {st["name"]:26} best along route {max(x[0] for x in row):6.1f} dBm')

    STRIDE = 4
    print(f"footprints: 4 stations + walker every {STRIDE}th sample...")
    for st in STATIONS:
        st["poly"] = footprint(state, st["lat"], st["lon"], st["hg"])
    hiker_polys = [footprint(state, float(lats[i]), float(lons[i]), 1.5)
                   for i in range(0, n, STRIDE)]

    data = dict(
        route=dict(lat=[round(float(x), 6) for x in lats],
                   lon=[round(float(x), 6) for x in lons],
                   elev=[round(float(x), 1) for x in elevs],
                   t=[round(float(x)) for x in t_s]),
        distance_km=rt["distance_km"], summit_idx=summit_idx,
        stations=STATIONS, links=links, hiker_polys=hiker_polys,
        poly_stride=STRIDE, eirp=EIRP, thresh=THRESH, floor=FLOOR,
    )

    vendor = ROOT / "artifacts/vendor"
    html = TEMPLATE.replace("__LEAFLET_CSS__", (vendor / "leaflet.css").read_text()) \
                   .replace("__LEAFLET_JS__", (vendor / "leaflet.js").read_text()) \
                   .replace("__TITLE__", args.title) \
                   .replace("__DATA__", json.dumps(data))
    out_path.write_text(html)
    print(f"wrote {out_path} ({out_path.stat().st_size//1024} KB)")
    return 0


TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Monadnock — real nodes, live walk</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>__LEAFLET_CSS__</style>
<style>
html,body{height:100%;margin:0;font:12px monospace}
#map{position:fixed;top:0;left:0;right:0;bottom:150px}
#strip{position:fixed;left:0;right:0;bottom:0;height:150px;background:#0d1117;cursor:crosshair}
.bar{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:1200;
 background:rgba(255,255,255,.95);border:2px solid #333;border-radius:6px;padding:7px 12px;
 display:flex;gap:10px;align-items:center;flex-wrap:wrap;max-width:92vw}
.bar button{font:12px monospace;padding:2px 10px;cursor:pointer}
.hud{position:fixed;left:10px;top:10px;z-index:1200;background:rgba(255,255,255,.95);
 border:2px solid #333;border-radius:6px;padding:8px 11px;line-height:1.6;min-width:265px}
.hud .chip{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.banner{position:fixed;right:10px;top:10px;z-index:1200;background:rgba(255,248,225,.96);
 border:1.5px solid #b8860b;border-radius:6px;padding:6px 9px;font-size:10.5px;
 line-height:1.5;max-width:270px}
#err{position:fixed;left:50%;top:45%;transform:translateX(-50%);z-index:2000;display:none;
 background:#fff0f0;border:2px solid #c00;border-radius:6px;padding:12px 16px}
</style></head><body>
<div id="map"></div><canvas id="strip"></canvas>
<div class="bar">
 <b>__TITLE__</b>
 <button id="play">▶ walk</button>
 <select id="spd"><option value="60">60×</option><option value="180" selected>180×</option>
 <option value="600">600×</option></select>
 <span id="clock">08:00</span>
</div>
<div class="hud" id="hud"></div>
<div class="banner"><b>MODEL, NOT MEASUREMENT.</b> ITM q50 links + calibrated
viewshed footprints (aligned to design links, not field data). Station hardware
real (mesh telemetry); antenna height + EIRP ASSUMED stock. Observed overlay
lands here after the hike.</div>
<div id="err"><b>viewer failed to start</b><br><span id="errmsg"></span></div>
<script>__LEAFLET_JS__</script>
<script>
try{
const D=__DATA__;
const RT=D.route, N=RT.t.length, DUR=RT.t[N-1], T0=8*3600;
const map=L.map('map').setView([RT.lat[D.summit_idx],RT.lon[D.summit_idx]],12);
const osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
 {attribution:'© OpenStreetMap'}).addTo(map);
const topo=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
 {attribution:'© OpenTopoMap (CC-BY-SA)'});

const STOPS=[[-130,[0,0,0]],[-120,[180,0,0]],[-110,[255,80,0]],[-100,[255,210,0]],[-88,[0,200,60]]];
const rgb=c=>`rgb(${c[0]},${c[1]},${c[2]})`;
function rssiColor(v){ if(v==null)return '#666';
 if(v<=STOPS[0][0])return rgb(STOPS[0][1]); if(v>=STOPS[STOPS.length-1][0])return rgb(STOPS[STOPS.length-1][1]);
 for(let i=0;i<STOPS.length-1;i++){const[a,ca]=STOPS[i],[b,cb]=STOPS[i+1];
  if(v>=a&&v<=b){const t=(v-a)/(b-a);return rgb(ca.map((x,j)=>Math.round(x+(cb[j]-x)*t)));}}
 return '#666'}
const statusOf=v=>v>=D.thresh?'usable':(v>=D.floor?'marginal':'none');
const STATUS_COLOR={usable:'#18b04b',marginal:'#d9a013',none:'#3a2323'};

// trail colored by best station link (real OSM geometry)
for(let i=1;i<N;i++){
 let best=null; for(const s of D.stations){const v=D.links[s.id][i][0]; if(best==null||v>best)best=v;}
 L.polyline([[RT.lat[i-1],RT.lon[i-1]],[RT.lat[i],RT.lon[i]]],
  {color:rssiColor(best),weight:5,opacity:.92}).addTo(map);
}

// stations + footprints
const svcLayer=L.layerGroup().addTo(map);
for(const s of D.stations){
 L.polygon(s.poly,{color:'#0a7d2c',weight:1,opacity:.45,fillColor:'#18a34a',fillOpacity:.08})
  .addTo(svcLayer).bindTooltip(s.name+' — modeled footprint (≥ −100 dBm)');
 L.marker([s.lat,s.lon],{icon:L.divIcon({className:'',html:
  `<div style="background:#fff;border:2px solid #0a7d2c;border-radius:4px;padding:1px 5px;font:11px monospace;white-space:nowrap">📡 ${s.name.split(' (')[0]}</div>`,iconAnchor:[8,10]})})
  .addTo(map).bindPopup(`<b>${s.name}</b><br>hardware: ${s.hw}<br>${s.note}<br>EIRP ASSUMED ${D.eirp} dBm (stock)`);
}

// walker (arena styling: gold ring) + breadcrumb tail + own footprint
const hikerPoly=L.polygon(D.hiker_polys[0],{color:'#c96a10',weight:1.4,opacity:.7,
 fillColor:'#e8862c',fillOpacity:.12}).addTo(map);
const tail=L.polyline([],{color:'#ff9500',weight:3,opacity:.85}).addTo(map);
const hiker=L.circleMarker([RT.lat[0],RT.lon[0]],{radius:7,color:'#f7b500',weight:2.5,
 fillColor:'#3c3',fillOpacity:1}).addTo(map).bindTooltip('you');
const linkLines={};
for(const s of D.stations) linkLines[s.id]=L.polyline([[0,0],[0,0]],{weight:2.5}).addTo(map);

// arena routePos idiom: binary search + segment interpolation on timed polyline
function seg(t){
 let lo=0,hi=N-1;
 while(hi-lo>1){const m=(lo+hi)>>1; if(RT.t[m]<=t)lo=m; else hi=m;}
 const f=RT.t[hi]>RT.t[lo]?(t-RT.t[lo])/(RT.t[hi]-RT.t[lo]):0;
 return [lo,hi,f];
}
const lerp=(a,b,f)=>a+(b-a)*f;

let simT=0, playing=false, speed=180, lastReal=null;
const fmtClock=t=>{const x=T0+t;return String(Math.floor(x/3600)).padStart(2,'0')+':'+String(Math.floor(x%3600/60)).padStart(2,'0');};

function setTime(t){
 simT=Math.max(0,Math.min(DUR,t));
 const [lo,hi,f]=seg(simT);
 const la=lerp(RT.lat[lo],RT.lat[hi],f), lon=lerp(RT.lon[lo],RT.lon[hi],f);
 hiker.setLatLng([la,lon]);
 hikerPoly.setLatLngs(D.hiker_polys[Math.min(D.hiker_polys.length-1,Math.round(lo/D.poly_stride))]);
 // breadcrumb: last 45 min from geometry so switchbacks render at any speed
 const t0=Math.max(simT-2700,0), pts=[];
 for(let i=0;i<N;i++){ if(RT.t[i]>=t0&&RT.t[i]<=simT)pts.push([RT.lat[i],RT.lon[i]]); if(RT.t[i]>simT)break; }
 pts.push([la,lon]); tail.setLatLngs(pts);
 const elev=lerp(RT.elev[lo],RT.elev[hi],f);
 let hud=`<b>${lo<=D.summit_idx?'▲ ascending':'▼ descending'}</b> · ${elev.toFixed(0)} m · ${fmtClock(simT)}<br>`;
 for(const s of D.stations){
  const rx=lerp(D.links[s.id][lo][0],D.links[s.id][hi][0],f);
  const km=lerp(D.links[s.id][lo][1],D.links[s.id][hi][1],f);
  const st=statusOf(rx);
  linkLines[s.id].setLatLngs([[la,lon],[s.lat,s.lon]]);
  linkLines[s.id].setStyle({color:rssiColor(rx),opacity:st==='usable'?.95:(st==='marginal'?.55:.15),
   dashArray:st==='usable'?null:'5 7',weight:st==='usable'?3:1.8});
  hud+=`<span class="chip" style="background:${rssiColor(rx)}"></span>${s.name.split(' (')[0]}: <b>${rx.toFixed(0)} dBm</b> · ${km.toFixed(1)} km · ${st==='none'?'below floor':st.toUpperCase()}<br>`;
 }
 document.getElementById('hud').innerHTML=hud;
 document.getElementById('clock').textContent=fmtClock(simT);
 drawStrip();
}

// ── connection timeline: every station, ALL times, plus elevation profile ──
const strip=document.getElementById('strip');
const ROWS=D.stations.length, LBL=150;
function drawStrip(){
 const w=strip.clientWidth,h=strip.clientHeight;
 if(strip.width!==w)strip.width=w; if(strip.height!==h)strip.height=h;
 const g=strip.getContext('2d'); g.clearRect(0,0,w,h);
 const ex0=LBL, ew=w-LBL-8, eh=42, rowH=(h-eh-26)/ROWS;
 // elevation profile
 g.fillStyle='#161d26'; g.fillRect(ex0,4,ew,eh);
 const emin=Math.min(...RT.elev), emax=Math.max(...RT.elev);
 g.strokeStyle='#5a90c4'; g.beginPath();
 for(let i=0;i<N;i++){const x=ex0+RT.t[i]/DUR*ew, y=4+eh-4-(RT.elev[i]-emin)/(emax-emin)*(eh-8);
  i?g.lineTo(x,y):g.moveTo(x,y);} g.stroke();
 g.fillStyle='#8fa8c0'; g.font='10px monospace';
 g.fillText('elevation '+Math.round(emin)+'–'+Math.round(emax)+' m',ex0+6,15);
 // per-station status rows
 D.stations.forEach((s,r)=>{
  const y=eh+10+r*rowH;
  g.fillStyle='#c8d2dc'; g.font='11px monospace';
  g.fillText(s.name.split(' (')[0].slice(0,18), 6, y+rowH/2+4);
  for(let i=1;i<N;i++){
   const x0=ex0+RT.t[i-1]/DUR*ew, x1=ex0+RT.t[i]/DUR*ew;
   g.fillStyle=STATUS_COLOR[statusOf(D.links[s.id][i][0])];
   g.fillRect(x0,y,Math.max(x1-x0,1),rowH-4);
  }
 });
 // hour ticks + clock labels
 g.fillStyle='#8fa8c0'; g.font='10px monospace';
 for(let t=0;t<=DUR;t+=1800){const x=ex0+t/DUR*ew;
  g.fillRect(x,h-14,1,4); if(t%3600===0)g.fillText(fmtClock(t),x-13,h-2);}
 // summit mark + playhead
 const sx=ex0+RT.t[D.summit_idx]/DUR*ew;
 g.strokeStyle='#c8d2dc'; g.setLineDash([3,4]); g.beginPath(); g.moveTo(sx,4); g.lineTo(sx,h-16); g.stroke(); g.setLineDash([]);
 g.fillStyle='#c8d2dc'; g.fillText('▲',sx-4,h-18);
 g.strokeStyle='#fff'; g.lineWidth=1.5; g.beginPath();
 const px=ex0+simT/DUR*ew; g.moveTo(px,2); g.lineTo(px,h-16); g.stroke(); g.lineWidth=1;
 // legend
 g.fillStyle=STATUS_COLOR.usable; g.fillRect(6,h-13,9,9); g.fillStyle='#c8d2dc'; g.fillText('usable',18,h-5);
 g.fillStyle=STATUS_COLOR.marginal; g.fillRect(62,h-13,9,9); g.fillStyle='#c8d2dc'; g.fillText('marginal',74,h-5);
}
function stripSeek(e){
 const r=strip.getBoundingClientRect(), x=(e.touches?e.touches[0].clientX:e.clientX)-r.left;
 if(x>LBL) setTime((x-LBL)/(strip.clientWidth-LBL-8)*DUR);
}
strip.addEventListener('mousedown',e=>{stripSeek(e);
 const mv=ev=>stripSeek(ev), up=()=>{removeEventListener('mousemove',mv);removeEventListener('mouseup',up);};
 addEventListener('mousemove',mv); addEventListener('mouseup',up);});
strip.addEventListener('touchstart',stripSeek); strip.addEventListener('touchmove',stripSeek);

function tick(ts){
 if(!playing)return;
 if(lastReal!=null){ setTime(simT+(ts-lastReal)/1000*speed);
  if(simT>=DUR){playing=false;document.getElementById('play').textContent='▶ walk';} }
 lastReal=ts; if(playing)requestAnimationFrame(tick);
}
document.getElementById('play').onclick=()=>{
 playing=!playing;document.getElementById('play').textContent=playing?'⏸ pause':'▶ walk';
 if(playing){if(simT>=DUR)simT=0; lastReal=null;requestAnimationFrame(tick);}};
document.getElementById('spd').onchange=e=>speed=+e.target.value;
addEventListener('resize',()=>drawStrip());

L.control.layers({'street':osm,'topo':topo},
 {'station footprints':svcLayer,'your footprint':hikerPoly},
 {collapsed:false}).addTo(map);
let bla0=1e9,bla1=-1e9,blo0=1e9,blo1=-1e9;
for(const s of D.stations){bla0=Math.min(bla0,s.lat);bla1=Math.max(bla1,s.lat);blo0=Math.min(blo0,s.lon);blo1=Math.max(blo1,s.lon);}
for(let i=0;i<N;i+=20){bla0=Math.min(bla0,RT.lat[i]);bla1=Math.max(bla1,RT.lat[i]);blo0=Math.min(blo0,RT.lon[i]);blo1=Math.max(blo1,RT.lon[i]);}
map.fitBounds(L.latLngBounds([[bla0,blo0],[bla1,blo1]]),{padding:[24,24]});
setTime(0);
}catch(e){document.getElementById('err').style.display='block';
 document.getElementById('errmsg').textContent=e.message;throw e;}
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())

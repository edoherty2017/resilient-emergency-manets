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
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

MAX_EDGES_PER_RUN = 10000


def digest(trace_path: Path, sites: dict, keep_movers: bool, pos_at=None):
    kind_of_pkt: dict[int, str] = {}
    edges, bat, log = [], {}, []
    edges_h = []
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
            elif ev in ("rent", "return") and keep_movers:
                log.append([round(t, 1), ev, f"{e['n']} {ev} @ {e['kiosk']}"])
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
    return edges, bat, log, movers


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
        if not name.startswith("rent_"):
            return None
        body = name[5:]
        rname, _, k = body.rpartition("_")
        if rname not in rjson or not k.isdigit():
            return None
        return rname, (11.5 + 1.5 * int(k)) * 3600.0   # mesh_sim checkout times

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
        edges, bat, log, movers = digest(tp, sites,
                                         keep_movers=(movers_shared is None),
                                         pos_at=pos_at)
        if movers_shared is None and movers:
            movers_shared = movers
        fe = s.get("fleet_energy", {})
        runs[mode] = {
            "edges": edges, "bat": bat, "log": log,
            "stats": {"pdr": s["pdr_overall"],
                      "sos": f"{s['sos']['delivered']}/{s['sos']['sent']}",
                      "util": s["channel_utilization"],
                      "deaths": fe.get("deaths_total"),
                      "gini": fe.get("relay_energy_gini"),
                      "soc_min": fe.get("final_soc_min")},
        }
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

    data = {
        "title": args.title,
        "sites": {n: {"lat": s["lat"], "lon": s["lon"],
                      "mqtt": bool(s.get("mqtt_uplink"))} for n, s in sites.items()},
        "duration_s": duration, "start_utc": "2025-07-01T00:00:00Z",
        "movers": movers_shared or {}, "trails": trails, "nh": nh,
        "routegeom": routegeom, "moverdef": moverdef,
        "service": service, "runs": runs,
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
<div id="map"></div>
<div id="panel">
 <h2 id="ttl" style="font-size:14px"></h2>
 <select id="algo"></select>
 <label class="lg"><input type="checkbox" id="hikonly" checked> hiker traffic only
 (origins pulse at the hiker)</label>
 <table id="stats"><tr><th>algo</th><th>PDR</th><th>SOS</th><th>util</th><th>deaths</th><th>Gini</th></tr></table>
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
for(const line of Object.values(D.trails))
  L.polyline(line,{color:'#0a58ff',weight:1.8,opacity:0.5}).addTo(map);
const svcPolys={};
for(const [n,sv] of Object.entries(D.service)){
  const p=[],mlat=111320,mlon=111320*Math.cos(sv.lat*Math.PI/180);
  for(let k=0;k<sv.r.length;k++){const az=k*2*Math.PI/sv.r.length,r=Math.max(sv.r[k],40);
    p.push([sv.lat+r*Math.cos(az)/mlat,sv.lon+r*Math.sin(az)/mlon]);}
  svcPolys[n]=L.polygon(p,{color:'#0a7d2c',weight:0.8,opacity:0.4,
    fillColor:'#27b04b',fillOpacity:0.07}).addTo(map);
}
const markers={};
for(const [n,s] of Object.entries(D.sites))
  markers[n]=L.circleMarker([s.lat,s.lon],{radius:s.mqtt?8:5,color:'#fff',weight:1,
    fillColor:'#3c3',fillOpacity:0.9}).addTo(map).bindTooltip(n);
const moverMarkers={};
for(const [n,tk] of Object.entries(D.movers))
  moverMarkers[n]=L.circleMarker([tk[0][1],tk[0][2]],{radius:6,color:'#123',
    weight:1.5,fillColor:'#f7b500',fillOpacity:1}).addTo(map).bindTooltip(n);
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
let mode=modes[0];
const sel=document.getElementById('algo');
for(const m of modes){const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);}
const tbl=document.getElementById('stats');
for(const m of modes){
  const s=D.runs[m].stats, r=tbl.insertRow(); r.id='row_'+m;
  r.innerHTML=`<td>${m}</td><td>${(s.pdr*100).toFixed(1)}%</td><td>${s.sos}</td>`+
    `<td>${(s.util*100).toFixed(0)}%</td><td>${s.deaths??'—'}</td><td>${s.gini??'—'}</td>`;
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
 resetCursors();}
sel.onchange=e=>setMode(e.target.value);
function socColor(s,alive){if(!alive)return'#555';return`hsl(${Math.max(0,Math.min(120,s*120))},80%,45%)`;}
function applyBat(){for(const n in R.bat){const rec=R.bat[n][Math.min(bi[n],R.bat[n].length-1)];
 if(!rec)continue;if(markers[n])markers[n].setStyle({fillColor:socColor(rec[1],rec[3]===1)});
 if(moverMarkers[n]){moverMarkers[n].setStyle({fillColor:socColor(rec[1],rec[3]===1)});
  moverMarkers[n].setTooltipContent(n+' — battery '+Math.round(rec[1]*100)+'%');}
 if(svcPolys[n])svcPolys[n].setStyle(rec[3]===1?{opacity:0.4,fillOpacity:0.07}:{opacity:0.1,fillOpacity:0,color:'#c22'});}}
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
 if(dirty)applyBat();
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

#!/usr/bin/env python3
"""Statewide deployment proposal map — clickable per-node hardware BOMs.

Every marker is a proposed placement from the statewide topology; clicking
shows the exact build: chip, battery, panel, enclosure, antenna — with real
researched prices and product links (BOM JSON produced 2026-07-31).
Relays = RAK4631 (nRF52, ~2-6 mA idle — the B.1 zero-depletion hardware
class); kiosk rentals = Heltec V3 in printed cases; relay enclosures are
molded IP-rated boxes, never 3D printed.

HONESTY BANNER carried on the map: placements come from the planning
topology; the corrected −100 dBm planning screen FAILS for a large fraction
of sites (87/217 stranded, MODEL-ONLY) — this is a proposal map, not
validated coverage.

Usage: deployment_map.py --bom artifacts/deployment/bom_2026-07-31.json
"""
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL = ROOT / "artifacts/sim/corrected/release_v1"

ap = argparse.ArgumentParser()
ap.add_argument("--bom", required=True)
ap.add_argument("--out", default=str(ROOT / "artifacts/deployment/deployment_proposal_map.html"))
a = ap.parse_args()

bom = json.loads(Path(a.bom).read_text())["bom"]
topo = json.loads((REL / "topology_statewide.json").read_text())
routes = json.loads((REL / "routes_statewide.json").read_text())["routes"]
sites = topo["sites"]
kiosk_sites = set()
for r in routes.values():
    for k in (r.get("kiosk"), r.get("return_kiosk")):
        if k: kiosk_sites.add(k)

def cls_of(name, s):
    if s.get("category") == "portable": return "portable_sar"
    if name in kiosk_sites: return "kiosk"
    if s.get("power") == "grid" or s.get("mqtt_uplink"): return "gateway_grid"
    return "solar_relay"

CLS_META = {
  "solar_relay":  {"color": "#2a78d6", "label": "Solar relay — RAK4631 (nRF52)"},
  "gateway_grid": {"color": "#008300", "label": "Gateway — RAK4631, grid + uplink"},
  "kiosk":        {"color": "#eb6834", "label": "Rental kiosk — 22× Heltec V3"},
  "portable_sar": {"color": "#e34948", "label": "SAR portable — RAK kit, case"},
}

def bom_html(cls, site_is_grid):
    b = bom[cls]
    rows = ""
    for ln in b["lines"]:
        rows += (f"<tr><td><a href='{ln['url']}' target='_blank'>{ln['product']}</a>"
                 f"<div class='c'>{ln['component']}</div></td>"
                 f"<td class='n'>{ln['qty']}</td>"
                 f"<td class='n'>${ln['unit_price_usd']:,.2f}</td>"
                 f"<td class='n'>${ln['line_total_usd']:,.2f}</td></tr>")
    sub = b["subtotal_usd"]
    extra = ""
    if cls == "kiosk" and not site_is_grid and "offgrid_lines" in b:
        for ln in b["offgrid_lines"]:
            extra += (f"<tr class='og'><td><a href='{ln['url']}' target='_blank'>{ln['product']}</a>"
                      f"<div class='c'>{ln['component']} (off-grid site)</div></td>"
                      f"<td class='n'>{ln['qty']}</td><td class='n'>${ln['unit_price_usd']:,.2f}</td>"
                      f"<td class='n'>${ln['line_total_usd']:,.2f}</td></tr>")
        sub = b["subtotal_offgrid_usd"]
    return (f"<table class='bom'><tr><th>part</th><th>qty</th><th>unit</th><th>total</th></tr>"
            f"{rows}{extra}"
            f"<tr class='tot'><td colspan='3'>node total</td><td class='n'>${sub:,.2f}</td></tr></table>")

markers = []
counts, cost = {}, {}
for name, s in sites.items():
    c = cls_of(name, s)
    counts[c] = counts.get(c, 0) + 1
    grid = s.get("power") == "grid"
    node_cost = (bom[c]["subtotal_offgrid_usd"]
                 if c == "kiosk" and not grid and "subtotal_offgrid_usd" in bom[c]
                 else bom[c]["subtotal_usd"])
    if c == "kiosk":  # kiosk site also hosts a gateway radio node
        node_cost += bom["gateway_grid"]["subtotal_usd"]
    cost[c] = cost.get(c, 0.0) + node_cost
    pop = (f"<b>{s.get('label', name)}</b><br>"
           f"<span class='c'>{name} · {s.get('category')} · {s['elev_m']:.0f} m · "
           f"{s.get('power')}{' · MQTT uplink' if s.get('mqtt_uplink') else ''}</span>"
           f"<div class='cls' style='color:{CLS_META[c]['color']}'>{CLS_META[c]['label']}</div>"
           + bom_html(c, grid)
           + (f"<div class='c'>+ hosts the gateway radio node "
              f"(${bom['gateway_grid']['subtotal_usd']:,.2f}, itemized under gateway sites)</div>"
              if c == "kiosk" else ""))
    markers.append({"name": name, "lat": s["lat"], "lon": s["lon"], "cls": c, "pop": pop})

grand = sum(cost.values())
trails = [[[la, lo] for la, lo in zip(r["lat"][::4], r["lon"][::4])] for r in routes.values()]

vendor = ROOT / "artifacts/vendor"
totals_rows = "".join(
    f"<tr><td><span class='sw' style='background:{CLS_META[c]['color']}'></span>{CLS_META[c]['label']}</td>"
    f"<td class='n'>{counts.get(c,0)}</td><td class='n'>${cost.get(c,0):,.0f}</td></tr>"
    for c in CLS_META)

html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Statewide deployment proposal — hardware and cost</title>
<style>{(vendor/'leaflet.css').read_text()}</style>
<style>
html,body,#map{{height:100%;margin:0;font:13px system-ui,-apple-system,sans-serif}}
.hdr{{position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:1200;background:rgba(255,255,255,.96);
 border:2px solid #333;border-radius:6px;padding:7px 14px;font:12px monospace;max-width:92vw}}
.totals{{position:fixed;right:10px;top:60px;z-index:1200;background:rgba(255,255,255,.96);
 border:2px solid #333;border-radius:6px;padding:10px 12px;font:12.5px system-ui}}
.totals table{{border-collapse:collapse}} .totals td{{padding:3px 8px}} .totals .n{{text-align:right;font-variant-numeric:tabular-nums}}
.totals .g{{font-weight:700;border-top:1.5px solid #333}}
.sw{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
.banner{{position:fixed;left:10px;bottom:10px;z-index:1200;background:rgba(255,248,225,.97);
 border:1.5px solid #b8860b;border-radius:6px;padding:7px 10px;font:11px/1.5 monospace;max-width:340px}}
.leaflet-popup-content{{font:12.5px system-ui;min-width:330px}}
.bom{{border-collapse:collapse;width:100%;margin-top:6px;font-size:11.5px}}
.bom th{{text-align:left;border-bottom:1px solid #999;font-size:10px;text-transform:uppercase}}
.bom td{{padding:3px 6px 3px 0;border-bottom:1px solid #eee;vertical-align:top}}
.bom .n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.bom .tot td{{font-weight:700;border-top:1.5px solid #333}}
.bom .og td{{background:#fff8e8}}
.c{{color:#777;font-size:10.5px}} .cls{{font-weight:600;margin-top:3px}}
</style></head><body><div id="map"></div>
<div class="hdr"><b>STATEWIDE DEPLOYMENT PROPOSAL</b> · exact hardware per node, click any marker ·
prices researched 2026-07-31 (live product links)</div>
<div class="totals"><table>{totals_rows}
<tr class="g"><td>Total ({len(sites)} sites)</td><td></td><td class="n">${grand:,.0f}</td></tr></table></div>
<div class="banner"><b>PROPOSAL, NOT VALIDATED COVERAGE.</b> Placements are the planning
topology; the corrected −100 dBm planning screen FAILS for 87/217 sites (MODEL-ONLY,
see report §5.1). Relay hardware class per the B.1 result: nRF52 ≤6 mA idle ⇒ zero
modeled depletions on stock energy kit. Site power/internet at gateways assumed
site-provided.</div>
<script>{(vendor/'leaflet.js').read_text()}</script>
<script>
const M={json.dumps(markers)};
const T={json.dumps(trails)};
const map=L.map('map').setView([44.0,-71.6],8);
L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',
 {{attribution:'© OpenStreetMap, © OpenTopoMap (CC-BY-SA)'}}).addTo(map);
const CLR={json.dumps({c: m["color"] for c, m in CLS_META.items()})};
const layers={{}};
for(const c of Object.keys(CLR)) layers[c]=L.layerGroup().addTo(map);
for(const m of M){{
 L.circleMarker([m.lat,m.lon],{{radius:m.cls==='kiosk'?8:6,color:'#fff',weight:1.4,
  fillColor:CLR[m.cls],fillOpacity:0.95}}).bindPopup(m.pop,{{maxWidth:420}}).addTo(layers[m.cls]);
}}
const tl=L.layerGroup(T.map(t=>L.polyline(t,{{color:'#666',weight:1.5,opacity:0.6,dashArray:'4 5'}})));
tl.addTo(map);
L.control.layers(null,{{'Solar relays (RAK)':layers.solar_relay,'Gateways':layers.gateway_grid,
 'Rental kiosks (Heltec)':layers.kiosk,'SAR portables':layers.portable_sar,'Rental routes':tl}},
 {{collapsed:false}}).addTo(map);
</script></body></html>"""
out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print(f"wrote {out} — {len(sites)} sites, grand total ${grand:,.0f}")
for c in CLS_META: print(f"  {c}: {counts.get(c,0)} × → ${cost.get(c,0):,.0f}")

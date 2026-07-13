"""OSM-derived trail geometry for the hiker-route simulation.

Fetches every mapped hiking path in a bounding box from the Overpass API
(cached to artifacts/osm/), builds a trail graph, and routes between waypoints
with Dijkstra. Individual legs fall back to straight chords when the filtered
OSM graph cannot connect them; callers receive explicit per-route provenance.

Used by build_hiker_routes.py; not a CLI.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "artifacts/osm"
OVERPASS = "https://overpass-api.de/api/interpreter"
SNAP_MAX_M = 800.0        # waypoint must be this close to a mapped trail
NODE_KEY_DECIMALS = 5     # ~1 m dedupe grid


def _cache_path(bbox: tuple[float, float, float, float]) -> Path:
    key = hashlib.sha256(
        json.dumps([round(value, 4) for value in bbox]).encode()
    ).hexdigest()[:16]
    return CACHE / f"trails_{key}.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_trails(bbox: tuple[float, float, float, float]) -> list[list[tuple[float, float]]]:
    """All hiking-usable ways in (south, west, north, east); cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_f = _cache_path(bbox)
    if cache_f.exists():
        return json.loads(cache_f.read_text())
    s, w, n, e = bbox
    q = (f'[out:json][timeout:90];'
         f'way["highway"~"^(path|footway|steps|track|bridleway)$"]({s},{w},{n},{e});'
         f'out geom;')
    req = urllib.request.Request(
        OVERPASS, data=urllib.parse.urlencode({"data": q}).encode(),
        headers={"User-Agent": "manet-research-sim/1.0"})
    data = None
    for attempt, backoff in enumerate((0, 8, 25)):
        if backoff:
            time.sleep(backoff)      # Overpass rate limit: back off and retry
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            break
        except Exception:
            if attempt == 2:
                raise
    ways = [[(nd["lat"], nd["lon"]) for nd in el.get("geometry", [])]
            for el in data.get("elements", []) if el["type"] == "way"]
    ways = [w_ for w_ in ways if len(w_) >= 2]
    cache_f.write_text(json.dumps(ways))
    time.sleep(1.5)          # be polite to Overpass between uncached fetches
    return ways


class TrailGraph:
    def __init__(self, ways):
        self.adj: dict[tuple, list] = {}
        for way in ways:
            keys = [(round(la, NODE_KEY_DECIMALS), round(lo, NODE_KEY_DECIMALS))
                    for la, lo in way]
            for a, b in zip(keys, keys[1:]):
                if a == b:
                    continue
                d = _haversine_m(a[0], a[1], b[0], b[1])
                self.adj.setdefault(a, []).append((b, d))
                self.adj.setdefault(b, []).append((a, d))
        self.nodes = list(self.adj)

    def nearest(self, lat, lon):
        best, bd = None, float("inf")
        # coarse prefilter on a degree box, then exact haversine
        for nd in self.nodes:
            dlat = abs(nd[0] - lat)
            dlon = abs(nd[1] - lon)
            if dlat > 0.01 or dlon > 0.014:
                continue
            d = _haversine_m(lat, lon, nd[0], nd[1])
            if d < bd:
                best, bd = nd, d
        return best, bd

    def components(self):
        """Label connected components (waypoints often snap onto isolated
        parking/campground path fragments whose road connectors are filtered
        out — candidate snapping must span components)."""
        if hasattr(self, "_comp"):
            return self._comp
        comp, cid = {}, 0
        for start in self.nodes:
            if start in comp:
                continue
            stack = [start]
            comp[start] = cid
            while stack:
                u = stack.pop()
                for v, _ in self.adj.get(u, ()):
                    if v not in comp:
                        comp[v] = cid
                        stack.append(v)
            cid += 1
        self._comp = comp
        return comp

    def nearest_k(self, lat, lon, k=6, max_m=SNAP_MAX_M):
        """k nearest nodes, at most one per component, within max_m."""
        comp = self.components()
        cands = []
        for nd in self.nodes:
            if abs(nd[0] - lat) > 0.012 or abs(nd[1] - lon) > 0.016:
                continue
            d = _haversine_m(lat, lon, nd[0], nd[1])
            if d <= max_m:
                cands.append((d, nd))
        cands.sort()
        out, seen = [], set()
        for d, nd in cands:
            c = comp[nd]
            if c in seen:
                continue
            seen.add(c)
            out.append((d, nd, c))
            if len(out) >= k:
                break
        return out

    def route(self, a, b):
        """Dijkstra shortest trail path between graph nodes; None if disconnected."""
        dist = {a: 0.0}
        prev: dict = {}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                break
            if d > dist.get(u, float("inf")):
                continue
            for v, w in self.adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))
        if b not in dist:
            return None
        path, cur = [b], b
        while cur != a:
            cur = prev[cur]
            path.append(cur)
        path.reverse()
        return path


def trail_polyline(
    waypoints: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], str, dict]:
    """Route a waypoint chain along the filtered OSM trail graph.

    Returns ``(polyline, source, provenance)``. ``source`` is ``osm`` only when
    every leg is graph-routed, ``mixed_osm_chord`` when at least one leg falls
    back, and ``chord`` when no leg can be graph-routed.
    """
    lats = [w[0] for w in waypoints]
    lons = [w[1] for w in waypoints]
    pad = 0.02
    bbox = (min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad)
    cache_path = _cache_path(bbox)
    provenance = {
        "provider": "OpenStreetMap via Overpass API",
        "overpass_endpoint": OVERPASS,
        "bbox_south_west_north_east": [round(value, 7) for value in bbox],
        "cache_path": str(cache_path.relative_to(ROOT)),
        "cache_sha256": None,
        "routed_legs": 0,
        "chord_fallback_legs": 0,
    }
    try:
        graph = TrailGraph(fetch_trails(bbox))
        if cache_path.is_file():
            provenance["cache_sha256"] = _sha256_file(cache_path)
    except Exception as exc:
        provenance["fetch_error_type"] = type(exc).__name__
        provenance["chord_fallback_legs"] = max(len(waypoints) - 1, 0)
        return list(waypoints), "chord", provenance
    if not graph.nodes:
        provenance["chord_fallback_legs"] = max(len(waypoints) - 1, 0)
        provenance["empty_filtered_graph"] = True
        return list(waypoints), "chord", provenance

    poly: list[tuple[float, float]] = []
    for (a_lat, a_lon), (b_lat, b_lon) in zip(waypoints, waypoints[1:]):
        # try candidate snap pairs across components until a leg routes
        a_cands = graph.nearest_k(a_lat, a_lon)
        b_cands = graph.nearest_k(b_lat, b_lon)
        seg = None
        pairs = sorted(((da + db, na, nb, ca, cb)
                        for da, na, ca in a_cands
                        for db, nb, cb in b_cands if ca == cb),
                       key=lambda x: x[0])
        for _, na, nb, _, _ in pairs[:8]:
            seg = graph.route(na, nb)
            if seg is not None:
                break
        if seg is None:
            seg = [(a_lat, a_lon), (b_lat, b_lon)]     # chord for this leg only
            provenance["chord_fallback_legs"] += 1
        else:
            provenance["routed_legs"] += 1
        if not poly:
            poly.extend(seg)
        else:
            poly.extend(seg[1:] if seg[0] == poly[-1] else seg)
    if provenance["chord_fallback_legs"] == 0:
        source = "osm"
    elif provenance["routed_legs"]:
        source = "mixed_osm_chord"
    else:
        source = "chord"
    return poly, source, provenance

#!/usr/bin/env python3
"""Multi-mode interactive replay viewer for the statewide mesh simulation.

Digests full-capture traces (rx_trace_sample=1.0) from run_replay_traces.sh
into one self-contained HTML player:
  - mode switcher across all replay runs (always-on, 2 mA RAK-class,
    duty family, wake-up-radio arms)
  - every packet's REAL hop-by-hop journey (no estimates): a Messages panel
    lists SOS / DM / family packets; clicking one enters follow mode and
    animates the exact recorded receptions, collisions, and (wur) wake
    failures along the way
  - auto-pause "story beats" computed from the trace: first death with its
    energy ledger, death waves, self-healing reroutes after a relay dies,
    SOS incidents, wake-budget hotspots, collision storms, sunrise revivals
  - toggleable layers: per-kind packet flashes, collisions, wake pings,
    sleep shading, dead markers, movers, trails, link health, beats
  - end-of-run metrics card: replay-window counts (this trace) next to the
    canonical year-scale results (fastsim Rust, 5 seeds x 365 d) and a
    cross-mode comparison table

All values MODEL-ONLY (uncalibrated). Sources: artifacts/sim/replay/ traces,
artifacts/sim/corrected/release_v1/ aggregates, artifacts/sim/wur_study/.

Run: .venv/bin/python scripts/render_replay_viewer.py
"""
from __future__ import annotations

import argparse
import base64
import glob
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── run roster ──────────────────────────────────────────────────────────────
RUNS = [
    dict(key="flood", label="Flood (always-on 68 mA)", color="#e74c3c",
         group="always-on", year=("rel", "flood"),
         blurb=("Every node repeats every packet, radios listen 24/7 at "
                "68 mA. Best delivery in the fleet — until the snow buries "
                "the panels and the battery bill comes due.")),
    dict(key="energy_aware", label="Energy-aware (68 mA Heltec)",
         color="#e67e22", group="always-on", year=("rel", "energy_aware"),
         blurb=("Solar-aware source routing on always-on Heltec-class "
                "hardware. Routing is smart; the 68 mA listen current "
                "doesn't care.")),
    dict(key="ea_rak2ma", label="Energy-aware @ 2 mA (RAK-class) ★",
         color="#2ecc71", group="low-idle", year=("wur", "cmp_ea2"),
         blurb=("The winner: identical routing, but nRF52-class silicon "
                "listens at 2 mA. Always-on delivery with zero deaths — "
                "the problem wake-up radios try to solve, solved by a "
                "$35 board.")),
    dict(key="duty_sync", label="Duty-cycled 5% (duty_sync)",
         color="#3498db", group="duty", year=("rel", "duty_sync"),
         blurb=("Relays sleep 95% of the time on a shared clock. Watch "
                "nodes ride out the storm on a trickle of power — and SOS "
                "packets wait at asleep relays.")),
    dict(key="selective_duty", label="Selective duty (awake backbone)",
         color="#5dade2", group="duty", year=("rel", "selective_duty"),
         blurb=("Cut-vertex relays and route-tree parents stay awake; "
                "everyone else sleeps. The compromise arm: most of the "
                "survivability, much less of the latency pain.")),
    dict(key="rotate_lb", label="Rotating backbone (rotate_lb)",
         color="#85c1e9", group="duty", year=("rel", "rotate_lb"),
         blurb=("An always-on relay backbone that rotates membership to "
                "spread the battery burn. Watch the awake set change on "
                "route rebuilds.")),
    dict(key="wur_d40", label="Wake-up radio Δ40 dB (realistic)",
         color="#9b59b6", group="wur", year=("wur", "wur_d40_blind"),
         blurb=("Relays sleep at 3 µW behind a wake receiver 40 dB less "
                "sensitive than the main radio. Frames physically reach "
                "asleep relays that cannot hear the wake chirp — watch "
                "the orange failed-wake pings.")),
    dict(key="wur_d0", label="Wake-up radio Δ0 dB (ideal)",
         color="#bb8fce", group="wur", year=("wur", "wur_d0_blind"),
         blurb=("The physically impossible best case: the wake receiver "
                "hears everything the main radio would. Even here the "
                "chirp+boot overhead taxes every single hop.")),
]

KIND_CODE = {"sos": 0, "msg": 1, "fam": 2, "tel": 3, "pos": 4, "ack": 5,
             "fwd": 6, "beacon": 7}
BAT_STEP = 600.0          # matches run_replay_traces.sh --bat-trace-s
CUM_STEP = 600.0          # cumulative-counter series step
MAX_AMBIENT = 9000        # ambient flash edges kept per run
MAX_WAKE_PINGS = 4000
MAX_LOG = 2500
MAX_HOPS_PER_PKT = 140
MAX_CURATED_MSG = 350     # per kind (msg / fam)
SAMPLE_TEL = 60


def log(msg: str) -> None:
    print(msg, flush=True)


# ── sunrise/sunset (NOAA approximation, for night bands on the chart) ──────
def night_bands(start_date: str, days: float, lat: float, lon: float):
    from datetime import date, timedelta
    y, m, d = (int(x) for x in start_date.split("-"))
    d0 = date(y, m, d)
    bands, prev_set = [], None
    for i in range(int(days) + 2):
        day = d0 + timedelta(days=i)
        n = day.toordinal() - date(2000, 1, 1).toordinal() + 0.5
        jc = n / 36525.0
        gmls = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360
        gmas = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
        eeo = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
        seoc = (math.sin(math.radians(gmas)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
                + math.sin(math.radians(2 * gmas)) * (0.019993 - 0.000101 * jc)
                + math.sin(math.radians(3 * gmas)) * 0.000289)
        stl = gmls + seoc
        sal = stl - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * jc))
        moe = 23 + (26 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60) / 60
        oc = moe + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * jc))
        decl = math.degrees(math.asin(math.sin(math.radians(oc))
                                      * math.sin(math.radians(sal))))
        vy = math.tan(math.radians(oc / 2)) ** 2
        eot = 4 * math.degrees(
            vy * math.sin(2 * math.radians(gmls))
            - 2 * eeo * math.sin(math.radians(gmas))
            + 4 * eeo * vy * math.sin(math.radians(gmas)) * math.cos(2 * math.radians(gmls))
            - 0.5 * vy * vy * math.sin(4 * math.radians(gmls))
            - 1.25 * eeo * eeo * math.sin(2 * math.radians(gmas)))
        try:
            ha = math.degrees(math.acos(
                math.cos(math.radians(90.833))
                / (math.cos(math.radians(lat)) * math.cos(math.radians(decl)))
                - math.tan(math.radians(lat)) * math.tan(math.radians(decl))))
        except ValueError:
            ha = 0.0
        noon_min = 720 - 4 * lon - eot            # minutes UTC
        rise_s = (i * 86400.0) + (noon_min - ha * 4) * 60.0
        set_s = (i * 86400.0) + (noon_min + ha * 4) * 60.0
        if prev_set is None:
            bands.append([0.0, max(rise_s, 0.0)])
        else:
            bands.append([prev_set, rise_s])
        prev_set = set_s
    bands.append([prev_set, days * 86400.0])
    return [[round(a, 0), round(b, 0)] for a, b in bands
            if b > 0 and a < days * 86400.0 and b > a]


def pctl(sorted_vals, q):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


# ── year-scale canonical metrics ────────────────────────────────────────────
def year_metrics():
    rel = ROOT / "artifacts/sim/corrected/release_v1"
    cs = json.loads((rel / "corrected_stats.json").read_text())
    mm = json.loads((rel / "meaningful_metrics.json").read_text())
    out = {}
    for spec in RUNS:
        src, key = spec["year"]
        if src == "rel":
            c = cs["modes"][key]
            m = mm["modes"][key]
            out[spec["key"]] = {
                "engine": "fastsim (Rust), release_v1, 5 seeds × 365 d",
                "pdr": c["pdr"], "deaths": c["deaths"],
                "avail": m["availability"]["fleet_availability"],
                "sos_rate": m["sos"]["delivery_rate"],
                "sos_p95_s": m["sos"]["latency_p95_s"],
                "mwh_pkt": m["efficiency"]["tx_mwh_per_delivered_packet"],
            }
        else:  # wur_study aggregate over seeds (current engine)
            files = sorted(glob.glob(str(
                ROOT / f"artifacts/sim/wur_study/{key}_s*.json")))
            if not files:
                log(f"  !! no wur_study files for {key}; year card omitted")
                continue
            pdrs, deaths, avail, lats, s_sent, s_del = [], [], [], [], 0, 0
            for f in files:
                r = json.loads(Path(f).read_text())
                pdrs.append(r["pdr_overall"])
                deaths.append(r["fleet_energy"]["deaths_total"])
                avail.append(r["fleet_energy"]["availability"])
                sos = r.get("sos", {})
                lats += sos.get("latencies_s", [])
                s_del += sos.get("delivered", 0)
                s_sent += sos.get("sent", sos.get("delivered", 0))
            lats.sort()
            out[spec["key"]] = {
                "engine": f"fastsim (Rust), WuR-study campaign, "
                          f"{len(files)} seeds × 365 d",
                "pdr": sum(pdrs) / len(pdrs),
                "deaths": sum(deaths) / len(deaths),
                "avail": sum(avail) / len(avail),
                "sos_rate": (s_del / s_sent) if s_sent else None,
                "sos_p95_s": pctl(lats, 0.95),
                "mwh_pkt": None,
            }
    return out


# ── trace digest ────────────────────────────────────────────────────────────
def digest_run(spec, replay_dir, sites, name2idx, hiker_names):
    key = spec["key"]
    tp = replay_dir / f"{key}_trace.jsonl"
    sp = replay_dir / f"{key}_summary.json"
    summary = json.loads(sp.read_text())
    # windowed traces (--trace-after-days W): the engine ran from day 0 in
    # real accumulated state, the trace covers only [W, days]. Rebase every
    # timestamp to the window and present window-local metrics from the
    # trace itself; the engine summary becomes "season to date".
    win_off = float(summary.get("trace_after_days", 0.0)) * 86400.0
    win_days = summary["days"] - float(summary.get("trace_after_days", 0.0))
    dur = win_days * 86400.0
    summary = dict(summary)
    summary["daily_kt"] = summary.get("daily_kt", [])[
        int(summary.get("trace_after_days", 0.0)):]

    mover_ids: dict[str, int] = {}          # name -> negative idx (-1, -2, …)

    def nid(name):
        i = name2idx.get(name)
        if i is not None:
            return i
        if name not in mover_ids:
            mover_ids[name] = -(len(mover_ids) + 1)
        return mover_ids[name]

    kind_of = {}
    pkt_first_tx = {}
    pkt_orig = {}
    hops = defaultdict(list)          # pid -> [t, from, to, flag, rssi]
    delivered = {}                    # pid -> [t, viaIdx, lat_s, kindCode]
    ambient = []                      # sampled [t, a, b, ok, kind]
    wakes = []                        # sampled [t, nodeIdx, ok]
    wake_fail_pair = defaultdict(int)  # (from,to) -> budget fails
    wake_fail_node = defaultdict(int)
    bat = {}                          # idx -> [[soc‰, state], ...]
    deaths, revives = [], []          # [t, idx]
    logrows = []
    movers_tracks = defaultdict(list)
    n_tx = n_rx = n_col = 0
    tx_bins = defaultdict(int)        # 10-min tx counts
    col_bins = defaultdict(int)
    rx_bins = defaultdict(int)

    STATE = {"dead": 0, "awake": 1, "sniff": 2, "wur_asleep": 3,
             "wur_boot": 4, "wur_hang": 5}

    amb_keep = 1.0                    # adjusted after first pass? single pass:
    # reservoir-free thinning: keep every Kth ambient edge, K adapted from
    # flood-scale traces by kind (SOS always kept)
    amb_ctr = defaultdict(int)
    AMB_STRIDE = {"sos": 1, "msg": 2, "fam": 2, "ack": 2, "tel": 25,
                  "fwd": 25, "pos": 40, "beacon": 40}

    with tp.open() as fh:
        for line in fh:
            e = json.loads(line)
            ev = e["ev"]
            t = e["t"] - win_off
            if t < 0:
                continue
            if ev == "tx":
                pid = e["pkt"]
                k = e["kind"]
                if k != "fwd" or pid not in kind_of:
                    kind_of.setdefault(pid, k if k != "fwd" else "tel")
                pkt_first_tx.setdefault(pid, (t, e["n"]))
                pkt_orig.setdefault(pid, e.get("orig", e["n"]))
                n_tx += 1
                tx_bins[int(t // 600)] += 1
            elif ev in ("rx", "col"):
                pid = e["pkt"]
                ok = 1 if ev == "rx" else 0
                frm, to = nid(e["from"]), nid(e["n"])
                if ok:
                    n_rx += 1
                    rx_bins[int(t // 600)] += 1
                else:
                    n_col += 1
                    col_bins[int(t // 600)] += 1
                if len(hops[pid]) < MAX_HOPS_PER_PKT:
                    hops[pid].append([round(t, 2), frm, to, ok,
                                      e.get("rssi")])
                k = kind_of.get(pid, "tel")
                amb_ctr[k] += 1
                if amb_ctr[k] % AMB_STRIDE.get(k, 25) == 0 or k == "sos":
                    ambient.append([round(t, 1), frm, to, ok,
                                    KIND_CODE.get(k, 3)])
            elif ev == "bat":
                i = nid(e["n"])
                alive = e.get("alive", True)
                d = e.get("d", 1.0)
                wk = e.get("wk")
                if not alive:
                    st = STATE["dead"]
                elif wk is not None:
                    st = (STATE["wur_boot"] if wk == 1 else
                          STATE["wur_hang"] if wk == 2 else
                          STATE["wur_asleep"])
                elif d >= 1.0:
                    st = STATE["awake"]
                else:
                    st = STATE["sniff"]
                bat.setdefault(i, []).append(
                    [int(round(e["soc"] * 1000)), st,
                     round(e.get("sw", 0.0), 1)])
            elif ev == "deliver":
                pid = e["pkt"]
                k = e.get("kind", kind_of.get(pid, "tel"))
                kind_of[pid] = k
                pkt_orig.setdefault(pid, e.get("orig", "?"))
                delivered[pid] = [round(t, 2), nid(e["via"]), e["lat_s"],
                                  KIND_CODE.get(k, 3)]
                if k in ("sos", "msg", "fam") and len(logrows) < MAX_LOG:
                    icon = {"sos": "🆘", "msg": "✉", "fam": "🏠"}[k]
                    logrows.append([round(t, 1), "deliver",
                                    f"{icon} {k.upper()} from {e['orig']} "
                                    f"→ {e['via']} in {e['lat_s']}s"])
            elif ev == "wake":
                i = nid(e["n"])
                ok = e.get("ok", 0)
                if ok:
                    if len(wakes) < MAX_WAKE_PINGS * 2:
                        wakes.append([round(t, 1), i, 1])
                else:
                    wake_fail_node[e["n"]] += 1
                    wake_fail_pair[(e.get("from", "?"), e["n"])] += 1
                    if len(wakes) < MAX_WAKE_PINGS * 2:
                        wakes.append([round(t, 1), i, 0])
                    pid = e.get("pkt")
                    if pid is not None and len(hops[pid]) < MAX_HOPS_PER_PKT:
                        hops[pid].append([round(t, 2), nid(e.get("from", "?")),
                                          i, 2 if e.get("why") == "budget"
                                          else 3, None])
            elif ev == "dead":
                deaths.append([round(t, 1), nid(e["n"])])
                if len(logrows) < MAX_LOG:
                    logrows.append([round(t, 1), "dead", f"✕ {e['n']} died"])
            elif ev == "alive":
                revives.append([round(t, 1), nid(e["n"])])
                if len(logrows) < MAX_LOG:
                    logrows.append([round(t, 1), "alive",
                                    f"↻ {e['n']} recovered"])
            elif ev == "pos":
                movers_tracks[e["n"]].append(
                    [round(t, 1), e["lat"], e["lon"], e.get("dk", 0)])

    # thin oversampled collections
    if len(ambient) > MAX_AMBIENT:
        stride = len(ambient) / MAX_AMBIENT
        ambient = [ambient[int(i * stride)] for i in range(MAX_AMBIENT)]
    if len(wakes) > MAX_WAKE_PINGS:
        stride = len(wakes) / MAX_WAKE_PINGS
        wakes = [wakes[int(i * stride)] for i in range(MAX_WAKE_PINGS)]

    idx2name = {v: k for k, v in name2idx.items()}
    idx2name.update({v: k for k, v in mover_ids.items()})

    # ── curate packets ──────────────────────────────────────────────────────
    curated = {}

    def curate(pid, why=""):
        if pid in curated or pid not in hops and pid not in pkt_first_tx:
            return
        h = sorted(hops.get(pid, []))[:MAX_HOPS_PER_PKT]
        t0, first_n = pkt_first_tx.get(
            pid, ((h[0][0], idx2name.get(h[0][1], "?")) if h else (None, "?")))
        if t0 is None:
            return
        curated[pid] = {
            "k": KIND_CODE.get(kind_of.get(pid, "tel"), 3),
            "o": pkt_orig.get(pid, first_n),
            "t0": round(t0, 2),
            "h": [[hh[0], hh[1], hh[2], hh[3]] +
                  ([hh[4]] if hh[4] is not None else []) for hh in h],
            "del": delivered.get(pid),
            "why": why,
        }

    by_kind = defaultdict(list)
    for pid, k in kind_of.items():
        by_kind[k].append(pid)
    for pid in by_kind.get("sos", []):
        curate(pid, "sos")
    for pid in by_kind.get("ack", []):
        curate(pid, "sos-ack")
    for k in ("msg", "fam"):
        pids = sorted(by_kind.get(k, []), key=lambda p: pkt_first_tx.get(p, (0,))[0])
        if len(pids) > MAX_CURATED_MSG:
            stride = len(pids) / MAX_CURATED_MSG
            pids = [pids[int(i * stride)] for i in range(MAX_CURATED_MSG)]
        for pid in pids:
            curate(pid)
    tel = sorted(by_kind.get("tel", []), key=lambda p: -len(hops.get(p, [])))
    for pid in tel[:SAMPLE_TEL]:
        curate(pid, "long-haul telemetry")

    # ── beats ───────────────────────────────────────────────────────────────
    beats = build_beats(spec, summary, sites, idx2name, name2idx, bat,
                        deaths, revives, curated, hops, delivered, kind_of,
                        pkt_orig, pkt_first_tx, wake_fail_pair, col_bins,
                        rx_bins, dur, curate)

    # cumulative series (10-min bins)
    nbins = int(dur // CUM_STEP) + 1
    cum = {"tx": [0] * nbins, "col": [0] * nbins, "rx": [0] * nbins}
    for b, v in tx_bins.items():
        if b < nbins:
            cum["tx"][b] = v
    for b, v in col_bins.items():
        if b < nbins:
            cum["col"][b] = v
    for b, v in rx_bins.items():
        if b < nbins:
            cum["rx"][b] = v

    fe = summary["fleet_energy"]
    sos = summary.get("sos", {})
    lat_sorted = sorted(sos.get("latencies_s", []))
    # window metrics straight from the full-capture trace
    orig_w = sum(1 for pid, (tt, n) in pkt_first_tx.items()
                 if pkt_orig.get(pid) == n)
    sos_del_lat = sorted(v[2] for p, v in delivered.items()
                         if kind_of.get(p) == "sos")
    sos_orig_ts = sorted(pkt_first_tx[p][0] for p in kind_of
                         if kind_of[p] == "sos" and p in pkt_first_tx)
    sos_incidents = 0
    last_t = -1e9
    for tt in sos_orig_ts:            # collapse retries of one incident
        if tt - last_t >= 240:
            sos_incidents += 1
        last_t = tt
    replay_metrics = {
        "window": {
            "pdr": (len(delivered) / orig_w) if orig_w else None,
            "originated": orig_w, "delivered": len(delivered),
            "deaths": len(deaths), "unique_dead": len({i for _, i in deaths}),
            "revives": len(revives),
            "sos_incidents": sos_incidents, "sos_del": len(sos_del_lat),
            "sos_p95_s": pctl(sos_del_lat, 0.95),
            "trace_tx": n_tx, "trace_rx": n_rx, "trace_col": n_col,
        },
        "season": {
            "pdr": summary["pdr_overall"],
            "originated": summary.get("packets_originated"),
            "deaths": fe.get("death_events_total", fe.get("deaths_total")),
            "unique_dead": fe.get("unique_nodes_died"),
            "avail": fe.get("availability"),
            "sos_sent": sos.get("sent"), "sos_del": sos.get("delivered"),
            "sos_p95_s": pctl(lat_sorted, 0.95),
            "sos_max_s": lat_sorted[-1] if lat_sorted else None,
            "since": summary.get("start_date", ""),
        },
    }

    # link-health layer: fixed-site pairs only, worth drawing (>=50 tries)
    links = [[name2idx[r["a"]], name2idx[r["b"]], round(r["prr"], 3),
              r["tries"], round(r.get("mean_margin_db", 0.0), 1)]
             for r in summary.get("link_health", [])
             if r["a"] in name2idx and r["b"] in name2idx
             and r["tries"] >= 50]

    from datetime import date, timedelta
    season_start = summary.get("start_date", "2026-01-01")
    y0, m0, d0 = (int(x) for x in season_start.split("-"))
    win_start = (date(y0, m0, d0)
                 + timedelta(days=int(summary.get("trace_after_days", 0.0)))
                 ).isoformat()

    return {
        "key": key, "label": spec["label"], "color": spec["color"],
        "group": spec["group"], "blurb": spec["blurb"],
        "mode": summary["mode"], "seed": summary["seed"],
        "days": win_days, "start": win_start,
        "ambient": ambient, "wakes": wakes,
        "bat": {str(i): v for i, v in bat.items() if i >= 0},
        "deaths": deaths, "revives": revives, "log": logrows[:MAX_LOG],
        "packets": {str(p): v for p, v in curated.items()},
        "beats": beats, "cum": cum,
        "movers": {n: v for n, v in movers_tracks.items()},
        "moverIdx": {str(v): k for k, v in mover_ids.items()},
        "links": links,
        "replay": replay_metrics,
    }


def fmt_hms(t):
    et = t - 5 * 3600.0
    day = int(et // 86400) + 1
    h = int(et % 86400) // 3600
    m = int(et % 3600) // 60
    return f"day {day} {h:02d}:{m:02d} ET"


def build_beats(spec, summary, sites, idx2name, name2idx, bat, deaths,
                revives, curated, hops, delivered, kind_of, pkt_orig,
                pkt_first_tx, wake_fail_pair, col_bins, rx_bins, dur, curate):
    beats = []
    daily_kt = summary.get("daily_kt", [])

    def kt_txt(t):
        d = int(t // 86400)
        if d < len(daily_kt):
            kt = daily_kt[d]
            sky = ("heavy overcast" if kt < 0.25 else
                   "overcast" if kt < 0.4 else
                   "partly cloudy" if kt < 0.6 else "clear")
            return f"{sky} (clearness kt={kt:.2f})"
        return "unknown sky"

    # 1) first death with energy ledger
    if deaths:
        t0, i0 = deaths[0]
        n0 = idx2name.get(i0, "?")
        series = bat.get(i0, [])
        last_sun = None
        for j, row in enumerate(series):
            if j * BAT_STEP > t0:
                break
            if row[2] > 0.5:
                last_sun = j * BAT_STEP
        sun_txt = (f"no meaningful solar since {fmt_hms(last_sun)}"
                   if last_sun is not None else "no solar harvested at all")
        beats.append(dict(
            t=round(t0 + 5, 1), pri=1, id="first_death",
            title=f"First battery death: {n0}",
            body=(f"<b>{n0}</b> hit 0% at {fmt_hms(t0)} — the first casualty "
                  f"of this run. Cause in this mode: {spec['blurb'].split('.')[0]}. "
                  f"Conditions: {kt_txt(t0)}, {sun_txt}. Every node with the "
                  f"same duty clock is on the same countdown."),
            nodes=[i0]))

    # 2) death waves (>=5 deaths in 2 h) + downfall marker at first wave
    wave_start, wave_nodes, downfall_done = None, [], False
    for t, i in deaths:
        if wave_start is None or t - wave_start > 7200:
            if len(wave_nodes) >= 5 and not downfall_done:
                beats.append(dict(
                    t=round(wave_start + 60, 1), pri=2, id="downfall",
                    title=f"The downfall starts: {len(wave_nodes)} relays "
                          f"die within 2 h",
                    body=(f"Starting {fmt_hms(wave_start)}, "
                          f"{len(wave_nodes)} relays deplete in one wave "
                          f"({', '.join(idx2name.get(i,'?') for i in wave_nodes[:5])}"
                          f"{'…' if len(wave_nodes) > 5 else ''}). They all "
                          f"charged and drained on the same schedule, so "
                          f"they die on the same schedule — a fleet-wide "
                          f"clock, not bad luck. {kt_txt(wave_start)}."),
                    nodes=wave_nodes[:12]))
                downfall_done = True
            wave_start, wave_nodes = t, [i]
        else:
            wave_nodes.append(i)
    if len(wave_nodes) >= 5 and not downfall_done:
        beats.append(dict(
            t=round(wave_start + 60, 1), pri=2, id="downfall",
            title=f"The downfall starts: {len(wave_nodes)} relays die within 2 h",
            body=(f"Starting {fmt_hms(wave_start)}, {len(wave_nodes)} relays "
                  f"deplete in one wave. Same charge clock, same death clock. "
                  f"{kt_txt(wave_start)}."),
            nodes=wave_nodes[:12]))

    # 3) self-healing: relay dies -> same-origin traffic reroutes around it
    # (index-first: the window can hold hundreds of deaths and tens of
    # thousands of deliveries, so the naive cross-scan is too slow)
    used_by = defaultdict(list)        # node idx -> [(deliver_t, pid)]
    orig_deliv = defaultdict(list)     # origin -> [(deliver_t, pid)]
    for pid, dl in delivered.items():
        seen_n = set()
        for r in hops.get(pid, []):
            seen_n.add(r[1])
            seen_n.add(r[2])
        for n in seen_n:
            used_by[n].append((dl[0], pid))
        orig_deliv[pkt_orig.get(pid, "?")].append((dl[0], pid))
    for lst in used_by.values():
        lst.sort()
    for lst in orig_deliv.values():
        lst.sort()

    healed = 0
    for td, di in deaths:
        if healed >= 3:
            break
        if di < 0:
            continue
        cand = [(tt, pid) for tt, pid in used_by.get(di, [])
                if td - 21600 < tt < td]
        if len(cand) < 3:
            continue
        pre = cand[-1][1]
        o = pkt_orig.get(pre)
        post = None
        for tt, pid in orig_deliv.get(o, []):
            if tt <= td:
                continue
            if tt > td + 21600:
                break
            if any(r[1] == di or r[2] == di for r in hops.get(pid, [])):
                continue
            post = pid
            break
        if post is None:
            continue
        pre_uses = len(cand)
        dn = idx2name.get(di, "?")
        curate(pre, f"healing: used {dn} before it died")
        curate(post, f"healing: rerouted around dead {dn}")
        beats.append(dict(
            t=round(delivered[post][0] + 2, 1), pri=1, id=f"heal_{dn}",
            title=f"Self-healing: traffic reroutes around dead {dn}",
            body=(f"<b>{dn}</b> carried {pre_uses} delivered flows in the "
                  f"6 h before it died at {fmt_hms(td)}. "
                  f"{fmt_hms(delivered[post][0])}: the first delivery from "
                  f"<b>{o}</b> arrives over a path that avoids it entirely. "
                  f"No operator, no reconfiguration — the route tree "
                  f"rebuilt itself. Use the buttons below to replay the "
                  f"before/after packet journeys."),
            nodes=[di], pair=[str(pre), str(post)]))
        healed += 1

    # 4) SOS incidents (every origination is a beat; delivery adds detail)
    sos_pids = sorted([p for p, k in kind_of.items() if k == "sos"],
                      key=lambda p: pkt_first_tx.get(p, (1e18,))[0])
    seen_orig_t = []
    for pid in sos_pids:
        t0, n0 = pkt_first_tx.get(pid, (None, None))
        if t0 is None:
            continue
        if any(abs(t0 - x) < 240 for x in seen_orig_t):
            continue          # retries of the same incident
        seen_orig_t.append(t0)
        dl = delivered.get(pid)
        if dl:
            dtl = (f"Delivered to SAR HQ via <b>{idx2name.get(dl[1], '?')}</b> "
                   f"in <b>{dl[2]:.1f} s</b>.")
        else:
            later = [q for q in sos_pids
                     if pkt_orig.get(q) == pkt_orig.get(pid)
                     and delivered.get(q)
                     and pkt_first_tx.get(q, (0,))[0] >= t0]
            if later:
                q = later[0]
                dtl = (f"This attempt did NOT get through — a retry finally "
                       f"reached SAR HQ {delivered[q][0] - t0:.0f} s after "
                       f"the first cry for help.")
            else:
                dtl = ("<b>Never delivered inside the replay window.</b>")
        beats.append(dict(
            t=round(t0 - 1, 1), pri=0, id=f"sos_{pid}",
            title=f"🆘 SOS raised by {pkt_orig.get(pid, n0)}",
            body=(f"A hiker triggers an SOS at {fmt_hms(t0)}. {dtl} "
                  f"Click Follow to watch every real hop this packet made."),
            nodes=[], pkt=str(pid)))

    # 5) wake-budget hotspot (wur only)
    if wake_fail_pair:
        (frm, to), cnt = max(wake_fail_pair.items(), key=lambda kv: kv[1])
        ii = name2idx.get(to)
        first_t = dur * 0.35
        beats.append(dict(
            t=round(first_t, 1), pri=2, id="wake_hotspot",
            title=f"Wake-budget black hole: {frm} → {to}",
            body=(f"Over this run, <b>{cnt}</b> frames from <b>{frm}</b> "
                  f"physically reached <b>{to}</b> loud enough for the main "
                  f"radio — but not loud enough for its less-sensitive wake "
                  f"receiver. The relay slept through every one (orange "
                  f"pings). This is the wake-sensitivity delta doing the "
                  f"damage: the link exists, the wake radio can't hear it."),
            nodes=[ii] if ii is not None else []))

    # 6) collision storm (worst 10-min bin, flood-ish runs)
    if col_bins:
        b, c = max(col_bins.items(), key=lambda kv: kv[1])
        r = rx_bins.get(b, 0)
        if c >= 200 and c / max(c + r, 1) > 0.12:
            beats.append(dict(
                t=round(b * 600 + 300, 1), pri=3, id="col_storm",
                title=f"Collision storm: {c} collisions in 10 min",
                body=(f"Midday traffic peak: {c} frame collisions against "
                      f"{r} clean receptions in this 10-minute window "
                      f"({100 * c / max(c + r, 1):.0f}% of the channel lost). "
                      f"Every repeat is another lottery ticket for overlap — "
                      f"the price of flooding."),
                nodes=[]))

    # 7) sunrise mass-recovery (post-loop flush mirrors the death-wave one)
    def _sunrise_beat(rev_start, rev_nodes):
        return dict(
            t=round(rev_start + 60, 1), pri=3, id="sunrise",
            title=f"Sunrise: {len(rev_nodes)} relays come back",
            body=(f"{fmt_hms(rev_start)}: panels finally see the sun "
                  f"and {len(rev_nodes)} dead relays recharge past "
                  f"the revive threshold within the hour. The mesh "
                  f"breathes with the daylight — dying every night, "
                  f"resurrecting every morning."),
            nodes=rev_nodes[:12])

    rev_start, rev_nodes, done_rev = None, [], False
    for t, i in revives:
        if rev_start is None or t - rev_start > 3600:
            if len(rev_nodes) >= 5 and not done_rev:
                beats.append(_sunrise_beat(rev_start, rev_nodes))
                done_rev = True
            rev_start, rev_nodes = t, [i]
        else:
            rev_nodes.append(i)
    if len(rev_nodes) >= 5 and not done_rev:
        beats.append(_sunrise_beat(rev_start, rev_nodes))

    beats.sort(key=lambda b: b["t"])
    # enforce spacing: SOS (pri 0) always kept; others >= 15 min apart
    out, last_t = [], -1e9
    for b in beats:
        if b["pri"] == 0 or b["t"] - last_t >= 900:
            out.append(b)
            last_t = b["t"]
    return out[:16]


# ── main ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--replay-dir", default="artifacts/sim/replay")
    ap.add_argument("--topology",
                    default="artifacts/sim/corrected/release_v1/topology_statewide.json")
    ap.add_argument("--routes",
                    default="artifacts/sim/corrected/release_v1/routes_statewide.json")
    ap.add_argument("--out", default="artifacts/sim/replay/replay_viewer.html")
    ap.add_argument("--only", default=None,
                    help="comma-separated run keys (debug)")
    args = ap.parse_args()

    replay_dir = ROOT / args.replay_dir
    topo = json.loads((ROOT / args.topology).read_text())
    sites = topo["sites"]
    site_names = sorted(sites)
    name2idx = {n: i for i, n in enumerate(site_names)}
    hiker_names = {"hiker_alpha"}

    sites_out = [{
        "n": n, "lat": sites[n]["lat"], "lon": sites[n]["lon"],
        "gw": bool(sites[n].get("mqtt_uplink")),
        "p": sites[n].get("power", "battery"),
        "cat": sites[n].get("category", "relay"),
        "l": sites[n].get("label", n),
    } for n in site_names]

    trails, routegeom = {}, {}
    rp = ROOT / args.routes
    if rp.exists():
        rj = json.loads(rp.read_text())
        for rn, r in rj["routes"].items():
            pts = list(zip(r["lat"], r["lon"]))
            trails[rn] = [[round(a, 5), round(b, 5)] for a, b in pts[::4]]
            routegeom[rn] = {
                "t": [round(float(x), 1) for x in r["t_s"][::3]],
                "lat": [round(float(x), 5) for x in r["lat"][::3]],
                "lon": [round(float(x), 5) for x in r["lon"][::3]],
                "dur": r["duration_s"], "kiosk": r.get("kiosk")}

    nh = []
    nh_p = ROOT / "artifacts/osm/nh_boundary.json"
    if nh_p.exists():
        g = json.loads(nh_p.read_text())
        ring = (g["coordinates"][0] if g["type"] == "Polygon"
                else g["coordinates"][0][0])
        nh = [[round(c[1], 4), round(c[0], 4)] for c in ring]

    ym = year_metrics()

    run_keys = ([k.strip() for k in args.only.split(",")]
                if args.only else [r["key"] for r in RUNS])
    runs_b64, run_list = {}, []
    lat_c = sum(s["lat"] for s in sites_out) / len(sites_out)
    lon_c = sum(s["lon"] for s in sites_out) / len(sites_out)
    for spec in RUNS:
        if spec["key"] not in run_keys:
            continue
        tp = replay_dir / f"{spec['key']}_trace.jsonl"
        sp = replay_dir / f"{spec['key']}_summary.json"
        if not tp.exists() or not sp.exists():
            log(f"  -- skipping {spec['key']} (trace not ready)")
            continue
        log(f"digesting {spec['key']} "
            f"({tp.stat().st_size / 1e6:.0f} MB trace) ...")
        d = digest_run(spec, replay_dir, sites, name2idx, hiker_names)
        d["night"] = night_bands(d["start"], d["days"], lat_c, lon_c)
        d["year"] = ym.get(spec["key"])
        raw = json.dumps(d, separators=(",", ":")).encode()
        runs_b64[spec["key"]] = base64.b64encode(
            gzip.compress(raw, 6)).decode()
        run_list.append({k: spec[k] for k in
                         ("key", "label", "color", "group")})
        log(f"  {spec['key']}: {len(d['packets'])} curated packets, "
            f"{len(d['beats'])} beats, {len(d['ambient'])} ambient edges, "
            f"{len(raw) / 1e6:.1f} MB raw -> "
            f"{len(runs_b64[spec['key']]) / 1e6:.2f} MB embedded")

    if not run_list:
        log("no runs ready; aborting")
        return 1

    common = {
        "sites": sites_out, "trails": trails, "routegeom": routegeom,
        "nh": nh, "runs": run_list,
        "year": ym,
        "note": ("MODEL-ONLY (uncalibrated). Replay traces: Python twin "
                 "engine, statewide topology, seed 42, full event capture "
                 "over the darkest 5-day window of the pinned weather year "
                 "(Nov 30 – Dec 4) after a 14-day warmup that carries real "
                 "accumulated battery state into the window. Year-scale "
                 "cards: fastsim (Rust) released campaigns, 5 seeds × "
                 "365 days."),
    }

    vendor = ROOT / "artifacts/vendor"
    template = (ROOT / "scripts/replay_viewer_template.html").read_text()
    html = (template
            .replace("__LEAFLET_CSS__", (vendor / "leaflet.css").read_text())
            .replace("__LEAFLET_JS__", (vendor / "leaflet.js").read_text())
            .replace("__COMMON__", json.dumps(common, separators=(",", ":")))
            .replace("__RUNS_B64__", json.dumps(runs_b64)))
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    log(f"viewer: {out} ({out.stat().st_size / 1e6:.1f} MB, "
        f"{len(run_list)} runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

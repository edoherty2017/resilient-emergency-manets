#!/usr/bin/env python3
"""Broadcast-storm threshold sweep for the WMNF flood mesh.

Managed flooding rebroadcasts every packet up to hop_limit times, so offered
load is multiplied by the mesh itself. This sweep finds where that turns into
a storm: PDR and SOS latency vs (number of beaconing hikers × beacon interval),
plus a hop-limit sweep at a fixed heavy load.

Prospective threshold definition: the storm knee is the lowest offered load at
which network-wide PDR < 0.90. This becomes a frozen analysis rule only when
versioned before a clean corrected run; the historical sweep is superseded.

Outputs: artifacts/sim/storm_sweep.csv, storm_sweep.png, storm_summary.json
Run: .venv/bin/python scripts/broadcast_storm_sweep.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mesh_sim import run_sim  # noqa: E402

HIKERS = [0, 5, 10, 20, 40]
INTERVALS_S = [300, 120, 60, 30]
HOP_LIMITS = [1, 2, 3, 5, 7]
HOP_SWEEP_LOAD = {"extra_hikers": 20, "beacon_interval_s": 60}
PDR_THRESHOLD = 0.90


def one_run(**kw) -> dict:
    # 6 sim-hours per cell: the storm knee is a steady-state property of offered
    # load, not of diurnal structure; extras beacon continuously.
    s = run_sim(days=0.25, mode="flood", always_beacon=True, **kw)
    col = sum(v["collisions"] for v in s["per_node"].values())
    rx = sum(v["rx_ok"] for v in s["per_node"].values())
    # hiker-origin PDR: the storm metric. Overall PDR is composition-biased —
    # added hikers land at well-connected spots and dilute the RF-island sites.
    h_sent = sum(o["sent"] for k, o in s["per_origin"].items() if k.startswith("hiker"))
    h_del = sum(o["delivered"] for k, o in s["per_origin"].items() if k.startswith("hiker"))
    return {
        "pdr_hiker": round(h_del / h_sent, 4) if h_sent else None,
        "extra_hikers": kw.get("extra_hikers", 0),
        "beacon_interval_s": kw.get("beacon_interval_s") or 300,
        "hop_limit": kw.get("hop_limit") or 3,
        "n_nodes": s["n_nodes"],
        "packets_originated": s["packets_originated"],
        "pdr": s["pdr_overall"],
        "channel_utilization": s["channel_utilization"],
        "collision_fraction": round(col / max(col + rx, 1), 4),
        "sos_delivered": s["sos"]["delivered"],
        "sos_latency_s": (s["sos"]["latencies_s"][0] if s["sos"]["latencies_s"] else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Broadcast storm threshold sweep")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out-dir", default="artifacts/sim")
    args = ap.parse_args()
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    print("load grid (hop_limit=3):")
    for nh in HIKERS:
        for iv in INTERVALS_S:
            r = one_run(seed=args.seed, extra_hikers=nh, beacon_interval_s=iv)
            r["sweep"] = "load"
            rows.append(r)
            print(f"  hikers={nh:3d} interval={iv:4d}s  PDR_hiker {r['pdr_hiker']:.3f}  "
                  f"util {r['channel_utilization']:.3f}  col {r['collision_fraction']:.3f}")
    print(f"hop-limit sweep @ {HOP_SWEEP_LOAD}:")
    for hl in HOP_LIMITS:
        r = one_run(seed=args.seed, hop_limit=hl, **HOP_SWEEP_LOAD)
        r["sweep"] = "hop_limit"
        rows.append(r)
        print(f"  hop_limit={hl}  PDR_hiker {r['pdr_hiker']:.3f}  "
              f"util {r['channel_utilization']:.3f}  col {r['collision_fraction']:.3f}")

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "storm_sweep.csv", index=False)

    # storm knee: offered originations/hour where PDR first dips below threshold
    load = df[df["sweep"] == "load"].copy()
    load["beacons_per_hour"] = (load["extra_hikers"] + 1) * 3600.0 / load["beacon_interval_s"]
    load = load.sort_values("beacons_per_hour")
    below = load[load["pdr_hiker"] < PDR_THRESHOLD]
    knee = None
    if len(below):
        k = below.iloc[0]
        knee = {"beacons_per_hour": float(k["beacons_per_hour"]),
                "extra_hikers": int(k["extra_hikers"]),
                "beacon_interval_s": int(k["beacon_interval_s"]),
                "pdr_hiker": float(k["pdr_hiker"]),
                "channel_utilization": float(k["channel_utilization"])}

    # ── figure ────────────────────────────────────────────────────────────────
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    piv = load.pivot_table(index="extra_hikers", columns="beacon_interval_s", values="pdr_hiker")
    im = axes[0].imshow(piv.to_numpy(), cmap="RdYlGn", vmin=0.4, vmax=1.0, aspect="auto")
    axes[0].set_xticks(range(len(piv.columns)), [f"{c}s" for c in piv.columns])
    axes[0].set_yticks(range(len(piv.index)), piv.index)
    axes[0].set_xlabel("beacon interval"); axes[0].set_ylabel("extra hikers")
    axes[0].set_title("Hiker-origin PDR (flood, hop_limit=3)")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            axes[0].text(j, i, f"{piv.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=axes[0], shrink=0.85)

    axes[1].semilogx(load["beacons_per_hour"], load["pdr_hiker"], "o", alpha=0.7)
    axes[1].axhline(PDR_THRESHOLD, color="r", ls="--", label=f"threshold {PDR_THRESHOLD}")
    if knee:
        axes[1].axvline(knee["beacons_per_hour"], color="r", ls=":",
                        label=f"knee ≈ {knee['beacons_per_hour']:.0f} pkt/h")
    axes[1].set_xlabel("offered beacons/hour (all hikers)")
    axes[1].set_ylabel("hiker-origin PDR"); axes[1].legend(); axes[1].grid(alpha=0.3)
    axes[1].set_title("Storm knee")

    hop = df[df["sweep"] == "hop_limit"]
    ax2 = axes[2]
    ax2.plot(hop["hop_limit"], hop["pdr_hiker"], "o-", color="tab:green", label="PDR")
    ax2.set_xlabel("hop_limit"); ax2.set_ylabel("PDR", color="tab:green")
    ax2b = ax2.twinx()
    ax2b.plot(hop["hop_limit"], hop["channel_utilization"], "s--",
              color="tab:red", label="channel util")
    ax2b.set_ylabel("channel utilization", color="tab:red")
    ax2.set_title(f"hop_limit @ {HOP_SWEEP_LOAD['extra_hikers']} hikers / "
                  f"{HOP_SWEEP_LOAD['beacon_interval_s']}s")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "storm_sweep.png", dpi=140)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_status": "EXPLORATORY_SIMULATION_NOT_FIELD_VALIDATION",
        "provenance_warning": "Use a clean corrected-engine run manifest with hashed inputs before citing this sweep; historical outputs are superseded.",
        "pdr_threshold": PDR_THRESHOLD,
        "storm_knee": knee,
        "hop_limit_sweep": hop[["hop_limit", "pdr_hiker", "pdr", "channel_utilization",
                                "collision_fraction"]].to_dict("records"),
        "note": "6 simulated hours per cell, seed fixed; extras beacon continuously "
                "(worst case). Knee = lowest offered load with hiker-origin PDR < threshold.",
    }
    (out_dir / "storm_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["storm_knee"], indent=2))
    print(f"wrote {out_dir}/storm_sweep.csv, storm_sweep.png, storm_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

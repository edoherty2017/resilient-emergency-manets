#!/usr/bin/env python3
"""Infrastructure Failure Matrix (proposal deliverable #4).

Cross-technology connectivity floor by terrain: for each communication technology
(LoRa mesh, cellular, satellite/Starlink) and each terrain class, the fraction of
observations with service available, with Wilson 95% CIs and sample counts.

Availability is measured at the service layer (can a packet get through), not raw
signal strength — comparing LoRa RSSI to cellular RSRP is a category error
(methodology note, TODO-ANCHOR P4). A leg with no field data is shown as "no data"
rather than fabricated.

Inputs: an enriched telemetry/predictions parquet that may carry any of
  rssi_dbm (mesh received), cell_available (cellular), satellite_link_status.

Usage:
  python3 scripts/build_failure_matrix.py \
      --input artifacts/weather/telemetry_weather_enriched.parquet
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

SAT_UP = {"connected", "up", "online", "active", "true", "1", "yes"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * max(c - h, 0), 1), round(100 * min(c + h, 1), 1))


def availability_series(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Per-technology boolean availability, only for technologies with data."""
    techs = {}
    if "rssi_dbm" in df.columns:
        techs["lora_mesh"] = pd.to_numeric(df["rssi_dbm"], errors="coerce").notna()
    if "cell_available" in df.columns and df["cell_available"].notna().any():
        techs["cellular"] = df["cell_available"].fillna(False).astype(bool)
    if "satellite_link_status" in df.columns and df["satellite_link_status"].notna().any():
        techs["satellite"] = (
            df["satellite_link_status"].astype(str).str.lower().isin(SAT_UP)
        )
    return techs


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Infrastructure Failure Matrix")
    ap.add_argument("--input", required=True)
    ap.add_argument("--terrain-col", default="topography_class")
    ap.add_argument("--out-dir", default="artifacts/failure_matrix")
    args = ap.parse_args()

    in_path = ROOT / args.input if not Path(args.input).is_absolute() else Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")
    df = pd.read_parquet(in_path) if in_path.suffix == ".parquet" else pd.read_csv(in_path)
    if args.terrain_col not in df.columns:
        df[args.terrain_col] = "unknown"
    df[args.terrain_col] = df[args.terrain_col].fillna("unknown")

    techs = availability_series(df)
    if not techs:
        raise SystemExit("no technology availability columns present (need rssi_dbm/cell_available/satellite_link_status)")

    terrains = sorted(df[args.terrain_col].unique())
    rows = []
    matrix_pct = {}  # tech -> {terrain -> pct or None}
    for tech, avail in techs.items():
        matrix_pct[tech] = {}
        for terr in terrains:
            mask = df[args.terrain_col] == terr
            n = int(mask.sum())
            k = int(avail[mask].sum())
            pct = round(100 * k / n, 1) if n else None
            lo, hi = wilson(k, n)
            rows.append({
                "technology": tech, "terrain_class": terr,
                "n": n, "available": k, "availability_pct": pct,
                "wilson95_lo": lo, "wilson95_hi": hi,
            })
            matrix_pct[tech][terr] = pct

    out_dir = ROOT / args.out_dir if not Path(args.out_dir).is_absolute() else Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    long_df = pd.DataFrame(rows)
    long_df.to_csv(out_dir / "failure_matrix.csv", index=False)

    # markdown table
    md = ["# Infrastructure Failure Matrix",
          "",
          "Service-layer availability % (Wilson 95% CI), by technology × terrain.",
          "",
          "| Technology | " + " | ".join(terrains) + " |",
          "|---|" + "|".join(["---"] * len(terrains)) + "|"]
    for tech in techs:
        cells = []
        for terr in terrains:
            r = next(x for x in rows if x["technology"] == tech and x["terrain_class"] == terr)
            if r["n"] == 0 or r["availability_pct"] is None:
                cells.append("no data")
            else:
                cells.append(f"{r['availability_pct']:.0f}% (n={r['n']})")
        md.append(f"| {tech} | " + " | ".join(cells) + " |")
    (out_dir / "failure_matrix.md").write_text("\n".join(md))

    # heatmap PNG
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tech_list = list(techs)
    grid = np.array([[matrix_pct[t].get(terr) if matrix_pct[t].get(terr) is not None else np.nan
                      for terr in terrains] for t in tech_list], dtype=float)
    fig, ax = plt.subplots(figsize=(1.6 * len(terrains) + 2, 1.1 * len(tech_list) + 2))
    im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(terrains))); ax.set_xticklabels(terrains, rotation=20, ha="right")
    ax.set_yticks(range(len(tech_list))); ax.set_yticklabels(tech_list)
    for i in range(len(tech_list)):
        for j in range(len(terrains)):
            v = grid[i, j]
            txt = "no data" if np.isnan(v) else f"{v:.0f}%"
            ax.text(j, i, txt, ha="center", va="center",
                    color="black", fontsize=9)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Availability %")
    ax.set_title("Infrastructure Failure Matrix\n(service-layer availability by technology × terrain)")
    fig.tight_layout()
    fig.savefig(out_dir / "failure_matrix.png", dpi=140)
    plt.close(fig)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(in_path.relative_to(ROOT)) if in_path.is_relative_to(ROOT) else str(in_path),
        "technologies": tech_list,
        "terrain_classes": terrains,
        "matrix_availability_pct": matrix_pct,
        "missing_legs": [t for t in ("lora_mesh", "cellular", "satellite") if t not in techs],
        "outputs": ["failure_matrix.csv", "failure_matrix.md", "failure_matrix.png"],
    }
    (out_dir / "failure_matrix_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

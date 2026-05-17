#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def classify_topography(slope: float, elev: float) -> str:
    if slope >= 28:
        return "cliff_or_ridge"
    if slope >= 16:
        return "steep_hillside"
    if elev <= 500:
        return "valley_floor"
    return "rolling_highlands"


def classify_material(elev: float, slope: float) -> str:
    if elev >= 1200:
        return "exposed_rock"
    if slope >= 20:
        return "mixed_talus"
    if elev <= 600:
        return "dense_forest"
    return "mixed_forest"


def attenuation_prior_db(material_class: str, topography_class: str, freq_mhz: float) -> float:
    base = {
        "dense_forest": 10.0,
        "mixed_forest": 7.0,
        "mixed_talus": 12.0,
        "exposed_rock": 5.5,
    }[material_class]

    topo_adj = {
        "valley_floor": 3.0,
        "rolling_highlands": 1.5,
        "steep_hillside": 4.0,
        "cliff_or_ridge": 5.5,
    }[topography_class]

    # weak frequency scaling anchored near 915 MHz
    fscale = (freq_mhz / 915.0) ** 0.25
    return float((base + topo_adj) * fscale)


def main() -> int:
    ap = argparse.ArgumentParser(description="Add geology/topography attenuation priors to route features")
    ap.add_argument("--input", default="artifacts/dem/route_topography_features.parquet")
    ap.add_argument("--output", default="artifacts/dem/geology_loss_features.parquet")
    ap.add_argument("--output-csv", default="artifacts/dem/geology_loss_features.csv")
    ap.add_argument("--summary", default="artifacts/dem/geology_loss_summary.json")
    ap.add_argument("--freq-mhz", type=float, default=915.0)
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        raise SystemExit(f"input not found: {inp}")

    df = pd.read_parquet(inp)
    if df.empty:
        raise SystemExit("empty input feature table")

    df["dem_slope_deg"] = pd.to_numeric(df.get("dem_slope_deg"), errors="coerce")
    df["dem_elev_m"] = pd.to_numeric(df.get("dem_elev_m"), errors="coerce")
    df = df.dropna(subset=["dem_slope_deg", "dem_elev_m"]).copy()

    df["topography_class"] = [classify_topography(s, e) for s, e in zip(df["dem_slope_deg"], df["dem_elev_m"])]
    df["material_class"] = [classify_material(e, s) for s, e in zip(df["dem_slope_deg"], df["dem_elev_m"])]

    df["expected_loss_db"] = [
        attenuation_prior_db(m, t, args.freq_mhz)
        for m, t in zip(df["material_class"], df["topography_class"])
    ]

    # A conservative uncertainty band widens for steeper terrain.
    df["loss_uncertainty_db"] = np.where(df["dem_slope_deg"] >= 20, 3.0, 1.5)

    out_parquet = Path(args.output)
    out_csv = Path(args.output_csv)
    out_parquet.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(out_parquet, index=False)
    df.to_csv(out_csv, index=False)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(df)),
        "freq_mhz": float(args.freq_mhz),
        "topography_counts": df["topography_class"].value_counts(dropna=False).to_dict(),
        "material_counts": df["material_class"].value_counts(dropna=False).to_dict(),
        "expected_loss_db": {
            "min": float(df["expected_loss_db"].min()),
            "max": float(df["expected_loss_db"].max()),
            "mean": float(df["expected_loss_db"].mean()),
        },
        "uncertainty_db": {
            "min": float(df["loss_uncertainty_db"].min()),
            "max": float(df["loss_uncertainty_db"].max()),
            "mean": float(df["loss_uncertainty_db"].mean()),
        },
        "outputs": {
            "parquet": str(out_parquet),
            "csv": str(out_csv),
        },
    }

    summary_path = Path(args.summary)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

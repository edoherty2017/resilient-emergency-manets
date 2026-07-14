#!/bin/bash
# Reproducible corrected replacement-run release (audit §9 priority 3 / bucket 5).
# Freezes a hash-locked copy of the inputs, runs the 9 shared modes x 5 seeds on
# the committed FastSim (Rust) engine, aggregates per-mode means + t-based 95% CIs,
# and writes a git/hash-bound release manifest. MODEL-ONLY, single-engine.
#
# Usage: scripts/run_corrected_release.sh [release_dir]
set -euo pipefail
cd "$(dirname "$0")/.."
REL="${1:-artifacts/sim/corrected/release_v1}"
BIN="fastsim/target/release/fastsim"
CFG="config/sim/wmnf_sim.yaml"
MODES="flood min_hop etx energy_aware lb_energy duty_sync duty_adaptive rotate_lb selective_duty"
SEEDS="42 43 44 45 46"

[ -x "$BIN" ] || { echo "build fastsim first: (cd fastsim && cargo build --release)"; exit 1; }
mkdir -p "$REL"

# 1. freeze + hash the inputs so a mid-run edit cannot change the release
cp artifacts/sim/topology_statewide.json artifacts/sim/routes_statewide.json \
   artifacts/sim/weather_year.json "$CFG" "$REL/"
( cd "$REL" && shasum -a 256 topology_statewide.json routes_statewide.json \
    weather_year.json wmnf_sim.yaml > input_hashes.txt )
echo "git HEAD: $(git rev-parse --short HEAD)" >> "$REL/input_hashes.txt"

# 2. run the sweep (8-way parallel, batched)
i=0
for M in $MODES; do for S in $SEEDS; do
  "$BIN" --topology "$REL/topology_statewide.json" --routes "$REL/routes_statewide.json" \
    --weather "$REL/weather_year.json" --config "$REL/wmnf_sim.yaml" --days 365 --seed "$S" \
    --sos-retry --renters-per-route 2 --telemetry-interval-s 3600 --beacon-interval-s 900 \
    --energy-step-s 600 --route-refresh-s 3600 --mode "$M" \
    --out "$REL/fs_${M}_s${S}.json" >/dev/null 2>&1 &
  i=$((i+1)); [ $((i % 8)) -eq 0 ] && wait
done; done
wait
echo "ran $i corrected runs"

# 3. aggregate + manifest (delegated to the Python helper for testability)
.venv/bin/python scripts/aggregate_corrected_release.py --release "$REL"
echo "release complete: $REL/corrected_stats.json + release_manifest.json"

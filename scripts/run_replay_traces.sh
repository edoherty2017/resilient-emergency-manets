#!/bin/bash
# Replay-trace generator for the interactive viewer (Python twin engine).
# Full-capture traces (rx_trace_sample=1.0 — every tx/rx/col/wake event of
# every packet) over the 5-day early-December window (weather days 152-156,
# 2025-11-30..12-04: the insolation-weighted darkest stretch of the pinned
# year — two snowstorms into solstice-short days). The sim starts Nov 16
# (--start-day 138) and runs 14 warmup days so every arm enters the window
# in its true weather-accumulated battery state; only the window is traced
# (--trace-after-days 14). Canonical release_v1 frozen inputs, seed 42,
# --sos-retry. MODEL-ONLY.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
REL=artifacts/sim/corrected/release_v1
OUT=artifacts/sim/replay
mkdir -p "$OUT"
COMMON=(--topology "$REL/topology_statewide.json"
        --routes "$REL/routes_statewide.json"
        --weather "$REL/weather_year.json"
        --config "$REL/wmnf_sim.yaml"
        --days 19 --seed 42 --sos-retry
        --start-day 138 --trace-after-days 14
        --rx-trace-sample 1.0 --hiker-trace-sample 1.0
        --bat-trace-s 600 --pos-trace-s 120)
run() { local name=$1; shift
  [ -s "$OUT/${name}_summary.json" ] && { echo "skip $name"; return; }
  echo "start $name ..."
  $PY scripts/mesh_sim.py "${COMMON[@]}" \
      --trace "$OUT/${name}_trace.jsonl" --out "$OUT/${name}_summary.json" \
      "$@" >/dev/null
  echo "done $name"
}
par() { while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 15; done; }
run flood          --mode flood          & par
run energy_aware   --mode energy_aware   & par
run ea_rak2ma      --mode energy_aware --relay-rx-ma 2 & par
run duty_sync      --mode duty_sync      & par
run selective_duty --mode selective_duty & par
run rotate_lb      --mode rotate_lb      & par
run wur_d40        --mode wur --wur-delta-db 40 & par
run wur_d0         --mode wur --wur-delta-db 0  & par
wait
echo REPLAY_TRACES_COMPLETE

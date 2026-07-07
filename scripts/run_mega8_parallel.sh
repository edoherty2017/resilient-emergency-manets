#!/bin/bash
# Parallel remainder of mega8: 8 year runs concurrently (rotate_lb already live),
# then THE_YEAR.html + comparison when all summaries exist.
cd "$(dirname "$0")/.." || exit 1
SIM="artifacts/sim"
COMMON="--topology $SIM/topology_statewide.json --routes $SIM/routes_statewide.json \
 --days 365 --weather $SIM/weather_year.json --seed 42 --kiosk-pool \
 --telemetry-interval-s 3600 --beacon-interval-s 900 --energy-step-s 600 \
 --route-refresh-s 3600 --bat-trace-s 21600 --pos-trace-s 3600"

PIDS=()
for SPEC in duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  MODE=$SPEC
  [ "$SPEC" = "lb_energy_r" ] && MODE=lb_energy
  RPR=2; RX=0.003; RETRY="--sos-retry"
  [ "$SPEC" = "flood" ] && { RPR=1; RX=0.002; }
  [ "$SPEC" = "lb_energy" ] && RETRY=""
  # shellcheck disable=SC2086
  .venv/bin/python scripts/mesh_sim.py $COMMON $RETRY --mode "$MODE" \
    --renters-per-route $RPR --rx-trace-sample $RX \
    --trace "$SIM/kiosk_trace_$SPEC.jsonl" \
    --out "$SIM/kiosk_summary_$SPEC.json" \
    > "$SIM/kiosk_year_$SPEC.log" 2>&1 &
  PIDS+=($!)
  echo "launched $SPEC pid ${PIDS[-1]}"
done

# wait for the whole fleet (plus rotate_lb from the sequential run)
wait
while pgrep -f "mesh_sim.py.*rotate_lb" > /dev/null; do sleep 60; done

for SPEC in rotate_lb duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  [ -f "$SIM/kiosk_summary_$SPEC.json" ] \
    && cp "$SIM/kiosk_summary_$SPEC.json" "$SIM/algo_year/summary_$SPEC.json" \
    && echo "SUMMARY-$SPEC"
done

ARGS=""
for M in flood min_hop etx energy_aware lb_energy lb_energy_r duty_sync duty_adaptive rotate_lb; do
  [ -f "$SIM/kiosk_summary_$M.json" ] && ARGS="$ARGS --run $M"
done
# shellcheck disable=SC2086
.venv/bin/python scripts/render_year_arena.py --prefix "$SIM/kiosk_" $ARGS \
  --out "$SIM/THE_YEAR.html" \
  --title "THE YEAR — nine algorithms, kiosk rentals, real 2025-26 weather" \
  > "$SIM/the_year_render.log" 2>&1 && echo "THE_YEAR-RENDERED"
.venv/bin/python scripts/build_algo_comparison.py > "$SIM/algo_year/comparison.log" 2>&1 \
  && echo "MEGA8P-ALL-OK"

#!/bin/bash
# mega8: the definitive nine-algorithm kiosk-pool YEAR suite → THE_YEAR.html
# All runs: identical topology/routes/weather/seed, kiosk rental pools with
# best-charge checkout, SOS ACK+retry, traces written (via symlinks) to Kelp.
cd "$(dirname "$0")/.." || exit 1
SIM="artifacts/sim"
COMMON="--topology $SIM/topology_statewide.json --routes $SIM/routes_statewide.json \
 --days 365 --weather $SIM/weather_year.json --seed 42 --kiosk-pool \
 --telemetry-interval-s 3600 --beacon-interval-s 900 --energy-step-s 600 \
 --route-refresh-s 3600 --bat-trace-s 21600 --pos-trace-s 3600"

render_the_year() {
  ARGS=""
  for M in flood min_hop etx energy_aware lb_energy lb_energy_r duty_sync duty_adaptive rotate_lb; do
    [ -f "$SIM/kiosk_summary_$M.json" ] && ARGS="$ARGS --run $M"
  done
  # shellcheck disable=SC2086
  .venv/bin/python scripts/render_year_arena.py --prefix "$SIM/kiosk_" $ARGS \
    --out "$SIM/THE_YEAR.html" \
    --title "THE YEAR — nine algorithms, kiosk rentals, real 2025-26 weather" \
    > "$SIM/the_year_render.log" 2>&1 && echo "THE_YEAR-UPDATED"
}

for SPEC in rotate_lb duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  MODE=$SPEC
  [ "$SPEC" = "lb_energy_r" ] && MODE=lb_energy
  RPR=2; RX=0.003; RETRY="--sos-retry"
  if [ "$SPEC" = "flood" ]; then RPR=1; RX=0.002; fi
  # plain lb_energy is the no-retry ablation; lb_energy_r isolates the
  # ACK+retry contribution on the identical algorithm
  [ "$SPEC" = "lb_energy" ] && RETRY=
  echo "=== $SPEC (mode=$MODE) $(date '+%H:%M') ==="
  # shellcheck disable=SC2086
  .venv/bin/python scripts/mesh_sim.py $COMMON $RETRY --mode "$MODE" \
    --renters-per-route $RPR --rx-trace-sample $RX \
    --trace "$SIM/kiosk_trace_$SPEC.jsonl" \
    --out "$SIM/kiosk_summary_$SPEC.json" \
    > "$SIM/kiosk_year_$SPEC.log" 2>&1 || { echo "FAILED-$SPEC"; continue; }
  cp "$SIM/kiosk_summary_$SPEC.json" "$SIM/algo_year/summary_$SPEC.json"
  echo "YEAR-DONE-$SPEC"
  render_the_year
done
.venv/bin/python scripts/build_algo_comparison.py > "$SIM/algo_year/comparison.log" 2>&1 \
  && echo "MEGA8-ALL-OK"

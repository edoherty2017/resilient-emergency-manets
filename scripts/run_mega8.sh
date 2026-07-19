#!/bin/bash
# mega8: nine-run kiosk-pool YEAR suite → THE_YEAR.html
# All comparison arms use identical topology/routes/weather/seed/demand.
# `lb_energy` is the explicitly labelled no-retry ablation; the other runs use
# SOS ACK+retry. Traces are written alongside their summaries.
cd "$(dirname "$0")/.." || exit 1
SIM="artifacts/sim"
ARCHIVE="$SIM/archive/pre_mega8_$(date -u '+%Y%m%dT%H%M%SZ')"
mkdir -p "$ARCHIVE" "$SIM/algo_year"
# Preserve prior outputs, but move them out of the active filenames so a
# failed arm can never be mistaken for a result from this invocation.
for OLD in "$SIM"/kiosk_summary_*.json "$SIM"/kiosk_trace_*.jsonl \
  "$SIM"/kiosk_year_*.log "$SIM"/run_manifest_*.json \
  "$SIM"/run_manifest_*.log "$SIM"/algo_year/summary_*.json \
  "$SIM"/algo_year/algo_comparison.* "$SIM"/THE_YEAR.html; do
  [ -e "$OLD" ] || continue
  mv "$OLD" "$ARCHIVE/"
done
COMMON="--topology $SIM/topology_statewide.json --routes $SIM/routes_statewide.json \
 --days 365 --weather $SIM/weather_year.json --seed 42 --kiosk-pool \
 --telemetry-interval-s 3600 --beacon-interval-s 900 --energy-step-s 600 \
 --route-refresh-s 3600 --bat-trace-s 21600 --pos-trace-s 3600"
FAILED=0

render_the_year() {
  ARGS=""
  for M in flood min_hop etx energy_aware lb_energy lb_energy_r duty_sync duty_adaptive rotate_lb; do
    [ -f "$SIM/kiosk_summary_$M.json" ] && ARGS="$ARGS --run $M"
  done
  # shellcheck disable=SC2086
  .venv/bin/python scripts/render_year_arena.py --prefix "$SIM/kiosk_" $ARGS \
    --out "$SIM/THE_YEAR.html" \
    --title "THE YEAR — nine algorithms, kiosk rentals, pinned ERA5 reanalysis" \
    > "$SIM/the_year_render.log" 2>&1 && echo "THE_YEAR-UPDATED"
}

for SPEC in rotate_lb duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  MODE=$SPEC
  [ "$SPEC" = "lb_energy_r" ] && MODE=lb_energy
  # Experimental arms must see the same rental demand and trace sampling.
  # Trace sampling has its own RNG stream, but keeping it identical also makes
  # artifact volume and observability directly comparable.
  RPR=2; RX=0.003; RETRY="--sos-retry"
  # plain lb_energy is the no-retry ablation; lb_energy_r isolates the
  # ACK+retry contribution on the identical algorithm
  [ "$SPEC" = "lb_energy" ] && RETRY=
  echo "=== $SPEC (mode=$MODE) $(date '+%H:%M') ==="
  # shellcheck disable=SC2086
  .venv/bin/python scripts/mesh_sim.py $COMMON $RETRY --mode "$MODE" \
    --renters-per-route $RPR --rx-trace-sample $RX \
    --trace "$SIM/kiosk_trace_$SPEC.jsonl" \
    --out "$SIM/kiosk_summary_$SPEC.json" \
    > "$SIM/kiosk_year_$SPEC.log" 2>&1 \
    || { echo "FAILED-$SPEC"; FAILED=1; continue; }
  RETRY_VALUE=true
  [ -z "$RETRY" ] && RETRY_VALUE=false
  .venv/bin/python scripts/sim_run_manifest.py \
    --out "$SIM/run_manifest_$SPEC.json" --engine python \
    --mode "$MODE" --days 365 --seed 42 \
    --input "topology=$SIM/topology_statewide.json" \
    --input "routes=$SIM/routes_statewide.json" \
    --input "weather=$SIM/weather_year.json" \
    --input "config=config/sim/wmnf_sim.yaml" \
    --input "simulator=scripts/mesh_sim.py" \
    --input "environment=requirements.txt" \
    --result "$SIM/kiosk_summary_$SPEC.json" \
    --arg "experiment_arm=$SPEC" --arg "renters_per_route=$RPR" \
    --arg "rx_trace_sample=$RX" --arg "sos_retry=$RETRY_VALUE" \
    --command ".venv/bin/python scripts/mesh_sim.py $COMMON $RETRY --mode $MODE --renters-per-route $RPR --rx-trace-sample $RX --trace $SIM/kiosk_trace_$SPEC.jsonl --out $SIM/kiosk_summary_$SPEC.json" \
    > "$SIM/run_manifest_$SPEC.log" 2>&1 \
    || { echo "FAILED-MANIFEST-$SPEC"; FAILED=1; continue; }
  cp "$SIM/kiosk_summary_$SPEC.json" "$SIM/algo_year/summary_$SPEC.json"
  echo "YEAR-DONE-$SPEC"
  render_the_year || FAILED=1
done
if .venv/bin/python scripts/build_algo_comparison.py \
  > "$SIM/algo_year/comparison.log" 2>&1; then
  echo "MEGA8-ALL-OK"
else
  echo "MEGA8-COMPARISON-FAILED" >&2
  FAILED=1
fi
exit "$FAILED"

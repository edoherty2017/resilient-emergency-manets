#!/bin/bash
# Parallel mega8: all nine corrected arms run in this invocation, then render
# only the summaries they actually produced. All comparison arms use identical
# demand; `lb_energy` is the explicitly labelled no-retry ablation.
cd "$(dirname "$0")/.." || exit 1
SIM="artifacts/sim"
ARCHIVE="$SIM/archive/pre_mega8_parallel_$(date -u '+%Y%m%dT%H%M%SZ')"
mkdir -p "$ARCHIVE"
# Preserve prior outputs outside the active filenames. A failed arm then has
# no stale summary that can be silently included in the new comparison.
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

PIDS=()
SPECS=()
for SPEC in rotate_lb duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  MODE=$SPEC
  [ "$SPEC" = "lb_energy_r" ] && MODE=lb_energy
  # Every algorithm arm receives the same demand and trace-sampling settings.
  RPR=2; RX=0.003; RETRY="--sos-retry"
  [ "$SPEC" = "lb_energy" ] && RETRY=""
  # shellcheck disable=SC2086
  .venv/bin/python scripts/mesh_sim.py $COMMON $RETRY --mode "$MODE" \
    --renters-per-route $RPR --rx-trace-sample $RX \
    --trace "$SIM/kiosk_trace_$SPEC.jsonl" \
    --out "$SIM/kiosk_summary_$SPEC.json" \
    > "$SIM/kiosk_year_$SPEC.log" 2>&1 &
  PID=$!
  PIDS+=("$PID")
  SPECS+=("$SPEC")
  echo "launched $SPEC pid $PID"
done

# Record each arm's status rather than allowing a failed background process to
# disappear inside a blanket `wait`.
FAILED=0
for INDEX in "${!PIDS[@]}"; do
  if wait "${PIDS[$INDEX]}"; then
    echo "RUN-DONE-${SPECS[$INDEX]}"
  else
    echo "RUN-FAILED-${SPECS[$INDEX]}" >&2
    FAILED=1
  fi
done

for SPEC in rotate_lb duty_adaptive duty_sync lb_energy_r lb_energy energy_aware etx min_hop flood; do
  [ -f "$SIM/kiosk_summary_$SPEC.json" ] || continue
  MODE=$SPEC
  [ "$SPEC" = "lb_energy_r" ] && MODE=lb_energy
  RETRY_VALUE=true
  [ "$SPEC" = "lb_energy" ] && RETRY_VALUE=false
  cp "$SIM/kiosk_summary_$SPEC.json" "$SIM/algo_year/summary_$SPEC.json"
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
    --arg "experiment_arm=$SPEC" --arg "renters_per_route=2" \
    --arg "rx_trace_sample=0.003" --arg "sos_retry=$RETRY_VALUE" \
    --command "scripts/run_mega8_parallel.sh arm=$SPEC" \
    > "$SIM/run_manifest_$SPEC.log" 2>&1 \
    || { echo "FAILED-MANIFEST-$SPEC"; FAILED=1; continue; }
  echo "SUMMARY-$SPEC"
done

ARGS=""
for M in flood min_hop etx energy_aware lb_energy lb_energy_r duty_sync duty_adaptive rotate_lb; do
  [ -f "$SIM/kiosk_summary_$M.json" ] && ARGS="$ARGS --run $M"
done
# shellcheck disable=SC2086
if .venv/bin/python scripts/render_year_arena.py --prefix "$SIM/kiosk_" $ARGS \
  --out "$SIM/THE_YEAR.html" \
  --title "THE YEAR — nine algorithms, kiosk rentals, pinned ERA5 reanalysis" \
  > "$SIM/the_year_render.log" 2>&1; then
  echo "THE_YEAR-RENDERED"
else
  echo "THE_YEAR-RENDER-FAILED" >&2
  FAILED=1
fi
if .venv/bin/python scripts/build_algo_comparison.py \
  > "$SIM/algo_year/comparison.log" 2>&1; then
  echo "MEGA8P-ALL-OK"
else
  echo "MEGA8P-COMPARISON-FAILED" >&2
  FAILED=1
fi
exit "$FAILED"

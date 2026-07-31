#!/bin/bash
# Climate-robustness re-earn: duty advantage across 10 pinned ERA5 weather years.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=fastsim/target/release/fastsim
REL=artifacts/sim/corrected/release_v1
OUT=artifacts/sim/weather_decade
run() { local name=$1 wy=$2; shift 2
  [ -s "$OUT/$name.json" ] && { echo "skip $name"; return; }
  "$BIN" --topology "$REL/topology_statewide.json" --routes "$REL/routes_statewide.json" \
    --weather "$OUT/weather_${wy}.json" --config "$REL/wmnf_sim.yaml" --days 365 --seed 42 --sos-retry \
    --out "$OUT/$name.json" "$@" >/dev/null && echo "done $name"
}
for Y in 2016 2017 2018 2019 2020 2021 2022 2023 2024 2025; do
  [ -s "$OUT/weather_${Y}.json" ] || { echo "MISSING weather_${Y}"; continue; }
  run "duty_${Y}" "$Y" --mode duty_sync &
  run "ea_${Y}"   "$Y" --mode energy_aware &
  while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 5; done
done
wait
python3 - <<'PYEOF'
import json,glob,hashlib,os
d='artifacts/sim/weather_decade'; sha=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
json.dump({'purpose':'climate-robustness re-earn: duty vs always-on across 10 pinned ERA5 years',
 'runs':{os.path.basename(p):sha(p) for p in sorted(glob.glob(d+'/*.json'))}},
 open(d+'/manifest.json','w'),indent=1); print('manifest written')
PYEOF
echo DECADE_RUNS_DONE

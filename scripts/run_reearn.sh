#!/bin/bash
# Re-earn campaign: withdrawn-but-cheap claims re-run on the corrected engine.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=fastsim/target/release/fastsim
REL=artifacts/sim/corrected/release_v1
OUT=artifacts/sim/reearn
mkdir -p "$OUT"
COMMON=(--topology "$REL/topology_statewide.json" --routes "$REL/routes_statewide.json"
        --weather "$REL/weather_year.json" --config "$REL/wmnf_sim.yaml" --days 365)
run() { local name=$1; shift
  [ -s "$OUT/$name.json" ] && { echo "skip $name"; return; }
  "$BIN" "${COMMON[@]}" --out "$OUT/$name.json" "$@" >/dev/null && echo "done $name"
}
par() { while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 5; done; }
for S in 42 43 44; do
  # 1. SOS-retry ablation (rotate_lb with vs without)
  run "retry_on_s${S}"  --mode rotate_lb --seed "$S" --sos-retry & par
  run "retry_off_s${S}" --mode rotate_lb --seed "$S" & par
  # 2. regional channels (duty_sync on/off)
  run "regional_on_s${S}"  --mode duty_sync --seed "$S" --sos-retry --regional-channels & par
  run "regional_off_s${S}" --mode duty_sync --seed "$S" --sos-retry & par
  # 3. kiosk zero spares
  run "spares0_s${S}" --mode rotate_lb --seed "$S" --sos-retry --kiosk-spares 0 & par
  # 4. peak demand 4x (renters-per-route 8)
  run "peak_duty_s${S}"  --mode duty_sync --seed "$S" --sos-retry --renters-per-route 8 & par
  run "peak_flood_s${S}" --mode flood     --seed "$S" --sos-retry --renters-per-route 8 & par
  # 5. gateway redundancy: mid-winter 30-day outage of the summit gateway
  run "gwout_s${S}" --mode rotate_lb --seed "$S" --sos-retry --outage summit_shermanadams:180:210 & par
done
wait
python3 - <<'PYEOF'
import json,glob,hashlib,subprocess,os
d='artifacts/sim/reearn'; sha=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
m={'purpose':'re-earn campaign: withdrawn-but-cheap claims re-run on corrected engine (2026-07-31)',
'engine_git_head':subprocess.run(['git','rev-parse','--short','HEAD'],capture_output=True,text=True).stdout.strip(),
'runs':{os.path.basename(p):sha(p) for p in sorted(glob.glob(d+'/*.json')) if 'manifest' not in p}}
json.dump(m,open(d+'/manifest.json','w'),indent=1); print('manifest:',len(m['runs']))
PYEOF
echo REEARN_COMPLETE

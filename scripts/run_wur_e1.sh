#!/bin/bash
# WuR study E1/E2 runner (docs/wur-design-2026-07-31.md v2 §4).
# Dedicated runner — fails loudly on any error; does NOT extend the
# release-era scripts' hardcoded mode lists.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=fastsim/target/release/fastsim
REL=artifacts/sim/corrected/release_v1
OUT=artifacts/sim/wur_study
mkdir -p "$OUT"
COMMON=(--topology "$REL/topology_statewide.json" --routes "$REL/routes_statewide.json"
        --weather "$REL/weather_year.json" --config "$REL/wmnf_sim.yaml"
        --days 365 --sos-retry)
run() { local name=$1; shift
  [ -s "$OUT/$name.json" ] && { echo "skip $name"; return; }
  "$BIN" "${COMMON[@]}" --out "$OUT/$name.json" "$@" >/dev/null
  echo "done $name"
}
SEEDS="42 43 44 45 46"
# E1: wur delta sweep, both routing arms
for D in 0 40 50 60 70 80; do for S in $SEEDS; do
  run "wur_d${D}_blind_s${S}"    --mode wur --seed "$S" --wur-delta-db "$D" &
  run "wur_d${D}_informed_s${S}" --mode wur --seed "$S" --wur-delta-db "$D" --wur-informed-tree &
  while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 5; done
done; done
wait
# E1 comparison rows (current engine, same seeds)
for S in $SEEDS; do
  run "cmp_ea68_s${S}"  --mode energy_aware   --seed "$S" &
  run "cmp_ea2_s${S}"   --mode energy_aware   --seed "$S" --relay-rx-ma 2 &
  run "cmp_dsync_s${S}" --mode duty_sync      --seed "$S" &
  run "cmp_rlb_s${S}"   --mode rotate_lb      --seed "$S" &
  run "cmp_sduty_s${S}" --mode selective_duty --seed "$S" &
  while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 5; done
done
wait
# E2: boot-latency sensitivity at delta 55
for B in 50 100 200; do for S in 42 43 44; do
  run "wur_e2_boot${B}_s${S}" --mode wur --seed "$S" --wur-delta-db 55 --wur-boot-ms "$B" &
  while [ "$(jobs -r | wc -l)" -ge 4 ]; do sleep 5; done
done; done
wait
# manifest
python3 - <<'PYEOF'
import json, glob, hashlib, subprocess, os
d='artifacts/sim/wur_study'
sha=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()
m={'purpose':'WuR study E1/E2 (spec v2 pre-registered); MODEL-ONLY; current engine',
   'engine_git_head':subprocess.run(['git','rev-parse','--short','HEAD'],capture_output=True,text=True).stdout.strip(),
   'engine_binary_sha256':sha('fastsim/target/release/fastsim'),
   'inputs':'release_v1 frozen copies','spec':'docs/wur-design-2026-07-31.md',
   'runs':{os.path.basename(p):sha(p) for p in sorted(glob.glob(d+'/*.json')) if 'manifest' not in p}}
json.dump(m,open(d+'/manifest.json','w'),indent=1)
print('manifest:',len(m['runs']),'runs')
PYEOF
echo E1_E2_COMPLETE

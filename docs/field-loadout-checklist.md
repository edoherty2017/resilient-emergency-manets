# Field Loadout Checklist (T4)

## Roles
- **Role A — HEAD Carrier**: carries MeshRadioHead stack, verifies ingest continuity.
- **Role B — Hiker Node Carrier**: carries MeshHikerNode1 stack, executes route waypoints.
- **Role C — Safety/Observer (optional)**: weather watch, timestamped incident notes, backup power reserve.

## Required per-person carry

### Role A — HEAD Carrier
- Raspberry Pi host + Heltec node + known-good USB data/power cable
- Primary power bank (>=20,000 mAh) + short spare cable
- Secondary backup bank (>=10,000 mAh)
- Waterproof pouch for electronics
- Printed quick-check card:
  - `ssh meshradiohead`
  - `ls -l /dev/lora_radio`
  - `tail -n 5 /home/pump/telemetry_head/jsonl/telemetry_stream.jsonl`

### Role B — Hiker Node Carrier
- Hiker Pi/node assembly + known-good cable
- Primary power bank (>=20,000 mAh)
- Spare battery-compatible lead + one spare USB-C cable
- Weatherproof bag + tether/retention strap
- Printed quick-check card:
  - `ssh meshhikernode1`
  - `ls -l /dev/lora_radio`
  - `tail -n 5 /home/pump/telemetry/jsonl/telemetry_stream.jsonl`

### Role C — Safety/Observer
- Route map + weather snapshot + no-go thresholds
- UTC-synced phone for incident timestamps
- Reserve power bank + emergency charging cable set
- Paper log for anomaly tags (weather, terrain shadowing, line-of-sight breaks)

## Pre-hike go/no-go gates
- Buddy system confirmed
- Weather no-go check passed
- Both nodes reachable via SSH
- `/dev/lora_radio` present on both nodes
- JSONL files growing on both nodes in last 2 minutes
- Backup endpoint reachable (`root@100.101.35.58`)

## In-field checkpoints
- Every major segment transition: confirm JSONL growth on both nodes
- If power flap detected (`usbPower` transitions / repeated power-loss logs): swap cable first, then bank
- Tag anomalies immediately with UTC timestamp

## End-of-run checklist
- Confirm both JSONL files closed cleanly
- Trigger storage guard manually once
- Archive run metadata: route ID, weather tag, team roles, anomalies

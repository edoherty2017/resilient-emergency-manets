# Field Loadout Checklist (T4)

## Roles
- **Role A — HEAD Carrier**: carries MeshRadioHead stack, verifies ingest continuity.
- **Role B — Hiker Node Carrier**: carries MeshHikerNode1 stack, executes route waypoints.
- **Role C — Safety/Observer (optional)**: weather watch, timestamped incident notes, backup power reserve.

## Required per-person carry

### Role A — HEAD Carrier
- Raspberry Pi host + Heltec node + known-good USB data/power cable
- **Starlink Mini kit** (dish/router + power lead + mount/orientation card)
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
- Starlink Mini link on meshhead validated (WAN up + Tailscale endpoint reachable)

## Live trial connectivity tiers (required planning assumption)
1. **Tier 1 — Full IP control plane (preferred):**
   - Starlink Mini online in the same pack as `meshhead`
   - Hermes reaches `meshradiohead` over Tailscale SSH
2. **Tier 2 — Proximal node reachability (opportunistic):**
   - Nearby hiker nodes may be reachable via Starlink-backed meshhead path while in RF/IP range
3. **Tier 3 — Degraded control plane (expected out of range):**
   - When remote nodes lose Starlink/IP path, direct SSH may drop
   - Continue data-plane collection over Meshtastic
   - Use Meshtastic messages as low-bandwidth command/telemetry fallback and mark all fallback windows in logs

## Meshtastic fallback checklist (when SSH drops)
- Record `CONTROL_PLANE_DOWN_START` timestamp
- Confirm meshhead still reachable and logging
- Send low-rate Meshtastic heartbeat/check command to remote node(s)
- Log ACK/no-ACK and rough latency class
- Avoid high-frequency command bursts (preserve airtime)
- Record `CONTROL_PLANE_DOWN_END` when SSH/Tailscale path returns

## In-field checkpoints
- Every major segment transition: confirm JSONL growth on both nodes
- If power flap detected (`usbPower` transitions / repeated power-loss logs): swap cable first, then bank
- Tag anomalies immediately with UTC timestamp

## End-of-run checklist
- Confirm both JSONL files closed cleanly
- Trigger storage guard manually once
- Archive run metadata: route ID, weather tag, team roles, anomalies

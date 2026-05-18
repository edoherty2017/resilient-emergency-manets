# Starlink Mini Connectivity Plan — 2026-05-17

## Decision
- Adopt **Starlink Mini** as the primary live-trial IP backhaul for `meshhead`.
- Replace prior assumption of using a dongle-only satellite path for live operations.

## Operational intent
- Keep Hermes connected to `meshradiohead` over Tailscale SSH during live trials.
- Treat `meshhikernode*` SSH reachability as opportunistic (available only while in RF/IP range of head backhaul).
- Preserve data collection even when remote-node SSH drops by using Meshtastic as degraded fallback.

## Connectivity model (for trial analysis)
1. `IP_FULL`
   - Starlink link up at meshhead
   - Hermes can SSH to `meshradiohead`
   - Some/near hiker nodes may also be reachable
2. `IP_DEGRADED`
   - Intermittent SSH reachability to head and/or nearby nodes
3. `MESH_ONLY`
   - No direct SSH to remote nodes; only Meshtastic command/heartbeat fallback

## Required logging tags
- `CONTROL_PLANE_DOWN_START`
- `CONTROL_PLANE_DOWN_END`
- `MODE_IP_FULL`
- `MODE_IP_DEGRADED`
- `MODE_MESH_ONLY`

## Immediate pre-trial checks
- Confirm Starlink Mini WAN up from meshhead pack location.
- Confirm `ssh meshradiohead` works from doher/Hermes side.
- Confirm head/hiker collectors are active and JSONL files are growing.
- Confirm stale watchdog + SSH matrix watchdog jobs are running.

## Connectivity options to explore (Meshtastic fallback)
1. **Low-rate command channel over Meshtastic**
   - heartbeat pings, status request/ACK, mode transitions
2. **Store-and-forward command queue**
   - queue intended commands while out-of-IP-range; apply on reconnection
3. **Head-mediated relay behavior**
   - test whether head can relay limited control/status for out-of-range nodes
4. **Control-message schema**
   - standardize minimal command payloads (`cmd_id`, `target`, `ttl`, `ack_required`, `issued_at_utc`)
5. **Fallback performance envelope**
   - measure message success, median ACK latency, and failure rate by terrain segment

## Success criteria for this planning change
- Documentation reflects Starlink Mini as primary live backhaul.
- Trial logs cleanly separate RF mesh degradation from IP backhaul outages.
- At least one live run records transitions across `IP_FULL`/`IP_DEGRADED`/`MESH_ONLY` with usable evidence.

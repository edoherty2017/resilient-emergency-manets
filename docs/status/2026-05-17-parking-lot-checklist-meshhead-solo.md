# Parking Lot Checklist (Solo) — meshhead / meshhikernode

Date: 2026-05-17  
Route: Tom–Field–Willey–Avalon Loop (~9.4 mi)  
Operator: Solo

This is the **quick-use live checklist** to run at the trailhead before you step off.

---

## Device Naming (use exactly)

- **meshhead** = anchor/head node (trailhead anchor for this run)
- **meshhikernode** = your moving node (on your body/pack)

If you only run one node, run `meshhikernode` and mark all anchor tests as N/A.

---

## What must be running before hike starts

## A) meshhead (anchor) runtime
Required state:
1. meshhead is powered and booted
2. radio interface up
3. ingest/logging process running
4. log file writable
5. message receive + transmit confirmed

Minimum verification (pass/fail):
- [ ] meshhead boots without restart loop
- [ ] meshhead shows live timestamp updates in log output
- [ ] meshhead receives at least 1 test message from meshhikernode
- [ ] meshhead successfully sends at least 1 message back

## B) meshhikernode (mobile) runtime
Required state:
1. meshhikernode powered and mounted high/stable
2. radio interface up
3. local telemetry/logging active (if available on node)
4. battery level recorded

Minimum verification (pass/fail):
- [ ] meshhikernode boots cleanly
- [ ] meshhikernode sends 3-message test burst
- [ ] at least 2/3 test messages acknowledged by meshhead

## C) Logging and time sync
- [ ] phone clock and node clocks are in sync (close enough for segment analysis)
- [ ] field log note is open and ready
- [ ] GPS capture working

---

## 5-minute pre-launch test sequence (exact order)

1. Start **meshhead** first.
2. Confirm meshhead logs are writing.
3. Start **meshhikernode**.
4. Send `Burst #0` (3 messages from meshhikernode -> meshhead).
5. Send `Burst #1` (3 messages from meshhead -> meshhikernode).
6. Record baseline:
   - time
   - GPS
   - battery meshhead / meshhikernode
   - success count each direction
   - latency class (fast/moderate/slow)
7. If all pass, start hike.

If fail: do one short troubleshooting cycle (max 10 min), then downgrade to manual observational hike.

---

## On-trail cadence

At every 15 minutes **and** at each terrain transition:
- Send 5-message burst (meshhikernode -> meshhead)
- Record recv count and latency class
- Log terrain tag:
  - exposed ridge
  - forested slope
  - notch/gully
  - summit shoulder

Recommended log line format:

```text
time | gps | segment | terrain | pair | sent | recv | latency | batt_head/hiker | notes
```

---

## Mid-hike power-source swap procedure (battery A -> battery B)

Use this exact procedure to avoid corrupted logs and ambiguous outage data.

## 1) Before unplugging (T-30 seconds)
- [ ] Stop moving if terrain allows safe pause
- [ ] Record pre-swap log line: `POWER_SWAP_START`
- [ ] Record current battery levels and timestamp
- [ ] Send one quick 3-message burst and record result

## 2) Swap operation (target under 60 seconds)
- [ ] Disconnect old battery
- [ ] Connect new battery
- [ ] Confirm device power LED/activity
- [ ] Confirm cable strain relief and waterproofing restored

## 3) Recovery verification (immediately after)
- [ ] Record `POWER_SWAP_END` timestamp
- [ ] Wait for node/app to rejoin (if needed)
- [ ] Send 3-message verification burst
- [ ] Record whether post-swap behavior matches pre-swap baseline

## 4) If node does not recover within 3 minutes
- [ ] Execute one reboot attempt
- [ ] Record `RECOVERY_REBOOT_ATTEMPT`
- [ ] If still down: continue as degraded run + document outage window exactly

Important: always mark swap windows so later analysis does not mistake power interruption for terrain shadow.

---

## Hard rules (solo)

- Turnaround time is non-negotiable.
- No off-trail detours for comm testing.
- If weather degrades, abort and preserve collected data.
- Safety beats data collection.

---

## End-of-run closeout (trailhead)

- [ ] Final 5-message burst
- [ ] Record end battery meshhead / meshhikernode
- [ ] Confirm logs saved/exported
- [ ] Write 5-line debrief:
  1. first weak zone
  2. first failure zone
  3. strongest zone
  4. swap impact (if any)
  5. top blocker for run #2

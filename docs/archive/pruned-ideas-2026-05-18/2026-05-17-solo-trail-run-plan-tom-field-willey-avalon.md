# Solo Trail Run Plan — Tom–Field–Willey–Avalon Loop (~9.4 mi)

Date: 2026-05-17
Owner: doher
Scope: One-day solo field validation run in the White Mountains (7–11 mile target met)

## Mission Objective

Validate terrain-shadow hypothesis for MANET field comms:

> Terrain transitions on Tom–Field–Willey–Avalon create predictable RF shadow segments that reduce link reliability and increase latency.

Primary success criterion: return with a complete, timestamped field log that maps degradation/failure zones to terrain context.

---

## Route Selection

**Selected route:** Mount Tom – Mount Field – Mount Willey – Mount Avalon Loop  
**Target distance:** ~9.4 miles  
**Route class:** Day hike loop, high data value due to mixed exposure/terrain transitions.

---

## Solo Loadout (Exact)

### A) Core comms kit
- Node A (mobile node) + antenna
- Node C (optional trailhead anchor node)
- 2x power banks minimum
- 3x cables (1 active + 2 spare)
- Waterproof pouch / dry bag
- Tape/strap/zip ties (cable strain relief)

### B) Logging kit
- Phone with offline map loaded for selected route
- Pre-created field log template (phone note)
- Paper backup + pencil
- Battery tracker entries at: start / midpoint / end

### C) Safety kit
- Headlamp
- Insulation layer + shell
- Water + calories for full day + reserve
- First aid + blister care
- Emergency comms (phone / inReach if available)
- Written hard-turnaround rule card

---

## Node Layout

- **Node A (mobile):** shoulder strap or upper chest, high/stable mount.
- **Node C (optional):** trailhead anchor only for run #1 (no remote unattended cache placement on first solo run).

If Node C is used: record exact GPS/time/photo of placement and retrieval.

---

## Day-of Procedure (Hard Sequence)

### Phase 1 — Trailhead Pre-Launch (must pass)
1. Record weather snapshot.
2. Record battery start: phone + Node A (+ Node C if used).
3. Boot Node A.
4. Boot Node C (if used).
5. Send baseline test burst (3 messages each direction where applicable).
6. Confirm logging is active and writable.
7. Start hike only if above steps pass.

Fallback if comm setup fails after one short troubleshooting pass: continue as manual observational run and capture failure details.

### Phase 2 — On-Trail Execution
Trigger a test cycle:
- Every 15 minutes, and
- At each terrain transition (ridge, notch/gully, dense forest, exposed slab)

Test cycle steps:
1. Record timestamp + GPS.
2. Send 5-message burst.
3. Record success count (0–5).
4. Record latency class: Fast / Moderate / Slow / Fail.
5. Record terrain tag: Exposed ridge / Forested slope / Notch-gully / Summit shoulder.

### Phase 3 — Turnaround and Abort Rules
- Hard turnaround cutoff is non-negotiable.
- Abort conditions:
  - Deteriorating weather/visibility
  - Equipment instability
  - Navigation uncertainty
  - Fatigue/injury risk

Mission priority is safe return with usable data, not forced loop completion.

### Phase 4 — Trailhead Closeout
1. Send final comm burst.
2. Record end battery values.
3. Save/export logs.
4. Write a 5-line debrief:
   - First weak zone
   - First fail zone
   - Strongest link zone
   - Unexpected behavior
   - Top blocker before run #2

---

## Field Log Template

```text
time | gps | segment | terrain | node pair | burst sent | burst recv | latency class | battery A/C | notes
```

Example:

```text
10:42 | 44.x,-71.x | between Field-Willey | notch-gully | A-C | 5 | 1 | slow/fail | 82/91 | deep tree cover, steep wall
```

---

## Hypothesis Validation Conditions

H1 (Terrain Shadowing) supported if repeated degradation/failure clusters in consistent terrain segment types.  
H2 (Mobility Reliability Baseline) supported if packet/latency stability degrades at expected occlusion transitions.  
H3 (Anchor Utility, if Node C used) supported if reacquisition and continuity improve on return corridor versus no-anchor behavior.

---

## Notes for Next Run Planning

Use this run to prioritize one of the following for upgrade weekend:
1. Power budget
2. Antenna/mounting
3. Logging workflow
4. Safety/operations cadence

Only purchase/add equipment tied directly to observed failure modes.

# System Architecture — Acquisition Platform

Companion to the directed-study deliverable "Technical Repository & Design Doc."
Describes the hardware, EMI isolation, power management, and data-flow design of
the MANET RF acquisition platform. Software pipeline internals live in the
top-level `CLAUDE.md`; this document covers the physical and systems-engineering
layer the proposal requires.

## 1. Overview

The platform measures LoRa mesh propagation and cross-technology connectivity in
extreme terrain. It is a three-tier system:

| Tier | Hardware | Role |
|---|---|---|
| HEAD node | Raspberry Pi 4 + Heltec LoRa32 V3 (SX1262, 915 MHz) + Starlink Mini + optional Verizon MiFi | Carried collector: logs all received mesh packets, Starlink service metrics, cellular availability |
| Hiker/beacon node | Heltec LoRa32 V3, battery + solar | Position-beaconing source node for controlled link measurements |
| Ground truth | Garmin GPS (external) | Independent position track, 1 Hz, not dependent on mesh GPS |

The HEAD node is the only device that must run reliably for hours in the field;
the architecture optimizes for *its* survivability and data integrity. All
modeling and analysis happen off-platform (operator Mac) — the field hardware does
capture and transport only.

## 2. HEAD node responsibilities

- **Meshtastic-native capture.** `telemetry_collector.py` subscribes to the
  Meshtastic Python API (not serial regex) and logs every received packet —
  including strangers — with `is_own_node`, `from_mesh_id`, `portnum`,
  `hop_limit`/`hop_start` (hop count is required to distinguish direct links from
  relays — the single most important field for valid calibration).
- **Append-only JSONL.** One JSON object per line; never rewritten. Parser
  integrity fields (`checksum_ok`/`checksum_bad`/`malformed_frame`) are emitted per
  line so corruption is observable, not silent.
- **Starlink service metrics.** gRPC poller + window aggregator log RTT, throughput,
  obstruction, and outage seconds — service-layer availability, the correct
  cross-technology metric.
- **Cellular availability (optional).** `cellular_ping_collector.py` pings through
  the MiFi every 30 s, null-safe on timeout, logging RTT + reachability.
- **Store-and-forward.** `telemetry_sync_spool.sh` rsyncs to the operator host
  every 2 min when IP is up; emits connectivity mode changes (`IP_FULL`,
  `IP_DEGRADED`, `MESH_ONLY`).

## 3. Hiker / beacon node responsibilities

For Trial 2 the second node is a **controlled beacon**: fixed broadcast cadence
with sequence numbers, surveyed position. This is what makes PDR measurable
(known denominator) and gives clean distance–signal pairs. It does capture/transport
only; it carries no analysis logic.

## 4. RF + telemetry pipeline

Capture (Pi) → append-only JSONL → rsync spool → operator Mac pipeline
(schema validation → AIRMap predict/calibrate → sentinel QA → error quantifier →
weather/coverage overlays → evidence index). See `CLAUDE.md` "Architecture: Data
Flow" for the full per-script contract. The ownership rule is strict: runtime
repos capture and move bytes; all modeling lives in `resilient-emergency-manets`.

## 5. EMI / power isolation

The proposal calls out EMI isolation and power management explicitly; both are
real risks for a Pi + LoRa + Starlink stack carried in a pack.

### 5.1 Electromagnetic interference

- **Antenna separation.** The 915 MHz LoRa whip and the Starlink phased array
  radiate in very different bands (915 MHz vs ~10–12 GHz Ku) so co-channel
  interference is not the concern; the concern is **broadband switching noise**
  from the Pi and the Starlink PoE injector desensitizing the LoRa front end.
  Mitigation: keep the LoRa antenna ≥0.5 m from the Pi and the Starlink router,
  and orient the whip vertically clear of the pack frame.
- **Conducted noise.** Shared USB power rails couple switching noise into the
  radio. Mitigation: power the Heltec from a separate battery bank or a filtered
  rail (ferrite bead on the USB lead); never power the radio off the same buck
  converter feeding the Starlink router under load.
- **Shielding / conformal coating.** Field hardening per the proposal Week 1–3
  plan: conformal-coat the Heltec PCB against condensation, and keep the SX1262
  module away from the Pi's Ethernet magnetics and camera-connector harness.
- **Grounding.** Single-point ground between Pi and radio; avoid ground loops
  through the Starlink PoE chassis.

### 5.2 Power management

- **Budget (HEAD).** Pi 4 idle ~2.7 W, under collection load ~4–5 W; Heltec RX-on
  ~0.4 W; Starlink Mini ~20–40 W (dominant). The LoRa collection chain alone runs
  many hours off a 10 Ah USB bank; Starlink is the power sink and is duty-cycled
  to scheduled uplink windows rather than left on.
- **Brownout protection.** The Pi must not brown out mid-write (corrupts JSONL).
  Mitigations: a battery bank that passes through while charging (no switchover
  gap), and append-only writes with per-line flush so an abrupt loss truncates at
  most one line.
- **Beacon node.** Static beacons run RX/TX only with GPS disabled (position is
  surveyed once), cutting ~30 mA; a 10 Ah bank + small solar sustains a multi-day
  leave-behind (see `docs/brenta-trial-plan.md`).
- **Thermal.** Cold (−10 to −30 °C alpine) derates lithium capacity sharply;
  the power budget assumes ~70% of rated Wh and keeps banks against the body in
  winter conditions.

## 6. Failure modes and mitigations

| Failure | Observed / risk | Mitigation |
|---|---|---|
| Silent collector death | Trial 1: Meshtastic serial reconnect loop, 2h48m gap, no exception | `head_readiness_report.py` pre-departure gate; watchdog on JSONL write timestamp; periodic heartbeat line |
| GPS not paired before departure | Trial 1 Issue 2: no HEAD position in mesh | Pre-departure checklist verifies `lat`/`lon` updating in JSONL before leaving |
| No hop ground truth | Trial 1: could not separate direct vs relayed packets | Collector now logs `hop_limit`/`hop_start`; calibration gates on `hops_away == 0` |
| Adjacent-device contamination | Trial 1: co-located forwarder injected far-field packets with hot RSSI | Eligibility gate drops RSSI > −20 dBm and non-direct links; blacklist co-located IDs |
| Pi brownout corrupts data | Risk | Pass-through battery, per-line flush, append-only |
| EMI desense of LoRa front end | Risk | Antenna separation, filtered power rail, conformal coat |
| Lithium cold-derate | Alpine/winter | 70% capacity budget; body-warm storage; seasonal scoping |

## 7. Regulatory

- **US trials:** 915 MHz ISM, FCC Part 15. The compliance basis for Meshtastic's
  single-channel LoRa (vs §15.247 FHSS assumptions) is an open documentation item
  (review P4 item 19) and must be resolved before any fixed-infrastructure
  proposal to a state agency.
- **EU / Italy trials (Brenta):** US 915 MHz is illegal; nodes must run Meshtastic
  region EU_868 (869.525 MHz, ERC 70-03, 10% duty cycle) with 868-tuned antennas.
  See `docs/brenta-trial-plan.md`.

# Algorithm Research Survey — battery, SOS, and capacity levers

> **Evidence status (2026-07-13):** This is a design survey, not a validated result.
> The motivating simulator values (0.06%, 28,632 deaths/year, 37 lost SOS, and all
> downstream effect sizes) came from superseded runs. The source shorthand at the end
> is not a publication-quality bibliography; resolve every numeric literature claim
> to a primary source before using it in a report.

**Motivating hypothesis:** the historical runs suggested that idle listening may
dominate transmitter energy, but the magnitude requires corrected runs and board-level
bench measurement. Semtech specifies about 4.6 mA active RX for the SX1262 IC under
specified conditions; that is not the consumption of a Heltec board or proof that its
ESP32 accounts for the full difference. Host/radio sleep remains a design candidate,
with all board-level currents marked [BENCH-CALIBRATE].

## Family 1 — Duty-cycled MAC (the battery lever)

| protocol / idea | mechanism | why better | why worse |
|---|---|---|---|
| **S-MAC / T-MAC** (2002/03) | synchronized wake windows | simple, bounded latency | sync overhead; fixed windows waste energy at low load |
| **B-MAC / preamble sampling** | receivers sniff periodically; senders send long preamble | asynchronous, no sync needed | long preamble burns sender + channel |
| **X-MAC / ContikiMAC** | *strobed* preamble + early-ACK cuts preamble in half on average | best-of-class async LPL; ContikiMAC hits <1% duty | per-hop wake latency (~T_sniff/2·hops) |
| **WiseMAC** | learns neighbors' sniff phase, starts preamble just-in-time | near-optimal preamble cost | state per neighbor; drift |
| **LoRa CAD sniffing** (Semtech AN1200.48; LoRa-DuCy; MDPI preamble-sampling multi-hop 2023; JMAC) | SX126x Channel Activity Detection = a few ms sniff, radio wakes host on hit | LoRa-native X-MAC; CAD costs ~ms of RX per second → % duty | SF11 CAD windows are long; strobes lengthen airtime → more collisions |
| **TDMA / On-demand TDMA** | scheduled slots (GPS can provide time to equipped nodes) | near-zero idle listening in an ideal schedule | GPS/clock energy and sky view; schedule maintenance; hikers are unscheduled |
| **Wake-up radio (WuR)** | separate ~3 µW receiver (−83 dBm @ 868 MHz demonstrated) triggers main radio | 99.9%+ idle reduction, ms latency | extra hardware; −83 dBm sensitivity ≪ −131 (range gap) |
| **LEACH / HEED role rotation** | rotate which nodes serve as always-on relays; rest sleep | marries fairness (our lb_energy) to the actual lever | cluster churn; coverage holes if rotation too aggressive |

**Implemented simulation designs** (correctness/results require the post-audit suite):
- `duty_sync` — X-MAC-style preamble sampling network-wide: every fixed
  non-gateway node at duty *d*=5% (CAD sniff each second); every transmission
  pays a strobe of mean T_sniff/2 (longer airtime → honest collision/latency
  cost). Routing = lb_energy tree.
- `duty_adaptive` — per-node duty from **energy runway** (our solar forecast):
  rich nodes 25% (responsive), poor nodes 2% (survival). The scheduler is the
  self-monitoring idea moved from routing (where it couldn't matter) to the
  MAC (where it can).
- `rotate_lb` — LEACH-style: only nodes on the current lb_energy route tree
  stay always-on; every off-tree relay drops to 2% sniff duty. The lb EWMA
  penalty rotates the tree hourly, so relay *roles* rotate — drain equalizes
  via who-sleeps, not who-forwards.

**Historical design expectations (not a preregistration):** duty modes were expected
to cut fleet listen energy 4–15×
(bounded below by the 12 mA sleep floor of ESP32 [BENCH-CALIBRATE; nRF52
~2 mA would triple the gain]); winter deaths drop dramatically; November–
February SOS availability becomes the discriminating metric; PDR dips a few
points from strobe collisions; per-hop latency +~0.5 s.

## Family 2 — SOS reliability (the life-safety lever)

| idea | mechanism | trade |
|---|---|---|
| **hybrid flood** (implemented) | SOS floods in all modes | tiny airtime, big redundancy |
| **priority MAC** (implemented) | PIFS-like backoff, relays forward first, triple-send | none meaningful at SOS rarity |
| **ACK + originator retry** (new) | gateway floods a small ACK; originator retries every 5 min until heard | converts winter "network was down at T₀" losses into delayed deliveries — the hiker keeps walking toward coverage |
| store-carry-forward (DTN: epidemic / spray-and-wait / PRoPHET) | any met node carries the SOS | future: hiker↔hiker custody in partitions |
| gateway anycast (implemented) | any of 55 gateways completes delivery | — |

**Implemented candidate:** `--sos-retry` (ACK + retry, layered on every mode). A
superseded pilot run reported 37/365 lost SOS; it cannot establish the rate, seasonality,
or recovery benefit. Evaluate retry delivery, delay, duplicate handling, custody, and
energy on the corrected simulator and controlled hardware.

## Family 3 — Capacity (the flood/scale lever)

- **Regional channels** (each gateway component on its own frequency) —
  designed, queued behind the current runs.
- RPL/Trickle-style control-plane suppression — our hourly tree rebuild is
  already Trickle-spirited; not separately tested.

## What we deliberately did NOT implement
- Wake-up radio: hardware, not algorithm — goes in the Phase-3 BOM discussion.
- PRoPHET/full DTN: needs multi-day hiker encounter patterns our rental model
  doesn't yet generate honestly.
- Reinforcement-learning routing was not implemented at the time of this survey; it was
  added later for exploratory runs. The old G3 result cannot establish a flat reward
  surface, and the new RL outputs are not yet validated.

Source leads (incomplete; verify editions and replace shorthand with full citations):
Semtech AN1200.48 (SX126x CAD), RAKwireless CAD note, SX1262 datasheet
(4.6 mA RX), Buettner et al. X-MAC, Dunkels ContikiMAC, El-Hoiydi WiseMAC,
Ye et al. S-MAC, Heinzelman et al. LEACH, JMAC (arXiv 2312.08387), LoRa-DuCy,
MDPI Sensors 23(11):4994 preamble-sampling LoRa multi-hop, Oller et al.
wake-up-radio vs duty-cycling (IEEE/ACM ToN), 3 µW 868 MHz WuR (JSSC).

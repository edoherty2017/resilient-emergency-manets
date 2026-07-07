# Algorithm Research Survey — battery, SOS, and capacity levers

**Motivating result (year runs, G3):** with always-listening routers, transmit
energy is 0.06% of the fleet budget; every routing algorithm produced identical
survival (28,632 deaths/yr). Therefore: *anything that claims to optimize
battery must attack idle listening or it is theater.* This survey is organized
around that fact. A second, subtler fact from the datasheets: the SX1262 radio
itself receives at only ~4.6 mA — our 68 mA listen figure is dominated by the
**ESP32 host staying awake**. The real deployment lever is host sleep with
radio-autonomous wake (nRF52-class Meshtastic hardware sleeps at ~2 mA;
[SITE-SURVEY/BENCH]).

## Family 1 — Duty-cycled MAC (the battery lever)

| protocol / idea | mechanism | why better | why worse |
|---|---|---|---|
| **S-MAC / T-MAC** (2002/03) | synchronized wake windows | simple, bounded latency | sync overhead; fixed windows waste energy at low load |
| **B-MAC / preamble sampling** | receivers sniff periodically; senders send long preamble | asynchronous, no sync needed | long preamble burns sender + channel |
| **X-MAC / ContikiMAC** | *strobed* preamble + early-ACK cuts preamble in half on average | best-of-class async LPL; ContikiMAC hits <1% duty | per-hop wake latency (~T_sniff/2·hops) |
| **WiseMAC** | learns neighbors' sniff phase, starts preamble just-in-time | near-optimal preamble cost | state per neighbor; drift |
| **LoRa CAD sniffing** (AN1200.85; LoRa-DuCy; MDPI preamble-sampling multi-hop 2023; JMAC) | SX126x Channel Activity Detection = a few ms sniff, radio wakes host on hit | LoRa-native X-MAC; CAD costs ~ms of RX per second → % duty | SF11 CAD windows are long; strobes lengthen airtime → more collisions |
| **TDMA / On-demand TDMA** | scheduled slots (GPS gives us free time-sync!) | zero idle listening in theory | schedule maintenance; hikers are unscheduled |
| **Wake-up radio (WuR)** | separate ~3 µW receiver (−83 dBm @ 868 MHz demonstrated) triggers main radio | 99.9%+ idle reduction, ms latency | extra hardware; −83 dBm sensitivity ≪ −131 (range gap) |
| **LEACH / HEED role rotation** | rotate which nodes serve as always-on relays; rest sleep | marries fairness (our lb_energy) to the actual lever | cluster churn; coverage holes if rotation too aggressive |

**Chosen implementations** (sim modes, all year-runnable):
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

**Pre-registered expectations:** duty modes cut fleet listen energy 4–15×
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

**Chosen:** `--sos-retry` (ACK + retry, layered on every mode). The pilot year
lost 37/365 SOS — all during winter outages; retry-until-ACK should recover
most, because outages are intermittent and hikers move.

## Family 3 — Capacity (the flood/scale lever)

- **Regional channels** (each gateway component on its own frequency) —
  designed, queued behind the current runs.
- RPL/Trickle-style control-plane suppression — our hourly tree rebuild is
  already Trickle-spirited; not separately tested.

## What we deliberately did NOT implement
- Wake-up radio: hardware, not algorithm — goes in the Phase-3 BOM discussion.
- PRoPHET/full DTN: needs multi-day hiker encounter patterns our rental model
  doesn't yet generate honestly.
- Reinforcement-learning routing: the G3 result says the reward surface for
  routing-energy is flat; RL belongs on the duty-cycle scheduler later.

Sources: Semtech AN1200.85 (CAD), RAKwireless CAD note, SX1262 datasheet
(4.6 mA RX), Buettner et al. X-MAC, Dunkels ContikiMAC, El-Hoiydi WiseMAC,
Ye et al. S-MAC, Heinzelman et al. LEACH, JMAC (arXiv 2312.08387), LoRa-DuCy,
MDPI Sensors 23(11):4994 preamble-sampling LoRa multi-hop, Oller et al.
wake-up-radio vs duty-cycling (IEEE/ACM ToN), 3 µW 868 MHz WuR (JSSC).

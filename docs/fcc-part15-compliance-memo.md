# FCC Regulatory Compliance Memo — 915 MHz LoRa Fixed Infrastructure

**Status:** Engineering analysis for advisor/legal review — NOT a legal opinion.
**Date:** 2026-06-15
**Scope:** Regulatory basis for operating Meshtastic LongFast (915 MHz, SF11/BW250)
hardware, and specifically for proposing *fixed relay infrastructure* to NH Fish &
Game / Mt. Washington State Park.

> **Bottom line up front:** Meshtastic LongFast as typically operated — a single
> 250 kHz channel, no frequency hopping, up to +22 dBm — does **not** cleanly fit
> any FCC Part 15 unlicensed pathway. The honest, defensible options are (1) operate
> the deployment under an **Amateur Radio license (Part 97)**, (2) reconfigure to a
> **≥500 kHz bandwidth** preset to qualify as Part 15.247 digital modulation, or
> (3) drastically reduce power. This must be resolved before any fixed-infrastructure
> proposal to a state agency, and confirmed with a TCB/FCC or counsel — it is the
> "Regulatory" KPI in the directed-study proposal.

---

## 1. Why this matters

The proposal lists "Verification of FCC Part 15 compliance (915 MHz, FHSS, <1W)" as a
KPI. Two problems with that line as written:

1. Meshtastic does **not** implement FHSS (frequency-hopping spread spectrum) — it
   transmits on a single fixed channel per region/preset. So the stated compliance
   basis ("FHSS") does not match the actual device behavior.
2. A research project carrying a handheld node is a different regulatory question
   from *installing permanent transmitters on public land*. The moment we propose
   fixed infrastructure to a state agency, the compliance basis has to be real and
   documented, not assumed from the fact that the hardware is sold in the US.

## 2. The three Part 15 pathways and why LongFast fails each

Operation in the 902–928 MHz ISM band is governed mainly by **§15.247** (spread
spectrum / digital modulation, up to 1 W) and **§15.249** (very low power, field-strength
limited). LoRa can be certified under §15.247 by one of two routes:

### 2.1 §15.247 digital modulation — FAILS on bandwidth
Digital-modulation systems must have a **minimum 6 dB bandwidth of at least 500 kHz**,
may transmit up to **1 W (30 dBm) conducted**, and must keep power spectral density
**≤ 8 dBm in any 3 kHz**.

- LongFast uses **BW = 250 kHz** → a single LongFast channel is ~250 kHz wide and
  **does not meet the 500 kHz minimum**. A single 125/250 kHz LoRa channel does not
  qualify as digital modulation on its own.
- (PSD is fine: 22 dBm spread over 250 kHz ≈ +2.8 dBm/3 kHz, under the +8 limit — but
  PSD compliance does not substitute for the bandwidth requirement.)

### 2.2 §15.247 frequency hopping — FAILS because Meshtastic doesn't hop
Narrowband channels (<500 kHz) are permitted under §15.247 **only** via a compliant
frequency-hopping scheme (hopping across many channels, bounded dwell time, ~random
spectral spread). Meshtastic sits on one channel; it implements no FHSS. So the
narrowband route is unavailable as-operated.

### 2.3 §15.249 very low power — FAILS on power by ~23 dB
§15.249 permits narrowband operation with **no bandwidth minimum**, but caps field
strength at **50 mV/m at 3 m ≈ −1.23 dBm EIRP** (sub-milliwatt). The proposed relays
run **+22 dBm + ~2 dBi antenna ≈ +24 dBm EIRP** — roughly **25 dB (≈300×) over** the
§15.249 ceiling. Not viable at any useful range.

**Net:** at +22 dBm on a single 250 kHz channel with no hopping, none of the three
unlicensed pathways is satisfied.

## 3. The module-certification nuance (important)

Heltec LoRa32 V3 boards and their SX1262 modules carry FCC IDs. But an FCC grant
covers a **specific tested configuration**. LoRa modules in this band are typically
granted under §15.247 — often as part of a frequency-hopping (LoRaWAN) test mode.
Operating the same silicon **single-channel, non-hopping, at full power** is outside
that granted modular condition, which shifts compliance responsibility onto the
integrator/operator (us) and means we **cannot simply cite the module's FCC ID** as
cover for a fixed deployment. Action item: pull the actual FCC grant for the specific
board/module (FCC ID on the label → fcc.gov/oet/ea/fccid) and read the granted
modulation/bandwidth/antenna conditions.

## 4. Compliant options (ranked for this project)

### Option A — Operate under Amateur Radio license (Part 97)  ★ recommended for research
915 MHz (902–928) is the **33 cm US amateur band**. A licensed amateur may run LoRa
here with far more headroom than Part 15 (higher power, gain antennas), which removes
the bandwidth/hopping problem entirely. Trade-offs that matter for *this* system:
- **No encryption** (Part 97 prohibits messages encoded to obscure meaning) — fine for
  a research/telemetry and SAR-beacon use case, but Meshtastic's default channel
  encryption must be **disabled** to be Part 97-legal.
- **Station identification** every 10 minutes and at end of exchange — Meshtastic node
  IDs/callsign config can satisfy this; must be configured deliberately.
- Operator (and ideally each fixed station's control operator) must be licensed; a
  permanent unattended station has additional Part 97 rules (auto-control).
- This is the path most US high-power Meshtastic/AREDN deployments actually use. It is
  the most realistic basis for a research deployment and a SAR pilot. **Decision needed:
  is the student (or advisor) willing to obtain a Technician license?** (Sufficient for
  33 cm; a weekend's study.)

### Option B — Reconfigure to ≥500 kHz bandwidth (stay Part 15.247 digital modulation)
Switch the deployment preset to a **BW = 500 kHz** LoRa configuration (e.g. Meshtastic
SHORT_TURBO is 500 kHz) so the signal qualifies as §15.247 digital modulation at up to
1 W. Trade-off: wider bandwidth **raises the noise floor and reduces sensitivity/range**
(roughly −3 dB sensitivity vs 250 kHz, more vs SF11 LongFast), partially offsetting the
power headroom. Range modeling (ITM) should be re-run at the 500 kHz preset before
committing — this changes the whole link budget and the relay-spacing conclusions.
Antenna note: in 902–928 MHz, antenna gain **>6 dBi requires dB-for-dB power reduction**
(the relaxed 1-dB-per-3-dB fixed point-to-point relief applies only to the 2.4 GHz
band, not here), so keep relay antennas ≤6 dBi or reduce conducted power accordingly.

### Option C — Sub-milliwatt §15.249 operation
Drop EIRP to ≤ −1.23 dBm. Kills the link budget (the whole project is about range), so
this is only relevant for incidental/handheld use, not relays. Not recommended.

### Option D — Experimental / Special Temporary Authorization
For a time-boxed research deployment, an FCC experimental license (Part 5) can authorize
otherwise-non-compliant operation. Heavier process; worth knowing it exists if Options A/B
are blocked.

## 5. What changes for the deployment proposal

- The relay-infrastructure proposal to NH Fish & Game should state its compliance basis
  explicitly. Recommended language: *"Fixed relays operate under Amateur Radio license
  (Part 97, 33 cm band) with encryption disabled and automatic station identification,"*
  **or** *"under Part 15.247 digital modulation at 500 kHz bandwidth, ≤1 W, ≤6 dBi."*
- Either choice **feeds back into the engineering**: Part 97 lets you keep LongFast
  (best range) but forbids encryption and needs licensed control operators; Part 15
  keeps it license-free but forces the 500 kHz preset and re-opens the range/spacing
  analysis. **This is a real fork that should be decided before Trial 2 hardware is
  finalized.**

## 6. Open questions requiring human/legal sign-off

1. Will the project obtain an amateur license (Option A), or commit to the 500 kHz Part
   15 reconfiguration (Option B)? (Drives the radio config and the link budget.)
2. Pull and read the actual FCC grant for the exact Heltec board/module in use — what
   modulation/bandwidth/antenna conditions were granted?
3. For a *permanent* relay on state land: does NH Fish & Game / the State Park require
   its own RF authorization, frequency coordination, or land-use permit independent of
   FCC rules?
4. Encryption vs Part 97: an emergency SOS system arguably should not obscure content,
   but operational privacy may matter — reconcile with the no-encryption rule.
5. Confirm all of the above with a TCB (Telecommunications Certification Body) or FCC OET
   / counsel before any agency proposal. **This memo is engineering analysis, not legal
   advice.**

## 7. Recommendation

For the **research trials**, pursue **Option A (Part 97 amateur license)** — it is the
honest, well-trodden basis for higher-power 915 MHz LoRa in the US and unblocks the
existing LongFast link budget. For any **permanent public-land deployment**, document
the chosen basis explicitly and get it confirmed in writing by a TCB/counsel and the
state agency. Update the proposal KPI from the inaccurate "FHSS, <1W" to the actual
basis chosen. Re-run the ITM link budget if Option B (500 kHz) is selected.

---

### Sources
- [eCFR 47 CFR §15.247 — 902–928 MHz operation](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-15/subpart-C/subject-group-ECFR2f2e5828339709e/section-15.247)
- [eCFR 47 CFR §15.249 — low-power 902–928 MHz](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-15/subpart-C/subject-group-ECFR2f2e5828339709e/section-15.249)
- [Sunfire Testing — LoRa FCC Certification Guide (digital modulation vs FHSS, 500 kHz minimum)](https://www.sunfiretesting.com/LoRa-FCC-Certification-Guide/)
- [Semtech AN1200.26 — LoRa and FCC Part 15.247 Measurement Guidance](https://studylib.net/doc/18090231/an1200.26-lora%E2%84%A2-and-fcc-part-15.247--measurement)
- [Radiocrafts — Approaches to FCC certify a radio in 902–928 MHz](https://radiocrafts.com/the-different-approaches-to-fcc-certify-a-radio-solution-in-the-license-free-band-902-915-mhz/)
- §15.249 field strength 50 mV/m @ 3 m ≈ −1.23 dBm EIRP (per multiple app-note sources above)

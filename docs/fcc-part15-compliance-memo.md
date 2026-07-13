# FCC Regulatory Compliance Memo — 915 MHz LoRa Fixed Infrastructure

**Status:** Engineering analysis for advisor/legal review — NOT a legal opinion.
**Date:** 2026-06-15; claim/source review updated 2026-07-13
**Scope:** Regulatory basis for operating Meshtastic LongFast (915 MHz, SF11/BW250)
hardware, and specifically for proposing *fixed relay infrastructure* to NH Fish &
Game / Mt. Washington State Park.

> **Bottom line up front:** The repository does not yet document a lawful operating
> basis for the proposed configuration. A nominal 250 kHz, single-channel,
> non-hopping, +22 dBm LongFast transmission does not satisfy the technical screens
> below for §15.247 digital modulation, §15.247 frequency hopping, or §15.249.
> That is not, by itself, a final equipment-authorization determination: the exact
> FCC ID, grant, approved antenna/integration conditions, firmware configuration,
> and measured emissions must be checked. Part 97, a nominal 500 kHz preset, reduced
> power, and Part 5 are **candidate pathways, not automatic authorizations**. Do not
> transmit in a trial or describe a fixed deployment as compliant until the selected
> basis is documented and confirmed by a qualified TCB/FCC counsel.

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

## 2. Part 15 engineering screen for the stated LongFast configuration

Operation in the 902–928 MHz ISM band is governed mainly by **§15.247** (spread
spectrum / digital modulation, up to 1 W) and **§15.249** (very low power, field-strength
limited). LoRa can be certified under §15.247 by one of two routes:

### 2.1 §15.247 digital modulation — stated configuration does not meet the bandwidth screen
Digital-modulation systems must have a **measured 6 dB bandwidth of at least 500 kHz**,
may transmit up to **1 W (30 dBm) conducted**, and must keep power spectral density
**≤ 8 dBm in any 3 kHz**.

- LongFast's configured modulation bandwidth is **250 kHz**, so it cannot establish
  a measured 6 dB bandwidth of at least 500 kHz. A configuration label is not a
  substitute for the required measurement.
- The earlier arithmetic that divided total power uniformly across 250 kHz was only
  a rough spectral-density estimate. §15.247 PSD and band-edge/unwanted-emission
  compliance require the prescribed measurements; they are not established here.

### 2.2 §15.247 frequency hopping — stated configuration does not hop
Narrowband channels (<500 kHz) are permitted under §15.247 **only** via a compliant
frequency-hopping scheme (hopping across many channels, bounded dwell time, ~random
spectral spread). Meshtastic sits on one channel; it implements no FHSS. So the
narrowband route is unavailable as-operated.

### 2.3 §15.249 very low power — stated power is far above the screen
§15.249 permits narrowband operation with **no bandwidth minimum**, but caps field
strength at **50 mV/m at 3 m**, approximately **−1.23 dBm EIRP** under an idealized
far-field conversion. The proposed link budget uses **+22 dBm conducted + 2.15 dBi
antenna = +24.15 dBm EIRP** — about **25.4 dB (≈350× in power) above** that screen.
Actual compliance is determined by the required field-strength and emissions tests,
not this conversion.

**Net:** the stated operating facts do not demonstrate any of these Part 15 pathways.

## 3. The module-certification nuance (important)

The repository does not record the FCC ID printed on each exact unit, so it cannot yet
say whether the board, a module within it, or neither has an applicable authorization.
An FCC grant covers the tested device and listed operating, antenna, and integration
conditions; approval of the underlying transceiver silicon is not approval of every
end-product configuration. Action item: photograph each label, retrieve the grant and
test exhibits from FCC OET, and compare the exact firmware preset, power, frequency,
antenna, host integration, and user instructions. Do not infer authorization from the
fact that a board is sold in the United States.

## 4. Compliant options (ranked for this project)

### Option A — Evaluate a Part 97 amateur-radio design
915 MHz (902–928) is the **33 cm US amateur band**. A licensed amateur may run LoRa
here subject to Part 97, so the Part 15 bandwidth/hopping screen would no longer be
the operating basis. A license alone does **not** legalize the proposed service or
stock mesh behavior. Questions that matter for this system include:
- **No messages encoded to obscure meaning.** Meshtastic's default channel encryption
  would ordinarily need to be disabled and the application/routing representation
  reviewed. Satisfying that technical condition does not by itself establish an
  amateur-service purpose or make research, agency, hiker, or SAR traffic permissible.
- **Station identification** must comply with §97.119. A Meshtastic node name or a
  callsign entered in an app is not, without an implementation check, proof that every
  station identifies at the required times and by a permitted method.
- A licensed control operator and compliant control method are required. Third-party
  messages, automatically controlled data operation, and automatic retransmission are
  governed by §§97.109, 97.113, 97.115, 97.201/205, and 97.221. A public hiker/SAR
  service, unattended relays, and stock Meshtastic flooding therefore need a
  design-specific review; they cannot be approved merely because one researcher earns
  a Technician license.
- §97.113 restricts pecuniary/employer communications and regular communications that
  could reasonably be furnished by another radio service. §97.403's emergency safety
  exception addresses immediate emergencies; it is not a routine deployment license.

### Option B — Evaluate an authorized ≥500 kHz Part 15.247 configuration
A nominal **BW = 500 kHz** LoRa configuration (for example, a Meshtastic preset whose
configured bandwidth is 500 kHz) is a candidate for laboratory and grant review; the
preset name does **not** make the end product compliant. The exact device/configuration
must be authorized and must meet measured 6 dB bandwidth, PSD, conducted-power,
band-edge/unwanted-emission, and antenna/integration requirements. A user firmware
change outside the grant conditions can invalidate the modular/end-product basis.

Wider bandwidth **raises the noise floor and reduces sensitivity/range**
(roughly −3 dB sensitivity vs 250 kHz, more vs SF11 LongFast), partially offsetting the
power headroom. Range modeling (ITM) should be re-run at the 500 kHz preset before
committing — this changes the whole link budget and the relay-spacing conclusions.
Antenna note: in 902–928 MHz, antenna gain **>6 dBi requires dB-for-dB power reduction**
(the relaxed 1-dB-per-3-dB fixed point-to-point relief applies only to the 2.4 GHz
band, not here), so keep relay antennas ≤6 dBi or reduce conducted power accordingly.

### Option C — Evaluate §15.249 at very low field strength
Reducing nominal EIRP to approximately the screening value would severely reduce the
link budget, and compliance would still require field-strength and emissions testing.
This appears impractical for the relay objective but is not established by calculation
alone.

### Option D — Experimental / Special Temporary Authorization
For a time-boxed research deployment, an FCC experimental license (Part 5) can authorize
otherwise-non-compliant operation. Heavier process; worth knowing it exists if Options A/B
are blocked.

## 5. What changes for the deployment proposal

- Do not put a compliance declaration in the NH Fish & Game proposal yet. Attach the
  exact grant/authorization and operating design after review, then state only what
  that record supports.
- Any selected basis **feeds back into the engineering**. Part 97 requires a compliant
  amateur-service purpose, messages, identification, control, and relay architecture;
  Part 15 requires an authorized hardware/firmware/antenna configuration and may change
  the link budget. Decide and document the basis before Trial 2 transmits.

## 6. Open questions requiring human/legal sign-off

1. Pull and read the actual FCC grant for the exact Heltec board/module in use — what
   modulation/bandwidth/antenna conditions were granted?
2. Ask a qualified reviewer whether a controlled research trial is better supported by
   the exact Part 15 grant, Part 5 experimental authority, or a redesigned Part 97
   operation. Do not reduce this to “get a license or select 500 kHz.”
3. If Part 97 is considered, document station purpose, control points/operators,
   third-party traffic, automatic control, retransmission/repeater classification,
   identification, encryption state, and employer/agency involvement.
4. For a *permanent* relay on state land: does NH Fish & Game / the State Park require
   its own RF authorization, frequency coordination, or land-use permit independent of
   FCC rules?
5. Encryption vs Part 97: an emergency SOS system arguably should not obscure content,
   but operational privacy may matter — reconcile with the no-encryption rule.
6. Confirm all of the above with a TCB (Telecommunications Certification Body) or FCC OET
   / counsel before any agency proposal. **This memo is engineering analysis, not legal
   advice.**

## 7. Recommendation

Before any further transmission at the disputed configuration, inventory the exact
hardware/FCC IDs and obtain a written configuration-specific review. For a controlled
research trial, compare the actual Part 15 grant, Part 5 authority, and a fully specified
Part 97 design. For any permanent public-land deployment, document the selected basis
and obtain the necessary RF and land-use approvals. Update the proposal KPI from the
unsupported "FHSS, <1W" assertion to “authorization basis documented for the exact
hardware, firmware, antenna, power, traffic, and control design.” Re-run the ITM link
budget if the authorized radio configuration changes.

---

### Sources
- [eCFR 47 CFR §15.247 — 902–928 MHz operation](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-15/subpart-C/subject-group-ECFR2f2e5828339709e/section-15.247)
- [eCFR 47 CFR §15.249 — low-power 902–928 MHz](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-15/subpart-C/subject-group-ECFR2f2e5828339709e/section-15.249)
- [FCC OET Equipment Authorization Search](https://apps.fcc.gov/oetcf/eas/reports/GenericSearch.cfm)
- [eCFR Part 5 — Experimental Radio Service](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-5)
- [eCFR Part 97 — Amateur Radio Service](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-D/part-97)
- [§97.113 — prohibited transmissions](https://www.ecfr.gov/current/title-47/part-97/section-97.113)
- [§97.115 — third-party communications](https://www.ecfr.gov/current/title-47/part-97/section-97.115)
- [§97.119 — station identification](https://www.ecfr.gov/current/title-47/part-97/section-97.119)
- [§97.221 — automatically controlled digital stations](https://www.ecfr.gov/current/title-47/part-97/section-97.221)
- [§97.403 — safety of life and protection of property](https://www.ecfr.gov/current/title-47/part-97/section-97.403)

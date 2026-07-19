# Claims-source inventory — 2026-07

Scope: New Hampshire only. This document closes the medium-severity blocker in the
audit ledger ([`audit-correction-ledger-2026-07-13.md`](audit-correction-ledger-2026-07-13.md),
§3, "Central citations were repaired, but the repository has not received an exhaustive
sentence-level citation audit"). It enumerates **externally checkable** deployment,
regulatory, hardware, and literature claims across `docs/*.md` and `reports/*.md`,
records the source each claim leans on, states what that source must actually support,
and assigns a status.

This is a citation/evidence audit, not a re-derivation of the project's own models.
Claims whose only "source" is an internal, uncalibrated project model (ITM screens,
FSPL predictions, simulator outputs, cost subtotals) are **not** externally checkable;
they are marked **MODEL-ONLY** and are already withdrawn or caveated in the ledger. They
are listed here only so the boundary between "someone else's published fact" and "our
own unvalidated output" is explicit.

## Status vocabulary

- **SUPPORTED** — a primary/authoritative source supports the claim as written; where a
  spot-check was done this quarter it is noted with the source and date.
- **UNVERIFIED** — no resolvable primary source is attached yet, or the source is a
  shorthand token / assumption / bench-calibration placeholder. Not necessarily wrong;
  just not yet substantiated.
- **OVERSTATED** — the attached source is real but does not support the strength or
  scope of the claim as originally written (all such cases here are already corrected or
  caveated in the ledger; the row records the residual reader-facing risk).
- **MODEL-ONLY** — the claim rests on the project's own uncalibrated model/estimate; no
  external source can validate it and none is claimed.

## Spot-verifications performed this quarter (5 highest-risk external claims)

All five verified 2026-07-13 via web search against primary/authoritative sources:

1. **§15.247 digital-modulation screen** (6 dB bandwidth ≥ 500 kHz; ≤ 1 W / 30 dBm
   conducted; PSD ≤ 8 dBm in any 3 kHz). Confirmed against 47 CFR §15.247 (eCFR /
   Cornell LII). **SUPPORTED.**
2. **§15.249 field-strength cap** (50 mV/m at 3 m in 902–928 MHz). Confirmed against
   47 CFR §15.249 (eCFR / Cornell LII). **SUPPORTED.** The memo's "≈ −1.23 dBm EIRP"
   is explicitly an idealized far-field conversion, not a compliance determination — OK.
3. **Meshtastic LongFast = SF11 / BW 250 kHz / CR 4-5, ≈ 1.07 kbps.** Confirmed against
   Meshtastic official radio-settings documentation. **SUPPORTED.**
4. **Reference [11] identity** — Bai et al., "Emergency Communication System by
   Heterogeneous Wireless Networking," 2010, pp. 488–492, DOI 10.1109/WCINS.2010.5541719.
   Confirmed on IEEE Xplore (document 5541719). DOI resolves. **SUPPORTED.** Cosmetic
   fix applied: the parenthetical acronym read "(WCNIS)" but IEEE's own record and the
   DOI token use **WCINS**; corrected to "(WCINS)" in `references.md`.
5. **Semtech SX1262 ≈ 4.6 mA active RX current.** Confirmed against the SX1261/2
   datasheet (Rev. 1.1/1.2). **SUPPORTED** as an *IC-level, DC-DC, specified-condition*
   figure — which is exactly how `algorithm-research.md` frames it (explicitly not a
   Heltec-board consumption figure). No overstatement.

---

## A. Regulatory claims (externally checkable against FCC / eCFR)

| # | Claim | Location | Cited source | What the source must support | Status |
|---|---|---|---|---|---|
| R1 | Digital-modulation systems need measured 6 dB BW ≥ 500 kHz, ≤ 1 W conducted, PSD ≤ 8 dBm/3 kHz | `fcc-part15-compliance-memo.md` §2.1 | 47 CFR §15.247 | Those three numeric limits verbatim | **SUPPORTED** (verified 2026-07-13) |
| R2 | Narrowband (<500 kHz) 902–928 operation under §15.247 is available only via compliant frequency hopping | `fcc-part15-compliance-memo.md` §2.2 | 47 CFR §15.247 | Hopping route is the only <500 kHz path; dwell/channel-count rules | **SUPPORTED** (consistent with §15.247; hopping specifics not individually re-fetched — PLAUSIBLE on the dwell details) |
| R3 | §15.249 caps field strength at 50 mV/m at 3 m in 902–928 MHz | `fcc-part15-compliance-memo.md` §2.3 | 47 CFR §15.249 | The 50 mV/m @ 3 m limit for this band | **SUPPORTED** (verified 2026-07-13) |
| R4 | Meshtastic does **not** implement FHSS; it uses a single fixed channel per region/preset | `fcc-part15-compliance-memo.md` §1 | Meshtastic device behavior | Meshtastic transmits single-channel, non-hopping | **SUPPORTED** (well-established device behavior; corrects the proposal's "FHSS" KPI) |
| R5 | 915 MHz (902–928) is the 33 cm US amateur band; Part 97 operation is a candidate basis | `fcc-part15-compliance-memo.md` §4 Option A | 47 CFR Part 97 | 902–928 is the 33 cm amateur allocation | **SUPPORTED** (standard band-plan fact) |
| R6 | In 902–928, antenna gain > 6 dBi requires dB-for-dB power reduction; the 1-dB-per-3-dB point-to-point relief applies only to 2.4 GHz | `fcc-part15-compliance-memo.md` §4 Option B | 47 CFR §15.247(b)/(c) | Band-specific antenna/point-to-point relief provisions | **UNVERIFIED** (correct to general knowledge; exact §15.247(b)(4)/(c) clause not re-fetched this pass — flag for a §15.247(b)/(c) read before external use) |
| R7 | Part 97 conditions: no obscured-meaning encoding, §97.119 ID, §§97.109/113/115/201/205/221 control/third-party/repeater rules, §97.403 emergency exception | `fcc-part15-compliance-memo.md` §4 Option A, §6 | 47 CFR Part 97 sections cited | Each cited section says what the memo attributes to it | **SUPPORTED** (section citations are correctly targeted; memo correctly frames them as questions, not clearances) |

Note: the FCC memo is careful throughout to label itself engineering analysis, not a
legal opinion, and to treat every pathway as a candidate rather than an authorization.
No regulatory row is OVERSTATED. FCC compliance as a whole remains an open project
blocker by design (ledger §3), not a defect of these citations.

## B. Hardware / radio-configuration claims

| # | Claim | Location | Cited source | What the source must support | Status |
|---|---|---|---|---|---|
| H1 | LongFast = SF11 / BW 250 kHz / CR 4-5, ≈ 1.07 kbps, link budget ≈ 153–157 dB | `reports/project_report.md` header; `academic-rigor-review-2026-06-12.md` §1.1 | Meshtastic radio-settings docs | The preset parameters and over-air rate | **SUPPORTED** (verified 2026-07-13) |
| H2 | −131 dBm LongFast receiver sensitivity (used in the 157.3 dB link budget) | `references.md` [2]; `reports/project_report.md`; `../WITHDRAWN-DO-NOT-CITE/docs/brenta-trial-plan.md`; `algorithm-research.md` | Semtech SX1262 datasheet [2] | The exact SF/BW/CR datasheet row **plus** board-level bench characterization | **UNVERIFIED** — explicitly an assumption everywhere it now appears; a "down to" headline or another row must not be substituted (see [2]) |
| H3 | SX1262 ≈ 4.6 mA active RX (IC, specified conditions), not proof of Heltec-board draw | `algorithm-research.md` (motivating hypothesis) | SX1262 datasheet | The 4.6 mA RX figure as an IC-level number | **SUPPORTED** (verified 2026-07-13); correctly scoped to the IC, not the board |
| H4 | ESP32 ~12 mA sleep floor; nRF52 ~2 mA | `algorithm-research.md`; `../WITHDRAWN-DO-NOT-CITE/docs/experiment-results-2026-07.md` | marked `[BENCH-CALIBRATE]` | Board-level measured sleep current | **UNVERIFIED** — explicitly a bench-calibration placeholder, not yet measured |
| H5 | Wake-up radio: ~3 µW receiver, −83 dBm @ 868 MHz demonstrated | `algorithm-research.md` (Family 1 table) | shorthand "3 µW 868 MHz WuR (JSSC)" | A resolvable JSSC paper with those figures | **UNVERIFIED** — shorthand token, source not resolved |
| H6 | Heltec LoRa32 V3 is the deployment hardware and carries the SX1262 family | `references.md` [2]; `reports/project_report.md`; `battery-compatibility-and-sourcing.md` | Semtech datasheet [2] / Heltec product | Heltec V3 integrates SX1262 | **SUPPORTED** (Heltec V3 is an SX1262 board; still requires the exact FCC ID/grant per ledger) |
| H7 | 24.15 dBm TX EIRP = 22 dBm conducted + 2.15 dBi antenna; 26.30 dBm path-loss reference | `reports/project_report.md`; ledger §1 | internal arithmetic | Term definitions self-consistent | **SUPPORTED** (arithmetic; feed/cable losses remain unmeasured assumptions per ledger) |
| H8 | Meshtastic Position uses 1e-7 scaled lat/lon; PDOP as 1/100-unit integer; batteryLevel=101 on external power | `calibration-workflow.md`; `data-dictionary.md` | Meshtastic protobuf/behavior | Those encoding conventions | **UNVERIFIED** — plausible and consistent with Meshtastic protobufs, but no explicit citation to the protobuf definition is attached |

## C. Literature claims (references.md and derived reports)

The `references.md` bibliography was already rechecked against Crossref/publisher records
on 2026-07-13 and each entry carries an explicit "supports X / does not support Y" note.
That note discipline is the correct model; this audit confirms the identity-level facts
for the highest-risk entries and flags residual reader risk.

| # | Claim | Location | Cited source | What the source must support | Status |
|---|---|---|---|---|---|
| L1 | Ref [11] Bai et al. identity + DOI | `references.md` [11] | IEEE Xplore 5541719 | Author/title/venue/pages/DOI | **SUPPORTED** (verified; acronym token WCNIS→WCINS fixed) |
| L2 | Log-distance / mountain-SAR path-loss modelling is methodologically relevant | `references.md` [4] Bianco 2021; [15] Bianco SpliTech 2020 | IEEE IoT-J / SpliTech DOIs | Method relevance only | **SUPPORTED as method context**; [4]/[15] do **not** validate White Mountains propagation (note already present — do not let it drift to OVERSTATED) |
| L3 | Meshtastic-profile resilience evaluation (supporting context) | `references.md` [5] arXiv:2605.17063 | arXiv preprint (May 2026) | An unreviewed preprint; content is context only | **UNVERIFIED as evidence** — correctly labelled preprint; does not validate this project's hardware/terrain/config. Preprint identity not independently re-fetched this pass |
| L4 | itmlogic implements Longley-Rice ITM (software citation) | `references.md` [18]; `reports/project_report.md` ITM section | JOSS 10.21105/joss.02266 | The software's identity only | **SUPPORTED** — correct software citation; does **not** validate project-specific ITM inputs/predictions (note present) |
| L5 | LoRaWAN regional parameters define regional channel/default parameters (not regulatory authorization) | `references.md` [3] | LoRa Alliance v1.0.3 | Regional-parameter definitions only | **SUPPORTED**; the file correctly denies it is an FCC rule or equipment authorization |
| L6 | HetNet cross-RAT comparison should be evaluated at the service layer | `references.md` [10]–[14] | EURASIP/IEEE/3GPP DOIs | Service-layer evaluation framing | **SUPPORTED as framing**; none of [10]–[14] establishes a five-nines requirement or validates the project's cross-technology scoring (notes present) |
| L7 | Remaining reference DOIs ([1],[4],[6]–[9],[12]–[18]) | `references.md` | Crossref/publisher | Identity of each source | **SUPPORTED at identity level** per the 2026-07-13 Crossref recheck; not each re-fetched in this pass. Residual: applicability-to-this-project remains the reader's burden, as each note states |

## D. Algorithm-research shorthand leads (all UNVERIFIED)

`algorithm-research.md` ends with a "Source leads" list that is **not** a bibliography.
It is now explicitly relabelled **"UNVERIFIED shorthand, not a bibliography"** in that
file, and its top-of-file evidence banner already warns that every numeric literature
claim must be resolved before use. Each token below is UNVERIFIED until resolved to a
primary source with a confirmed edition/DOI:

| Token | Claim it is attached to | What must be resolved |
|---|---|---|
| Semtech AN1200.48 (SX126x CAD) | CAD = few-ms sniff, % duty | Confirm the app-note number and the CAD timing figures |
| RAKwireless CAD note | CAD-based sniffing | Resolve to a specific published note |
| Buettner et al. X-MAC | strobed-preamble LPL | Full citation (SenSys 2006) + the claim it supports |
| Dunkels ContikiMAC | <1% duty LPL | Full citation + the "<1% duty" figure |
| El-Hoiydi WiseMAC | phase-learning preamble | Full citation |
| Ye et al. S-MAC | synchronized wake windows | Full citation |
| Heinzelman et al. LEACH | role rotation | Full citation |
| JMAC (arXiv 2312.08387) | LoRa MAC | Confirm arXiv id resolves and supports the claim |
| LoRa-DuCy | LoRa duty-cycling | Resolve to a real publication |
| MDPI Sensors 23(11):4994 | preamble-sampling LoRa multi-hop | Confirm vol/issue/article and content |
| Oller et al. WuR vs duty-cycling (IEEE/ACM ToN) | WuR energy comparison | Full citation |
| 3 µW 868 MHz WuR (JSSC) | −83 dBm WuR (row H5) | Full citation + the µW / sensitivity figures |

None of these were invented here and none is asserted as verified; they are leads to
chase, and the file now says so unambiguously.

## E. Deployment / results claims (mostly MODEL-ONLY or internal)

| # | Claim | Location | Cited source | Status |
|---|---|---|---|---|
| E1 | Relay ITM predictions (Ammo −132 dBm blocked; Jewell −119 dBm marginal; valley links strong) | `reports/project_report.md` | project ITM run over USGS 3DEP | **MODEL-ONLY** — uncalibrated model comparison; explicitly "not observed link states" |
| E2 | Historical FSPL "coverage if deployed" continuous coverage | `reports/project_report.md` map layer | project FSPL screen | **OVERSTATED → withdrawn** — layer label can imply continuous coverage; ledger + report now contradict it and tell readers not to use it as evidence |
| E3 | ~$690 hardware subtotal | `reports/project_report.md` | vendor list (unquoted) | **MODEL-ONLY / caveated** — explicitly "not a deployment cost"; excludes mounting/permits/service |
| E4 | Trial 1 node counts (50 decoded IDs vs 41 RF source IDs; 686 vs 764 records) | `reports/project_report.md`; ledger | internal catalogs | **UNVERIFIED (internal reconciliation pending)** — correctly presented as two non-authoritative counts, not one total |
| E5 | Live-trial delta/RMSE/MAE "calibration" values | `reports/project_report.md`; ledger | `artifacts/airmap/live_trial/` | **OVERSTATED → withdrawn** — zero calibration-eligible rows; filenames are not calibration evidence |
| E6 | DEM/terrain, geology-loss features | `reports/project_report.md` | `dem_transformer.py` synthetic pseudo-DEM | **MODEL-ONLY / synthetic** — explicitly not real elevation data; real USGS 3DEP ingestion pending |
| E7 | Brenta link predictions (all q90 below assumed −131 dBm sensitivity) | `../WITHDRAWN-DO-NOT-CITE/docs/brenta-trial-plan.md` | project ITM q50/q90 | **MODEL-ONLY** — EU/Brenta is descoped for NH work; predictions uncalibrated, no authorization/permission |

## Residual TODOs (not closed by this audit)

1. **R6** — read the exact §15.247(b)/(c) antenna-gain and point-to-point-relief clauses
   before that sentence is used in any external-facing document.
2. **H5 / Section D** — resolve every `algorithm-research.md` shorthand token to a primary
   source with a confirmed DOI/edition; only then may any of those numbers appear in a report.
3. **H8** — attach an explicit citation to the Meshtastic protobuf definition for the
   1e-7 lat/lon and PDOP-encoding claims (currently plausible-but-uncited).
4. **L3** — independently confirm arXiv:2605.17063 resolves and that its content matches the
   note (a 2026 preprint; identity not re-fetched this pass).
5. **L7** — the identity-level Crossref recheck (2026-07-13) was trusted, not re-run per
   entry in this pass; a full per-entry re-fetch remains available if a publication needs it.

This audit changed no scientific conclusion. It attaches sources and status to
externally checkable claims and records exactly what remains unverified.

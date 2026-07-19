> **DESCOPED 2026-07-13 — OUT OF PROJECT SCOPE.** The project is scoped to New
> Hampshire only. The Brenta (Italy/EU) extension is not part of the directed-study
> deliverable: its EU declaration of conformity, CEPT/Italian ERP authorization, and
> refuge/park site permissions are not being pursued. This document is retained as
> historical planning material and must not be cited as active or planned work.

# Brenta Dolomites Trial Plan — 4-Day Hut-to-Hut Extension

Route (booked): Madonna di Campiglio → Passo Grostè → Rif. Tuckett → Rif. Alimonta
(2,580 m) → Rif. Agostini → Molveno. T3 trails with sentiero attrezzato sections;
June snow possible at altitude.

## 1. Why the Brenta is scientifically valuable (the pitch)

1. **It reduces one NH confound.** Much of the route is above treeline, so selected
   segments can reduce canopy loss relative to the Presidentials. It is not a
   “terrain-only” experiment: geology, surface moisture/snow, weather, antenna
   orientation, human-body shadowing, siting, and hardware can still differ.
2. **Structured literature comparison.** Bianco et al. measured LoRa SAR performance
   in the Alps. Using the same model family permits comparison if frequency, link
   geometry, censoring, and sampling differences are reported; it does not make the
   datasets directly interchangeable.
3. **A cross-site transfer check.** Two mountain areas can test whether a model fitted
   at one site transfers to the other under the observed conditions. Two sites are
   not enough to establish generalization across terrain types.
4. **A concrete outreach opportunity.** The repository contains no citable evidence
   that there is no active relay infrastructure in the Brenta, or that any proposed
   node would be the first. Ask local contacts and hut/park authorities; describe the
   infrastructure status as unknown until independently verified.

## 2. ⚠ REGULATORY — must be done before transmitting in Italy

- Do not transmit using the US_915 plan in Italy. For the proposed license-exempt
  operation, evaluate Meshtastic **EU_868** at 869.525 MHz against the current Italian
  national implementation. CEPT ERC/REC 70-03 Annex 1 lists 869.4–869.65 MHz at up
  to 500 mW ERP with a ≤10% duty-cycle or LBT+AFA condition, but the CEPT
  recommendation is not itself proof of Italian authorization for this exact device.
- The SX1262's tuning range only establishes that the silicon can generate the
  frequency. Before use, obtain the exact Heltec model's EU declaration of conformity,
  confirm its RED/EN 300 220 assessment covers the selected firmware, output power,
  antenna, and operating mode, and confirm current Italian spectrum rules. A settings
  change alone does not establish conformity.
- Verify region on EVERY node before departure and pin `frequency_mhz: 869.525` in a
  `model-baseline-eu868.yaml` profile so artifacts carry the correct frequency.
- Airtime screen: the model estimates 559 ms for one 40 B position packet at
  SF11/BW250, or 1.9% at a 30 s cadence. Compliance accounting must include **every
  transmission by each device**—originated beacons, mesh rebroadcasts, acknowledgments,
  telemetry, retries, and administrative traffic—and use measured/firmware-recorded
  airtime. Disable uncontrolled ambient forwarding for the experiment and set a
  conservative aggregate budget; do not infer compliance from beacon airtime alone.
- Use an 868 MHz antenna that is both electrically suitable and permitted by the
  device's conformity documentation; verify the resulting ERP. A different antenna
  can affect both measurement comparability and the authorization basis.
- Flying with lithium: verify each battery's marked Wh rating and the operating
  airline's current rules immediately before travel. Spare cells and power banks must
  remain in carry-on baggage, protected individually against damage and short circuit;
  do not leave them in a gate-checked bag. Up to 100 Wh is the general passenger limit,
  not an unconditional airline acceptance. Installed-device and quantity rules differ,
  and 101–160 Wh normally requires operator approval. Do not carry damaged, swollen,
  recalled, or unmarked packs.

## 3. Prospective predictions (freeze before collecting data)

These numbers are a model-generated prediction record, not observations. They become
a defensible preregistration only after the exact artifact/config/code commit hashes,
analysis rules, and amendment history are made immutable and recorded before the first
measurement. A mutable heading or Git tag is not enough.

ITM/Longley-Rice over Copernicus GLO-30 at 869.525 MHz
(`scripts/brenta_itm_plan.py`, artifacts in `artifacts/itm/brenta_*`):

| Link | Dist | ITM q90 | Model screen |
|---|---|---|---|
| Campiglio → Grostè | 5.96 km | −141 dBm | below assumed −131 dBm sensitivity |
| Grostè → Tuckett | 3.05 km | −146 dBm | below assumed −131 dBm sensitivity |
| Tuckett → Alimonta | 2.15 km | −175 dBm | below assumed −131 dBm sensitivity |
| Alimonta → Agostini | 3.91 km | −172 dBm | below assumed −131 dBm sensitivity |
| Agostini → Molveno | 7.27 km | −180 dBm | below assumed −131 dBm sensitivity |
| Grostè → Molveno | 9.42 km | −160 dBm | below assumed −131 dBm sensitivity |

For these selected endpoints and stated assumptions, the ITM artifact places all six
q90 received-power estimates below the project's assumed −131 dBm sensitivity. That
is a conditional model screen, not proof of zero connectivity. The terrain description
and Fresnel calculations are inputs/checks, not causal proof.

- **H1 (model-challenge test):** a sequence-authenticated, direct-link packet received
  across a preregistered hut pair while both endpoints pass health/time/position gates
  shows that the binary “below sensitivity” screen missed at least one reception under
  those conditions. It does not falsify ITM generally or establish limestone scatter
  as the cause. Report the observed ESP/RSSI, hardware calibration uncertainty, and
  exact model residual.
- **Non-detection interpretation:** zero received packets does not validate ITM. Given
  N verified transmission opportunities, a healthy receiver, and a defensible
  independent-Bernoulli model, the one-sided 95% Clopper–Pearson upper bound is
  `1 - 0.05^(1/N)` (with `3/N` only as a clearly labelled approximation). When packets
  are clustered within passes, use pass/block-aware uncertainty instead. If the
  opportunity or receiver-health denominator is unknown, make no quantitative link
  claim.
- **H2 (calibration sweep):** within each day's open cirque/valley, estimate PDR and
  ESP versus distance with censoring and within-walk dependence accounted for. Compare
  with Bianco et al. descriptively unless protocols and parameter definitions are
  demonstrably compatible. Do not call a sweep complete unless scheduled-opportunity,
  receiver-health, GPS, and direct-link gates pass.
- The intended deliverable is a model-comparison dataset, not a working mesh. It
  becomes calibration-grade only if the preregistered data-quality gates pass.

## 4. Hardware kit (~2.5 kg total experiment weight)

| Item | Qty | Est. weight | Notes |
|---|---|---|---|
| HEAD kit: Pi + Heltec V3 + cabling | 1 | ~450 g | identical collector pipeline as NH (hop fields, JSONL) |
| Garmin (existing watch/unit) | 1 | — | ground-truth track, as in Trial 1 |
| Beacon nodes: Heltec V3 in case | 4 | ~80 g ea | one per night-hut + one for Passo Grostè |
| 10,000 mAh power bank | 4 | ~200 g ea | ≈3.5–4 days at ~110 mA avg RX-on (bench-verify!) |
| 868 MHz antennas | 6 | — | all nodes + spare |
| USB chargers + EU plug adapter | 2 | ~100 g | huts have outlets; hut nodes charge nightly |
| Velcro/zip ties, small dry bags | — | ~100 g | window/railing mounting at huts |
| Laminated info cards (IT/EN) | 5 | — | taped to each node: purpose, contact email/phone, QR to project page, "please do not remove" |

Bench-verify before booking flights: actual Heltec V3 RX-on draw with EU_868 +
position beacon every 30 s, GPS off (beacons are static — survey position with the
Garmin at placement instead; saves ~30 mA).

## 5. Per-day field protocol

**Day 0 (Campiglio):** full bench test in the hotel — all nodes EU_868, beacon
cadence 30 s recorded, hop fields confirmed in JSONL, clocks synced, head readiness
script green. Freeze a final git commit.

**Day 1 (Campiglio → Grostè → Tuckett):** at Passo Grostè (cable-car top), place
beacon #1 only at a pre-authorized location (~2 m), record Garmin waypoint + photo +
antenna orientation, and retrieve it as agreed. Hike path 316 to Tuckett with HEAD
logging — this is sweep #1 (Grostè beacon receding 0→3 km over open karst). At
Tuckett, mount a hut node only if the responsible party has already authorized the
specific window/railing, charging, duration, and retrieval plan.

**Days 2–4 (Tuckett → Alimonta → Agostini → Molveno):** each morning, the previous
night's hut node becomes the transmitter for that day's receding sweep; each evening,
mount + charge the next hut node only under the written permission plan. A successful
day can yield one controlled distance sweep (known cadence plus verified health gives
a PDR denominator), preregistered direct-link observations/non-detections, and a Garmin
track. Nightly: sync JSONL to phone AND laptop (two copies), paper log:
weather tag per segment, placement details, any anomalies.

**Field log discipline:** the NH lesson — record weather_tag manually per segment,
verify GPS pairing BEFORE leaving each hut (Trial 1 Issue 2), and run the readiness
check each morning (Trial 1 Issue 1: the silent collector death cost 2h48m of the
best terrain).

## 6. Leave-behind & retrieval (ranked)

1. **Only with explicit authorization: huts host nodes temporarily.** Obtain written
   hut/land-manager permission, an agreed end date, placement constraints, a responsible
   local contact, and a retrieval/data plan before leaving any powered transmitter.
   Do not call it persistent or first-of-kind infrastructure. Budget loss only after
   the owner and land manager have accepted the arrangement.
2. **Collection during the July Bolzano visit.** The planned EURAC outreach trip
   (Bianco / Mejia-Aguilar) is ~2 h from the Brenta valley towns. A meeting that
   includes "collect the nodes, share the dataset" is a much stronger first
   collaboration than a cold intro — you arrive with Alpine LoRa data measured in
   their backyard against their published models.
3. **Return shipping only under a checked carrier plan.** Postal/courier rules for
   lithium batteries and electronic equipment vary by service, country, packaging,
   and battery state. Do not improvise an international shipment or assume a bare
   board is automatically accepted. Arrange compliant local disposition or a carrier-
   approved return plan in advance.
4. Do NOT cache nodes in the wild: the route crosses Parco Naturale Adamello Brenta.
   A hut warden's consent may not substitute for the property owner's, park's, or radio
   authority's permission; verify the required approvals for both on- and off-structure
   placements.

Email the huts ahead (via the booking provider or hut sites) with the device's radio
operation, power source, mounting, dates, contact, retrieval, and data-handling details.
A reply is useful evidence only if it clearly authorizes those specific activities;
confirm whether park or property-owner permission is also required.

## 7. Collaboration angle (do this before the trek)

Write the Trento/Bolzano contacts a short note: "I'm hiking the Brenta on [dates] and
planning a controlled LoRa propagation experiment (prospective ITM predictions
attached). I have not verified the current Meshtastic infrastructure status and will
leave no equipment without the relevant written approvals. Would the resulting
dataset be useful, and would you be willing to advise on local radio/placement
requirements?" Attach the prospective link table. Do not imply prior confirmation,
interest, or hardware support until a contact replies.

## 8. Prospective analysis plan (freeze required before collection)

Planned pipeline: `airmap_live_trial.py
--require-calibration-grade` with the EU868 config profile; PDR via
`pdr_analysis.py` (beacon cadence known by design); ESP floating-intercept fit per
day-segment with blocked CV + bootstrap CIs; compare n̂/σ̂ against NH Trial 2 and
Bianco et al. only after checking parameter compatibility; H1 model-challenge count =
sequence-authenticated direct-link packets across preregistered hut pairs, with exact
opportunity denominators and receiver-health windows. Treat packets within a walk as
dependent and define the block/bootstrap unit before collection. Copernicus DSM caveat:
it includes canopy below treeline (only the Molveno descent), which may alter the ITM
estimate there; report the limitation rather than assuming the direction or correcting it.

## 9. Pre-departure checklist

- [ ] All nodes flashed/configured EU_868; verified with a live RX test
- [ ] 868 MHz antennas installed (all nodes + spare)
- [ ] `config/airmap/model-baseline-eu868.yaml` committed (869.525 MHz)
- [ ] Beacon cadence set + recorded (30 s); GPS off on static beacons
- [ ] Bench battery test: ≥4 days on 10 Ah bank confirmed
- [ ] Hop fields (`hop_limit`/`hop_start`) present in collector JSONL
- [ ] Prediction/config/code artifact hashes and amendment record frozen before data;
      immutable commit identifier recorded in the field log (a movable tag alone is insufficient)
- [ ] Exact-device EU declaration of conformity and Italian SRD rules checked; antenna,
      firmware, output power, and aggregate-airtime basis recorded
- [ ] Hut/land-manager permission replies saved (Tuckett, Alimonta, Agostini)
- [ ] Trento/Bolzano contacts emailed with prospective prediction table (§7)
- [ ] Laminated node cards printed (IT/EN, contact info, QR)
- [ ] Lithium in carry-on; EU plug adapter; readiness script on phone/laptop
- [ ] Travel insurance covers via ferrata; crampons decision per June snow report

## 10. Regulatory sources to verify immediately before departure

- [CEPT ERC/REC 70-03 record and current annexes](https://docdb.cept.org/document/845)
- [EFIS Annex 1 non-specific SRD parameters](https://efis.cept.org/adhoc_grabber.jsp?annex=4)
- [EU Radio Equipment Directive 2014/53/EU](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32014L0053)
- [Italian Ministry — radio equipment / RED](https://www.mimit.gov.it/it/comunicazioni/radio/apparati-radio)
- [FAA PackSafe — airline passengers and batteries](https://www.faa.gov/hazmat/packsafe/resources/airline-passengers-batteries)
- [IATA — passenger baggage rules](https://www.iata.org/en/programs/ops-infra/baggage/passenger-baggage-rules/)

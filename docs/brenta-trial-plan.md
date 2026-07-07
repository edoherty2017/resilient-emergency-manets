# Brenta Dolomites Trial Plan — 4-Day Hut-to-Hut Extension

Route (booked): Madonna di Campiglio → Passo Grostè → Rif. Tuckett → Rif. Alimonta
(2,580 m) → Rif. Agostini → Molveno. T3 trails with sentiero attrezzato sections;
June snow possible at altitude.

## 1. Why the Brenta is scientifically valuable (the pitch)

1. **It removes the NH confound.** The Presidentials' propagation results mix terrain
   diffraction with forest canopy loss. The Brenta route is almost entirely above
   treeline on bare limestone — terrain-only propagation, the clean test of the
   FSPL-vs-ITM disagreement found at Mt. Washington.
2. **Direct literature comparability.** Bianco et al. (the path-loss exponents cited
   throughout the project: n ≈ 2.0–3.5, σ ≈ 6–8 dB) measured LoRa SAR performance in
   the Alps. Fitting the same floating-intercept model on Brenta data makes the study
   directly comparable to its own reference literature.
3. **Cross-site generalization.** Two sites (granite/schist + mixed forest vs. bare
   limestone karst) turn "calibration of one mountain" into "does the calibrated
   error model transfer across terrain types" — a much stronger thesis claim.
4. **Nobody has nodes there.** Trento/Bolzano faculty confirmed no active relay
   infrastructure in the Brenta. Every node left behind is the seed of the first
   Meshtastic presence in the massif — a concrete collaboration hook (see §7).

## 2. ⚠ REGULATORY — must be done before transmitting in Italy

- **US 915 MHz (902–928) is illegal in Italy.** All nodes MUST be reconfigured to
  Meshtastic region **EU_868** (869.525 MHz; ERC 70-03 sub-band 869.4–869.65 MHz,
  up to 500 mW ERP, **10% duty cycle**). The Heltec V3's SX1262 covers this in
  hardware; it is a settings change, not new radios.
- Verify region on EVERY node before departure and pin `frequency_mhz: 869.525` in a
  `model-baseline-eu868.yaml` profile so artifacts carry the correct frequency.
- Duty cycle check: a 40 B position beacon at SF11/BW250 is 559 ms airtime; at a
  30 s cadence that is 1.9% — comfortably inside the 10% limit. Do not shorten the
  cadence below ~10 s (5.6%).
- Stock antennas are 915-tuned. Order 868 MHz antennas (SMA, ~$5 each) — a mistuned
  antenna costs several dB on both ends and corrupts comparability with NH data.
- Flying with lithium: 18650s and power banks in **carry-on** (≤100 Wh each, fine);
  bare spares in individual pouches. No lithium in checked bags.

## 3. Pre-registered predictions (FROZEN — commit before travel)

ITM/Longley-Rice over Copernicus GLO-30 at 869.525 MHz
(`scripts/brenta_itm_plan.py`, artifacts in `artifacts/itm/brenta_*`):

| Link | Dist | ITM q90 | Verdict |
|---|---|---|---|
| Campiglio → Grostè | 5.96 km | −141 dBm | dead |
| Grostè → Tuckett | 3.05 km | −146 dBm | dead |
| Tuckett → Alimonta | 2.15 km | −175 dBm | dead |
| Alimonta → Agostini | 3.91 km | −172 dBm | dead |
| Agostini → Molveno | 7.27 km | −180 dBm | dead |
| Grostè → Molveno | 9.42 km | −160 dBm | dead |

**ITM predicts ZERO hut-to-hut connectivity** — every rifugio sits in its own cirque
behind 2,900–3,100 m towers (worst Fresnel obstructions −15 to −40, far deeper than
anything at Mt. Washington). This is itself the pre-registered hypothesis:

- **H1 (falsification test):** any direct (hops_away = 0) packet received hut-to-hut
  falsifies the ITM prediction by tens of dB — multipath/scatter off limestone walls
  that the model cannot represent. Even a handful of such packets is a publishable
  observation. Zero such packets = ITM validated in deep-NLOS karst.
- **H2 (calibration sweep):** within each day's open cirque/valley, PDR and ESP vs.
  distance from the morning's hut beacon follow log-distance decay with n and σ in
  the Bianco et al. Alpine range. Each day is one complete, censoring-aware
  link-death profile over bare rock.
- The trek being radio-disconnected hut-to-hut does NOT hurt the experiment: the
  deliverable is calibration data + model validation, not a working mesh.

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

**Day 1 (Campiglio → Grostè → Tuckett):** at Passo Grostè (cable-car top), mount
beacon #1 on a cairn/structure (~2 m), record Garmin waypoint + photo + antenna
orientation. Hike path 316 to Tuckett with HEAD logging — this is sweep #1 (Grostè
beacon receding 0→3 km over open karst). At Tuckett: warden conversation (§7),
mount hut node #2 at a window/railing, on charger, waypoint + photo.

**Days 2–4 (Tuckett → Alimonta → Agostini → Molveno):** each morning, the previous
night's hut node becomes the transmitter for that day's receding sweep; each evening,
mount + charge the next hut node. Every day yields: one controlled distance sweep
(known cadence → PDR), ambient mesh logging (expected: silence — that's H1 data),
and a Garmin track. Nightly: sync JSONL to phone AND laptop (two copies), paper log:
weather tag per segment, placement details, any anomalies.

**Field log discipline:** the NH lesson — record weather_tag manually per segment,
verify GPS pairing BEFORE leaving each hut (Trial 1 Issue 2), and run the readiness
check each morning (Trial 1 Issue 1: the silent collector death cost 2h48m of the
best terrain).

## 6. Leave-behind & retrieval (ranked)

1. **Best: huts keep the nodes running.** Ask each warden to keep the node mounted
   and powered (it draws less than a phone charger). Each rifugio becomes a
   persistent node — the first Meshtastic infrastructure in the Brenta, and a
   long-duration ambient dataset if any future hiker carries a node through. Leave
   the laminated card + a contact sheet. Cost if never recovered: ~$40/node — budget
   them as consumables from the start.
2. **Collection during the July Bolzano visit.** The planned EURAC outreach trip
   (Bianco / Mejia-Aguilar) is ~2 h from the Brenta valley towns. A meeting that
   includes "collect the nodes, share the dataset" is a much stronger first
   collaboration than a cold intro — you arrive with Alpine LoRa data measured in
   their backyard against their published models.
3. **Mail-back WITHOUT batteries.** International post refuses/restricts loose
   lithium. If a hut mails a node back: batteries stay (gift them), bare Heltec ships
   fine in a padded envelope. Pre-pay/arrange this at check-in, leave a labeled
   envelope.
4. Do NOT cache nodes in the wild: the route crosses Parco Naturale Adamello Brenta;
   unattended equipment off-structure needs park permission you don't have. Hut
   placements with warden consent avoid the issue entirely.

Email the huts ahead (via the booking provider or hut sites) asking permission for a
"small, silent, battery-powered scientific radio logger (~80 g)" — wardens say yes
far more often when asked in advance, and a reply email is your written permission.

## 7. Collaboration angle (do this before the trek)

Write the Trento/Bolzano contacts a short note: "I'm hiking the Brenta on [dates],
running a calibrated LoRa propagation experiment (pre-registered ITM predictions
attached); there is currently no Meshtastic infrastructure in the massif — I'll be
leaving powered nodes at Tuckett/Alimonta/Agostini with warden consent. Interested
in the dataset, or in adopting the nodes afterward?" Attach the pre-registered link
table. Even professors with no active nodes will engage with a concrete dataset
offer — and someone may volunteer to collect the hardware.

## 8. Analysis plan (pre-committed)

Identical pipeline, no new methodology: `airmap_live_trial.py
--require-calibration-grade` with the EU868 config profile; PDR via
`pdr_analysis.py` (beacon cadence known by design); ESP floating-intercept fit per
day-segment with blocked CV + bootstrap CIs; compare n̂/σ̂ against NH Trial 2 and
Bianco et al.; H1 falsification check = count of hops_away=0 packets across any
hut-to-hut pair. Copernicus DSM caveat: it includes canopy below treeline (only the
Molveno descent), which biases ITM conservative there — note it, don't correct it.

## 9. Pre-departure checklist

- [ ] All nodes flashed/configured EU_868; verified with a live RX test
- [ ] 868 MHz antennas installed (all nodes + spare)
- [ ] `config/airmap/model-baseline-eu868.yaml` committed (869.525 MHz)
- [ ] Beacon cadence set + recorded (30 s); GPS off on static beacons
- [ ] Bench battery test: ≥4 days on 10 Ah bank confirmed
- [ ] Hop fields (`hop_limit`/`hop_start`) present in collector JSONL
- [ ] Pre-registered predictions committed (`artifacts/itm/brenta_*`) — git tag `brenta-prereg`
- [ ] Hut permission emails sent (Tuckett, Alimonta, Agostini)
- [ ] Trento/Bolzano contacts emailed with prereg table (§7)
- [ ] Laminated node cards printed (IT/EN, contact info, QR)
- [ ] Lithium in carry-on; EU plug adapter; readiness script on phone/laptop
- [ ] Travel insurance covers via ferrata; crampons decision per June snow report

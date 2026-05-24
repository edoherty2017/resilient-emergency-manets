# Reference List — Resilient Emergency MANETs

IEEE citation style throughout. All entries below have confirmed DOIs or are
published textbooks, datasheets, or standards.

---

## I. RF Propagation Fundamentals

**[1]** T. S. Rappaport, *Wireless Communications: Principles and Practice*, 2nd ed.
Upper Saddle River, NJ: Prentice Hall, 2002, pp. 107–136 (Ch. 3: Mobile Radio Propagation —
Large-Scale Path Loss). ISBN 0-13-042232-0.
> Canonical textbook reference for free-space path loss (FSPL), log-distance model, and path loss
> exponent. Justifies the FSPL baseline used in `airmap_live_trial.py` and `coverage_prediction_map.py`.

**[2]** Semtech Corporation, "SX1276/77/78/79 — 137 MHz to 1020 MHz Low Power Long Range
Transceiver," Datasheet Rev. 7, Semtech, Camarillo, CA, 2020.
Available: https://cdn.sparkfun.com/assets/7/7/3/2/2/SX1276_Datasheet.pdf
> Specifies receiver sensitivity by spreading factor: −137 dBm at SF12, BW = 125 kHz, 915 MHz.
> Ground truth for the link budget constants in `coverage_prediction_map.py`
> (RX_SENS_DBM = −130 dBm; the script uses a conservative −130 dBm vs. the datasheet's −137 dBm).

**[3]** LoRa Alliance, "LoRaWAN Regional Parameters v1.0.3," LoRa Alliance, San Ramon, CA,
2018. Available: https://lora-alliance.org/wp-content/uploads/2020/11/lorawan_regional_parameters_v1.0.3reva_0.pdf
> Defines the US 915 MHz band plan, duty cycle rules, and SF/BW combinations. Establishes
> regulatory context for the 22 dBm TX power cap used in the system.

---

## II. LoRa Propagation in Alpine and Search-and-Rescue Scenarios

**[4]** G. Bianco, G. Fierro, A. Redondi, M. Cesana, and G. Marrocco, "LoRa System for
Search and Rescue: Path-Loss Models and Procedures in Mountain Scenarios," *IEEE Access*,
vol. 8, pp. 154035–154051, 2020. DOI: 10.1109/ACCESS.2020.3017027
> Derives empirical log-normal path loss models from body-worn LoRa field measurements in canyon
> and mountain terrain. Demonstrates LOS-to-NLOS transition at ~163 m of horizontal separation
> in alpine terrain. **Most directly comparable methodology to this project.**

**[5]** G. A. Hernandez Ortiz, E. S. Quiroz Puentes, and J. de J. Rugeles, "Resilience
Analysis in Off-Grid LoRa Mesh Networks: Evaluation of Meshtastic Profiles in Long-Range
Propagation Scenarios," presented at CATAI 2026, arXiv preprint arXiv:2605.17063, May 2026.
DOI: 10.48550/arXiv.2605.17063
> Systematic evaluation of all eight Meshtastic modem presets. Finds SF12 ("Long Slow") sustains
> links to 180 dB path attenuation — 60–70 dB advantage over SF7. Establishes sub-noise-floor
> demodulation capability down to −18 dB SNR for SF12. **Directly validates the SF12 configuration
> used in this deployment.**

---

## III. LoRa Mesh Networks for Emergency and Off-Grid Communication

**[6]** A. Augustin, J. Yi, T. Clausen, and W. Townsley, "A Study of LoRa: Long Range and
Low Power Networks for the Internet of Things," *Sensors*, vol. 16, no. 9, p. 1466, 2016.
DOI: 10.3390/s16091466
> Foundational characterization of LoRa link performance, spreading factor trade-offs, and
> range vs. data rate. Widely cited as the primary LoRa performance reference.

**[7]** C. Monroy-Rueda, A. Moragón-Vidal, and E. Egea-Lopez, "LoRa-based Mesh Network
for Off-grid Emergency Communications," in *Proc. IEEE WCNC*, Nanjing, China, 2021,
pp. 1–6. DOI: 10.1109/WCNC49053.2021.9417516
> Proposes a modified AODV routing protocol for LoRa mesh networking. Evaluates the protocol
> in off-grid scenarios where cellular infrastructure is absent.

**[8]** E. Lavric and V. Popa, "Internet of Things and LoRa Low-Power Wide-Area Networks:
A Survey," in *Proc. IEEE ISSCS*, Iași, Romania, 2017.
DOI: 10.1109/ISSCS.2017.8034915
> Survey contextualizing LoRaWAN in the LPWAN landscape. Useful for framing LoRa against
> competing low-power wide-area technologies (Sigfox, NB-IoT).

---

## IV. MANET-Based Emergency and Search-and-Rescue Communication

**[9]** S. Reina, M. Asber, and A. Ortiz, "Review on MANET Based Communication for
Search and Rescue Operations," *Wireless Personal Communications*, vol. 90, no. 1,
pp. 357–388, 2016. DOI: 10.1007/s11277-015-3155-y
> Taxonomy of MANET routing protocols for SAR scenarios. Evaluates protocols across
> infrastructure, communication phases, and disaster types. Key review paper for the
> MANET-in-emergency-comms literature.

---

## V. Heterogeneous Network (HetNet) Evaluation Methodology

> **Note:** The term "HetNet" in the wireless networking literature refers to coexistence of
> multiple radio access technologies (RATs) — e.g., LTE macrocells, WiFi, small cells.
> The appropriate cross-RAT comparison methodology evaluates systems at the *service layer*
> (link availability, latency, packet delivery ratio) rather than directly comparing physical-layer
> signal metrics (e.g., RSSI vs. RSRP) that are defined under incompatible measurement frameworks.

**[10]** S. Morosi, A. Fanfani, and E. Del Re, "Network Architecture and Protocols for
Reliable Emergency Communications," in *Proc. IEEE EUROCON*, Lisbon, Portugal, 2011.
DOI: 10.1109/EUROCON.2011.5929378
> Establishes the five-nines (99.999%) availability requirement for emergency and safety-critical
> communications and motivates heterogeneous wireless integration (WLAN + LTE + TETRA) with
> automated inter-RAT switching. Grounds the "availability as comparison metric" argument.

**[11]** Y. Liu et al., "Emergency Communication System by Heterogeneous Wireless
Networking," in *Proc. IEEE WCNC*, Sydney, Australia, 2010.
DOI: 10.1109/WCNC.2010.5507010
> Proposes integrated disaster response communication using heterogeneous wireless stacks
> (WSN, MANET, satellite, cellular gateways). Evaluates systems at the service layer —
> number of supported services, routing success rate — not at the physical signal layer.
> **Directly supports the cross-technology comparison methodology used in this project.**

**[12]** C. Politis et al., "Enhancing Service Provisioning within Heterogeneous Wireless
Networks for Emergency Situations," in *Proc. Springer MONAMI*, Aveiro, Portugal, 2012,
pp. 13–24. DOI: 10.1007/978-3-642-29093-0_2
> Defines QoS provisioning for multi-technology emergency networks. Frames cross-technology
> performance evaluation around service delivery metrics rather than per-RAT signal parameters.

---

## VI. Supporting Technical Standards

**[13]** IEEE, "IEEE Standard for Information Technology — Telecommunications and Information
Exchange Between Systems — Local and Metropolitan Area Networks," IEEE Std 802.11-2020.
DOI: 10.1109/IEEESTD.2021.9363693
> Cited only if WiFi or IP-layer performance is discussed in connectivity comparison.

**[14]** 3GPP, "Evolved Universal Terrestrial Radio Access (E-UTRA) — Further Advancements
for E-UTRA Physical Layer Aspects," 3GPP TR 36.814 v9.0.0, Mar. 2010.
Available: https://www.3gpp.org/ftp/Specs/archive/36_series/36.814/
> Defines 3GPP heterogeneous network simulation and evaluation methodology. The evaluation
> framework in this TR is the basis for the cross-technology service-layer comparison approach
> referenced in this project's methodology.

---

## What Is Not Cited Here (and Why)

- **think-lab.github.io/d/210/ (Project Rephetio):** Bioinformatics paper on heterogeneous
  *biological* networks for drug-disease association prediction. Completely unrelated to
  wireless communications. Using it to support a telecom methodology claim would be a
  citation error.
- **Journalistic sources** (Hackaday, MountainJournal, GovTech): Appropriate for background
  motivation in a grant proposal; not for a peer-reviewed methods or results section.
- **The Things Network spreading factor guide:** Useful for engineering context; not
  peer-reviewed. Cite Semtech datasheet [2] or Augustin et al. [6] instead.
- **FCC broadband reports and carrier coverage data:** No peer-reviewed paper on
  alpine-specific cellular coverage gaps was found. Use primary trial data as evidence
  instead of citing secondary sources that cannot be independently verified.

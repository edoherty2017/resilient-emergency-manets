# Reference List — Resilient Emergency MANETs

IEEE citation style throughout. Bibliographic metadata and DOI targets were
rechecked against Crossref and publisher records on 2026-07-13. A DOI proves
the identity of a source, not the project's interpretation of it; the notes
below therefore distinguish source facts from project-specific engineering
choices. Preprints are labelled explicitly.

---

## I. RF Propagation Fundamentals

**[1]** T. S. Rappaport, *Wireless Communications: Principles and Practice*, 2nd ed.
Upper Saddle River, NJ: Prentice Hall, 2002, pp. 107–136 (Ch. 3: Mobile Radio Propagation —
Large-Scale Path Loss). ISBN 0-13-042232-0.
> Canonical textbook reference for free-space path loss (FSPL), log-distance model, and path loss
> exponent. Justifies the FSPL baseline used in `airmap_live_trial.py` and `coverage_prediction_map.py`.

**[2]** Semtech Corporation, "SX1261/SX1262 Long Range, Low Power, sub-GHz RF
Transceivers," datasheet, current release listed Apr. 7, 2025.
Available: https://www.semtech.com/products/wireless-rf/lora-connect/sx1262
> This is the transceiver family used by the stated Heltec V3 hardware. Sensitivity
> depends on the exact SF, bandwidth, coding, measurement conditions, RF board, and
> implementation. A “down to” headline or a value from another row/device must not be
> used as the LongFast receiver threshold; the project's −131 dBm value remains an
> assumption until tied to the exact datasheet row and bench characterization.

**[3]** LoRa Alliance, "LoRaWAN Regional Parameters v1.0.3," LoRa Alliance, San Ramon, CA,
2018. Available: https://lora-alliance.org/wp-content/uploads/2020/11/lorawan_regional_parameters_v1.0.3reva_0.pdf
> Defines LoRaWAN regional channel/default parameters; it is not an FCC rule, an
> equipment authorization, or documentation of Meshtastic's proprietary preset.
> The project's frequency and 22 dBm setting require their own legal and hardware basis.

---

## II. LoRa Propagation in Alpine and Search-and-Rescue Scenarios

**[4]** G. M. Bianco, R. Giuliano, G. Marrocco, F. Mazzenga, and A. Mejia-Aguilar,
"LoRa System for Search and Rescue: Path-Loss Models and Procedures in Mountain
Scenarios," *IEEE Internet of Things Journal*, vol. 8, no. 3, pp. 1985–1999, 2021.
DOI: 10.1109/JIOT.2020.3017044
> Reports mountain search-and-rescue LoRa path-loss measurement and modelling procedures.
> It is methodologically relevant, but its fitted parameters are not evidence that this
> project's White Mountains links have the same propagation distribution.

**[5]** G. A. Hernandez Ortiz, E. S. Quiroz Puentes, and J. de J. Rugeles, "Resilience
Analysis in Off-Grid LoRa Mesh Networks: Evaluation of Meshtastic Profiles in Long-Range
Propagation Scenarios," arXiv preprint arXiv:2605.17063, May 2026.
DOI: 10.48550/arXiv.2605.17063
> An unreviewed preprint evaluating Meshtastic modem profiles. Its reported results are
> supporting context only; they do not directly validate this project's hardware,
> terrain, link budget, or deployment configuration.

---

## III. LoRa Mesh Networks for Emergency and Off-Grid Communication

**[6]** A. Augustin, J. Yi, T. Clausen, and W. Townsley, "A Study of LoRa: Long Range and
Low Power Networks for the Internet of Things," *Sensors*, vol. 16, no. 9, p. 1466, 2016.
DOI: 10.3390/s16091466
> Foundational characterization of LoRa link performance, spreading factor trade-offs, and
> range vs. data rate. Widely cited as the primary LoRa performance reference.

**[7]** K. C. V. G. Macaraeg, C. A. G. Hilario, and C. D. C. Ambatali,
"LoRa-based Mesh Network for Off-grid Emergency Communications," in *Proc. 2020
IEEE Global Humanitarian Technology Conference (GHTC)*, 2020, pp. 1–4.
DOI: 10.1109/GHTC46280.2020.9342944
> Evaluates a LoRa mesh design for off-grid emergency communication. Applicability
> to this project's routing and traffic assumptions must be established by comparison,
> not inferred from the shared use of LoRa.

**[8]** E. Lavric and V. Popa, "Internet of Things and LoRa Low-Power Wide-Area Networks:
A Survey," in *Proc. IEEE ISSCS*, Iași, Romania, 2017.
DOI: 10.1109/ISSCS.2017.8034915
> Survey contextualizing LoRaWAN in the LPWAN landscape. Useful for framing LoRa against
> competing low-power wide-area technologies (Sigfox, NB-IoT).

---

## IV. MANET-Based Emergency and Search-and-Rescue Communication

**[9]** S. S. Anjum, R. Md. Noor, and M. H. Anisi, "Review on MANET Based
Communication for Search and Rescue Operations," *Wireless Personal Communications*,
vol. 94, no. 1, pp. 31–52, 2017. DOI: 10.1007/s11277-015-3155-y
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

**[10]** A. G. Fragkiadakis, I. G. Askoxylakis, E. Z. Tragos, and C. V. Verikoukis,
"Ubiquitous Robust Communications for Emergency Response Using Multi-operator
Heterogeneous Networks," *EURASIP Journal on Wireless Communications and
Networking*, vol. 2011, art. 13, 2011. DOI: 10.1186/1687-1499-2011-13
> Presents an emergency-response architecture spanning heterogeneous public and
> private access networks. It supports evaluating end-to-end availability and service
> delivery, but does not establish a five-nines requirement for this project.

**[11]** Y. Bai, W. Du, Z. Ma, C. Shen, Y. Zhou, and B. Chen, "Emergency
Communication System by Heterogeneous Wireless Networking," in *Proc. 2010 IEEE
International Conference on Wireless Communications, Networking and Information
Security (WCNIS)*, 2010, pp. 488–492. DOI: 10.1109/WCINS.2010.5541719
> Proposes integrated disaster response communication using heterogeneous wireless stacks
> (WSN, MANET, satellite, cellular gateways). Evaluates systems at the service layer —
> number of supported services, routing success rate — not at the physical signal layer.
> Provides relevant architectural precedent. It does not, by itself, validate this
> project's particular cross-technology scoring method.

**[12]** C. Lottermann, A. Klein, H. D. Schotten, and C. Mannweiler, "Enhancing
Service Provisioning within Heterogeneous Wireless Networks for Emergency Situations,"
in *Mobile Networks and Management*, Lecture Notes of the Institute for Computer
Sciences, Social Informatics and Telecommunications Engineering, vol. 97, 2012,
pp. 14–23. DOI: 10.1007/978-3-642-29093-0_2
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
> Provides 3GPP system-level evaluation context for E-UTRA heterogeneous deployments.
> It does not by itself establish this project's LoRa/cellular/Starlink service-layer
> scoring method; that method needs its own operational definitions and validation.

---

## VII. Additional Methods Cited by the Trial 1 Report

**[15]** G. M. Bianco, A. Mejia-Aguilar, and G. Marrocco, “Performance Evaluation
of LoRa LPWAN Technology for Mountain Search and Rescue,” in *Proc. 5th International
Conference on Smart and Sustainable Technologies (SpliTech)*, 2020, pp. 1–4.
DOI: 10.23919/SpliTech49282.2020.9243817
> A mountain-SAR measurement study relevant for methodological comparison. It does
> not validate this project's sites, configuration, or propagation predictions.

**[16]** J. A. Azevedo and F. Mendonça, “A Critical Review of the Propagation Models
Employed in LoRa Systems,” *Sensors*, vol. 24, no. 12, p. 3877, 2024.
DOI: 10.3390/s24123877
> Reviews LoRa propagation modelling and ESP/RSSI limitations. As a review, it is a
> source for methods and cautions rather than local calibration evidence.

**[17]** Q. Guo, F. Yang, and J. Wei, “Experimental Evaluation of the Packet Reception
Performance of LoRa,” *Sensors*, vol. 21, no. 4, p. 1071, 2021.
DOI: 10.3390/s21041071
> Laboratory evaluation of LoRa physical-layer parameter trade-offs; its hardware and
> setup are not interchangeable with the project's field configuration.

**[18]** E. J. Oughton, T. Russell, J. Johnson, C. Yardim, and J. Kusuma,
“itmlogic: The Irregular Terrain Model by Longley and Rice,” *Journal of Open Source
Software*, vol. 5, no. 51, p. 2266, 2020. DOI: 10.21105/joss.02266
> Documents the software implementation used for terrain-model screens. Correct
> software citation does not validate project-specific inputs or predictions.

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

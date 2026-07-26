# Final report specification — verified against the advisor record (2026-07-26)

Built by a 8-agent audit of the advisor communications and the full repo, then
adversarially verified twice (evidence-path trace check: PASS with 6 precision
fixes; advisor-proxy compliance check: 4 blockers, all incorporated below).
This document is the authoritative spec for rebuilding
`reports/final-directed-study-report-*.md` into the submission version.

## 1. The reference point: what was last agreed with Basagni

The controlling exchange is the **2026-07-21 email** (captured verbatim in
`docs/advisor-acceptance-criteria-2026-07-21.md` — NOTE: that doc itself is
untracked in git and must be committed; it is the document the assessment is
made against). It sets:

**Framing (confirmed by advisor):** "Trial 1 as a systems shakedown, the
simulation framework as the central completed contribution, and Trial 2 as the
controlled empirical test of the frozen predictions."

**Five requirements** (verbatim in the criteria doc): honest Trial 2 reporting
incl. underpowered strata; headline claims only from corrected sim runs or
Trial 2 measurements with superseded numbers archived; focused contribution
(year-scale survivability — duty-cycling, idle listening, delivery ratio, SOS
latency); explicit limitations (calibration, few field sites, purpose-built
simulator not independently validated); conservative safety/weather/radio
operation.

**Five-item final package:** frozen protocol pack · raw dataset · scored
results · corrected simulation package · full written report → Guevara
sign-off.

**Inherited proposal objective** (not in the email, but the assessment
inherits it): ≥2,500-point calibration dataset — **UNMET (0 points), stated in
those words.**

## 2. Milestone scorecard (statuses as verified — no inflation)

| id | requirement/deliverable | status | how |
|---|---|---|---|
| FRAMING | shakedown / central sim / controlled Trial 2 | ACHIEVED_WITH_CAVEAT | 2026-07-17 report already adopts it; §7 must be rebuilt on the real Jul 18–26 record |
| R1 honest Trial 2 | label underpowered/inconclusive, omit nothing | PARTIAL → ACHIEVED by this rebuild | evidence discipline complete (all failures preserved w/ raw; nulls registered pre-collection); the WRITTEN report must now say: zero calibration-eligible strata, ≥40-opportunity target unmet |
| R2 corrected-numbers-only | headline claims from corrected runs or Trial 2 only | ACHIEVED_WITH_CAVEAT | verified: every §5.2/5.3 number traces to release_v1; fix 5 unarchived prose numbers (47+3 tests, 53 m, 13.9%, ~48 s, −72.9 dBm) — archive or delete |
| R3 focused contribution | survivability/duty/idle/PDR/SOS | ACHIEVED_WITH_CAVEAT | release_v1 delivers the axis: routing indistinguishable on deaths (<0.3% spread) vs duty 5.5–24× reduction, PDR/SOS costs explicit; purge off-axis volume (below) |
| R4 explicit limitations | calibration, sites, no third-party validation | ACHIEVED_WITH_CAVEAT | all three present in current report; ADD: dirty-worktree provenance, release_v2 incomplete, statewide parity pending, in-doc-hash registrations, **production fixed-relay FCC authorization unresolved (per compliance memo — advisor-named, was missing from draft spec)** |
| R5 conservative operation | compliant, appropriate config | ACHIEVED (compressed treatment, per Ethan 2026-07-26) | one factual ops note in §9: stock FCC-certified consumer hardware, unmodified firmware/TX power, standard US 915 MHz ISM-band frequencies, default channel-access behavior, own traffic, equipment retrieved same day; plus the single advisor-named limitation line in §10. All other regulatory history/analysis purged from the report body. (Do NOT write "correct duty cycle" — no duty-cycle rule exists in the US band; the supportable phrasing is "stock channel-access behavior of the certified device.") |
| P1 frozen protocol pack | | SPLIT: **ACHIEVED** (2026-07-19 Washington prereg: prereg_manifest.json, git 3d15a57, clean worktree, 12 hashed inputs) / **PARTIAL** (Moosilauke/Monadnock/Pack packs: in-doc SHA-256s only, gitignored artifacts, pending E1 commit) |
| P2 raw dataset | | PARTIAL | raw preserved (20260721 + 20260726 w/ SHA256SUMS on main streams); **`build_dataset_release.py` never run — pre-submission action added** (honest zero-calibration-grade evidence release + manifest; hash-harden 20260721 + drive files) |
| P3 scored results | | PARTIAL | Trial 1 scored (calibration_eligible_count=0); Pack Monadnock scored in **two tiers, never "0/4 registered"**: Tier 1 hash-registered pack = 0/1 CONTACT (Greenville) + Keene null HELD; Tier 2 supplement = 0/3, provenance explicitly weaker (hash f50bda83cb60f5f60a4a466806abcfb3b50489fef4722ed183a97b97fd153c5f recorded here, post-hoc — first durable record); nulls transmit-censored (stations 0–4 TX/hr; own node stock cadence); all decodes hop-relayed (zero hops_away==0) |
| P4 corrected sim package | | ACHIEVED_WITH_CAVEAT | release_v1 hash-locked (45 runs, 9 modes × seeds 42–46 × 365 d) + micro-parity 18/18 (2026-07-17 rerun supersedes the manifest's older parity note — say so) + byte-identity repro; disclose dirty worktree + d37172c/f5e83f0 inconsistency; release_v2 not citable (5/9 modes, no manifest) |
| P5 full written report | | PARTIAL → the rebuild specified here completes it |
| A5 ≥2,500 points | | **UNMET** | 0 calibration-grade points; measured reasons (broken beacon rig, USB failure, TX-censoring, hop ambiguity); ≥40-opportunity amendment is PROPOSED, not approved — present as pending |

## 3. Report structure (12 sections + 3 appendices)

0. **Claim policy & provenance** — artifact-backed or MODEL-ONLY; WITHDRAWN
   firewall; note post-07-19 registrations rest on in-doc hashes pending E1.
1. **Executive summary** — contribution inverted (sim central; Trial 2 honest
   campaign, calibration unmet); duty-not-routing MODEL-ONLY headline;
   status line: 0 of ≥2,500 calibration points; first operationally successful
   field day 2026-07-26 with "registered binary-contact scoring in progress"
   — **no miss-count in §1** (tiered count lives in §9.5 only).
2. **Objectives, amendments, what changed** — proposal criteria table with
   honest outcomes; RSRP→ESP (drafted, UNSIGNED — A1), ≥40-rule (proposed);
   regulatory row reduced to one factual line: "operated stock certified
   hardware as marketed (A2); production-deployment authorization deferred";
   NH-only descope.
3. **Simulator architecture** — two engines; constants labeled BENCH-CALIBRATE;
   TTL 600 s cited to `fastsim/src/sim.rs` (not the yaml).
4. **Why purpose-built, not ns-3** — ex-post rationale, flagged; ns-3 = the
   future third-party check.
5. **Verification** — micro-parity 18/18 (worst 0.0045 PDR abs / 1.3% airtime);
   byte-identity repro (4 runs, sha 9d182b0d…); statewide parity PENDING;
   archive a cargo-test log or drop the "47+3" number.
6. **Trial 1 shakedown** — reconciled counts (65,271 lines / 65,268 parseable
   convention stated); zero calibration-eligible (footnote: quality_gates
   "passed" flag = relaxed operational gate, not the calibration gate);
   ITM-vs-FSPL and statewide screen **labeled model-to-model, MODEL-ONLY,
   confined to §6 + Appendix C, never §1**.
7. **Corrected year-scale results (release_v1)** — the 9-mode table; provenance
   disclosure; no winner declared (manifest note is binding).
8. **Central insight** — duty policy, not routing, governs survivability;
   forbidden withdrawn forms listed (12.4×, 0.06%, 7–15×, 99.98%, 74 Wh knee,
   $5k, RL rankings).
9. **Trial 2: frozen predictions & the honest field record** — open the
   section with the causal frame, stated plainly: **the two-radio
   controlled-beacon protocol could not be executed because the beacon node's
   hardware failed in the field week (internal battery would not charge, then
   the USB-C port broke); Trial 2 was therefore adjusted — registered before
   collection — to a receiver-only day scoring prospective public-station
   contact predictions.** The beacon packs stay frozen for a future two-radio
   day. Include the one-paragraph radio-ops note here (stock certified
   hardware, unmodified firmware/power, standard US 915 MHz ISM frequencies,
   default channel-access behavior, own traffic, same-day retrieval).
   Then chronological:
   prereg + Amendment 1 + 07-19 freeze (scope stated precisely: binds the
   Washington pack; fieldday packs registered via in-doc hashes 2026-07-23,
   "before any calibration-eligible data" — and disclose the 22 pre-freeze
   Jul-19 rig rows); attempts 1–3 failure record; ecosystem finding
   (MeshCore migration, checksummed snapshot); Monadnock registered-never-
   executed; **Pack Monadnock 2026-07-26**: first operationally successful
   day — protocol executed, raw + hashes, summit dwell 13:31–14:04Z, receiver
   PROVEN working (foreign frames incl. one during the dwell at −117 dBm),
   two-tier contact scoring pending Ethan's confirmation, both quantified
   field findings (transmit-opportunity starvation: 0–4 TX/hr × 13-min dwell;
   hop ambiguity: 6/6 decodes relayed) as the empirical justification of the
   controlled-beacon protocol; trial_id anomalies disclosed (27 pre-departure
   rows 10:07–11:5xZ; 8 post-hike drive rows).
10. **Limitations** — advisor's three verbatim-adjacent + full honest list +
    the single retained regulatory line (advisor-named, do not cut):
    "authorization for a production fixed-relay deployment remains an open
    question" (cite docs/fcc-part15-compliance-memo.md once, here only).
11. **Process findings & audit record** — defects real and repaired; quarantine
    mechanism; ledger wording on no-deception.
12. **Future work** — release_v2 completion; bench calibration (G2); the
    two-radio beacon day (~$25 board) to score the frozen packs; statewide
    parity; ns-3 spot-check; advisor-decided amendments.

**Appendix A** Evidence map (every row → archived artifact, pinned by SHA-256)
+ **Reproduction instructions preamble** (regenerate release_v1 aggregates,
re-verify hashes, rerun parity/repro — restores the proposal's "advisor can
independently rerun" criterion; the no-run-it-yourself rule bans claims that
REQUIRE rerunning, it does not remove rerun instructions).
**Appendix B** Advisor compliance map (verbatim requirement → where satisfied;
statuses match §2 of this spec — PARTIAL/UNMET stated plainly).
**Appendix C** Frozen prediction packs & scoring ledger (Washington deferred,
Moosilauke frozen-unscored, Kearsarge ITM-deaf deferred, Monadnock registered-
unexecuted, Pack Monadnock two-tier scored-pending-confirmation).

## 4. Purge list (what the report omits, and why)

OMIT ENTIRELY: statewide build-out corpus (polygons, proposal map, BOM —
advisor-named scope creep; sole exception: the statewide screen cited as a
FAILING internal model-to-model check); Brenta/Italy (descoped 2026-07-13);
all RL/ML routing + Algorithm Arena results (withdrawn training data;
release_v1 contains no RL mode); Starlink/cellular/Garmin backhaul
comparisons; rescue_links SAR studies; sim viewers + 65 MB traces; the
withdrawn experiment suite (E1–E7, 89 sim-years); every withdrawn headline
number; stale "corrected_*" trap files at corrected/ root + sweep/; ledger
one-day smoke numbers; release_v2 partials; PM/logistics/checklist docs; NH
F&G kiosk pack; ops/ingest plumbing.
OMIT ENTIRELY (added 2026-07-26, per Ethan): all regulatory history and
analysis — Part 97 selection/reversal, callsign discussion, compliance-memo
§15.247/§15.249 analysis, FHSS-premise discussion, FCC-ID photo requirement.
Survivors: the §9 factual ops note + the §10 advisor-named limitation line.
ONE-LINE MENTION: RSRP→ESP amendment (drafted, unsigned — pending A1); field
viewers (illustrations, never evidence); MeshCore/live-map tooling; old xval
maxima (labeled withdrawn history).
APPENDIX ONLY: routing/algorithm survey docs; propagation/DEM/link-budget
method detail (geology priors flagged uncited/unused — A3).

## 5. Pre-submission actions (from the verifiers)

1. **E1 commit (needs Ethan):** `git add -f` (or .gitignore exceptions
   mirroring lines 76–77) for predictions_fieldday.{csv,manifest}, both
   livemesh JSONs + supplement; plus the two siting docs, the advisor-criteria
   doc, this spec, and modified scripts. Update open-decisions E1 wording
   (currently says RESOLVED-2026-07-07; the ongoing rule lives in its caveat).
2. Run `build_dataset_release.py` over Trial 1 + both raw pulls → honest
   zero-calibration-grade evidence release with manifest; add SHA256SUMS for
   raw_pull_20260721 and the drive files.
3. Record full (untruncated) SHA-256s for both Pack Monadnock JSONs in a dated
   addendum (supplement hash now recorded in §2 above).
4. Archive a cargo-test log (or drop the test-count claim); archive or delete
   the five unarchived prose numbers.
5. RESOLVED 2026-07-26 (Ethan): no phone evidence exists — the Pi log is the
   complete instrument record and the Jul 26 scoring is final on it (drop the
   "pending confirmation" hedge; state the evidence basis plainly). A1 stays a
   disclosed pending line. Ship on release_v1 with provenance disclosed
   (release_v2 noted as incomplete in Limitations/Future work). FCC-ID photo
   requirement dropped with the compressed regulatory treatment. AllTrails
   phone track offered but not required (Pi 1 Hz GPS is primary; archive only
   if provided).

# Wake-up radio (WuR) mode — design spec

Status: **v2 (2026-07-31)** — v1 revised after a three-judge adversarial
design review (physics, engine invariants, parity/experiments); all seven
blockers and the material minors are incorporated below. MODEL-ONLY by
construction; extends the framework without touching release_v1 or the nine
released modes. **Canonical tree: `/Users/ethandoherty/MANET/
resilient-emergency-manets`** (all anchors, edits, and parity runs there; the
MANNET sibling checkout is not touched).

## 1. Concept

Every solar relay carries a second, ultra-low-power wake-up receiver (WuR).
The main radio sleeps (µW idle). To forward across link A→B, A's
transmission is preceded by a wake chirp; if B's WuR hears it, B boots the
main radio, receives, forwards likewise, and returns to sleep after a
hangover window. Sleep no longer implies unreachability — but the wake
channel is a *worse* radio than the data channel, and the study quantifies
that asymmetry: wake-range shrinkage of the effective topology, per-hop wake
latency, and chirp airtime.

## 2. Model parameters (config `wur:`, CLI-overridable)

| key | default | basis |
|---|---|---|
| `wur_idle_ma` | 0.001 | ≈3 µW @3.7 V (literature class; survey in docs/algorithm-research.md) |
| `wake_sensitivity_delta_db` | 55.0 | µW OOK WuRs ≈ −60…−90 dBm vs main −131 dBm ⇒ realistic delta ∈ [41, 71]; default mid-bracket (judged: 40 dB = best-published aggressive end, not the default) |
| `wake_chirp_ms` | 20.0 | OOK address-coded preamble class |
| `main_boot_ms` | 100.0 | radio+stack sleep→RX-ready (50–200 ms class) |
| `wake_hangover_s` | 2.0 | stay-awake window, refreshed by activity |
| `wake_miss_prob` | 3.0e-6 | **compound** of 1% per-attempt decoder miss with 2 folded retries: 1−(1−0.01)³. v1 models the chirp-with-retries hardware class; the parameter stays exposed for future single-chirp studies. Restores delta=0 as the ideal-WuR bound (judged blocker: a raw 1% per-frame miss with no link ARQ imposed a ~3–5% PDR artifact floor at every delta) |

### Receiver decision (TxStart, frozen — the three-state rule)

Evaluated at the transmit() call site (which has the RSSI snapshot and the
flight id; `receiver_acquires_preamble_at` lacks both — judged blocker):

1. **Awake receiver** — duty ≥ 1.0 (gateways, hiker radios: never
   wake-gated) OR a wur relay with `hangover_until > tx_start`:
   acquires on the **data budget only** (rssi ≥ sens). No delta, no miss
   draw (skipping draws is safe: the miss stream is stateless keyed).
2. **Mid-boot** (`boot_until > tx_start`): treated as asleep in v1 (every
   frame carries its own chirp+boot preamble) — explicit, testable choice.
3. **Asleep wur relay**: acquires iff rssi ≥ sens + delta (wake budget) AND
   the wake-miss draw passes.

On acquisition by an asleep relay, at TxStart: `accrue_node_energy_state(rx)`
first, then set `boot_until = tx_start + main_boot_ms` and
`hangover_until = max(current, frame_end + wake_hangover_s)` (invariant:
`boot_until ≤ hangover_until`; acquisition freezes at TxStart exactly as the
released CAD rule — test engine2.rs:1522 pattern). A woken/awake receiver
refreshes `hangover_until` the same way.

### Wake accounting (attempt-level, TxStart; independent of frame outcome)

For each sleeping wur receiver inside the RX gate: `wake_attempts += 1`;
below wake budget → `wake_budget_fail += 1`; budget-pass but draw fail →
`wake_misses += 1`. **`duty_misses` is never touched in wur mode** (judged
blocker: the TxEnd `phy_ok && !cad_acquired` increment at engine2.rs:620-622
gets an explicit Wur arm). Frame loss thus decomposes into
budget / decoder-miss / collision / (never CAD) causes.

### Miss draw keying

`RNG_WUR_MISS` (fresh 64-bit domain tag), `keyed_f64` with the
collision-safe `event_draw_key`-style combine of **(pkt_id, tx, rx)** —
stateless and immutable; different forwarders of the same packet draw
independently (judged: keying by (pkt, rx) alone deleted flood spatial
diversity). SOS 5-minute retries carry fresh ids and re-draw.

### Chirp/overhead semantics (sender side)

`wake_overhead = wake_chirp_ms + main_boot_ms`. In wur mode the sender's
frame occupies the channel for `overhead + data airtime`: TxEnd scheduling,
TX energy (horizon-clip rules unchanged), busy intervals, capture-overlap
windows, half-duplex, offered airtime, and truncation refunds all inherit
coherently (the invariants judge verified transmit() at engine2.rs:472 is the
sole production consumer of airtime). One chirp serves all receivers
(broadcast ≡ unicast wake). Pessimistic-but-safe simplifications, stated in
the writeup: real systems are silent during boot; chirps here contend and
interfere like signal; report the overhead fraction vs mean frame airtime
and the operating-point offered airtime to show contention distortion is
second-order.

### Energy model

- Wur relays: sleep current replaced by `wur_idle_ma` at BOTH duplicated
  consumption sites (transmit baseline engine2.rs:478-489 AND settle
  767-777).
- New per-node `boot_until` / `hangover_until` beside `energy_state_t`;
  `accrue_node_energy_state` splits elapsed intervals at those boundaries:
  boot sub-interval → new `boot_s` accumulator (listen-current rate);
  hangover sub-interval → forced listen (duty=1); remainder → normal split.
  Accrue-first-then-set anchoring (set_docked pattern); the unconditional
  Active-segment merge stays valid (per-rate accumulators, rate-linear
  drain).
- **TX baseline is wake-state-aware** (judged blocker — the ~50–60% TX
  overcharge): in wur mode transmit() computes baseline from the wake state
  (listen_ma while `now < hangover_until/boot_until`, else `wur_idle_ma`),
  and a wur sender refreshes its own `hangover_until ≥ frame end` at TxStart
  so mid-frame expiry cannot undercut the baseline. Pinned by a wur-gated
  twin of the `transmit_energy_uses_the_actual_duty_baseline` test.
- Revival boot windows: gated to wur **relays** only (the docked-revival
  path touches hiker radios and must not — judged). Both revival sites set
  the window for wur relays.
- Acknowledged v1 gap: a sleeping relay originating its own telemetry/beacon
  transmits without a self-wake boot charge (bounded: boot_ms at listen
  current per originated frame; stated in the writeup).

### Node classes & routing

Relays (solar fixed sites) get WuR semantics; gateways (mqtt/grid) and hiker
radios are unchanged and never wake-gated. Routing composes with the
**energy_aware** tree — `weight_mode()` gets an explicit `Wur →
EnergyAware-weights` arm (judged: the is_duty() default would silently give
lb_energy weights). **v1 routing is wake-blind by design and that is a
persistent hazard, stated honestly**: a wake-infeasible tree edge is a black
hole the router cannot learn (link_health is acquisition-gated; node
availability never fires because µW relays don't die; lazy refresh recomputes
the same tree). Recovery only via node death/revival or shadowing excursions.
Therefore E1 carries a **wake-aware-routing control arm**
(`--wur-informed-tree`): edge admission additionally requires static q50
margin ≥ delta when the edge's receiver is a wur relay; E1 reports the
[blind, informed] bracket. Wake failures do NOT feed link_health (no new
oracle knowledge in either arm).

## 3. Comparability invariants (unchanged from v1, plus)

1. Zero behavioral change to the nine released modes (full suite + byte
   -identity reproducibility test must pass; released-row re-run identical).
2. New draws only from the new stateless keyed domain; never touch the
   stateful RNG_PHY link streams; invariant test engine2.rs:2008 stays green.
3. Deterministic ordering for all new state changes.
4. Cross-engine parity before year-scale claims — with the **strengthened
   wur gate** (§5).
5. Explicit arms at ALL FIVE silent-default traps: duty-assignment catch-all
   (engine.rs:659), CAD phase match (engine2.rs:1087-1091), `weight_mode()`
   (sim.rs:79-85), the duty_misses increment (engine2.rs:620-622), and
   `duty_wake_model` labeling (main.rs:565-580 →
   `"wur_always_on_wake_receiver_v1"`).

## 4. Experiments (365 d, statewide, release_v1 frozen inputs, current engine)

All comparison rows re-run on the current engine (no cross-engine-state
comparisons with archived B.1/release_v1 rows).

- **E1 — delta sweep (primary)**: `wur` at delta ∈ {0, 40, 50, 60, 70, 80}
  (0 = ideal-WuR control; realistic bracket 40–80 sampled at 10 dB — judged:
  the old {0,20,40,60} grid spent half its points in a physically
  unrealizable regime) × seeds **{42–46}** (full registered set; N=3 was
  underpowered) × both routing arms (blind, informed). Comparison rows at
  the same seeds: `energy_aware` @68 mA (status quo), **`energy_aware`
  @2 mA (the ideal-hardware null — the study's actual competitor)**,
  `duty_sync`, `rotate_lb`, **`selective_duty`** (strongest duty incumbent).
  Metrics: depletions, availability, PDR, SOS delivered + p50/p95, overall
  delivery p50, offered airtime, wake_attempts / wake_budget_fail /
  wake_misses.
- **Pre-registered criteria** (falsifiable before the runs):
  - *Survivability*: wur depletions = 0 at every delta AND availability
    within 0.5 pp of the 2 mA comparator.
  - *Binding onset*: delta\* = smallest swept delta at which wur PDR's
    5-seed CI falls entirely below the 2 mA comparator's CI (blind arm,
    same seeds) while depletions remain 0. Claim under test: delta\* ∈
    (40, 70]. Refuted if delta\* ≤ 40, > 70, absent, or if depletions
    become nonzero first. The informed arm's delta\* bounds how much of the
    onset is routing blindness rather than wake budget.
- **E2 — boot-latency sensitivity**: delta=55, `main_boot_ms` ∈
  {50, 100, 200}, seeds {42, 43, 44}. Responsive endpoints (judged: SOS
  tails are retry-dominated and cannot respond): offered airtime and
  non-SOS overall delivery p50 (ms resolution). SOS tails reported
  descriptively only.
- **E3 — wake-feasibility census (static, three nested views per delta)**:
  (1) shrinkage fraction over **routing-eligible** links (q50 margin ≥ 3 dB
  — the router's own admission rule, not raw sensitivity); (2) stranded
  sites/routes = no wake-feasible path to any gateway over the
  wake-feasible subgraph, gating only edges whose receiver is a wur relay;
  (3) the **tree-edge subset**: margin distribution of edges the
  energy_aware tree actually uses. All labeled *median-channel*; alongside,
  the analytic per-link wake probability Φ((margin − delta)/σ_eff) under
  the model's own shadowing, the count of links within ±1σ of each
  threshold, and a consistency cross-check against E1's dynamic
  budget-fail rates. (Judged: a crisp q50 census alone would be crisper
  than the model it summarizes; σ=8 dB ≈ half a 10 dB grid step.)

## 5. Parity plan (strengthened — the six-metric gate was toothless for wur)

Judged findings incorporated: micro-scale deaths are structurally 0/0 (no
power), the harness whitelists six scalars and ignores everything else, and
sos counts auto-pass at micro scale.

- **Python twin**: five mode hooks (membership, duty assignment duty=0
  relays, TxStart acquisition branch with the same three-state rule, energy,
  overhead). Boot/hangover energy as **event-driven lump debits** at each
  wake (boot_ms at listen + hangover listen-time deltas as discrete energy
  events) — step-size independent, mirrors Rust's segments without ordered
  segments; the 600 s step stays.
- **Harness extension (pre-registered here)**: add for wur rows —
  `wake_attempts_total` (rel 0.10), `wake_misses_total` (abs 5),
  `wake_budget_fail_total` (rel 0.10), fleet consumed energy Wh (rel 0.10;
  added to both engines' summaries), overall delivery p50 (abs 0.5 s).
  `duty_misses ≡ 0` pinned by tests in BOTH engines. Parity runs at **two
  deltas (0 and 55)** so the wake-budget mechanism is differentially
  exercised.
- **Harness conformance**: rel_diff denominator brought to the
  pre-registered symmetric form max(|py|,|rs|,1e-9) (plan §4.2 is the
  registered authority; the current harness deviates) — noted in results.
- Incumbent three modes re-run first as the baseline parity check.

## 6. Implementation checklist additions (from the review)

- Explicit arms at all five silent-default traps (§3.5).
- New CLI: `--wur-delta-db`, `--wur-informed-tree` (flag), `--wur-boot-ms`
  — five-station pattern; validate_params gets wur-specific bounds (the µA
  idle current must NOT reuse the ≤ tx_current_ma check).
- New tests: three-state acquisition (incl. frame-2-in-hangover received on
  a margin<delta link; gateway receives at plain data sensitivity);
  wake counters (attempt/budget-fail/miss) pinned at TxStart; boot/hangover
  accrual split across a boundary; TX-in-hangover baseline (2179-twin);
  overhead in airtime+energy+truncation; wur byte-determinism (clone of the
  reproducibility test with mode=wur); released-mode non-perturbation
  (existing suite + engine2.rs:2008 + reproducibility.rs:47 untouched).
- E1 uses a dedicated runner that fails loudly on unknown modes (the
  release-era scripts' hardcoded mode lists are NOT extended).
- E3 census script over the same topology/routes inputs, with hashes.

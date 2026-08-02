# Wake-up-radio study — results (E1–E3)

Companion to the pre-registered design in `wur-design-2026-07-31.md`.
Runs: fastsim (Rust), statewide 457-node topology, release_v1 frozen inputs,
365 days, seeds 42–46 (E1) / 42–44 (E2), campaign artifacts + manifest in
`artifacts/sim/wur_study/`. Dual-engine implementation is parity-verified
(`scripts/sim_micro_parity.py`, two operating points). All values
MODEL-ONLY (uncalibrated); energy constants remain BENCH-CALIBRATE (G2).

## Headline

**Both pre-registered claims are refuted, and the study's own null wins.**
A plain always-on fleet on 2 mA-class silicon (nRF52/RAK-class listen
current — the "ideal-hardware null" registered as the actual competitor)
dominates every wake-up-radio arm on every axis, including the physically
unrealizable Δ=0 dB best case:

| arm (5 seeds × 365 d) | PDR | deaths/yr | avail | SOS del. | SOS p95 |
|---|---|---|---|---|---|
| **energy_aware @ 2 mA (null)** | **0.8315** | **0.0** | **1.0000** | **100%** | **3.0 s** |
| wur Δ0 (ideal, blind) | 0.8269 | 488.8 | 0.9919 | 100% | 3.3 s |
| wur Δ40 (realistic, blind) | 0.7282 | 488.0 | 0.9919 | 99.68% | 600.8 s |
| wur Δ50 (blind) | 0.6935 | 488.0 | 0.9919 | 99.15% | 1202.3 s |
| wur Δ60 (blind) | 0.6681 | 488.0 | 0.9919 | 98.73% | 2703.5 s |
| wur Δ70 (blind) | 0.6612 | 488.0 | 0.9919 | 96.19% | 3600.9 s |
| wur Δ80 (blind) | 0.6600 | 488.0 | 0.9919 | 94.61% | 3300.8 s |
| energy_aware @ 68 mA (status quo) | 0.8429 | 29,175.6 | 0.5352 | 100% | 4.0 s |
| duty_sync (incumbent) | 0.6876 | 1,254.6 | 0.9632 | 94.50% | 2100.7 s |
| selective_duty | 0.7778 | 5,309.4 | 0.8963 | 99.47% | 301.8 s |
| rotate_lb | 0.7751 | 4,860.2 | 0.9106 | 99.79% | 60.8 s |

Informed-routing arms are statistically indistinguishable from blind at
every Δ (e.g. Δ40: 0.7342 vs 0.7282) — the degradation is wake-budget
physics, not routing blindness.

## Pre-registered verdicts

- **Survivability criterion** (wur depletions = 0 at every Δ AND
  availability within 0.5 pp of the 2 mA comparator): **refuted on both
  halves.** Depletions are 488 ± ~1 per year at every Δ, and availability
  sits 0.81 pp below the comparator (0.9919 vs 1.0000).
- **Binding onset** (Δ\* ∈ (40, 70], with depletions still 0): **refuted.**
  The depletions-nonzero disqualifier fires at every Δ, and on PDR alone
  even the Δ=0 arm (0.8269) sits below the 2 mA comparator (0.8315) — the
  onset is at or before Δ=0, i.e. the claimed window never exists.

## E2 — boot-latency sensitivity (Δ=55, seeds 42–44)

| main_boot_ms | PDR | SOS del. |
|---|---|---|
| 50 | 0.6788 | 99.13% |
| 100 | 0.6779 | 98.95% |
| 200 | 0.6766 | 99.30% |

Flat to third decimal: boot latency is second-order; the wake-sensitivity
delta is the entire story.

## E3 — static wake-feasibility census

Over routing-eligible links (q50 margin ≥ 3 dB, the router's own admission
rule; σ_eff = 8.25 dB):

| Δ (dB) | directed link shrinkage (q50) | stranded sites (q50, no wake path to any gateway) |
|---|---|---|
| 0 | 0.0% | 32 |
| 40 | 40.1% | 89 |
| 50 | 57.8% | 116 |
| 60 | 75.6% | 157 |
| 70 | 80.9% | 162 |
| 80 | 81.6% | 162 |

At the realistic Δ=40, 40% of usable links cannot carry a wake chirp and a
median of 89 of 457 sites lose every wake-feasible gateway path — the
mechanism behind the delivery collapse in E1. (The 32 stranded at Δ=0 are
marginal-coverage sites near the admission threshold, a property of the
topology, not of the wake receiver.)

## Interpretation

The question WuR answers — "how do we listen without paying 68 mA?" — is
answered better by hardware that listens at 2 mA than by a second radio
that cannot hear. The 2 mA arm keeps always-on routing semantics (no wake
chirp airtime, no boot stalls, no budget black-holes), zero deaths, and
100% SOS delivery at interactive latency. The engineering recommendation
stays with the deployment BOM: RAK-class nodes for relays; wake-up
receivers are not a path worth hardware-prototyping for this network.

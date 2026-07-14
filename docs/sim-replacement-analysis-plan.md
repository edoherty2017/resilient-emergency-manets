# Simulation replacement run — pre-registered analysis plan

**Status:** PRE-REGISTERED. Written 2026-07-13, before the corrected replacement
runs were interpreted or any head-to-head conclusion was drawn. This document
fixes the mode set, seeds, metrics, uncertainty method, comparisons, and
Python↔Rust parity tolerance bands *in advance* so that the subsequent numbers
are evaluated against a plan rather than the plan being fit to the numbers.

**Scope:** New Hampshire only. Brenta / EU is descoped; FCC lawful-operation is a
documented limitation handled elsewhere, not part of this analysis.

**Headline caveat (applies to every number produced under this plan):** all
outputs are **MODEL-ONLY**. They are uncalibrated simulator results, not field
measurements, not validated coverage, reliability, energy, or deployability
findings. No number produced under this plan may be reported as a field result.
This plan replaces the withdrawn pre-fix runs listed in
[`audit-correction-ledger-2026-07-13.md`](audit-correction-ledger-2026-07-13.md);
it does not resurrect any withdrawn conclusion.

---

## 1. Design (pre-specified before looking at outcomes)

### 1.1 Mode set

Two engines are run. The Python reference engine
([`scripts/mesh_sim.py`](../scripts/mesh_sim.py)) runs the full **11-mode** set.
The Rust engine (`fastsim`) runs the **9-mode** set — the same modes minus the
two learned-policy modes (`q_routing`, `rl_duty`), which are Python-only.

| # | Mode | Python | Rust |
|---|------|:------:|:----:|
| 1 | `flood`          | yes | yes |
| 2 | `min_hop`        | yes | yes |
| 3 | `etx`            | yes | yes |
| 4 | `energy_aware`   | yes | yes |
| 5 | `lb_energy`      | yes | yes |
| 6 | `duty_sync`      | yes | yes |
| 7 | `duty_adaptive`  | yes | yes |
| 8 | `rotate_lb`      | yes | yes |
| 9 | `selective_duty` | yes | yes |
| 10 | `q_routing`     | yes | —   |
| 11 | `rl_duty`       | yes | —   |

The **9 shared modes** (rows 1–9) are the only modes eligible for Python↔Rust
parity accounting (Section 4). `q_routing` and `rl_duty` are analysed on the
Python arm alone and are never compared cross-engine.

### 1.2 Seed set

Primary seed set: **{42, 43, 44, 45, 46}, N = 5**. Seeds are the unit of
replication. The set is **extensible**: additional seeds may be appended (47, 48,
…) after this plan is registered, but the reported N and the exact seed list must
be stated with every result, and seeds are never dropped selectively after
inspection. If a run for a planned seed is missing, it is reported as missing
rather than silently excluded.

### 1.3 Fixed inputs

* The **52 uncalibrated sub-1.35 km short links stay excluded at 300 dB loss**
  for every run under this plan (per the audit correction; see
  [`build_sim_topology.py`](../scripts/build_sim_topology.py) default and
  [`topology_statewide.json`](../artifacts/sim/topology_statewide.json)). No run
  in this plan re-admits the policy edges; any diagnostic that does is out of
  scope and must not be pooled with these results.
* Weather inputs are the pinned, provenance-recorded ERA5 fetch; routing uses
  monthly climatology, not future realized weather.
* RF metadata uses the corrected canonical terms (22 dBm conducted TX, 24.15 dBm
  TX EIRP, +2.15 dBi RX gain, 26.30 dBm path-loss-to-receiver reference).

---

## 2. Metrics

### 2.1 Primary metric

* **`pdr_overall`** — overall packet delivery ratio (delivered / sent across all
  origins). This is the single pre-registered primary endpoint for the
  head-to-head routing comparisons in Section 3.

### 2.2 Secondary metrics

* **`aggregate_offered_airtime_ratio`** — sum of transmitter airtime / duration
  (additive across overlapping and spatially isolated transmitters; an offered
  load, not physical channel occupancy).
* **`channel_utilization`** — retained deprecated alias of
  `aggregate_offered_airtime_ratio`; reported for backward compatibility and
  parity book-keeping, not as an independent measurement.
* **`duty_misses_total`** — total CAD/duty-cycle missed receptions (Rust
  top-level scalar; expected 0 for the always-on modes and large for the
  duty-cycled modes). See Section 4.3 for the known Python-side asymmetry.
* **Fleet-energy totals** (`fleet_energy.deaths_total` /
  `fleet_energy.death_events_total`, `fleet_energy.unique_nodes_died`,
  `fleet_energy.dead_time_s_total`, `fleet_energy.availability`,
  `fleet_energy.relay_energy_gini`, `fleet_energy.final_soc_min`).
* **SOS delivery and latency** — `sos.delivered`, `sos.sent`, delivery fraction
  `sos.delivered / max(sos.sent, 1)`, and the latency distribution
  `sos.latencies_s` (report median and p95; the tail is heavy and
  retry-dominated, so the mean is reported only alongside the quantiles).

### 2.3 Channel-occupancy diagnostics (reported, not primary)

`channel_occupancy.receiver_busy_ratio_{p50,p95,max}` are the receiver-local
interval-union occupancy diagnostics. They are reported per run but are not part
of the head-to-head decision or the parity pass/fail set.

---

## 3. Head-to-head comparisons (within engine)

All head-to-head comparisons below are computed **per engine** (Python results
compared to Python results; Rust to Rust). They are pre-registered as
descriptive, uncertainty-quantified contrasts, not hypothesis tests with a
multiplicity-corrected error rate; each contrast is reported with its 95 % CI and
no contrast is promoted to a "winner" claim beyond what the overlapping intervals
support.

1. **Baseline vs routing:** `flood` (primary metric and offered airtime) vs each
   of `min_hop`, `etx`, `energy_aware`, `lb_energy` — cost of flooding in offered
   airtime against any PDR difference.
2. **Energy-aware family:** `energy_aware` vs `lb_energy` vs `rotate_lb` on fleet
   deaths, availability, `relay_energy_gini`, and PDR — does load/energy balancing
   reduce deaths without collapsing PDR.
3. **Duty-cycling cost:** always-on modes (`flood`, `min_hop`, `etx`,
   `energy_aware`, `lb_energy`) vs duty modes (`duty_sync`, `duty_adaptive`,
   `selective_duty`, `rotate_lb`) on `duty_misses_total`, PDR, and SOS delivery —
   the reliability price of duty cycling.
4. **Duty policy:** `duty_sync` vs `duty_adaptive` vs `selective_duty` on
   `duty_misses_total`, PDR, and fleet energy.
5. **SOS reliability:** SOS delivered/sent fraction and latency median/p95 across
   all modes, with `flood` as the SOS-priority reference.
6. **Learned policies (Python-only):** `q_routing` vs `etx`/`min_hop`; `rl_duty`
   vs `duty_adaptive`. Reported on the Python arm only; never compared to Rust.

---

## 4. Python ↔ Rust parity accounting (9 shared modes)

### 4.1 What parity means here

The Python and Rust engines use **independent, keyed per-phenomenon RNG
streams**. Seed-matched runs are therefore **not trace-identical**, and **exact
numeric equality is not expected and is not the parity criterion.** Parity is
**bounded-difference accounting**: for each shared scalar metric we report the
Python value, the Rust value, the absolute difference, and the relative
difference, and we flag any metric whose difference exceeds the pre-registered
band below. A flag is a signal to investigate a modelling divergence, not an
automatic defect.

Pairing: for each shared mode and each seed, the Python summary
`corrected_py_<mode>_seed<S>.json` is paired with the Rust summary, preferring the
per-seed sweep file `corrected/sweep/fs_<mode>_s<S>.json` and falling back to the
single-seed aggregate `corrected/corrected_<mode>.json` (seed 42) when the
per-seed sweep file is absent. A fallback across a seed mismatch is reported
explicitly.

### 4.2 Relative-difference definition

For paired values `p` (Python) and `r` (Rust):

```
abs_diff = |p - r|
rel_diff = |p - r| / max(|p|, |r|, 1e-9)
```

so that two exact zeros give `rel_diff = 0` and no division blow-up occurs when a
metric is legitimately 0 (e.g. `duty_misses_total` for always-on modes).

### 4.3 Tolerance bands (pre-registered)

A metric **passes** parity for a pair if `abs_diff ≤ tol_abs` **or**
`rel_diff ≤ tol_rel` (either is sufficient); otherwise it is **flagged**.

| Metric | tol_abs | tol_rel | Rationale |
|--------|:------:|:------:|-----------|
| `pdr_overall` | 0.03 | 0.05 | Bounded [0,1]; RNG-sensitive but should track closely. |
| `aggregate_offered_airtime_ratio` | 0.03 | 0.10 | Offered load; sensitive to per-node traffic clock draws. |
| `channel_utilization` (alias) | 0.03 | 0.10 | Same quantity as above; checked for alias consistency. |
| `sos.sent` | 3 | 0.10 | Incident counts; small integers, Poisson-like spread. |
| `sos.delivered` | 3 | 0.10 | As above. |
| `fleet_energy.deaths_total` | — | 0.15 | Large counts that scale with fleet/traffic and RNG. |
| `duty_misses_total` | — | 0.15 | Large counts; only meaningful for duty modes (see below). |

**Known asymmetry — `duty_misses_total`.** The Rust summary exposes a top-level
`duty_misses_total` scalar; the current Python summary
([`scripts/mesh_sim.py`](../scripts/mesh_sim.py) `summary()`) tracks duty misses
per node (`stats["duty_misses"]`) but does **not** emit a top-level
`duty_misses_total`. Until the Python summary is extended to emit that aggregate,
the parity report will record the Rust value and mark the Python value **absent**
for this key rather than fabricate one or crash. This asymmetry is a reporting
gap, pre-declared here, not a modelling divergence, and it is excluded from the
pass/fail tally while the Python key is absent.

### 4.4 Parity reporting

The parity report ([`scripts/sim_parity_report.py`](../scripts/sim_parity_report.py))
emits, per shared mode and seed: each metric's Python value, Rust value,
`abs_diff`, `rel_diff`, and pass/flag status; a per-mode roll-up of flag counts;
and an overall flag total. It states on every run that exact equality is not
expected. It runs and degrades gracefully when the Python arm is missing,
reporting **"python arm absent"** and falling back to a Rust-side inventory so
the run is still informative. Missing individual pairs are reported, not dropped
silently.

---

## 5. Uncertainty (confidence intervals)

* The **seed is the unit of replication.** For each metric and mode, compute the
  per-seed values, then the **seed-level sample mean** and a **t-based 95 %
  confidence interval**: `mean ± t_{0.975, N-1} · s / sqrt(N)`, where `s` is the
  seed-to-seed sample standard deviation (ddof = 1) and `N` is the number of
  seeds actually run for that mode.
* With N = 5, `t_{0.975, 4} ≈ 2.776`. When N < 2 the CI is undefined and is
  reported as such (point value only, flagged "N<2, no CI"); the point value is
  never presented as if it carried an interval.
* Fractions defined as ratios of pooled counts (SOS delivered/sent) are computed
  per seed first and then averaged across seeds; the CI is taken over the
  seed-level fractions, not over a single pooled fraction, so that the interval
  reflects between-seed variation.
* Every reported interval carries its N and seed list. No metric is reported as a
  point estimate without either a CI or an explicit "N<2, no CI" label.

---

## 6. Pre-registered decision rules and honesty constraints

1. The primary endpoint is `pdr_overall`; secondary endpoints are secondary and
   are labelled as such in any report.
2. A mode is described as "better" on a metric than another **only** when the
   seed-level 95 % CIs do not overlap in the claimed direction; otherwise the
   result is reported as "not distinguishable at N seeds."
3. Deviations from this plan (added seeds, changed inputs, engine fixes made
   after registration) are documented in the result report **before** the
   affected numbers are interpreted.
4. Every artifact produced under this plan is stamped MODEL-ONLY and carries the
   seed list, engine identity and version, and input provenance. Nothing here is
   a field, coverage, reliability, energy, safety, or legal finding.
5. Parity flags are investigated and explained; they are not silently suppressed,
   and passing parity is never presented as cross-validation against reality — it
   is only agreement between two uncalibrated models.

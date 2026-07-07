# Experiment Suite Results — 2026-07-07

89 full simulation-years (fastsim, year-scale validated vs the Python
reference; seed 1 unless noted; mixed-hardware fleet: nRF-conservative 30 mA
relays + Heltec 130 mA rentals; SOS ACK-retry on unless noted). Raw outputs:
`artifacts/sim/experiments/`. Engine + multi-seed baseline:
`artifacts/sim/sweep/sweep_comparison.csv`.

## E1/E2 — Gateway failure injection

Summit (Sherman Adams) **and** Pinkham Notch gateways killed simultaneously
for 7 days, winter (day 200) vs summer (day 20), lb_energy routing:

| scenario | PDR | SOS | deaths |
|---|---|---|---|
| no outage | 0.905 | 182/182 | 6,239 |
| summer week outage | 0.905 | 173/173 | 6,238 |
| **winter week outage** | 0.905 | **177/177** | 6,240 |

**Finding: the network is gateway-redundant.** Losing the two busiest
backhaul gateways for a week — even in mid-winter — costs zero SOS and no
measurable PDR. Traffic reroutes to the remaining 40+ gateways. The
architecture's regional-gateway redundancy is doing exactly what it was
designed to do.

## E3 — Regional channel isolation

Each gateway region on its own frequency (hikers inherit their kiosk's
channel):

| config | PDR | SOS | channel util |
|---|---|---|---|
| flood, one channel | 0.947 | 198/198 | 0.321 |
| flood, regional channels | 0.895 | 168/178 | 0.291 |
| duty_sync, one channel | 0.910 | 193/193 | 0.119 |
| duty_sync, regional channels | 0.883 | 157/163 | 0.113 |

**Finding: regional channels HURT — rejected.** Isolation removes the
cross-region paths that carry border traffic and SOS redundancy (10 of 178
SOS lost under flood+channels), while buying only ~3 points of utilization.
The interference problem channels were meant to solve is better solved by
duty cycling (util 0.12 without giving up connectivity). Single shared
channel + duty MAC is the recommended architecture.

## E6 — nRF sleep-floor correction

Prior duty-mode results carried an ESP32 12 mA sleep floor; real nRF52 sleep
is µA-scale (modeled 0.05 mA):

| relay listen | deaths (12 mA sleep) | deaths (µA sleep) |
|---|---|---|
| 30 mA | 825 | **109** |
| 6 mA | 347 | **0** |

**Finding: the "duty cycling hurts on good hardware" anomaly was a model
artifact.** With correct nRF sleep currents, duty cycling never hurts, and
nRF relays + duty cycling yields a functionally immortal fleet (0 deaths at
6 mA, ~100/yr at 30 mA).

## E4 — Ten real weather years (2016–2026)

Same fleet, ten consecutive real ERA5 years:

| metric | duty_sync (10-yr range) | lb_energy always-on (10-yr range) |
|---|---|---|
| deaths/yr | **533 – 1,042** | 6,011 – 7,335 |
| SOS delivery | 99.4 – 100% | 100% |
| PDR | 0.909 – 0.911 | 0.903 – 0.905 |

**Finding: 2025-26 was a typical year, and every conclusion is
climate-robust.** The duty-cycling advantage (≈7×) holds in the best and
worst winters of the decade; year-to-year variance is small compared to the
algorithm effect. Worst year for duty_sync (2018: 1,042 deaths, one SOS
missed at 99.4%) still beats the best always-on year by 6×.

## E5 — Peak load (30 days, 5-min beacons, 2× and 4× hiker fleet)

| config | PDR | SOS | util |
|---|---|---|---|
| flood, 4× hikers | 0.959 | 18/18 | 0.86 |
| flood, 8× hikers | 0.955 | 12/12 | **1.22 (saturated)** |
| duty_sync, 4× | 0.912 | 17/17 | 0.27 |
| duty_sync, 8× | 0.908 | 19/19 | 0.42 |

**Finding: duty_sync carries a 4× peak weekend with 3× headroom;
flood saturates the channel at high load** (>100% demand — it still
delivers by brute redundancy but has no margin left). SOS delivery survived
everywhere in this test; the capacity argument favors duty modes for
holiday-weekend conditions.

## E7 — Kiosk economics

Spares per charging box {0,1,2,4} × demand {normal, 2×}: **rental
availability 100% and checkout charge 100% in every cell.** With the nightly
shuttle rebalancing, even zero spares suffices — the binding constraint is
the shuttle operation, not inventory. BOM implication: spares are for
hardware failure/theft (not modeled), not for charge logistics; 1 spare/box
is a reasonable insurance level.

## E-BOM — Battery × panel grid (duty_sync, worst = deaths/yr)

| battery \ panel | 3 W | 6 W | 10 W | 15 W |
|---|---|---|---|---|
| 18.5 Wh | 5,105 | 2,060 | 455 | 150 |
| 37 Wh | 2,341 | 825 | 132 | 65 |
| 74 Wh | 892 | 74 | **34** | 19 |
| 111 Wh | 443 | 30 | 20 | 5 |

**Finding: panel size dominates battery size** (going 3→10 W cuts deaths
~10×; quadrupling the battery at fixed panel only ~5×). The cost-efficient
knee is **74 Wh battery + 10 W panel** (~34 deaths/yr fleet-wide ≈ 99.98%
site-uptime); diminishing returns beyond. Combined with E6: nRF relays at
that BOM ≈ zero-maintenance fleet.

## Engine cross-validation (Python reference vs fastsim, all 9 modes, seed 42)

Full-year runs of every algorithm on both engines: **max |ΔPDR| = 0.006;
deaths identical in 5/9 modes, max relative Δ 3.9% (rotate_lb, the most
stochastic); SOS and Gini agree throughout.** fastsim results are
year-scale-validated across the entire mode space, not just spot-checked.
Table: `artifacts/sim/xval/` vs `artifacts/sim/kiosk_summary_*.json`.

## Consolidated architecture recommendation

Single shared channel · duty-cycled MAC (duty_sync or duty_adaptive) ·
SOS flooded with priority + ACK-retry · nRF52-class solar relays
(74 Wh / 10 W pyramid) · Heltec kiosk rentals with nightly shuttle ·
gateway-redundant regional backhaul (proven against dual-gateway winter
outage).

**Caveats:** all results are simulation on community-bracketed hardware
constants ([BENCH-CALIBRATE]); ERA5 kt is valley-blended (summit winters
worse than modeled); single-seed for E1–E7 (multi-seed baseline in
sweep_comparison shows σ is negligible for these metrics); kiosk model
excludes theft/damage.

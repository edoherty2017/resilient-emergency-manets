# Trial 2 Pre-Registration — Predictions Committed Before Fieldwork

Generated 2026-07-07T18:44:04.550967+00:00 — commit hash is
the timestamp of record. Model: Longley-Rice ITM q50 over USGS 3DEP
+ lognormal shadowing σ=8.0 dB (pre-registered placeholder;
Trial 2 fits the real σ). EIRP 26.3 dBm; heights: beacon 3 m mast,
receiver 1.5 m handheld.

**Scoring rule (fixed now):** a stratum PASSES if measured median
RSSI is within ±12 dB of prediction and measured PDR within ±0.15
of predicted packet success. KPI = held-out RMSE across strata.

**Protocol:** surveyed static beacon, fixed 30 s cadence, sequence
numbers, hops_away==0 filtering, 600–1,000 packets/stratum, ≥2
repeat runs. Radio config per decision A2 (both tabled below).


## Beacon: ammo_relay (Ammonoosuc treeline relay)

| band (m) | stratum | n | config | pred RSSI (dBm) | pred P(success) |
|---|---|---|---|---|---|
| 0-500 | above_treeline | 24 | LongFast_Part97 | -51.1 | 1.0 |
| 0-500 | above_treeline | 24 | 500kHz_Part15 | -51.1 | 1.0 |
| 0-500 | below_treeline | 8 | LongFast_Part97 | -57.3 | 1.0 |
| 0-500 | below_treeline | 8 | 500kHz_Part15 | -57.3 | 1.0 |
| 500-1000 | above_treeline | 74 | LongFast_Part97 | -115.2 | 0.976 |
| 500-1000 | above_treeline | 74 | 500kHz_Part15 | -115.2 | 0.589 |
| 500-1000 | below_treeline | 10 | LongFast_Part97 | -73.3 | 1.0 |
| 500-1000 | below_treeline | 10 | 500kHz_Part15 | -73.3 | 1.0 |
| 1000-2000 | above_treeline | 246 | LongFast_Part97 | -124.3 | 0.799 |
| 1000-2000 | above_treeline | 246 | 500kHz_Part15 | -124.3 | 0.181 |
| 1000-2000 | below_treeline | 14 | LongFast_Part97 | -74.1 | 1.0 |
| 1000-2000 | below_treeline | 14 | 500kHz_Part15 | -74.1 | 1.0 |
| 2000-4000 | above_treeline | 39 | LongFast_Part97 | -132.1 | 0.445 |
| 2000-4000 | above_treeline | 39 | 500kHz_Part15 | -132.1 | 0.03 |
| 2000-4000 | below_treeline | 18 | LongFast_Part97 | -89.8 | 1.0 |
| 2000-4000 | below_treeline | 18 | 500kHz_Part15 | -89.8 | 1.0 |

## Beacon: jewell_relay (Jewell Trail treeline relay)

| band (m) | stratum | n | config | pred RSSI (dBm) | pred P(success) |
|---|---|---|---|---|---|
| 0-500 | above_treeline | 9 | LongFast_Part97 | -60.4 | 1.0 |
| 0-500 | above_treeline | 9 | 500kHz_Part15 | -60.4 | 1.0 |
| 500-1000 | above_treeline | 10 | LongFast_Part97 | -108.4 | 0.998 |
| 500-1000 | above_treeline | 10 | 500kHz_Part15 | -108.4 | 0.859 |
| 1000-2000 | above_treeline | 84 | LongFast_Part97 | -99.4 | 1.0 |
| 1000-2000 | above_treeline | 84 | 500kHz_Part15 | -99.4 | 0.986 |
| 1000-2000 | below_treeline | 32 | LongFast_Part97 | -130.2 | 0.54 |
| 1000-2000 | below_treeline | 32 | 500kHz_Part15 | -130.2 | 0.049 |
| 2000-4000 | above_treeline | 280 | LongFast_Part97 | -119.7 | 0.921 |
| 2000-4000 | above_treeline | 280 | 500kHz_Part15 | -119.7 | 0.368 |
| 2000-4000 | below_treeline | 18 | LongFast_Part97 | -73.7 | 1.0 |
| 2000-4000 | below_treeline | 18 | 500kHz_Part15 | -73.7 | 1.0 |

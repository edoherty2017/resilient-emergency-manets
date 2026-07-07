# Scope Amendment 1 — RSRP → ESP + Service-Layer Availability

**CS 5976, Summer 2026 · Student: Ethan Doherty · For advisor sign-off**

## Original text (Proposal V3, Deliverable 2)
> "…a standardized CSV/JSON dataset containing at least 2,500 unique data
> points (GNSS, RSSI, SNR, **RSRP**, and Satellite Link Status)…"

## Problem
RSRP (Reference Signal Received Power) is defined over LTE/5G reference
signals; it is a cellular-modem measurement that LoRa hardware cannot
produce. Recording an "RSRP" column from the mesh nodes would be a category
error, and comparing LoRa RSSI to cellular RSRP directly is not physically
meaningful (different bandwidths, reference definitions, and link margins).

## Proposed substitution (preserves the deliverable's intent)
1. **ESP (Effective Signal Power)** per packet on the LoRa side:
   `ESP = RSSI + SNR − 10·log₁₀(1 + 10^(SNR/10))` — the standard LoRa
   metric that removes the noise-floor contribution from RSSI, giving the
   correct analogue of a reference-signal power for path-loss fitting.
2. **Service-layer availability** for the cellular comparison: timestamped
   reachability probes (ICMP/HTTP over the cellular modem) recorded by the
   existing `cellular_ping_collector.py`, merged per-position — i.e., "was
   the cellular service usable here," which is the operational question the
   Coverage Delta actually needs. RSRP, where the modem exposes it, is
   retained as an optional diagnostic column, sourced from the modem — not
   from the mesh nodes.

## Impact
- Dataset schema: `rsrp` column replaced by `esp_dbm` (mesh) +
  `cell_available` / `cell_rtt_ms` (service layer), `modem_rsrp_dbm`
  (optional, modem-sourced).
- The "Mesh vs. the World" comparison becomes availability-vs-availability
  — like-for-like — rather than power-vs-power across incompatible metrics.
- No change to point-count target (≥2,500), topographies (3), or KPIs.

## Sign-off
Advisor: ______________________  Date: ____________

# Trial 2 field day 5 — re-site to Pack Monadnock (2026-07-26, dog constraint)

**Registered pre-departure, before any collection.** Ethan is bringing his dog;
**Mount Monadnock State Park prohibits dogs**, so the 2026-07-24/25 Monadnock
plan cannot run today. Re-sited to **Pack Monadnock (Miller State Park)** —
leashed dogs allowed — keeping the live-region criterion.

## Evidence (fresh nhmesh.live pull, 2026-07-26 ~10:20 UTC)

271 positioned Meshtastic nodes seen ≤12 h. Live SNHM cluster around Pack:
SNHM New Ipswich (RAK4631, 10.4 km, 1.0 h), Greenville (RAK4631, 13.4 km,
0.5 h), 603-CM (Heltec V3, 14.8 km, 1.7 h), SNHM Mason2 (15.8 km, 1.3 h).

## Registered predictions (ITM q50, statewide DEM, EIRP ref 26.3 dBm)

`artifacts/trial2/packmonadnock_livemesh_predictions_20260726.json`
(sha256 71db9f0045f91368…):

- **Greenville — CONTACT_PREDICTED, best −87.9 dBm** along the loop
- SNHM New Ipswich −126.8, 603-CM −120.9, SNHM Mason2 −124.5 — MARGINAL
- Keene Court St Rooftop −144.4 — **NO_CONTACT_PREDICTED** (registered null)

Route: `pack_monadnock_loop` (OSM-routed, 187 pts, 3.08 km, Tobler 0.89 h,
summit sample 93). Viewer: `artifacts/trial2/packmonadnock_real_nodes_viewer.html`.
Non-calibration-grade (station EIRP/antennas ASSUMED stock); receiver-only
Plan B day — no controlled beacon, zero calibration strata expected; the
Monadnock + Moosilauke beacon packs stay frozen and unscored.

## Rig state at departure (checked over LAN + Tailscale)

go/no-go 5/6 PASS (beacon_heard fails legitimately). Radio on /dev/lora_radio,
collector active, `TRIAL_ID=trial2-packmonadnock-20260726` set, GPS NMEA
flowing (no fix indoors — expected), journald persistent, disk 7%.
**Tailscale SSH fixed** by disabling Tailscale-SSH interception on the Pi
(`tailscale set --ssh=false`) so port 22 reaches the real key-auth sshd —
trailhead remote checks now possible IF the Pi gets internet (phone hotspot;
hotspot SSID not yet in the Pi's NetworkManager — pending Ethan's creds, or
rename hotspot to the known "Loft 18" network).

## Addendum 2026-07-26 (post-field, pre-report): full registration hashes

Recorded verbatim so nothing rests on truncated digests. The main prediction
pack's in-body hash above is truncated to 16 hex chars; full values:

```
71db9f0045f91368ece9bda17e18710c7f4794303178cb76b84370826932e9e2  packmonadnock_livemesh_predictions_20260726.json  (registered pre-departure; hash recorded pre-collection in truncated form, full form here)
f50bda83cb60f5f60a4a466806abcfb3b50489fef4722ed183a97b97fd153c5f  packmonadnock_livemesh_supplement_20260726.json   (trailhead supplement; hash first durably recorded HERE, post-collection — provenance tier explicitly weaker; its pre-walk timestamp is self-asserted inside the file)
aba23c13ad402fa2d7910ff6ac95059acc100833393ce4abaaeb1b66827eb882  monadnock_livemesh_predictions_20260723.json      (matches the 2026-07-23 siting doc)
```

Scoring therefore reports two tiers and never aggregates them: Tier 1 =
the registered pack (1 CONTACT + 1 NULL prediction among 5 links); Tier 2 =
the supplement (3 CONTACT among 8 links). SHA256SUMS added to
raw_pull_20260721/ and extended to the drive files in raw_pull_20260726/
this same day.

## Field protocol (unchanged otherwise)

Summit/ridge dwell 15–20 min with app open; screenshot node list; photograph
hardware labels (FCC ID, advisor criterion 5); evening = preserve raw first,
score contacts vs the registered JSON, check nhmesh.live for our node heard
by SNHM gateways.

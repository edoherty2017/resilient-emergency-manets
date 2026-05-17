# P6 Release Notes Draft (2026-05-17)

## Overall Gate
- overall_ok: **True**
- artifact_count: **48**

## Live Trial Metrics
- n: 3543
- mae: 42.49698351671674
- rmse: 44.869974408322705
- source_counts: {'rsrp_dbm': 0, 'rssi_dbm': 3543}

## Join Quality
- matched_pct: 4.590415065435865
- unmatched_pct: 95.40958493456414
- median_time_offset_seconds: 0.536013

## Quality Gates
- live_quality_passed: True
- live_quality_warnings: ['running on fallback metric rssi_dbm; rsrp_dbm unavailable']
- sentinel_decision: PASS (99.93000805567661% accepted)
- eval_decision: PASS

## Weather Guard
- risk_state: normal
- recommendation: proceed

## Notes
- Live metrics currently use fallback observation source (`rssi_dbm`) due no `rsrp_dbm` samples.
- See `artifacts/release/dryrun_vs_live_comparison.json` for dry vs live deltas.

# P6 Command Sequence (End-to-End)

```bash
cd /home/doher/projects/manet/resilient-emergency-manets

# P1 refresh
python3 scripts/validation/schema_validate.py --input /home/doher/manet_ingest/meshradiohead/jsonl/telemetry_stream.jsonl --output artifacts/reports/schema_validation_head.json
python3 scripts/validation/schema_validate.py --input /home/doher/manet_ingest/meshhikernode1/jsonl/telemetry_stream.jsonl --output artifacts/reports/schema_validation_hiker.json

# P3/P2/P4/P5/P6 integrated
python3 scripts/p6_integrated_run.py --ingest-root /home/doher/manet_ingest --trial-id trial-live
```

Primary outputs:
- `artifacts/release/p6_artifact_index.json`
- `artifacts/release/p6_runlog.json`

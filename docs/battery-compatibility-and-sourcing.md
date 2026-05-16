# Battery Compatibility + Sourcing (T5)

## Compatibility rules (Heltec V3 path)
- Verify connector type and polarity before purchase/use.
- Do not assume high-capacity LiPo is pin-compatible out of box.
- Prefer vendors that publish connector pitch, polarity diagram, and protection board details.

## Procurement policy
1. Buy **2 test units first** per candidate SKU.
2. Bench-validate fit/polarity before bulk order.
3. Approve only SKUs that pass 2-hour powered run without power flaps.

## Acceptance tests for a candidate battery
- Connector mates cleanly (no force/no wobble)
- Correct polarity verified by meter before connection
- Stable operation under telemetry load for >=2 hours
- No repeated power-fault signatures in raw logs

## Recommended carry-power model
- External USB power bank is primary in field
- Internal LiPo acts as ride-through/backup buffer
- Carry spare cable before carrying extra battery SKUs

## Sourcing fallback order
1. Previously validated exact SKU/vendor
2. Vendor with explicit connector/polarity docs
3. Generic marketplace listings only if seller provides wiring proof

## Recordkeeping
For each approved battery SKU, store:
- Vendor URL
- Stated connector + polarity
- Measured resting voltage range
- Test run date + pass/fail
- Notes on fit/cable strain relief

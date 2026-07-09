# Cancelled order

## Symptom

A webhook arrives with a non-null `cancelled_at`. The order is stored `on_hold` and a `cancelled_order` incident reaches `expected_behavior`.

## Diagnosis guidance

1. Confirm `cancelled_at` is present and non-null in the payload.
2. Cancelled marketplace orders are intentionally not fulfilled by this OMS.
3. This is not a mapping or normalizer defect.

## Fix policy

Expected behavior, no action, no artifact. Do not open a GitHub issue or PR. Do not change region mappings or phone rules. Cite this runbook in the incident summary and leave the status at `expected_behavior`.

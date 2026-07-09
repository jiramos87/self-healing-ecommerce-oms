# Duplicate delivery

## Symptom

A webhook arrives with the same `(store, order_number)` as an order already stored. The response is `200 duplicate`. A `duplicate_delivery` incident is recorded and linked to the original delivery.

## Diagnosis guidance

1. Confirm the store domain and `order_number` match an existing order row.
2. Treat this as idempotent redelivery (retries, marketplace replay, or the demo double-send), not a new order.
3. No region or phone validation failure is involved when the first delivery already succeeded.

## Fix policy

No code or data-file change. Do not open a fix PR. Record the duplicate incident for visibility; the agent does not run. If duplicates spike unexpectedly, investigate upstream retry behavior outside this OMS.

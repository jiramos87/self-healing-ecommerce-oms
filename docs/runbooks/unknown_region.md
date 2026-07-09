# Unknown region

## Symptom

Order ingestion fails because `shipping_address.province_code` is not present in the region mapping data file. The order is stored `on_hold` and an `unknown_region` incident is opened.

## Diagnosis guidance

1. Confirm the webhook payload includes `province_code` and `province`.
2. Check `app/data/regions.json` for a key matching the code (case-insensitive).
3. If the code is missing, the correct display name is the payload's `province` field verbatim. No judgment call is required.
4. Recurrence of the same fingerprint means the mapping was never added or the PR was not merged.

## Fix policy

Add one mapping line to `app/data/regions.json`: `province_code` -> `province` from the incident payload. Exactly one file, one added line, zero deletions. Open a GitHub issue and a one-line fix PR; a human merges. Do not invent region names.

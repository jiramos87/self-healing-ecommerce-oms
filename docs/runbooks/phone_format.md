# Phone format

## Symptom

Order ingestion fails because `phone` does not match any rule in the phone normalizer data file. The order is stored `on_hold` and a `phone_format` incident is opened.

## Diagnosis guidance

1. Confirm the raw `phone` value from the webhook payload.
2. Check `app/data/phone_rules.json` rules; each rule is a named regex pattern.
3. If no rule matches, the phone shape is novel for this demo store and needs a new rule.
4. Prefer a narrow pattern that accepts the observed shape without loosening unrelated formats.

## Fix policy

Append exactly one new rule to `app/data/phone_rules.json` that matches the offending phone. Exactly one file, one added rule (within the recipe line budget), zero deletions. Open a GitHub issue and a one-line fix PR; a human merges. Do not rewrite existing rules.

# Trace schema (template)

Copy into the target repo's `verification/` and fill in for the component being ported.
Write this **before** broad instrumentation — ambiguous trace semantics cause fragile
comparisons and false confidence. See `../../reference/trace-contract.md`.

## Events

| event          | meaning                          | params                          |
|----------------|----------------------------------|---------------------------------|
| `Start`        | run/session begins               | (none)                          |
| `HeaderParsed` | header successfully parsed        | `kind: "v1" \| "v2"`            |
| `BodyAccepted` | body bytes accepted               | `bytes: int >= 0`               |
| `Finish`       | run completed successfully        | (none)                          |
| `ErrorRaised`  | terminal error                    | `code: string` (shared code set)|

## Parameter types

Document the exact type and allowed range of every parameter. Parameters that feed state
machine guards must be deterministic and normalized.

## Normalization rules

- IDs (session/resource/transaction): stabilized in first-appearance order.
- Error representations: C++ `errno` / Rust error `kind` → shared `code` (maintain a table).
- Timestamps, pointers, hash-iteration order: dropped or canonicalized.
- List allowed implementation differences and how nondeterministic fields are handled.

## Versioning

Bump `version` in every event and in `state_machine.yaml` when the event vocabulary changes.

## Positive trace examples (accepted)

```jsonl
{"version":1,"run_id":"r1","seq":1,"impl":"cpp","component":"parser","event":"Start","params":{}}
{"version":1,"run_id":"r1","seq":2,"impl":"cpp","component":"parser","event":"HeaderParsed","params":{"kind":"v2"}}
{"version":1,"run_id":"r1","seq":3,"impl":"cpp","component":"parser","event":"BodyAccepted","params":{"bytes":128}}
{"version":1,"run_id":"r1","seq":4,"impl":"cpp","component":"parser","event":"Finish","params":{}}
```

## Negative trace examples (rejected)

```jsonl
{"version":1,"run_id":"r2","seq":1,"impl":"cpp","component":"parser","event":"Finish","params":{}}
```
(rejected: `Finish` before `Start`)

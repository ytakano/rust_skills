# Fail-closed equivalence contract

`equivalence_contract.json` is the single machine-readable source of truth for
trace, outcome, and side-effect comparison. The contract is deliberately
fail-closed:

- every semantic scalar has an explicit comparison policy;
- every event and required field is declared;
- unknown events and fields are rejected;
- `additional_properties: true` is forbidden;
- an ignored field or coverage waiver requires a non-empty reason.

The contract establishes **complete accounting of every external or semantically
observable value selected as in-scope by the port-equivalence contract**, not
equality of every implementation-local variable. Determine that scope from the
intended specification, public interfaces, existing tests, and behavior on which
real users depend. A behavior can therefore be in-scope even when a specification
document does not mention it.

Build the accounting first in `trace_schema.md`: enumerate in-scope public
results, errors, semantic state, resource lifecycle, and external side effects;
then map every row to a contract path, a C++ emission point, a Rust emission
point, and at least one test. Record every out-of-scope decision with a reason.
An absent row is not an exclusion decision and must not become an implicit ignore.

## Contract structure

Start from
[`../templates/conformance/equivalence_contract.json`](../templates/conformance/equivalence_contract.json).
The top-level sections are mandatory:

```json
{
  "version": 1,
  "trace": {
    "ordering": "total",
    "event_schema": {},
    "events": {}
  },
  "outcomes": {
    "stdout": {},
    "stderr": {},
    "exit_code": {}
  },
  "side_effects": {
    "mode": "manifest",
    "schema": {}
  }
}
```

The template implements exact total-order event comparison. A concurrent target
may instead need per-session, per-resource, or happens-before comparison. That
is a target-specific comparator: implement it explicitly, document the allowed
reordering, and mutation-test it. Do not set an unsupported ordering value and
do not canonicalize order around shared state, transactions, external I/O, or
security decisions.

## Recursive schemas

Object and array schemas account for every nested value:

```json
{
  "type": "object",
  "required": ["name", "samples"],
  "properties": {
    "name": {
      "type": "string",
      "compare": {"kind": "exact"}
    },
    "samples": {
      "type": "array",
      "items": {
        "type": "integer",
        "compare": {"kind": "exact"}
      }
    }
  },
  "additional_properties": false
}
```

Supported scalar types are `string`, `integer`, `float`, `boolean`, `null`,
and `bytes`. `bytes` is used by the harness for stdout/stderr. JSON trace and
manifest values cannot contain raw bytes.

For a dynamic map, `additional_properties` must itself be a schema:

```json
{
  "type": "object",
  "required": [],
  "properties": {},
  "additional_properties": {
    "type": "integer",
    "compare": {"kind": "exact"}
  }
}
```

This declares that keys are dynamic but every value is still compared. Bare
`true` is rejected because it would admit untyped, unconfigured values.

## Comparison policies

Non-floating scalars use exact comparison:

```json
{"type": "string", "compare": {"kind": "exact"}}
```

Ignoring a value is an explicit specification decision:

```json
{
  "type": "string",
  "compare": {
    "kind": "ignore",
    "reason": "run id differs by construction and has no external meaning"
  }
}
```

Never ignore an outcome, protocol state, error kind, persistent value, or
external side effect merely to make a port pass.

### Floating-point values

Do not round floats during normalization. Choose a field-specific policy from
the specification, numeric error analysis, or an externally defined
resolution—not from the largest difference observed in the current corpus.

Absolute/relative tolerance:

```json
{
  "type": "float",
  "compare": {
    "kind": "abs_rel",
    "abs_tol": 1e-9,
    "rel_tol": 1e-7,
    "nan": "reject",
    "infinity": "reject",
    "signed_zero": "equal"
  }
}
```

The comparison is:

```text
abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))
```

ULP comparison:

```json
{
  "type": "float",
  "compare": {
    "kind": "ulp",
    "precision": "f64",
    "max_ulps": 4,
    "nan": "reject",
    "infinity": "same_sign",
    "signed_zero": "equal"
  }
}
```

Bit-exact floating comparison:

```json
{
  "type": "float",
  "compare": {
    "kind": "bit_exact",
    "precision": "f32",
    "nan": "reject",
    "infinity": "same_sign",
    "signed_zero": "distinct"
  }
}
```

Standard JSON has no NaN or infinity literals. Encode non-finite values as the
strings `"nan"`, `"+inf"`, and `"-inf"`. Raw `NaN`/`Infinity` JSON constants
are rejected. If NaN payload bits are part of the contract, record the bits in
a separate exact field; otherwise retain them as an explicitly ignored
diagnostic field with a reason.

Approximate numeric equality applies only to that numeric leaf. It must never
make a different event sequence, terminal state, success/error result,
commit/rollback decision, or side effect equivalent. If a tiny numeric
difference changes control flow, align the arithmetic environment/algorithm or
specify a legitimate boundary band in the state machine; do not widen epsilon
or normalize the outcome away.

## Coverage

Every non-ignored scalar and every event is coverage-required by default. A
corpus run fails when a declared semantic path is never observed.

A genuine staged/out-of-scope case may be waived:

```json
{
  "type": "string",
  "coverage": "waived",
  "coverage_reason": "feature is disabled in this product configuration",
  "compare": {"kind": "exact"}
}
```

Waiver means “not exercised by this corpus”; if the field appears, it is still
validated and compared. Keep waivers narrow and report them as remaining risk.

## Outcomes and side effects

`stdout`, `stderr`, and `exit_code` are always declared in `outcomes`. Compare
them exactly unless the specification explicitly permits an ignored stream
with a reason.

For side effects, prefer observations independent of application trace code:
filesystem snapshots, database queries, captured requests from a fake service,
or test-double histories. Serialize the canonical observation to the path in
`SIDE_EFFECTS_OUT`, then declare its recursive schema:

```json
{
  "mode": "manifest",
  "schema": {
    "type": "object",
    "required": ["files"],
    "properties": {
      "files": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["path", "sha256"],
          "properties": {
            "path": {
              "type": "string",
              "compare": {"kind": "exact"}
            },
            "sha256": {
              "type": "string",
              "compare": {"kind": "exact"}
            }
          },
          "additional_properties": false
        }
      }
    },
    "additional_properties": false
  }
}
```

Only a target with no external side effects may use:

```json
{
  "mode": "out_of_scope",
  "reason": "pure function; no files, database, network, or persistent state"
}
```

Missing mode, a missing manifest, an unexpected manifest in `out_of_scope`
mode, or an empty reason fails.

## Comparator audit

Run `diff_trace.py --audit` and run the corpus through `run_diff.py`.
The audit mutates every observed semantic scalar outside its comparison
policy, deletes values/events, adds unknown fields/events, and reorders
distinguishable adjacent events. Every semantic mutation must be detected;
mutations of explicitly ignored values must remain ignored.

The corpus coverage report answers the separate question: whether every
declared semantic event and field was observed at least once. Both checks are
required:

```text
comparator audit  -> the checker is sensitive to observed values
contract coverage -> the corpus exercised every declared value
```

Neither replaces state/transition/guard coverage, property testing, fuzzing,
or review of the observability matrix.

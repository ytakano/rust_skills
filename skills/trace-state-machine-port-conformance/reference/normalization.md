# Trace normalization

Normalization maps both the C++ and Rust traces into a common form so they can be compared
directly. Implement it as `normalize_trace.py` (see
[../templates/conformance/normalize_trace.py](../templates/conformance/normalize_trace.py)).

**Golden rule:** normalization is allowed to remove *noise*. It must **not** hide meaningful
specification differences. Every normalization rule you add is a claim that "this difference
is allowed by the spec" — be able to justify it.

Normalization and approximate comparison are separate operations:

```text
normalize   -> remove/canonicalize specification-approved noise
compare     -> apply the field policy from equivalence_contract.json
```

Never round, truncate, bucket, stringify, or otherwise reduce floating-point precision during
normalization. Use `abs_rel`, `ulp`, or `bit_exact` in the equivalence contract. Tolerances come
from the specification, numeric error analysis, or an external resolution—not from observed
C++/Rust differences.

## What to normalize

- Implementation-specific fields
- Nondeterministic IDs → stable, sequence-assigned IDs
- Timestamps (drop, or replace with logical order)
- Pointer values (drop)
- Hash-map iteration order (canonicalize)
- Independent event ordering, **only when the spec allows it** (see
  [differential-checks.md](./differential-checks.md) on concurrency)
- C++/Rust-specific error representations → shared error codes
- Internal events that are explicitly non-semantic (drop)

## Example: unifying error representations

```text
C++:  ErrorRaised(errno=2)
Rust: ErrorRaised(kind="NotFound")
Normalized: ErrorRaised(code="not_found")
```

Maintain an explicit mapping table from each side's native error representation to the shared
code set. An unmapped error must fail loudly, not silently pass through — an unknown error is
exactly the kind of difference you want to catch.

## ID stabilization

Replace nondeterministic ids (pointers, allocation-order ids, UUIDs) with ids assigned in
**first-appearance order** per scope:

```text
session "0x55ab…" -> "S1"   (first session seen)
session "0x77cd…" -> "S2"   (second session seen)
```

Apply the same scheme to both traces so equivalent runs map to identical normalized ids.
Keep the mapping per-scope (session, resource, transaction) so cross-references stay
consistent.

## Things normalization must NOT erase

If you find yourself normalizing any of these away, you are hiding a real difference:

- A missing close/drop/release event
- A different terminal/error outcome
- Commit vs rollback
- A changed protocol state transition
- An extra or missing external side effect
- A numeric difference that changes an event, state transition, success/error outcome,
  commit/rollback decision, or side effect

Every dropped or canonicalized field must also be accounted for as an explicitly ignored or
normalized path in the observability matrix. Unknown/unmapped data fails; it is never passed
through or dropped opportunistically.

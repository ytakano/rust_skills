# Differential equivalence checks

State-machine acceptance is **necessary but not sufficient**. A trace can be accepted by `M`
and still differ from the corresponding C++ behavior. Always validate and compare the
normalized traces, outputs, and side effects under the same fail-closed equivalence contract.

## The seven checks (single source of truth)

For a corpus `C`, check all of the following:

```text
1. validates(contract, normalize(trace_cpp(input)))             for every input in C
2. validates(contract, normalize(trace_rust(input)))            for every input in C
3. accepts(M, normalize(trace_cpp(input)))                       for every input in C
4. accepts(M, normalize(trace_rust(input)))                      for every input in C
5. equivalent_trace(contract, cpp, rust)                         for every input in C
6. equivalent_outcomes_and_side_effects(contract, cpp, rust)     for every input in C
7. complete_contract_coverage(C) and comparator_mutation_audit
```

`equivalent_trace` includes event sequence, every declared event parameter, session/resource
mapping, terminal state, and error-code equivalence. `equivalent_outcomes_and_side_effects`
includes stdout, stderr, exit code, return result where applicable, and the canonical
side-effect manifest.

## Fail-closed comparison

`diff_trace.py` reads `equivalence_contract.json` and recursively validates and compares every
declared value. It rejects:

- an unknown event or field;
- a missing required field;
- a type mismatch;
- an object with undeclared additional properties;
- a scalar with no comparison policy;
- an `ignore` or coverage waiver without a reason;
- an unsupported event-ordering policy.

Never implement comparison as a hand-selected list of “important” fields. A fixed allowlist
silently misses newly added observables. The contract must instead account for every field,
with explicit reasons for the small set that is non-semantic.

## Numeric equivalence

Floating-point parameters use field-specific policies from the contract:

- `abs_rel` for specification/error-analysis tolerances;
- `ulp` for bounded representation-level drift at a declared `f32`/`f64` precision;
- `bit_exact` when the binary result is part of the contract.

Each policy explicitly defines NaN, infinity, and signed-zero handling. Standard JSON
non-finite values use `"nan"`, `"+inf"`, and `"-inf"` string tokens.

Approximate equality is local to the numeric leaf. These differences are **never** made
equivalent by a numeric tolerance:

```text
Different event sequence or protocol state
Success versus error
Different error kind
Commit versus rollback
Different exit code when contractual
Missing release/cleanup
Different external or persistent side effect
Security-boundary decision
```

If small numeric drift changes one of those outcomes, align arithmetic type/order, FMA policy,
rounding mode, fast-math/libm/target environment, or use a specification-approved robust
algorithm. If the specification truly permits a boundary band, model it explicitly in the
state machine and tests; do not widen epsilon until the traces pass.

## Coverage and comparator audit

Two independent checks prevent selective comparison:

```text
contract coverage -> every declared semantic event/field appeared in the corpus
mutation audit    -> changing every observed semantic value is detected
```

All events and non-ignored scalar fields are coverage-required by default. A narrow
`coverage: waived` needs a reason and remains a reported risk. The audit changes scalar values
outside their policies, deletes values/events, inserts unknown values/events, and reorders
distinguishable events. Semantic mutations must fail; explicitly ignored values must remain
ignored.

Also measure state, transition, guard true/false, boundary, and declared-error coverage.
Contract-field coverage does not prove that every behavioral path was exercised.

## Concurrency and async

The provided comparator implements total-order equality. Do not use it unchanged when the
specification allows concurrent reordering. Implement and test one or more of:

- per-session trace comparison;
- per-resource trace comparison;
- happens-before comparison for lock/unlock, send/receive, spawn/join, request/response;
- explicit canonical order for independent events.

Do not ignore ordering around shared state, locks, transactions, external I/O, or security
boundaries. The target-specific comparator must remain fail-closed for fields and must pass
the same mutation audit.

## Outcomes and side effects

The harness runs C++ and Rust in separate working directories and compares:

```text
stdout            stderr             exit code
return result     generated files    network requests
database state    updated/deleted files
persistent state  resource lifecycle
```

When side effects exist, capture them independently and write canonical JSON to
`SIDE_EFFECTS_OUT`. The contract recursively validates and compares the manifests. A
side-effect-free target may use reasoned `out_of_scope`; missing mode or an unresolved TODO
is a conformance-contract failure.

See [equivalence-contract.md](./equivalence-contract.md) for the contract format and
[`../templates/conformance/run_diff.py`](../templates/conformance/run_diff.py) for the
executable harness.

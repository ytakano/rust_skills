# Failure triage and regression

When a differential check fails, **classify before changing any code**. The fix differs
completely depending on the class, and "make the test pass" is the wrong instinct here.

## Failure classes

```text
cpp_rejected
  The C++ trace is rejected by the state machine.
  Possible causes: state-machine bug, existing C++ bug, instrumentation bug.

rust_rejected
  The Rust trace is rejected by the state machine.
  Possible causes: Rust port bug, Rust instrumentation bug, overly strict state machine.

trace_mismatch
  Both traces are accepted, but the normalized C++ and Rust traces are not equivalent.
  Possible causes: Rust port bug, instrumentation bug, or an incorrect contract/normalization
  rule. Do not loosen the rule until the specification justifies the difference.

output_mismatch
  Traces are equivalent, but outputs differ.
  Check formatting, encoding, numeric conversion, rounding, and error representation.

side_effect_mismatch
  File, database, network, persistent state, or other side effects differ.
  Check test isolation and side-effect comparison rules.

nondeterministic_failure
  Re-running changes the result.
  Stabilize or normalize randomness, time, thread scheduling, hash order, or external I/O.

instrumentation_bug
  Tracing changes behavior or emits events at the wrong place.
  Fix instrumentation before changing the port.

contract_error
  An event/field is unknown, missing, mistyped, or lacks a comparison policy.
  Fix the observability inventory, instrumentation, or contract; never ignore it implicitly.

coverage_gap
  A declared semantic event/field was never observed in the corpus.
  Add a boundary/error/path case, or document a narrow reasoned coverage waiver.

comparator_audit_failure
  A semantic mutation passed, or an explicitly ignored value was compared.
  Fix the comparator before drawing any conclusion about the port.

numeric_mismatch
  A float violates its specification-derived abs/rel, ULP, or bit policy.
  Check arithmetic environment and algorithm; do not tune tolerance to the observed failure.
```

When a C++ trace is rejected (`cpp_rejected`), classify the cause before editing anything:

```text
A. The state machine does not correctly express the intended specification.
B. The C++ implementation has an existing bug.
C. The trace instrumentation is placed incorrectly.
D. The normalization rules are wrong.
E. The test input or expectation is wrong.
F. The equivalence contract or its numeric policy is incomplete or wrong.
```

Remember: the C++ implementation is **not** unconditionally correct. A difference in Rust may
expose a C++ bug, undefined behavior, or implementation-defined behavior — do not "fix" Rust
to match a broken original. Document the decision instead.

## Save every repro

Every discovered failure must be preserved (in the target repo, under `conformance/repro/`):

```text
conformance/repro/<issue-name>/input
conformance/repro/<issue-name>/cpp.trace.jsonl
conformance/repro/<issue-name>/rust.trace.jsonl
conformance/repro/<issue-name>/cpp.normalized.jsonl
conformance/repro/<issue-name>/rust.normalized.jsonl
conformance/repro/<issue-name>/cpp.stdout
conformance/repro/<issue-name>/rust.stdout
conformance/repro/<issue-name>/cpp.stderr
conformance/repro/<issue-name>/rust.stderr
conformance/repro/<issue-name>/cpp.exit_code
conformance/repro/<issue-name>/rust.exit_code
conformance/repro/<issue-name>/cpp.side_effects.json    # manifest mode
conformance/repro/<issue-name>/rust.side_effects.json   # manifest mode
conformance/repro/<issue-name>/report.json
```

The repro `report.json` records the automated mismatches and audit failures. Add a companion
README when human investigation is complete, covering:

- Failure class
- Expected specification behavior
- Actual C++ behavior
- Actual Rust behavior
- Root cause
- Fix summary
- Regression test command

## Turn repros into regression tests

Minimization + regression loop:

```text
for input in generated_inputs:
    run differential conformance and equivalence checks
    if failed:
        minimize input
        save to conformance/repro/
        add regression test
```

Never discard a failing input after debugging — it becomes a permanent regression test.

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
  Possible causes: Rust port bug, or a missing/incorrect equivalence (normalization) rule.

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
```

When a C++ trace is rejected (`cpp_rejected`), classify the cause before editing anything:

```text
A. The state machine does not correctly express the intended specification.
B. The C++ implementation has an existing bug.
C. The trace instrumentation is placed incorrectly.
D. The normalization rules are wrong.
E. The test input or expectation is wrong.
```

Remember: the C++ implementation is **not** unconditionally correct. A difference in Rust may
expose a C++ bug, undefined behavior, or implementation-defined behavior — do not "fix" Rust
to match a broken original. Document the decision instead.

## Save every repro

Every discovered failure must be preserved (in the target repo, under `verification/repro/`):

```text
verification/repro/<issue-name>/input
verification/repro/<issue-name>/cpp.trace.jsonl
verification/repro/<issue-name>/rust.trace.jsonl
verification/repro/<issue-name>/normalized_cpp.jsonl
verification/repro/<issue-name>/normalized_rust.jsonl
verification/repro/<issue-name>/README.md
```

The repro `README.md` should include:

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
    run differential verification
    if failed:
        minimize input
        save to verification/repro/
        add regression test
```

Never discard a failing input after debugging — it becomes a permanent regression test.

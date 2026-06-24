---
name: rust-coverage-meaningful-tests
description: Use when measuring or improving test coverage for a Rust crate. Focus on behavior, invariants, edge cases, unsafe contracts, and regression protection. Do not add shallow tests whose only purpose is to execute lines.
---

# Rust Coverage and Meaningful Tests

## Goal

Improve the Rust crate's test suite using coverage as a diagnostic map, not as the objective.

A good outcome is not "higher coverage" by itself. A good outcome is:

* important public behavior is checked;
* edge cases and error paths are exercised;
* unsafe code contracts are tested or isolated;
* regressions are captured;
* tests would fail for plausible bugs;
* coverage reports have fewer untested high-risk regions.

## Core rule

Never add tests that merely call functions to increase line coverage.

Every new test must have an oracle: an assertion, expected error, invariant check, round-trip property, reference-model comparison, panic expectation, UB check, or regression condition.

Bad:

```rust
#[test]
fn covers_parse() {
    let _ = parse("123");
}
```

Good:

```rust
#[test]
fn parse_rejects_overflowing_u32() {
    let err = parse_u32("4294967296").unwrap_err();
    assert_eq!(err.kind(), ParseErrorKind::Overflow);
}
```

## Preferred tools

Use `cargo llvm-cov` as the default coverage tool.

Useful commands:

```bash
cargo test --workspace --all-features
cargo llvm-cov --workspace --all-features --html
cargo llvm-cov --workspace --all-features --lcov --output-path lcov.info
```

If the project uses nextest:

```bash
cargo llvm-cov nextest --workspace --all-features
```

If doctests are important, include them explicitly. On some setups this may require nightly:

```bash
cargo +nightly llvm-cov --workspace --all-features --doc
```

For test quality beyond coverage, consider:

```bash
cargo mutants
cargo +nightly miri test
cargo fuzz run <target>
```

These are not bundled with the toolchain; install them first if needed:

```bash
cargo install cargo-mutants
rustup +nightly component add miri
cargo install cargo-fuzz
```

Use these selectively. Do not block ordinary development on long fuzz or mutation campaigns unless the user asks for it.

## Workflow

### 1. Establish a clean baseline

Run:

```bash
cargo test --workspace --all-features
cargo llvm-cov --workspace --all-features --html
```

`cargo llvm-cov` runs the test binaries itself (under instrumentation, so it recompiles). The preceding `cargo test` is only a fast check that the suite passes before you spend time on the instrumented run.

If the crate has feature combinations, also inspect:

```bash
cargo test --workspace --no-default-features
cargo test --workspace --all-features
```

For crates with meaningful feature matrices, test the smallest important combinations rather than every possible combination.

### 2. Read the coverage report as a risk map

Do not simply sort by lowest percentage.

Prioritize uncovered code in this order:

1. public API behavior;
2. unsafe code and safe wrappers around unsafe code;
3. parsing, serialization, validation, and boundary handling;
4. error paths;
5. concurrency, synchronization, cancellation, and state transitions;
6. resource management: allocation, deallocation, closing, flushing, rollback;
7. arithmetic: overflow, saturation, rounding, indexing, length calculations;
8. security-sensitive logic;
9. platform-specific or feature-gated code;
10. internal helpers only if they encode nontrivial logic.

Low coverage in dead, deprecated, debug-only, or trivial forwarding code is less important.

### 3. Create a test plan before editing

For each uncovered high-risk region, write a compact note:

```text
Target:
Risk:
Missing behavior:
Test type:
Oracle:
Expected failure if bug exists:
```

Example:

```text
Target: src/ring.rs RingBuffer::push/pop wraparound
Risk: off-by-one bug at capacity boundary
Missing behavior: full -> pop -> push -> order preserved
Test type: unit + property test
Oracle: compare against VecDeque model
Expected failure if bug exists: observed sequence differs from model
```

Only implement tests that have a clear oracle.

### 4. Choose the right test type

Use ordinary example tests for fixed edge cases.

Use property tests when many inputs share the same invariant:

* parser then formatter round-trips;
* encode then decode round-trips;
* custom collection behaves like a reference collection;
* normalization is idempotent;
* sorting preserves elements and produces order;
* state machine never violates invariants.

Use regression tests when a specific bug was fixed:

* name the bug condition;
* include the smallest reproducer;
* assert the fixed behavior;
* add a comment only if the reproducer is not obvious.

Use fuzzing when input shape is complex or adversarial:

* parsers;
* binary formats;
* network packets;
* compression/decompression;
* deserializers;
* unsafe byte manipulation.

Use Miri when unsafe code, aliasing, initialization, pointer arithmetic, or layout assumptions are involved.

Use mutation testing when coverage is high but confidence is low.

## What good tests should check

Good tests should usually check at least one of these:

* return value;
* exact error kind;
* state after operation;
* invariant after a sequence of operations;
* emitted bytes or parsed structure;
* idempotence;
* round-trip behavior;
* equivalence to a reference implementation;
* preservation of ordering or membership;
* panic or no-panic contract, only when that is the API contract;
* resource cleanup;
* behavior under feature flags;
* behavior with empty, singleton, large, malformed, or boundary inputs.

A test that only verifies "this function runs" is usually not enough.

## Rust-specific test targets

### Public API

Prefer testing through public or crate-visible APIs.

Private helper tests are acceptable when:

* the helper encodes subtle logic;
* public setup would be too indirect;
* the helper has a meaningful local invariant.

Do not make private functions public just to test them.

### Error paths

Exercise errors deliberately:

* malformed input;
* truncated input;
* invalid enum tag;
* unsupported version;
* permission denied;
* missing file;
* duplicate key;
* out-of-range value;
* overflow;
* impossible state from external input.

Assert the error category, not only `is_err()`.

Prefer:

```rust
assert!(matches!(result, Err(Error::InvalidHeader { .. })));
```

over:

```rust
assert!(result.is_err());
```

### Boundary cases

Always consider:

* empty input;
* one element;
* exactly capacity;
* capacity plus one;
* minimum numeric value;
* maximum numeric value;
* overflow boundary;
* non-UTF-8 bytes;
* repeated values;
* duplicate keys;
* already-normalized input;
* deeply nested input;
* zero-sized types, if generic code is involved.

### Unsafe code

For every safe abstraction containing unsafe code, identify its safety contract.

Test:

* aliasing-sensitive operations;
* drop behavior;
* panic during partial initialization;
* out-of-bounds prevention;
* alignment assumptions;
* `Send` / `Sync` expectations, if relevant;
* no use-after-free under normal API usage.

Run at least the relevant tests under Miri:

```bash
cargo +nightly miri test
```

If Miri does not support part of the crate, isolate smaller tests or mark unsupported tests with `#[cfg_attr(miri, ignore)]`.

### Concurrency

For concurrent code, normal tests are weak.

Prefer:

* deterministic small-state tests;
* model-style tests;
* Loom tests, if the crate already uses Loom or the abstraction is small enough;
* stress tests only as a supplement.

Never treat a stress test as proof of correctness.

### Serialization and parsing

Good parser tests include:

* valid minimal input;
* valid maximal or complex input;
* malformed input;
* truncated input;
* unknown fields;
* duplicate fields;
* round-trip tests;
* compatibility examples from the format specification.

For binary formats, test exact bytes where stable.

### Feature-gated code

Coverage with `--all-features` can hide bugs in `--no-default-features`.

Run important feature modes separately:

```bash
cargo test --workspace --no-default-features
cargo test --workspace --all-features
```

If the crate supports `no_std`, do not accidentally add tests that require `std` in library code.

## Property test pattern

Use property tests for invariants, not random examples.

Example:

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn normalize_is_idempotent(input in ".*") {
        let once = normalize(&input);
        let twice = normalize(&once);
        prop_assert_eq!(once, twice);
    }
}
```

For data structures, compare against a simple model:

```rust
use proptest::prelude::*;
use std::collections::VecDeque;

proptest! {
    #[test]
    fn ring_buffer_matches_vecdeque(ops in proptest::collection::vec(0u8..=2, 0..100)) {
        let mut rb = RingBuffer::with_capacity(8);
        let mut model = VecDeque::new();

        for op in ops {
            match op {
                0 => {
                    if model.len() < 8 {
                        let value = model.len() as u32;
                        prop_assert_eq!(rb.push(value), Ok(()));
                        model.push_back(value);
                    }
                }
                1 => {
                    prop_assert_eq!(rb.pop(), model.pop_front());
                }
                _ => {
                    prop_assert_eq!(rb.len(), model.len());
                    prop_assert_eq!(rb.is_empty(), model.is_empty());
                }
            }
        }
    }
}
```

Keep generated inputs small at first. Increase size only after the test is stable.

## Regression test pattern

When fixing a bug, add the smallest failing case.

```rust
#[test]
fn parse_rejects_trailing_bytes_after_valid_header() {
    let input = b"HEADER\0unexpected";
    let err = parse_header(input).unwrap_err();

    assert!(matches!(err, ParseError::TrailingBytes { offset: 7 }));
}
```

A regression test should fail on the old code and pass on the fixed code.

If possible, confirm this before finalizing.

## Mutation testing sanity check

Coverage shows that code was executed. Mutation testing helps check whether assertions detect behavioral changes.

Run:

```bash
cargo mutants
```

Use mutation results to identify tests that are too weak.

If a mutant survives, do not blindly add an assertion. First ask:

* Is the mutant behavior actually observable?
* Is the mutated code part of the public contract?
* Is the code dead or redundant?
* Should the implementation be simplified instead of tested?

Sometimes the right fix is deleting unreachable code, not adding a test.

## Coverage exclusions

Avoid excluding code from coverage unless there is a strong reason.

Acceptable exclusions may include:

* platform-specific code impossible to run in current CI;
* defensive branches that cannot be reached from safe public APIs;
* debug-only diagnostics;
* generated code;
* code exercised only by external integration tests.

When excluding code, leave a short reason.

Do not exclude hard-to-test logic just to improve the coverage percentage.

## Anti-patterns

Do not add:

```rust
assert!(true);
```

Do not add tests that only call getters without checking behavior.

Do not assert unstable debug strings unless the debug output is part of the contract.

Do not overfit to the current implementation.

Do not make tests depend on hash map iteration order unless the order is guaranteed.

Do not add sleeps to "fix" flaky async or concurrency tests unless there is no alternative.

Do not weaken the API or expose internals just to test them.

Do not update snapshots without inspecting the semantic diff.

Do not accept higher coverage if the new tests would still pass after deleting the important assertion.

## Final validation

Before finishing, run the relevant subset:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-features --all-targets -- -D warnings
cargo test --workspace --all-features
cargo llvm-cov --workspace --all-features --summary-only
```

If the project uses nextest:

```bash
cargo llvm-cov nextest --workspace --all-features
```

If unsafe code was touched or tested:

```bash
cargo +nightly miri test
```

If property tests were added, make sure failures are reproducible and no excessive cases make CI slow.

## Final report

Summarize:

* baseline coverage;
* final coverage;
* files/functions improved;
* tests added;
* behavior or invariant each test checks;
* remaining uncovered high-risk code;
* any tests intentionally not added and why;
* commands run.

Do not report coverage as the only success criterion. Emphasize the new behavioral guarantees.


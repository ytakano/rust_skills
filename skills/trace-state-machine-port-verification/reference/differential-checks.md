# Differential equivalence checks

State-machine acceptance is **necessary but not sufficient**. A trace can be accepted by `M`
and still differ from the corresponding C++ behavior. Always compare the two normalized
traces directly, plus outputs and side effects.

## The five checks (single source of truth)

For each input, verify **all** of the following:

```text
1. accepts(M, normalize(trace_cpp(input)))                                   # C++ trace is spec-valid
2. accepts(M, normalize(trace_rust(input)))                                  # Rust trace is spec-valid
3. equivalent_trace(normalize(trace_cpp(input)), normalize(trace_rust(input)))  # the two agree  (this is "≈")
4. equivalent_output(output_cpp(input), output_rust(input))                  # stdout/stderr/exit/return
5. equivalent_side_effects(side_effects_cpp(input), side_effects_rust(input))   # files/db/network/state
```

`≈` throughout this skill means check #3: `equivalent_trace` over normalized traces.

## Trace equivalence checker

`diff_trace.py` (see [../templates/verification/diff_trace.py](../templates/verification/diff_trace.py))
compares normalized C++ and Rust traces. Minimum comparisons:

- Event sequence equivalence
- Event parameter equivalence
- Session mapping equivalence
- Resource mapping equivalence
- Terminal state equivalence
- Error code equivalence

For non-concurrent programs, a normalized event-sequence comparison is usually enough.

## Allowed vs disallowed differences

Do not require exact low-level trace identity. Document which differences the spec allows.

**Potentially acceptable** (often just implementation detail):

```text
Internal buffer allocation counts
Internal function boundaries
Order of independent events
Resource release timing caused by Rust Drop
Log wording
Non-semantic IDs (before normalization)
```

**Never acceptable** — a difference here is a real bug:

```text
Final output
Error kind or success/failure result
Exit code when it is part of the contract
Missing close/drop/release equivalent
Commit versus rollback behavior
Protocol state transitions
External side effects
Security boundary handling
Persistent state
```

## Concurrency and async

If the target is multithreaded or async, do **not** require exact total-order trace equality
unless the specification requires it. Instead use one or more of:

- Per-session trace comparison
- Per-resource trace comparison
- Happens-before comparison for lock/unlock, send/receive, spawn/join, request/response
- Canonical ordering of independent events
- Explicit, documented reordering rules for events whose relative order is not meaningful

Example — these may be equivalent if the `A` and `B` event families are independent:

```text
A1, B1, A2, B2
B1, A1, B2, A2
```

Do **not** ignore ordering around shared state, locks, transactions, external I/O, or
security boundaries.

## Output and side-effect equivalence

Always compare observable results in addition to traces:

```text
stdout            Return value      Generated files     Network requests
stderr            Error kind        Updated files       Metrics
Exit code                           Database updates     Persistent state
```

Make side effects testable by isolating them:

- Use temporary directories.
- Use a test database or in-memory database.
- Mock or fake network services.
- Fix time and random seeds.
- Capture generated files and compare normalized content.

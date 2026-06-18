---
name: trace-state-machine-port-verification
description: Use when porting a C++ implementation to Rust and you need confidence the port is behavior-equivalent. Guides the full workflow — establish a C++ baseline, design a spec-level state machine and abstract trace, instrument both sides, port to Rust, then prove observable equivalence by differential testing, with failure triage and regression tests.
---

# C++ → Rust port verification with state machines and traces

## Core principle

The goal of a port is **not** to reproduce the low-level C++ implementation in Rust. It is to
make the Rust version **specification-correct** and **observably equivalent** to the C++
original for the same inputs. The Rust internal structure may differ freely; the abstract
behavior must not.

To get there, drive the port with four checks, always together:

1. **Trace acceptance** by a specification-level state machine `M`.
2. **Differential testing** of C++ vs Rust on identical inputs.
3. **Equivalence** of outputs, errors, side effects, and final states.
4. **Failure minimization** and regression tests.

> `trace_cpp ∈ M` and `trace_rust ∈ M` are **necessary but not sufficient**.
> Always also verify `normalize(trace_cpp) ≈ normalize(trace_rust)` (where `≈` means
> `equivalent_trace`), plus output and side-effect equivalence.

The state machine is a spec monitor — by itself it does not prove the port is equivalent.
Do **not** treat the C++ implementation as unconditionally correct: a difference in Rust may
expose a C++ bug, undefined behavior, or implementation-defined behavior. Investigate and
document — do not "fix" Rust to match a broken original, and do not reproduce C++ UB in Rust.

## When to use this skill

Use it when porting C++ to Rust **and** plain output comparison is too weak — i.e. the
program has meaningful state: protocol phases, processing stages, sessions, transactions, or
resource lifecycles. Typical targets: parsers, protocol handlers, file processors,
transaction/session managers, stream processors, compiler/transformation pipelines, stateful
library APIs, concurrent service logic, resource-lifecycle code.

## Inputs to gather first

Collect as many as possible; if some are missing, infer a **provisional** specification from
the repo, tests, and code structure, and document the assumptions. Do not stop because inputs
are missing.

- Paths to the C++ source and the Rust port (or its intended location).
- C++ and Rust build/test commands (ask the user or infer from the repo — never hard-code).
- Existing tests, sample inputs, fixtures, corpora, production logs.
- Expected outputs, errors, exit codes, side effects.
- Specs, READMEs, comments, API docs, design notes, known bug fixes, edge cases.
- Sources of nondeterminism: randomness, time, thread scheduling, I/O ordering, hash
  iteration order, external service responses.
- Suspected C++ undefined or implementation-defined behavior.

## Porting workflow

Reference material lives in [`reference/`](./reference/); copy-and-adapt scaffolds live in
[`templates/`](./templates/). The verification assets (`state_machine.yaml`, the Python
tools, traces, repros) are created in the **target repo**, conventionally under
`verification/` — start from the templates rather than writing from scratch.

1. **Establish the C++ baseline.** Run existing tests and representative inputs; record
   outputs, errors, exit codes, final states, and side effects. Run sanitizers (ASan, UBSan,
   TSan, Valgrind) if available. Document known UB / implementation-defined / environment-
   dependent behavior.
2. **Design the abstract event vocabulary and trace schema.** Pick semantic events both
   implementations can emit at meaningful boundaries; write the schema before broad
   instrumentation. → [`reference/trace-contract.md`](./reference/trace-contract.md),
   template [`templates/verification/trace_schema.md`](./templates/verification/trace_schema.md).
3. **Design the spec-level state machine.** Use specs, tests, docs, and domain knowledge —
   not just C++ logs. Include normal paths, error paths, forbidden transitions, terminal vs
   accepting states, lifecycle rules, and guards. Test both accepted and rejected traces. →
   [`reference/state-machine-format.md`](./reference/state-machine-format.md), template
   [`templates/verification/state_machine.yaml`](./templates/verification/state_machine.yaml).
4. **Instrument C++.** Add minimal, isolated, easy-to-disable tracing using the same event
   names. Emit on exceptions, early returns, and error/close/drop paths. Confirm tracing does
   not change existing test results. → [`templates/cpp/`](./templates/cpp/). Then validate the
   normalized C++ trace against `M`; if it is rejected, classify the cause before editing
   ([`reference/failure-triage.md`](./reference/failure-triage.md)).
5. **Port to Rust.** Preserve spec-level behavior; the internal structure need not match.
   Keep abstract events, outputs, errors, and side effects equivalent. When a C++ bug or spec
   ambiguity surfaces, document the decision rather than copying the C++ behavior blindly.
6. **Instrument Rust** with the same abstract event API. If release events come from `Drop`,
   avoid double-counting an explicit `close`. → [`templates/rust/trace.rs`](./templates/rust/trace.rs).
7. **Run differential tests on identical inputs** and check all five conditions (acceptance ×2,
   trace equivalence, output equivalence, side-effect equivalence). Document which low-level
   differences the spec allows; never accept differences in outcomes, side effects, or
   protocol state. → [`reference/differential-checks.md`](./reference/differential-checks.md),
   harness [`templates/verification/run_diff.py`](./templates/verification/run_diff.py).
8. **Stand up the tooling**: normalization, the state-machine monitor, the trace-equivalence
   checker, and the harness. → [`templates/verification/`](./templates/verification/)
   (`normalize_trace.py`, `trace_monitor.py`, `diff_trace.py`, `run_diff.py`) and
   [`reference/normalization.md`](./reference/normalization.md).
9. **Expand the input space** beyond a few hand-written cases: existing tests, sample inputs,
   production-log replay, boundary values, error-triggering inputs, historical repros,
   property-based testing, fuzzing.
10. **Triage and fix failures, then lock them in.** Classify before changing code, minimize,
    save a repro, and add a regression test. → [`reference/failure-triage.md`](./reference/failure-triage.md).

Track completion and report results against
[`reference/reporting.md`](./reference/reporting.md).

## Never do

- Declare the port correct just because `trace_cpp ∈ M` and `trace_rust ∈ M`.
- Define the state machine solely from current C++ behavior without checking the intended spec.
- Loosen the state machine, or add a normalization rule, to make an incorrect Rust trace pass.
- Compare raw debug logs as if they were semantic traces.
- Compare memory addresses, wall-clock time, random IDs, or hash order without normalization.
- Reproduce C++ undefined behavior in Rust just to match the original.
- Let trace instrumentation change program behavior.
- Require exact total-order equality for concurrent traces unless the spec demands it.
- Discard a failing input after debugging — turn it into a regression test.

## Minimal flow

Start small — get one useful check running before building out. Copy `templates/verification/`
into the target repo, then:

```bash
# 1. Run each implementation, emitting a JSON Lines trace to TRACE_OUT.
TRACE_OUT=/tmp/cpp.trace.jsonl  ./build/original     < input.bin > /tmp/cpp.out
TRACE_OUT=/tmp/rust.trace.jsonl ./target/debug/ported < input.bin > /tmp/rust.out

# 2. Normalize both traces into a comparable form.
python verification/normalize_trace.py /tmp/cpp.trace.jsonl  > /tmp/cpp.norm.jsonl
python verification/normalize_trace.py /tmp/rust.trace.jsonl > /tmp/rust.norm.jsonl

# 3. Validate each trace against the state machine.
python verification/trace_monitor.py verification/state_machine.yaml /tmp/cpp.norm.jsonl
python verification/trace_monitor.py verification/state_machine.yaml /tmp/rust.norm.jsonl

# 4. Compare normalized traces, then outputs.
python verification/diff_trace.py /tmp/cpp.norm.jsonl /tmp/rust.norm.jsonl
diff -u /tmp/cpp.out /tmp/rust.out
```

Once this works for one case, drive it over a corpus with
[`templates/verification/run_diff.py`](./templates/verification/run_diff.py).

## Final rule

Make the Rust implementation specification-correct and observably equivalent to the C++
original for the same inputs, with ongoing verification through traces, state-machine
monitoring, differential testing, and regression tests.

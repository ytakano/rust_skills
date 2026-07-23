---
name: trace-state-machine-port-conformance
description: >-
  Use when porting a C++ implementation to Rust and you need confidence the port is
  behavior-equivalent. Guides the full workflow — establish a C++ baseline, inventory every
  external or semantically observable value selected as in-scope by the port-equivalence
  contract, define that fail-closed contract and a state machine, instrument both sides, port
  to Rust, then check contract/state-machine conformance and trace/outcome/side-effect
  equivalence with field-specific numeric policies, complete contract coverage, comparator
  mutation audit, failure triage, and regression tests.
---

# C++ → Rust port conformance and equivalence testing

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
> Always also validate both traces against the fail-closed equivalence contract, check
> `normalize(trace_cpp) ≈ normalize(trace_rust)` (where `≈` means the contract's
> `equivalent_trace`), compare outcomes and side effects, cover every declared semantic path,
> and mutation-audit the comparator.

“Complete comparison” means complete accounting of the **external or semantically observable
values selected as in-scope by the port-equivalence contract**: public results/errors, semantic
state, resource lifecycle, and external side effects. Select that scope using the intended
specification, public interfaces, existing tests, and behavior on which real users depend; do
not limit it to what a specification document happens to mention. It does not mean coupling the
port to every implementation-local variable. A value with no observability-matrix row and
contract path is not checked; an unknown or unconfigured value is a hard failure, never an
implicit ignore.

The state machine is a spec monitor — by itself it does not prove the port is equivalent.
This workflow produces test evidence and confidence, not a formal proof of correctness or
completeness beyond the declared contract and exercised corpus.
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
- A complete inventory of public results, semantic state, error/cleanup paths, resources, and
  external effects, with their C++ and Rust observation points.
- Specs, READMEs, comments, API docs, design notes, known bug fixes, edge cases.
- Numeric requirements: precision, rounding/FMA/fast-math environment, external resolution,
  error bounds, NaN/infinity/signed-zero behavior, and control-flow thresholds.
- Sources of nondeterminism: randomness, time, thread scheduling, I/O ordering, hash
  iteration order, external service responses.
- Suspected C++ undefined or implementation-defined behavior.

## Porting workflow

Reference material lives in [`reference/`](./reference/); copy-and-adapt scaffolds live in
[`templates/`](./templates/). The conformance assets (`state_machine.yaml`, the Python
tools, traces, repros) are created in the **target repo**, conventionally under
`conformance/` — start from the templates rather than writing from scratch.

1. **Establish the C++ baseline.** Run existing tests and representative inputs; record
   outputs, errors, exit codes, final states, and side effects. Run sanitizers (ASan, UBSan,
   TSan, Valgrind) if available. Document known UB / implementation-defined / environment-
   dependent behavior.
2. **Inventory observables and define the fail-closed contract.** Select in-scope external or
   semantically observable values using specifications, public interfaces, existing tests, and
   behavior on which real users depend. Fill in the observability matrix before broad
   instrumentation:
   every in-scope result, error, state, lifecycle action, and side effect maps to a C++ point,
   Rust point, contract path, comparator, and tests. Record a reason for every explicit
   exclusion; never let an absent row become an implicit exclusion.
   Make `equivalence_contract.json` the machine-readable source of truth. Every scalar has an
   explicit policy; unknown/missing/untyped data fails; ignores and coverage waivers require
   reasons. → [`reference/trace-contract.md`](./reference/trace-contract.md),
   [`reference/equivalence-contract.md`](./reference/equivalence-contract.md), templates
   [`templates/conformance/trace_schema.md`](./templates/conformance/trace_schema.md) and
   [`templates/conformance/equivalence_contract.json`](./templates/conformance/equivalence_contract.json).
3. **Design the spec-level state machine.** Use specs, tests, docs, and domain knowledge —
   not just C++ logs. Include normal paths, error paths, forbidden transitions, terminal vs
   accepting states, lifecycle rules, guards, and any legitimate numeric boundary bands. Test
   both accepted and rejected traces. →
   [`reference/state-machine-format.md`](./reference/state-machine-format.md), template
   [`templates/conformance/state_machine.yaml`](./templates/conformance/state_machine.yaml).
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
7. **Run fail-closed differential tests on identical inputs.** Validate both traces against
   the contract; check state-machine acceptance ×2, recursive trace equivalence,
   stdout/stderr/exit equivalence, and canonical side-effect-manifest equivalence. Run C++ and
   Rust in separate workdirs. Never accept differences in outcomes, side effects, security
   decisions, or protocol state. → [`reference/differential-checks.md`](./reference/differential-checks.md),
   harness [`templates/conformance/run_diff.py`](./templates/conformance/run_diff.py).
8. **Stand up the tooling**: normalization, the state-machine monitor, the trace-equivalence
   checker, the contract, and the harness. Normalization removes only approved noise; it never
   rounds floats. Numeric tolerances live in the contract and come from the specification or
   error analysis, never observed drift. → [`templates/conformance/`](./templates/conformance/)
   and [`reference/normalization.md`](./reference/normalization.md).
9. **Expand the input space** beyond a few hand-written cases: existing tests, sample inputs,
   production-log replay, boundary values, error-triggering inputs, historical repros,
   property-based testing, fuzzing. Require zero missing contract paths across the corpus, and
   separately measure state/transition/guard/error coverage.
10. **Audit the comparator.** Mutation-audit every observed semantic scalar, required field,
    event, and event order; semantic changes must fail and explicitly ignored values must remain
    ignored. Treat any audit failure as a broken checker, not evidence about the port.
11. **Triage and fix failures, then lock them in.** Classify before changing code, minimize,
    save a repro, and add a regression test. → [`reference/failure-triage.md`](./reference/failure-triage.md).

Track completion and report results against
[`reference/reporting.md`](./reference/reporting.md).

## Never do

- Declare the port correct just because `trace_cpp ∈ M` and `trace_rust ∈ M`.
- Define the state machine solely from current C++ behavior without checking the intended spec.
- Loosen the state machine, or add a normalization rule, to make an incorrect Rust trace pass.
- Compare raw debug logs as if they were semantic traces.
- Hand-select a few “important” values while silently ignoring the rest.
- Accept an unknown event/field, a missing required value, or a scalar without a comparison
  policy.
- Round or truncate floats during normalization, or choose epsilon from the current failures.
- Use approximate numeric equality to hide a changed event, terminal state, success/error,
  commit/rollback result, security decision, or external side effect.
- Compare memory addresses, wall-clock time, random IDs, or hash order without normalization.
- Reproduce C++ undefined behavior in Rust just to match the original.
- Let trace instrumentation change program behavior.
- Require exact total-order equality for concurrent traces unless the spec demands it.
- Discard a failing input after debugging — turn it into a regression test.

## Minimal flow

Start small — get one useful check running before building out. Copy `templates/conformance/`
into the target repo, then:

```bash
# 1. Run each implementation, emitting a JSON Lines trace to TRACE_OUT.
TRACE_OUT=/tmp/cpp.trace.jsonl  ./build/original     < input.bin > /tmp/cpp.out
TRACE_OUT=/tmp/rust.trace.jsonl ./target/debug/ported < input.bin > /tmp/rust.out

# 2. Normalize both traces into a comparable form.
python conformance/normalize_trace.py /tmp/cpp.trace.jsonl  > /tmp/cpp.norm.jsonl
python conformance/normalize_trace.py /tmp/rust.trace.jsonl > /tmp/rust.norm.jsonl

# 3. Validate each trace against the state machine.
python conformance/trace_monitor.py conformance/state_machine.yaml /tmp/cpp.norm.jsonl
python conformance/trace_monitor.py conformance/state_machine.yaml /tmp/rust.norm.jsonl

# 4. Compare every declared field and mutation-audit the comparator.
python conformance/diff_trace.py \
  --contract conformance/equivalence_contract.json \
  --audit \
  --coverage-out /tmp/trace-coverage.json \
  /tmp/cpp.norm.jsonl /tmp/rust.norm.jsonl
diff -u /tmp/cpp.out /tmp/rust.out
```

The manual flow is only a bring-up check. For a complete conformance and equivalence
assessment, drive the full corpus through the harness so stderr, exit code, isolated
side-effect manifests, aggregate contract coverage, audit, and repro preservation are enforced:

```bash
python conformance/run_diff.py \
  --cpp-bin build/original \
  --rust-bin target/debug/ported \
  --state-machine conformance/state_machine.yaml \
  --contract conformance/equivalence_contract.json \
  --cases conformance/corpus \
  --coverage-out conformance/coverage.json \
  --repro-dir conformance/repro
```

Run the scaffold's own comparator/harness tests whenever adapting the contract or tools:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest -v conformance/test_diff_trace.py
```

## Final rule

Make the Rust implementation specification-correct and observably equivalent to the C++
original for the same inputs. Account in a fail-closed contract for every external or
semantically observable value selected as in-scope by that contract, exercise every declared
semantic path, audit the comparator's sensitivity, and preserve ongoing confidence through
state-machine monitoring, differential testing, and regression tests.

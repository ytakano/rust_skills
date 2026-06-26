---
name: rust-realtime-review
description: Use when reviewing Rust patches, PRs, or files for real-time safety, WCET predictability, bounded execution, allocation-free RT paths, panic-free RT paths, synchronization risks, async poll bounds, data-structure predictability, and residual timing risks. Use quick review for normal patches and WCET audit mode for deeper timing-bound analysis.
---

# Rust Real-Time Review

## Goal

Review Rust code for **bounded real-time behavior**, not just correctness or average-case speed.

The review should identify changes that make RT-critical paths harder to bound:

```text
allocation, blocking, panic paths, unbounded loops, unbounded data structures,
hidden Drop work, logging/formatting, async poll blowups, lock contention,
priority inversion, variable-cost comparisons, and unknown callbacks.
```

If you need implementation guidance, read `../rust-realtime-implementation/SKILL.md`.
If you need deeper review examples and audit templates, read `rust-realtime-review-notes.md`.

---

## Review Modes

Use one of two modes.

```text
Quick review:
  Use for normal PRs/patches. Focus on actionable regressions and missing bounds.

WCET audit:
  Use when the user asks for WCET, worst-case latency, hard real-time readiness,
  deadline safety, boundedness, timing audit, or explicit execution-time reasoning.
```

If unspecified, start with quick review. Escalate to WCET audit if the diff touches scheduler, ISR, driver fast path, allocator, synchronization, async executor, or control loop code.

---

## First Step: Identify RT-Critical Paths

Before reviewing details, classify affected paths:

```text
RT-critical:
  ISR, scheduler tick, deadline task, driver fast path, packet Rx/Tx,
  control loop, RT async poll, allocator/sync primitive used by RT code.

RT-adjacent:
  Deferred work, telemetry handoff, background reclaim, driver control path.

Non-RT:
  Startup, config parsing, debug dump, metrics formatting, CLI, tests.
```

Apply strict findings only to RT-critical or RT-adjacent paths. Do not complain about harmless non-RT conveniences unless they interfere with RT execution.

---

## Primary Review Questions

For each touched RT-critical path, answer:

```text
Can it allocate?
Can it block?
Can it panic?
Can it loop without a fixed/documented bound?
Can it resize, rehash, split, merge, or deallocate?
Can it log, format, or perform unknown-latency I/O?
Can it hold a lock across await or unknown work?
Can Drop hide unbounded cleanup?
Can key comparison or hashing depend on variable-length input?
Can it call user-provided code with unknown cost?
Is the WCET contract still true?
```

A review finding is strongest when it names the exact RT path and the exact operation that breaks boundedness.

---

## Red Flags in RT-Critical Code

Treat these as suspicious:

```rust
unwrap()
expect()
panic!()
assert!()
todo!()
unimplemented!()
unreachable!()
format!()
println!()
vec![]
String
Vec::new()
Box::new()
Arc::new()
HashMap
HashSet
std::sync::Mutex
std::sync::RwLock
Condvar
thread::sleep
```

Also inspect:

```text
indexing/slicing that may panic
Vec push/insert/remove without capacity proof
collect::<Vec<_>>()
to_string(), to_vec(), clone of large data
map-wide iteration
unbounded iterator chains
unbounded CAS retry loops
large owned values leaving scope
trait object calls or callbacks in RT paths
```

Do not flag these mechanically in tests, setup code, or non-RT paths unless they affect RT execution.

---

## Data Structure Review

Prefer this order in RT-critical paths:

```text
best:
  fixed array, fixed ring buffer, bitmap/bitset, indexed table,
  preallocated slab + integer ID, fixed-capacity queue, priority buckets

acceptable with proof:
  fixed-capacity heap, sorted fixed array, bounded Vec with no reallocation,
  BTreeMap read-only lookup, BTreeMap with bounded length and bounded key cost

risky:
  HashMap/HashSet, String/Vec/PathBuf keys, unbounded maps, resizing collections,
  map-wide iteration without a static bound
```

WCET note:

```text
HashMap:
  expected-case fast, but collision/probing/hash/resize behavior is hard to bound.

BTreeMap:
  usually more predictable, but still requires bounded n, bounded key comparison,
  and explicit reasoning about insert/remove allocation or node changes.
```

Prefer integer keys such as `TaskId(u32)`, `JobId(u32)`, `Deadline(u64)`, `Priority(u8)`, and `CpuId(u16)`.

---

## Loop and Async Review

Every RT-critical loop needs a static or documented bound.

Good:

```rust
for i in 0..MAX_TASKS {
    // bounded
}
```

Suspicious:

```rust
while let Some(x) = queue.pop() {
    // only OK if queue length is statically bounded and documented
}
```

For async Rust, review each RT-critical `Future::poll` path:

```text
maximum work per poll
allocation inside poll
locks held during poll
locks held across await
cancellation/Drop behavior
wake storm behavior
executor scheduling latency
```

A future is not RT-friendly merely because it is async. `poll()` must be bounded.

---

## Locking and Synchronization Review

Rust locks provide memory safety, not WCET safety.

For locks or atomics in RT-critical paths, check:

```text
maximum lock hold time
maximum wait time
priority inversion handling
interrupt-context behavior
lock ordering
allocation/logging/await while locked
bounded retry count for CAS loops
```

Prefer per-CPU data, bounded queues, SPSC handoff, priority ceiling/inheritance, short interrupt-disabled sections, or bounded retry loops.

Never accept `.await` while holding a lock in RT-critical code unless the lock and executor are explicitly designed for that behavior.

---

## Panic, Drop, and Hidden Work Review

Panic-capable APIs are timing and reliability risks in RT-critical paths:

```rust
arr[i]
slice[a..b]
unwrap()
expect()
assert!()
panic!()
```

Prefer checked access and explicit `Result` errors.

Inspect hidden work in `Drop`:

```text
Vec/String/Box/Arc drop
collection drop
large owned values leaving scope
guard types with side effects
deferred cleanup in destructors
```

If a type used in an RT-critical path implements `Drop`, its cost should be O(1) or bounded by a documented fixed capacity.

---

## WCET Contract Review

Important RT-critical functions should have short WCET contracts.

Check that each contract still matches the code:

```text
maximum loop bound
maximum collection size
allocation behavior
blocking behavior
panic behavior
lock/callback/await behavior
key comparison cost
interrupt-disabled impact
```

A missing or stale WCET contract is a valid review finding when the function is RT-critical.

---

## Severity Levels

Use these levels for findings:

```text
Critical:
  Can cause deadline miss, unbounded wait, allocation, panic, or blocking in an RT path.

High:
  Makes WCET hard to bound, introduces risky data structure or hidden cleanup.

Medium:
  Missing bound, stale WCET contract, weak error handling, insufficient validation.

Low:
  Style/readability issue that affects future RT maintainability.
```

Prefer fewer, sharper findings over a large list of generic complaints.

---

## Output Format: Quick Review

For normal patch review, produce concise actionable comments:

```text
Summary:
- Overall RT risk assessment.

Findings:
- [Severity] File/function: issue, why it matters for RT/WCET, suggested fix.

Missing evidence:
- Bounds, tests, measurements, or contracts that should be added.

Verdict:
- Accept / Accept with fixes / Needs changes / Needs WCET audit.
```

---

## Output Format: WCET Audit

For deep audit mode, produce a boundedness table:

```text
RT path | Operation | Bound | Evidence | Residual risk
```

Also include:

```text
allocation audit
panic audit
loop audit
collection audit
locking/synchronization audit
async poll audit
Drop audit
measurement or validation gaps
final residual risks
```

Do not claim hard real-time safety unless timing bounds are explicit and hardware/platform assumptions are stated.

---

## Final Rule

A Rust patch is not RT-safe merely because it is safe Rust, idiomatic Rust, or passes tests.

For RT-critical code, the reviewer must be able to answer:

```text
What is the maximum work?
What is the maximum number of elements touched?
Can it allocate, block, panic, or call unknown code?
What happens when the structure is full?
What timing risk remains?
```

If these cannot be answered, request a bound, redesign, measurement, or explicit residual-risk note.

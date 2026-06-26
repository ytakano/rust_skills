---
name: rust-realtime-implementation
description: Use when implementing or writing Rust code for real-time systems where predictable WCET matters. Apply to RT-critical paths such as ISRs, schedulers, drivers, packet fast paths, async poll loops, control loops, allocators, and synchronization code. Prefer bounded, allocation-free, panic-free, blocking-free designs over fast average-case code. For reviewing existing patches or PRs, use rust-realtime-review instead.
---

# Rust Real-Time Implementation

## Goal

Implement **bounded Rust** for real-time execution.

The priority is not average-case speed. The priority is that the maximum work of RT-critical operations is explicit, bounded, reviewable, and testable.

If more detail is needed, read `rust-realtime-implementation-notes.md` in this skill directory.

---

## 1. Classify the Path First

Before editing, classify the affected code:

```text
RT-critical:
  ISR, scheduler tick, deadline task, driver fast path, packet Rx/Tx,
  control loop, RT async poll, allocator/sync primitive used by RT code.

RT-adjacent:
  Deferred work, telemetry handoff, background reclaim, driver control path.

Non-RT:
  Startup, config parsing, debug dump, metrics formatting, CLI, tests.
```

Apply strict rules only to RT-critical paths. Do not overfit the whole project if only the RT path matters.

---

## 2. Required WCET Contract

For every important RT-critical function, add or update a short WCET contract.

```rust
/// WCET contract:
/// - No heap allocation.
/// - No blocking.
/// - No panic for valid caller inputs.
/// - Scans at most MAX_READY entries.
/// - Key comparisons are fixed-width integer comparisons.
/// - Does not log, format, call user code, or await.
/// - Caller already holds the required scheduler lock.
pub fn choose_next<const MAX_READY: usize>(
    ready: &[Job; MAX_READY],
    now: Time,
) -> Option<JobId> {
    // ...
}
```

A good contract names:

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

Avoid vague claims like “fast”, “small”, “efficient”, or “usually O(1)”.

---

## 3. Hard Rules for RT-Critical Code

RT-critical code should not contain:

```text
heap allocation
blocking waits
unbounded loops
panic paths
unwinding
formatting or logging
filesystem I/O
unknown-latency I/O
unbounded lock contention
recursive calls
unbounded iterator chains
large hidden Drop work
user callbacks with unknown cost
```

Treat these as suspicious in RT-critical code:

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

Replace panic-based failure with explicit `Result`.

---

## 4. Allocation Rule

RT-critical runtime code should not allocate.

Preferred phase split:

```text
setup/init phase:
  allocation, parsing, dynamic construction allowed

runtime RT phase:
  allocation forbidden
  buffers preallocated
  queue/map capacities fixed
```

Bad:

```rust
fn handle_packet(pkt: Packet, q: &mut Vec<Packet>) {
    q.push(pkt);
}
```

Better:

```rust
fn handle_packet<const N: usize>(
    pkt: Packet,
    q: &mut heapless::Vec<Packet, N>,
) -> Result<(), Packet> {
    // `heapless::Vec::push` returns Err(pkt) when the buffer is full;
    // no allocation, no panic.
    q.push(pkt)
}
```

If allocation is unavoidable, document allocator, failure behavior, locking behavior, interrupt-context behavior, and worst-case bound.

---

## 5. Data Structure Rule

Prefer fixed-size and index-based structures.

Best RT choices:

```text
fixed array
fixed ring buffer
bitmap / bitset
indexed table
preallocated slab + integer ID
fixed-capacity queue
fixed-capacity heap
sorted fixed array
priority buckets
```

Use with care:

```text
BTreeMap read-only lookup
BTreeMap with bounded length and bounded key comparison
BinaryHeap with preallocated capacity
Vec with proven fixed capacity and no reallocation
```

Avoid in RT-critical paths:

```text
HashMap / HashSet
Vec push without capacity proof
String / Vec / PathBuf keys
map-wide iteration without a static bound
collections that resize, rehash, allocate, or deallocate
```

WCET note:

```text
HashMap:
  expected-case fast, but collision/probing/resize/hash cost is hard to bound.

BTreeMap:
  more predictable than HashMap, but still not automatically RT-safe.
  Bound n, key comparison cost, and allocation behavior.
```

Prefer integer keys:

```rust
TaskId(u32)
JobId(u32)
Deadline(u64)
Priority(u8)
CpuId(u16)
```

---

## 6. Loop Rule

Every RT-critical loop must have a static or documented bound.

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

For async code, bound work per `poll()`.

```rust
for _ in 0..MAX_ITEMS_PER_POLL {
    let Some(item) = queue.pop() else { break };
    process_one(item);
}
yield_now().await;
```

---

## 7. Locking Rule

Rust locks provide memory safety, not WCET safety.

Before using a lock in an RT-critical path, document:

```text
maximum lock hold time
maximum wait time
priority inversion handling
whether interrupt context may take it
lock ordering
whether allocation/logging/await occurs while locked
```

Never hold a lock across `.await` in RT-critical code unless the executor and lock are explicitly designed for that case.

Prefer:

```text
per-CPU data
SPSC ring buffers
bounded MPSC queues
short interrupt-disabled sections
priority ceiling / priority inheritance
preallocated message passing
bounded atomic retry loops
```

---

## 8. Panic, Drop, and Hidden Work

Avoid panic-capable APIs in RT-critical code:

```rust
arr[i]
slice[a..b]
unwrap()
expect()
assert!()
panic!()
```

Prefer checked access and explicit errors.

```rust
let Some(x) = arr.get(i) else {
    return Err(RtError::OutOfRange);
};
```

Watch for hidden work in `Drop`:

```text
Vec/String/Box/Arc drop
collection drop
large owned values leaving scope
guard types with side effects
deferred cleanup in destructors
```

If a type used in RT-critical code implements `Drop`, its cost must be O(1) or bounded by a documented fixed capacity.

---

## 9. Suggested Lints for RT-Critical Crates

Use strict lints when RT-critical code is isolated into its own crate or module.

```rust
#![no_std]
#![deny(clippy::unwrap_used)]
#![deny(clippy::expect_used)]
#![deny(clippy::panic)]
#![deny(clippy::todo)]
#![deny(clippy::unimplemented)]
#![deny(clippy::indexing_slicing)]
```

Optional stricter lints:

```rust
#![deny(clippy::alloc_instead_of_core)]
#![deny(clippy::std_instead_of_core)]
#![deny(clippy::std_instead_of_alloc)]
```

Use `panic = "abort"` for release profiles when appropriate, but do not treat it as a substitute for eliminating panic paths.

---

## 10. Implementation Workflow

For each change:

```text
1. Identify RT-critical paths touched by the change.
2. Add/update WCET contracts.
3. Remove allocation from RT runtime paths.
4. Replace panic paths with Result-based handling.
5. Replace unbounded loops with fixed bounds or bounded batches.
6. Prefer fixed-capacity/indexed data structures.
7. Review synchronization for bounded wait and priority inversion.
8. Check hidden costs: Drop, iterators, trait objects, callbacks, formatting.
9. Run tests, clippy, and relevant benchmarks.
10. Report remaining unbounded behavior honestly.
```

---

## 11. Final Report Format

When finishing, report:

```text
Summary:
- What changed.

RT path impact:
- RT-critical paths touched.
- Allocation/blocking/panic/logging changes.

WCET reasoning:
- Loop bounds.
- Collection bounds.
- Data structure choices.
- Locking/synchronization reasoning.
- Remaining unbounded behavior.

Validation:
- Tests run.
- Clippy/checks run.
- Benchmarks/cycle measurements if available.

Residual risks:
- What still needs measurement, proof, or hardware validation.
```

Do not claim real-time safety merely because the code compiles or tests pass.

---

## Key Mental Model

Rust gives memory safety and strong ownership discipline.

Rust does not automatically give:

```text
bounded execution time
bounded allocation time
bounded lock wait time
bounded Drop time
bounded cache behavior
bounded interrupt latency
```

Real-time Rust means:

```text
safe Rust
+ bounded data structures
+ bounded loops
+ bounded synchronization
+ allocation-free RT paths
+ panic-free RT paths
+ explicit WCET contracts
```

The goal is not just safe Rust.

The goal is **bounded Rust**.

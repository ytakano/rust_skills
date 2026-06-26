# Rust Real-Time Review Notes

Supplement for `rust-realtime-review/SKILL.md`.

This file contains deeper review guidance, examples, and WCET audit templates. The main `SKILL.md` should stay compact; put detailed explanations here.

---

# 1. Review Philosophy

Real-time review is not the same as ordinary Rust review.

Ordinary review asks:

```text
Is it correct?
Is it safe?
Is it idiomatic?
Is it maintainable?
```

Real-time review also asks:

```text
Is the maximum execution time explainable?
Is the maximum wait time explainable?
Is the maximum memory behavior explainable?
Does the patch make a deadline miss more likely?
```

Rust prevents many memory-safety bugs, but it does not automatically prevent:

```text
heap allocation latency
panic paths
unbounded lock waits
priority inversion
unbounded async poll work
hash collision/probing behavior
large Drop cleanup
cache and DMA interference
interrupt latency
```

A good reviewer focuses on boundedness and evidence, not vibes like “this should be fast”.

---

# 2. Quick Review vs WCET Audit

## Quick Review

Use for ordinary PRs and patches.

Goal:

```text
Find concrete regressions that obviously hurt RT predictability.
```

Typical findings:

```text
HashMap added to scheduler fast path
Vec push added to packet receive path
unwrap introduced in interrupt handler
logging added while holding scheduler lock
loop changed from fixed bound to drain-until-empty
async task now processes unbounded work per poll
WCET contract no longer matches implementation
```

## WCET Audit

Use when the user asks for timing-bound reasoning or hard real-time readiness.

Goal:

```text
Construct an explicit boundedness argument for each RT-critical path.
```

Typical output includes:

```text
bound table
allocation audit
panic audit
loop audit
data structure audit
lock/wait analysis
Drop analysis
async poll analysis
hardware assumptions
residual risks
```

Do not run a deep audit by default for every small patch. It is expensive and can distract from actionable review.

---

# 3. How to Read a Diff

When reviewing a diff, first locate path changes.

Search mentally or mechanically for:

```text
ISR entry points
scheduler functions
ready queue functions
driver Rx/Tx functions
DMA ring handling
control loop steps
Future::poll implementations
allocator functions
lock implementations
critical sections
interrupt enable/disable code
```

Then look for new or changed operations:

```text
new collection type
new loop
new allocation
new lock
new await
new logging
new formatting
new Drop type
new callback or trait object
new panic-capable operation
```

A small-looking abstraction can hide a large timing change. Inspect helper functions called from RT paths.

---

# 4. Review Comment Style

Prefer review comments that are specific and fix-oriented.

Weak comment:

```text
This may be slow.
```

Better comment:

```text
This adds `HashMap::insert` to the scheduler tick path. That makes WCET harder to bound because hash/probing/resize behavior is input- and capacity-dependent. Can this be replaced with a fixed-capacity indexed table keyed by `TaskId`, or moved to setup time?
```

Weak comment:

```text
Avoid unwrap.
```

Better comment:

```text
`unwrap()` is now reachable from the interrupt handler. A malformed descriptor can panic the RT path. Please return `Err(RtError::InvalidDescriptor)` or drop the packet through a bounded error path.
```

Weak comment:

```text
This loop is unbounded.
```

Better comment:

```text
This loop drains the whole queue in one `poll()`. If producers outpace the consumer, one poll can process an arbitrary number of items. Please cap it with `MAX_ITEMS_PER_POLL` and reschedule remaining work.
```

---

# 5. Severity Guidance

## Critical

Use when the patch adds a direct deadline-risk operation to an RT-critical path.

Examples:

```text
blocking lock in ISR
heap allocation in scheduler tick
panic path in control loop
unbounded loop in packet fast path
await while holding scheduler lock
unbounded CAS loop in deadline path
```

## High

Use when boundedness becomes hard to explain.

Examples:

```text
HashMap added to RT lookup
String key comparison added to BTreeMap in RT path
large collection Drop may occur in RT scope
BTreeMap insert/remove added without allocation bound
unknown callback called from RT path
```

## Medium

Use when evidence is missing or contracts are stale.

Examples:

```text
WCET contract not updated
MAX bound not documented
queue-full behavior unclear
no measurement for changed fast path
```

## Low

Use for maintainability issues that may lead to future RT mistakes.

Examples:

```text
RT and non-RT helpers mixed in one module
function name hides allocation
missing comment on why a loop is bounded
```

---

# 6. WCET Audit Table Template

Use this table for deep audits:

```text
RT path | Operation | Bound | Evidence | Residual risk
--------|-----------|-------|----------|---------------
scheduler tick | choose_next | scans <= MAX_READY | for loop over fixed array | cache interference not measured
packet Rx | descriptor scan | <= RX_BUDGET descriptors | bounded budget constant | DMA contention not measured
async worker | poll batch | <= MAX_ITEMS_PER_POLL | explicit for loop | executor latency not audited
```

The table should distinguish:

```text
static bound:
  known from code structure or type-level capacity

documented bound:
  claimed by constant/config and validated by caller

measured bound:
  observed under benchmark, not a proof

unknown:
  cannot currently be bounded
```

Do not confuse measured worst observed latency with proven WCET.

---

# 7. Allocation Audit

Look for allocation directly and indirectly.

Direct allocation indicators:

```rust
Vec::new()
Vec::with_capacity(...)
Box::new(...)
String::new()
String::from(...)
Arc::new(...)
Rc::new(...)
HashMap::new()
BTreeMap insertion into an empty/growing map
```

Indirect allocation indicators:

```rust
to_string()
to_vec()
format!()
collect::<Vec<_>>()
clone() on owned heap-backed types
serde serialization into String/Vec
logging/tracing with formatting
```

Review questions:

```text
Is this allocation reachable from an RT-critical path?
Can it be moved to setup/init?
Can the buffer be preallocated?
What happens on allocation failure?
Does allocation take a global lock?
Can deallocation occur later through Drop in the RT path?
```

Preferred fixes:

```text
fixed-capacity queue
heapless collection
preallocated slab
caller-provided buffer
bounded ring buffer
setup-time allocation + runtime reuse
```

---

# 8. Panic Audit

Look for obvious and hidden panic sources.

Common sources:

```rust
unwrap()
expect()
panic!()
assert!()
unreachable!()
todo!()
unimplemented!()
arr[i]
slice[a..b]
Vec::remove(i)
Vec::insert(i, x)
```

Review questions:

```text
Can malformed input reach this path?
Can hardware/device state make this invalid?
Can a full queue or missing task trigger this?
Is the caller invariant local and obvious?
Should this return Result instead?
```

Suggested fixes:

```rust
let Some(entry) = table.get(idx) else {
    return Err(RtError::InvalidIndex);
};
```

```rust
let Some(next) = now.checked_add(delta) else {
    return Err(RtError::TimeOverflow);
};
```

A release profile with `panic = "abort"` simplifies failure behavior but does not make a panic acceptable in normal RT operation.

---

# 9. Loop Audit

Every RT-critical loop needs a bound.

Good patterns:

```rust
for i in 0..MAX_TASKS {
    // fixed bound
}
```

```rust
for _ in 0..MAX_ITEMS_PER_POLL {
    let Some(item) = queue.pop() else { break };
    process_one(item);
}
```

Suspicious patterns:

```rust
while let Some(item) = queue.pop() {
    process(item);
}
```

```rust
loop {
    if try_step() {
        break;
    }
}
```

```rust
items.iter().flat_map(...).collect::<Vec<_>>()
```

Review questions:

```text
What is the maximum iteration count?
Is it a constant, type capacity, or runtime config?
Who validates the runtime config?
Can producers keep the loop alive indefinitely?
Does each iteration call bounded code?
```

If the loop is bounded by a queue capacity, the capacity itself must be fixed or validated.

---

# 10. Data Structure Audit

## Fixed Arrays and Indexed Tables

Best for RT when IDs are dense or can be assigned.

Review positively when code uses:

```text
TaskId -> array index
JobId -> slab index
CpuId -> fixed CPU table
Priority -> bitmap/bucket index
```

Check invalid index handling.

## Bitmaps and Priority Buckets

Good for ready sets and priority queues when priority range is bounded.

Review questions:

```text
How many words are scanned?
Is priority range fixed?
Is tie-breaking deterministic?
```

## Vec

`Vec` is acceptable only when capacity and mutation behavior are controlled.

Review questions:

```text
Is capacity fixed before RT phase?
Can push reallocate?
Can insert/remove shift many elements?
Can drop deallocate in RT path?
```

## BTreeMap

Often more predictable than `HashMap`, but not automatically safe.

Review questions:

```text
Is map length bounded?
Are keys fixed-width integers?
Is the RT path lookup-only?
Can insert/remove allocate/deallocate or split/merge nodes?
Is range iteration bounded?
```

Good keys:

```rust
TaskId(u32)
JobId(u32)
Deadline(u64)
Priority(u8)
CpuId(u16)
```

Risky keys:

```rust
String
Vec<u8>
PathBuf
large structs
```

Remember:

```text
BTreeMap cost = O(log n * key_compare_cost)
```

## HashMap

Usually avoid in RT-critical paths.

Review concerns:

```text
expected-case rather than clean worst-case behavior
hash cost depends on key
collision/probing behavior depends on input
resize/rehash can be expensive
iteration may depend on capacity
randomized seed may change behavior between runs
```

Accept in non-RT paths such as config, metrics, debug, startup, and control plane.

---

# 11. Locking Audit

Rust synchronization primitives are not automatically real-time safe.

Review questions:

```text
Can this lock block?
Can a lower-priority task hold it while a higher-priority task waits?
Is priority inheritance or priority ceiling available?
Can interrupt context take this lock?
Is lock ordering fixed?
Does the guarded section allocate, log, format, or await?
What is the maximum hold time?
What is the maximum wait time?
```

Bad pattern:

```rust
let guard = lock.lock().unwrap();
log::info!("state = {:?}", *guard);
some_async_call().await;
drop(guard);
```

Better pattern:

```text
copy minimal state under short lock
release lock
perform non-RT work outside lock
```

For atomics, audit retry loops.

Bad:

```rust
loop {
    if atomic.compare_exchange(old, new, SeqCst, SeqCst).is_ok() {
        break;
    }
}
```

Better:

```rust
for _ in 0..MAX_RETRIES {
    if atomic.compare_exchange(old, new, SeqCst, SeqCst).is_ok() {
        return Ok(());
    }
}
Err(RtError::Contention)
```

A lock-free algorithm can still be WCET-hostile if retries are unbounded.

---

# 12. Async Audit

Async code must be reviewed at the `poll()` level.

Questions:

```text
How much work can one poll perform?
Can one wake cause unbounded processing?
Can producers create a wake storm?
Does poll allocate?
Does poll block?
Does poll hold locks?
Are locks held across await?
What happens on cancellation?
Does Drop run heavy cleanup?
What does the executor guarantee?
```

Bad:

```rust
async fn worker() {
    loop {
        while let Some(item) = queue.pop() {
            process(item);
        }
        event.await;
    }
}
```

Better:

```rust
async fn worker() {
    loop {
        for _ in 0..MAX_ITEMS_PER_POLL {
            let Some(item) = queue.pop() else { break };
            process_one(item);
        }
        yield_now().await;
    }
}
```

Note that `yield_now()` is only useful if the executor respects it in a bounded and predictable way.

---

# 13. Drop Audit

Rust destructors can hide work.

Audit types that leave scope in RT paths:

```text
Vec
String
Box
Arc
BTreeMap
HashMap
custom guard types
buffers containing elements with Drop
```

Review questions:

```text
Does Drop traverse elements?
Does Drop deallocate?
Does Drop take a lock?
Does Drop restore interrupts?
Does Drop wake tasks?
Can final Arc drop free a large object?
Is cleanup better deferred to non-RT code?
```

A common fix is to avoid ownership transfer into RT path or use fixed-capacity buffers with explicit bounded cleanup.

---

# 14. Logging and Tracing Audit

Logging is often unacceptable in RT-critical paths because it may format, allocate, lock, or perform I/O.

Flag:

```rust
println!()
eprintln!()
format!()
log::info!()
tracing::debug!()
```

Possible RT-friendly alternative:

```rust
#[derive(Clone, Copy)]
pub enum RtEvent {
    DeadlineMiss { task: TaskId, at: Time },
    QueueFull { queue: QueueId },
    InterruptDelay { irq: IrqId, cycles: u64 },
}
```

Push compact events into a bounded ring buffer. Decode and format outside the RT path.

---

# 15. Unsafe Code Audit

Unsafe code should document memory-safety and timing invariants.

Good comment:

```rust
// SAFETY:
// - idx was checked against MAX_TASKS above.
// - table has exactly MAX_TASKS entries.
// - Access is O(1), allocation-free, panic-free, and cannot block.
let task = unsafe { table.get_unchecked(idx) };
```

Review questions:

```text
Is the safety invariant local and obvious?
Is the timing invariant documented?
Is unsafe hiding a panic or bound check without proving the bound?
Can this interact with aliasing, atomics, DMA, or interrupts?
```

Unsafe is not bad by itself, but it must not hide unbounded behavior.

---

# 16. WCET Contract Audit

A good WCET contract mentions:

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

Example:

```rust
/// WCET contract:
/// - Scans at most MAX_READY entries, where MAX_READY <= 64.
/// - No heap allocation.
/// - No blocking or await.
/// - No panic for validated task IDs.
/// - Only fixed-width integer comparisons.
/// - Does not call user-provided code.
pub fn choose_next<const MAX_READY: usize>(...) -> Option<JobId> {
    // ...
}
```

Findings to report:

```text
missing contract for new RT-critical function
contract says no allocation, but Vec push was added
contract says scans MAX_READY, but function now drains queue
contract omits lock wait or callback behavior
```

---

# 17. Build and Binary Inspection

When possible, recommend or run checks such as:

```bash
cargo clippy --release --all-targets -- -D warnings
cargo tree
cargo bloat --release
nm target/release/<binary> | grep -E "alloc|dealloc|panic|fmt"
objdump -d target/release/<binary> > disasm.txt
```

For RT-critical crates, useful lints include:

```rust
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

Suspicious symbols:

```text
__rust_alloc
__rust_dealloc
core::panicking
alloc::fmt
std::
HashMap-related symbols
format machinery
```

These are not always bugs. They indicate code paths that need investigation.

---

# 18. Measurement and Validation Audit

For serious timing claims, request measurements beyond average latency.

Useful measurements:

```text
worst observed latency
p99 / p99.9 / p99.99 / p99.999
cold-cache behavior
warm-cache behavior
queue-full behavior
lock-contention behavior
interrupt-storm behavior
DMA contention
multi-core memory contention
```

Remember:

```text
function WCET
+ scheduler latency
+ interrupt latency
+ blocking time
+ cache/memory interference
+ device latency
= task response time
```

A benchmark does not prove WCET, but it can reveal regressions and missing assumptions.

---

# 19. Hardware and Platform Assumptions

Timing claims depend on platform assumptions.

Ask whether the system controls:

```text
DVFS / turbo boost
SMT
CPU isolation
IRQ affinity
cache sharing
DMA interference
NUMA placement
page faults
preemption settings
interrupt masking duration
```

If these are unknown, report them as residual risks rather than blocking every patch.

---

# 20. Example Quick Review Output

```text
Summary:
- The patch improves scheduler structure, but introduces one RT-critical boundedness regression.

Findings:
- [High] scheduler.rs::tick: `HashMap::insert` is now called from the scheduler tick path. This makes WCET difficult to bound due to hash/probing/resize behavior. Prefer a fixed indexed table keyed by `TaskId`, or move map updates to setup/deferred work.
- [Medium] ready_queue.rs::choose_next: WCET contract still says `MAX_READY` scan, but the implementation now drains `pending`. Please update the contract or cap the drain with a fixed budget.

Missing evidence:
- No bound is documented for `pending` length.

Verdict:
- Needs changes before merging into RT path.
```

---

# 21. Example WCET Audit Output

```text
Summary:
- The main scheduler selection path is bounded by MAX_READY.
- Packet Rx path has a fixed RX_BUDGET.
- The async telemetry worker is not yet bounded per poll.

Boundedness table:

RT path | Operation | Bound | Evidence | Residual risk
scheduler tick | choose_next | <= MAX_READY entries | fixed array scan | cache interference not measured
packet Rx | descriptor processing | <= RX_BUDGET descriptors | explicit for loop | DMA contention not measured
telemetry worker | poll | unknown | drains queue until empty | may starve executor

Findings:
- [Critical] telemetry_worker::poll drains the queue without a per-poll budget. Add MAX_EVENTS_PER_POLL and reschedule remaining work.
- [Medium] Drop cost for `TelemetryBatch` is not documented; it owns a Vec and may deallocate in RT-adjacent context.

Residual risks:
- Hardware timing under interrupt storm was not measured.
- Executor scheduling latency was not audited.
```

---

# 22. When Not to Over-Review

Do not block a patch merely because non-RT code uses convenient abstractions.

Usually acceptable outside RT paths:

```text
HashMap for config
String for CLI or debug output
Vec during initialization
serde during startup
logging in test code
panic in tests
std::sync::Mutex in non-RT control plane
```

The important question is whether the code is reachable from RT-critical execution or can interfere with it.

---

# 23. Final Reviewer Mindset

A real-time reviewer should be able to say:

```text
This operation is bounded because...
This operation is risky because...
This risk is outside the RT path because...
This claim still needs measurement because...
```

Avoid overclaiming. Prefer honest residual-risk notes.

The goal is not to make every Rust program look embedded.

The goal is to prevent RT-critical Rust from accidentally becoming unbounded Rust.

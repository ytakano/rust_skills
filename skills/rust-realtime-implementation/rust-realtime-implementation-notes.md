# Rust Real-Time Implementation Notes

Supplement for `rust-realtime-implementation/SKILL.md`.

This file preserves details intentionally removed from the compressed `SKILL.md`.

---

# 1. Why This Skill Exists

Rust is useful for real-time systems because it helps prevent memory unsafety and data races.

However, Rust does not automatically provide WCET guarantees.

The following can still be unbounded or hard to predict:

```text
heap allocation
hash table collision behavior
resize/rehash
lock wait time
priority inversion
Drop/destructor work
cache misses
DMA interference
interrupt latency
async poll duration
panic/unwind behavior
```

Therefore, real-time Rust code should be designed around bounded operations, not merely safe operations.

---

# 2. RT-Critical vs Non-RT Boundaries

A common mistake is applying RT restrictions everywhere.

Instead, isolate RT-critical code.

Good structure:

```text
rt-core/
  no_std
  fixed-capacity structures
  no allocation in runtime path
  no panic paths
  no logging/formatting

control-plane/
  std allowed
  allocation allowed
  HashMap allowed
  config parsing allowed
  debug/metrics allowed
```

This makes strict lints practical.

---

# 3. WCET Contract Examples

Good contract:

```rust
/// WCET contract:
/// - O(MAX_TASKS), MAX_TASKS <= 64.
/// - No heap allocation.
/// - No blocking.
/// - No panic if task IDs were validated by caller.
/// - Does not call user-provided code.
/// - Does not log or format.
/// - Only compares fixed-width integer deadlines.
pub fn select_earliest_deadline<const MAX_TASKS: usize>(
    tasks: &[Task; MAX_TASKS],
) -> Option<TaskId> {
    // ...
}
```

Weak contract:

```rust
/// Fast scheduler selection.
```

Better to be boring and precise than clever and vague.

---

# 4. Allocation Details

Even if an allocator is theoretically O(1), check:

```text
Does it take a lock?
Can it be called from interrupt context?
Can it fail?
Can failure panic?
Can deallocation happen implicitly through Drop?
Can fragmentation affect behavior?
Does it disable interrupts?
Does it interact with global allocator state?
```

If using a real-time allocator such as TLSF, slab, or fixed block pool, still document which code path may call it.

Recommended split:

```text
Initialization:
  create queues
  allocate buffers
  build maps
  parse config

Runtime:
  reuse buffers
  return Result on full queues
  never grow collections
```

---

# 5. Panic Details

Panic sources are not limited to `panic!`.

These may panic:

```rust
arr[i]
slice[a..b]
unwrap()
expect()
assert!()
unreachable!()
todo!()
unimplemented!()
Vec::remove(i)
Vec::insert(i, x)
Option::unwrap()
Result::unwrap()
```

Prefer checked APIs:

```rust
arr.get(i)
arr.get_mut(i)
checked_add
checked_sub
checked_mul
Result
Option
```

Use `panic = "abort"` to simplify failure behavior, but still remove normal-operation panic paths.

---

# 6. Collection Details

## Fixed Array

Best when maximum size is small and known.

```rust
struct TaskTable<const N: usize> {
    entries: [Option<Task>; N],
}
```

Good for:

```text
task table
CPU table
driver rings
small ready sets
fixed resource pools
```

## Bitmap / Bitset

Good for readiness, CPU masks, priority buckets, and free lists.

```text
O(1) or O(number_of_words)
very predictable
compact
cache-friendly
```

## Ring Buffer

Good for producer/consumer handoff.

Prefer fixed-capacity SPSC or bounded MPSC.

Failure should return `Full`, not allocate or panic.

## Sorted Fixed Array

Often excellent for small `N`.

For `N <= 32` or `N <= 64`, a linear scan may be more predictable than a tree or heap.

## BinaryHeap

Usable if capacity is fixed and no reallocation occurs.

Check whether update/removal operations require extra work.

## BTreeMap

More predictable than `HashMap`, but not free.

Check:

```text
maximum length
key comparison cost
whether insert/remove can allocate/deallocate
whether node split/merge can occur
whether only lookup occurs in RT path
```

Good:

```rust
BTreeMap<Deadline, JobId>
BTreeMap<TaskId, TaskState>
```

Risky:

```rust
BTreeMap<String, Task>
BTreeMap<Vec<u8>, Entry>
BTreeMap<PathBuf, Config>
```

Because actual cost is:

```text
O(log n * key_compare_cost)
```

## HashMap

Avoid in RT-critical paths.

Problems:

```text
expected-case behavior, not clean WCET behavior
hash cost depends on key
collision/probing behavior depends on input
resize/rehash can be expensive
iteration may depend on capacity
randomized seeding can change behavior between runs
```

Use in non-RT code for config, debug, metrics, caches, and control plane.

---

# 7. Locking Details

Do not assume Rust `Mutex` is real-time safe.

Potential problems:

```text
unbounded wait
priority inversion
OS scheduler interaction
blocking in interrupt context
poisoning/panic behavior
unknown fairness
```

In RT-critical paths, prefer:

```text
per-CPU data
single-writer ownership
short critical sections
bounded queues
priority ceiling
priority inheritance
bounded lock-free algorithms
```

For atomics, avoid unbounded CAS retry loops.

Bad:

```rust
loop {
    if atomic.compare_exchange(...).is_ok() {
        break;
    }
}
```

Better:

```rust
for _ in 0..MAX_RETRIES {
    if atomic.compare_exchange(...).is_ok() {
        return Ok(());
    }
}
Err(RtError::Contention)
```

---

# 8. Async Rust Details

Async is not automatically non-blocking in the WCET sense.

A future’s `poll()` can do arbitrary work.

For each RT-critical future, check:

```text
maximum work per poll
allocation inside poll
locks held during poll
locks held across await
Drop/cancellation behavior
executor scheduling latency
wake storm behavior
```

Bad:

```rust
async fn worker() {
    loop {
        while let Some(x) = queue.pop() {
            process(x);
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
            let Some(x) = queue.pop() else { break };
            process_one(x);
        }
        yield_now().await;
    }
}
```

The executor must also be reviewed. A bounded future on an unbounded executor is not enough.

---

# 9. Drop Details

`Drop` can hide expensive work.

Examples:

```text
Vec drop:
  drops all elements and deallocates

String drop:
  deallocates

Arc drop:
  atomic decrement; final drop may free object

Collection drop:
  may traverse many elements

Guard drop:
  may unlock, restore interrupts, or trigger side effects
```

RT-critical code should avoid creating owned values whose destructor cost is not bounded.

If necessary, move ownership transfer and cleanup to non-RT code.

---

# 10. Logging and Tracing Details

Formatting is often expensive and may allocate or lock.

Avoid in RT paths:

```rust
println!()
eprintln!()
format!()
log::info!()
tracing::debug!()
```

Prefer compact fixed-size event records:

```rust
#[derive(Clone, Copy)]
pub enum RtEvent {
    DeadlineMiss { task: TaskId, at: Time },
    QueueFull { queue: QueueId },
    InterruptDelay { irq: IrqId, cycles: u64 },
}
```

Push events to a bounded ring buffer.

Decode and format later in non-RT code.

---

# 11. Unsafe Code Details

Unsafe code in RT paths should document timing invariants as well as memory-safety invariants.

Example:

```rust
// SAFETY:
// - idx was checked against MAX_TASKS above.
// - table has exactly MAX_TASKS entries.
// - This access is O(1), allocation-free, panic-free, and cannot block.
let task = unsafe { table.get_unchecked(idx) };
```

Do not use unsafe only to silence bounds checks unless the bound is obvious and local.

---

# 12. Binary Inspection

Useful commands:

```bash
cargo clippy --release --all-targets -- -D warnings
cargo tree
cargo bloat --release
nm target/release/<binary> | grep -E "alloc|dealloc|panic|fmt"
objdump -d target/release/<binary> > disasm.txt
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

# 13. Measurement Details

Average latency is not enough.

Measure:

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

Hardware validation is required for serious real-time claims.

---

# 14. Hardware and Platform Notes

Modern CPUs can make WCET difficult because of:

```text
out-of-order execution
branch prediction
cache hierarchy
shared LLC
SMT
DVFS
turbo boost
interrupt routing
DMA contention
NUMA effects
```

For stricter real-time behavior, consider:

```text
disable or control DVFS/turbo
disable SMT if needed
pin RT tasks to isolated CPUs
control IRQ affinity
avoid shared memory contention
pre-fault/pre-touch memory
avoid page faults in RT paths
measure under interference
```

---

# 15. Review Questions

When reviewing a patch, ask:

```text
Did this add allocation to an RT path?
Did this add HashMap or String to an RT path?
Did this add an unbounded loop?
Did this add a panic path?
Did this add blocking or lock contention?
Did this add logging or formatting?
Did this hide work in Drop?
Did this use a variable-length key comparison?
Did this introduce an unbounded callback or trait object call?
Did this hold a lock across await?
Does the WCET contract still match the code?
```

---

# 16. Common Good Patterns

```text
TaskId/JobId indexed arrays
fixed-capacity queues
ring buffers
bitmap readiness sets
priority buckets
preallocated slabs
bounded batch processing
Result-based full/overflow handling
integer keys
setup-time allocation
runtime allocation-free operation
read-only maps in RT paths
per-CPU state
```

---

# 17. Common Anti-Patterns

```text
HashMap in scheduler fast path
Vec push in packet receive path
String formatting in ISR
logging while holding a lock
await while holding a lock
unbounded CAS retry loop
large collection dropped at scope exit
dynamic dispatch to unknown user code
panic-based error handling
allocation on deadline path
global lock around scheduler state
```

---

# 18. Short Rule of Thumb

If an operation appears in an RT-critical path, the agent should be able to answer:

```text
What is the maximum number of steps?
What is the maximum number of elements touched?
Can it allocate?
Can it block?
Can it panic?
Can it call unknown code?
Can Drop hide work?
What happens when the structure is full?
```

If these cannot be answered, the implementation is not ready for RT-critical use.

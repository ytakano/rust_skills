# Trace contract

The abstract trace is the shared language both the C++ original and the Rust port speak.
Both implementations must emit the **same event names and parameter shapes** so their
behavior can be compared.

## Abstract trace

An abstract trace is a sequence of **specification-level** events. It describes what the
program *means*, not how it happens internally. Because the Rust port often has a different
internal structure, only trace low-level implementation events when they are directly
relevant to the specification. Prefer stable, semantic events.

Good events:

```text
SessionStarted(session_id)
HeaderParsed(session_id, kind)
BodyAccepted(session_id, bytes)
TransactionCommitted(tx_id)
ResourceClosed(resource_id)
ErrorRaised(code)
```

Bad events (implementation noise, not specification):

```text
malloc(0x7ff...)
std::vector::push_back
Box::new
line 123 reached
raw pointer = 0xabc...
current timestamp = 2026-06-18T12:34:56
```

## Event format: JSON Lines

Use JSON Lines (one event per line) as the default trace format.

```jsonl
{"version":1,"run_id":"r1","seq":1,"impl":"cpp","component":"parser","event":"Start","session":"s1","params":{}}
{"version":1,"run_id":"r1","seq":2,"impl":"cpp","component":"parser","event":"HeaderParsed","session":"s1","params":{"kind":"v2"}}
{"version":1,"run_id":"r1","seq":3,"impl":"cpp","component":"parser","event":"BodyAccepted","session":"s1","params":{"bytes":128}}
{"version":1,"run_id":"r1","seq":4,"impl":"cpp","component":"parser","event":"Finish","session":"s1","params":{}}
```

Required fields:

```text
version     Trace format version
run_id      ID of this execution
seq         Monotonically increasing sequence number within the run
impl        "cpp" or "rust"
component   Component being traced
event       Abstract event name
params      Event parameters (object)
```

Conditional fields (add only when the validation needs them):

```text
session     Validation is session-scoped
resource    Validation is resource-scoped
thread      Validating threaded behavior
task        Validating async behavior
cause       Causal relationships must be represented
```

## Trace output mechanism

Define the emission mechanism once so both implementations behave identically and runs are
reproducible:

- **Sink**: each implementation writes JSON Lines to the path in the `TRACE_OUT` environment
  variable. If `TRACE_OUT` is unset, tracing is disabled (zero behavioral impact).
- **Truncate, don't append**: open `TRACE_OUT` with truncation at process start so each run
  produces a clean file. Never append across runs.
- **Flush**: flush after every event (or flush on exit and on every error path) so traces
  survive crashes and non-zero exits. Missing trailing events hide exactly the bugs this
  skill targets.
- **`run_id`**: a per-process id. Pass it in via an env var (e.g. `RUN_ID`) or derive it
  deterministically from the input — never from wall-clock time or randomness, or repeated
  runs will not be comparable.
- **`seq`**: a single monotonically increasing counter owned by the trace module. In
  concurrent code the counter must be atomic; emission must be thread-safe (one lock around
  format+write, or a per-thread buffer merged by `seq`).

## Do not use as equivalence criteria

Never compare these raw — normalize first (see [normalization.md](./normalization.md)):

- Raw pointer addresses
- Wall-clock timestamps
- Random IDs before normalization
- C++-specific or Rust-specific internal function names
- Debug log strings treated as specification traces
- Hash-map iteration order unless explicitly canonicalized

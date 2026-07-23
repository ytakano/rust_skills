# Trace contract

The abstract trace is the shared language both the C++ original and the Rust port speak.
Both implementations must emit the **same event names and parameter shapes** so their
behavior can be compared. The authoritative shapes and comparison policies live in
`conformance/equivalence_contract.json`; validate both traces against it before comparison.

## Complete observable inventory first

“Complete” means every **external or semantically observable value selected as in-scope by
the port-equivalence contract**, not every local variable. Determine the scope from the intended
specification, public interfaces, existing tests, and behavior on which real users depend; do
not assume that an undocumented behavior is automatically out of scope. Before instrumentation,
fill in `trace_schema.md` with:

- every public return value and error kind;
- every specification state and state-changing value;
- every early-return, exception, cleanup, and resource-lifecycle outcome;
- stdout, stderr, and exit code;
- files, database changes, network requests, and other persistent/external side effects;
- the C++ and Rust observation point, contract path, comparator, and exercising tests.

If a value has no contract path, it is not being compared. If a contract path has no
observation point or test, it is not checked. Do not declare the port complete with a blank
matrix cell. Record explicit exclusions and their reasons; absence from the matrix is not an
exclusion policy.

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

When adding a conditional field, add it to `equivalence_contract.json` at the same time.
Unknown fields are rejected; this prevents a newly emitted semantic value from being silently
ignored by an older comparator.

Standard JSON has no portable NaN or infinity literals. Encode non-finite floats as `"nan"`,
`"+inf"`, and `"-inf"` and give each float field an explicit `abs_rel`, `ulp`, or `bit_exact`
policy. See [equivalence-contract.md](./equivalence-contract.md).

## Trace output mechanism

Define the emission mechanism once so both implementations behave identically and runs are
reproducible:

- **Trace sink**: each implementation writes JSON Lines to the path in the `TRACE_OUT`
  environment variable. If `TRACE_OUT` is unset, tracing is disabled (zero behavioral impact).
- **Side-effect sink**: when the contract uses manifest mode, an independent observer writes
  canonical JSON to `SIDE_EFFECTS_OUT`. Prefer filesystem snapshots, database queries, and
  captured fake-service requests over self-reporting from the application.
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

Do not treat floating-point rounding as normalization. Preserve the value and apply the
field-specific numeric policy in the equivalence checker. Rounding creates discontinuities and
can hide specification-relevant differences.

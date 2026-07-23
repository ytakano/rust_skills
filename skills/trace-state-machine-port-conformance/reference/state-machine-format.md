# State machine specification

The state machine `M` is a **specification monitor**: it checks whether an abstract trace
follows the allowed order, guards, and lifecycle rules. It is not, by itself, a proof of
behavioral equivalence — see [differential-checks.md](./differential-checks.md).

A state machine that accepts almost everything provides little conformance evidence. Make invalid
behavior explicit.

## What the state machine must express

- Initial state
- Accepting states and terminal conditions (see the note below — they are not the same)
- Allowed transitions
- Forbidden transitions
- Guard conditions over event parameters
- Relationships between sessions, resources, transactions, or handles
- Valid behavior after errors
- Required cleanup or completion behavior

## Designing M (not copying C++)

Use more than the C++ logs. Consult specifications, existing tests, READMEs, comments,
historical bug fixes, domain knowledge, and expected user-visible behavior.

- Do **not** blindly copy current C++ behavior into the state machine — current behavior is
  not automatically the specification.
- Do **not** loosen the state machine to make an incorrect Rust trace pass.
- Always test both accepted and rejected traces.
- Guards over floating-point values need a specification-derived boundary policy. A tolerance
  may compare a numeric parameter, but it must not make different transitions or terminal
  outcomes equivalent. If a boundary band is legitimately nondeterministic, encode the allowed
  transitions explicitly and test both sides of the band.

## Format (YAML by default)

```yaml
name: parser_lifecycle
version: 1
initial: Idle

# Terminal states: no further semantic events are allowed after these.
terminal:
  - Finished
  - Failed

# Accepting states: terminal states that are a LEGITIMATE end of the run.
# A clean error path is a valid trace, so BOTH Finished and Failed are accepting.
# Membership here means "this is a complete, valid trajectory" — not "the run
# succeeded". List a terminal state here only if reaching it is legitimate; leave
# out illegitimate dead-ends (a "stuck"/aborted state) so the monitor rejects them.
accepting:
  - Finished
  - Failed

states:
  Idle: {}
  Started: {}
  HeaderReady: {}
  BodyReady: {}
  Finished: {}
  Failed: {}

transitions:
  - from: Idle
    event: Start
    to: Started

  - from: Started
    event: HeaderParsed
    to: HeaderReady
    guard: "params.kind in ['v1', 'v2']"

  - from: HeaderReady
    event: BodyAccepted
    to: BodyReady
    guard: "params.bytes >= 0"

  - from: BodyReady
    event: Finish
    to: Finished

  - from: [Idle, Started, HeaderReady, BodyReady]
    event: ErrorRaised
    to: Failed
    guard: "params.code != ''"

forbidden:
  - state: Idle
    event: Finish
    reason: "cannot finish before start"

  - state: Finished
    event: BodyAccepted
    reason: "cannot accept body after finish"

invariants:
  - name: no_event_after_terminal
    applies_to: [Finished, Failed]
    rule: "no further semantic events except TraceEnd"
```

## accepting vs terminal

- **terminal**: the run has ended; no further semantic events are valid.
- **accepting**: a *legitimate, complete* end state — the trace is a valid trajectory.

These are different axes, easy to conflate. `accepting` is **not** the same as "the run
succeeded". A clean error path (`... → ErrorRaised → Failed`) is a perfectly valid trace, so
`Failed` **is** accepting. If you excluded error states from `accepting`, the monitor would
reject every legitimate-error input — and the differential workflow requires *both* the C++
and Rust traces to be accepted, so error-path inputs would be impossible to assess.

What enforces "this input should have failed, not succeeded" is **not** the state machine —
it is the differential checks: both implementations must reach the *same* terminal state
(terminal-state equivalence) and produce equivalent outputs/errors. See
[differential-checks.md](./differential-checks.md).

Use non-accepting terminal states only for *illegitimate* dead-ends (e.g. a "stuck" or
aborted state that should never be a valid end) — the monitor will then reject any trace that
ends there.

## Examples are part of the spec

Keep positive (accepted) and negative (rejected) trace examples alongside the machine — in
`trace_schema.md` or a dedicated fixtures directory in the target repo. They double as the
monitor's own tests.

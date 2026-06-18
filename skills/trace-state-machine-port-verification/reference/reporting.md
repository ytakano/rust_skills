# Acceptance criteria and reporting

## Acceptance criteria

Do not consider the port complete until the following are true, or explicitly documented as
out of scope:

```text
[ ] Existing C++ tests pass.
[ ] Corresponding Rust tests pass.
[ ] trace_schema.md exists and defines the main events.
[ ] state_machine.yaml exists and includes normal paths, error paths, and forbidden transitions.
[ ] C++ traces are accepted by the state machine on representative inputs.
[ ] Rust traces are accepted by the state machine on representative inputs.
[ ] Normalized C++ and Rust traces are equivalent for identical inputs.
[ ] Outputs, errors, and exit codes are equivalent.
[ ] Important side effects are equivalent.
[ ] Boundary cases are included.
[ ] Error cases are included.
[ ] Discovered failures are saved under verification/repro/.
[ ] Repro cases are turned into regression tests.
[ ] Nondeterminism is fixed, isolated, or documented.
[ ] Suspected C++ undefined behavior is investigated or documented.
```

## Reporting format

When reporting completed work, use this structure:

```text
Summary
- Target component:
- Verification files added or updated:
- Trace events added:
- Main state-machine states:
- Number of test cases run:
- C++ trace accepted:
- Rust trace accepted:
- Trace equivalence:
- Output equivalence:
- Side-effect equivalence:

Findings
- Existing C++ issues found:
- Rust port issues found:
- State-machine or specification changes:
- Nondeterminism handling:

Regression
- Repro cases saved:
- Regression tests added:
- Re-run command:

Remaining Risks
- Untested input areas:
- Untested side effects:
- Suspected C++ undefined behavior:
- Remaining concurrency risks:
```

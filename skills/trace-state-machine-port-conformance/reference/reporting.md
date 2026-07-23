# Acceptance criteria and reporting

## Acceptance criteria

Do not consider the port complete until every item is true or is a narrow, reasoned, reported
waiver:

```text
[ ] Existing C++ tests pass.
[ ] Corresponding Rust tests pass.
[ ] The observability matrix accounts for every in-scope result, error, state, and side effect.
[ ] equivalence_contract.json validates and contains no implicit comparison/ignore policy.
[ ] C++ and Rust traces both validate against the contract.
[ ] state_machine.yaml includes normal paths, error paths, and forbidden transitions.
[ ] C++ and Rust traces are accepted by the state machine.
[ ] Normalized traces are equivalent under the contract for identical inputs.
[ ] stdout, stderr, exit code, and public return/error results are equivalent.
[ ] Side-effect manifests are equivalent, or no side effects is justified as out of scope.
[ ] Contract coverage has zero missing semantic events/fields.
[ ] Unknown events/fields and missing required fields are zero.
[ ] Comparator mutation audit passes for every observed semantic path.
[ ] States, transitions, guard outcomes, boundaries, and declared errors are exercised.
[ ] Floating policies are specification/error-analysis derived; normalization does not round them.
[ ] Failures are saved under conformance/repro/ and become regression tests.
[ ] Nondeterminism is fixed, isolated, or explicitly modeled.
[ ] Suspected C++ undefined/implementation-defined behavior is investigated or documented.
```

## Reporting format

```text
Summary
- Target component:
- Conformance assets added or updated:
- Corpus cases run / passed:
- C++ state-machine acceptance:
- Rust state-machine acceptance:
- Trace equivalence:
- stdout/stderr/exit equivalence:
- Side-effect equivalence:

Completeness
- Observable inventory rows complete:
- Contract semantic paths required / observed:
- Missing paths:
- Unknown or unconfigured paths:
- Explicitly ignored paths + reasons:
- Coverage waivers + reasons:
- Comparator mutation audit:
- State/transition/guard coverage:

Numeric policy
- Floating fields and policies:
- Specification/error-analysis sources:
- Non-finite and signed-zero policies:
- Arithmetic-environment differences:

Findings
- Existing C++ issues:
- Rust port issues:
- Contract/state-machine/specification changes:
- Nondeterminism handling:

Regression
- Repro cases saved:
- Regression tests added:
- Re-run command:

Remaining risks
- Untested input or behavioral areas:
- Waived observables/side effects:
- Suspected C++ undefined behavior:
- Remaining concurrency/numeric risks:
```

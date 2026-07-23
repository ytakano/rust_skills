# Observability and trace completeness matrix

Copy this file into the target repo's `conformance/` directory and complete it
**before** broad instrumentation. The authoritative machine-readable event
schema and comparison rules live in `equivalence_contract.json`; do not
duplicate them here.

The conformance and equivalence scope is every **external or semantically observable value
selected as in-scope by the port-equivalence contract**, not every
implementation-local variable. Select that scope using the intended
specification, public interfaces, existing tests, and behavior on which real
users depend. Inventory the public results, errors, semantic states, resource
lifecycle, and external side effects. Record every explicit exclusion and its
reason; absence from this matrix is not an exclusion decision.

## Observable inventory

No cell may remain blank when the port is declared complete.

| Observable | Specification meaning | C++ observation point | Rust observation point | Contract path | Comparison | Exercising tests |
|---|---|---|---|---|---|---|
| run started | lifecycle begins | process/API entry | process/API entry | `trace.events.Start` | event presence/order | normal + error cases |
| header kind | accepted protocol version | successful header parse | successful header parse | `trace.events.HeaderParsed.params.kind` | exact | v1, v2, invalid |
| accepted byte count | committed body length | body acceptance boundary | body acceptance boundary | `trace.events.BodyAccepted.params.bytes` | exact | zero, normal, maximum |
| terminal success | legitimate successful completion | success return | `Ok` return | `trace.events.Finish` | exact event/state | success cases |
| terminal error code | shared failure classification | exception/error return | `Err` return | `trace.events.ErrorRaised.params.code` | exact shared code | every declared error |
| stdout | public byte output | process boundary | process boundary | `outcomes.stdout` | contract policy | output cases |
| stderr | public diagnostic/error output | process boundary | process boundary | `outcomes.stderr` | contract policy | success + error |
| exit code | process result | process boundary | process boundary | `outcomes.exit_code` | exact | success + error |
| external effects | files/DB/network/persistent state | independent observer | independent observer | `side_effects` | manifest schema | effect + no-effect |

Add target-specific rows for every public return field, state-changing
parameter, security decision, persistent value, resource open/close, early
return, exception/error kind, and external effect.

## Event and path coverage

Map every state-machine state, transition, and guard outcome to corpus cases.
The contract automatically reports unobserved events and semantic fields, but
this matrix also accounts for behavior paths.

| State/transition/guard | Positive cases | Boundary/error cases | C++ covered | Rust covered |
|---|---|---|---|---|
| `Idle --Start--> Started` | | | [ ] | [ ] |
| `Started --HeaderParsed--> HeaderReady` | | | [ ] | [ ] |
| header-kind guard true/false | | | [ ] | [ ] |
| `HeaderReady --BodyAccepted--> BodyReady` | | | [ ] | [ ] |
| `BodyReady --Finish--> Finished` | | | [ ] | [ ] |
| error transition from every legal source state | | | [ ] | [ ] |

## Numeric policies

For every floating field, record the source of its policy. “Large enough for
the current tests” is not a valid source.

| Contract path | Policy | Parameters | Specification/error-analysis source | Control-flow sensitive? |
|---|---|---|---|---|
| | `abs_rel` / `ulp` / `bit_exact` | | | |

If a numeric difference changes event order, terminal state, success/error,
commit/rollback, or a side effect, classify it as behavioral divergence. Do
not hide it with normalization or a wider tolerance.

## Normalization and exclusions

List every normalization and ignored field. Each is a specification claim and
must match `equivalence_contract.json`.

| Path | Action | Reason allowed by specification | Regression test |
|---|---|---|---|
| `trace.common.run_id` | ignore | per-execution identity only | differing run ids compare equal |
| `trace.common.impl` | ignore | identifies implementation | `cpp` vs `rust` compare equal |

Never round floating-point values during normalization.

## Completion

- [ ] Every in-scope observable has a row and a machine-readable contract path.
- [ ] Every explicit exclusion has a reason; there are no implicit exclusions.
- [ ] Every C++ and Rust observation point is implemented, including errors and cleanup.
- [ ] Every event/field has an explicit comparator or a reasoned ignore.
- [ ] Unknown events/fields and missing required fields are rejected.
- [ ] Contract coverage reports no missing semantic paths.
- [ ] Comparator mutation audit passes.
- [ ] All state transitions, guard outcomes, boundary cases, and declared errors are exercised.
- [ ] stdout, stderr, exit code, and side-effect manifest are compared.
- [ ] Every waiver and ignored path is reported as an explicit remaining risk.

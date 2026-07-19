---
name: rust-hardening
description: >-
  Use whenever writing, reviewing, or generating Rust code — hardening is the default for all
  Rust, not just production. Enforces a zero-warning / zero-clippy-finding build, bans panicking
  constructs (unwrap/expect/panic/indexing/slicing) in non-test code, forbids silently-overflowing
  arithmetic and lossy `as` casts, and requires runtime failures from arithmetic, indexing,
  conversion, and other fallible operations to propagate as Result unless local recovery
  completes the documented contract. Also bans erasing failures through underscore bindings,
  default substitution, Result-to-Option conversion, or ignored overflow flags, and requires
  rustfmt. Lint suppression is the rare, self-cleaning exception: `#[expect(reason=…)]` over
  `#[allow]`, at the narrowest scope, only from an explicit production allowlist — while
  generated code and test code (#[cfg(test)], tests/, benches/, examples/) may relax freely.
---

# Rust hardening (default for all Rust code)

## Core principle

Rust code must **fail loudly at build time, never silently at runtime** — and this applies to
*all* Rust you write, not only code labelled "production". A clean `cargo build` is not enough:
warnings, clippy findings, hidden panics, and wrapping arithmetic are all latent runtime faults
that the default toolchain *permits*. Hardening means turning every one of those into a
compile-time error, so the only code that ships is code whose failure modes are explicit.

The single, narrow exception is **test code**, where `unwrap`/`expect`/`panic!` are idiomatic
ways to assert and are allowed (see "Test code is the exception" below).

Five non-negotiable gates, always together:

1. **No warnings.** Every compiler warning is treated as an error.
2. **No clippy findings.** Clippy runs in CI with `-D warnings`; its output is never ignored.
3. **No hidden panics.** `unwrap`, `expect`, `panic!`, indexing, slicing, and friends are denied
   in all non-test code — fallibility is expressed in the type system (`Result`/`Option`).
4. **No silent overflow.** Bare `+ - * / %` on integers are forbidden. Runtime-dependent
   arithmetic uses `checked_*` and propagates failure; saturating or wrapping behavior is allowed
   only when it is part of the documented algorithm or API contract.
5. **No swallowed failures.** Failures caused by runtime data are propagated as `Result` unless
   local recovery still completes the function's documented contract. Renaming, logging,
   converting to `Option`, substituting a default, or ignoring an overflow flag is not recovery.

After any change, the code is run through **rustfmt** before it is considered done.

## Lint configuration (the canonical setup)

Encode the gates in the crate so they cannot be forgotten. Prefer the `[lints]` table in
`Cargo.toml` (workspace-wide via `[workspace.lints]`) — see
[templates/Cargo-lints.toml](templates/Cargo-lints.toml) for a copy-paste block.

```toml
# Cargo.toml
[lints.rust]
warnings = "deny"
# FFI needs unsafe, so use "deny" (NOT "forbid": forbid can't be locally
# overridden, so it bans the unsafe FFI blocks you actually need). Each unsafe
# block must then carry a `#[allow(unsafe_code)]` with a SAFETY comment.
unsafe_code = "deny"
unsafe_op_in_unsafe_fn = "deny"   # require an explicit `unsafe {}` inside unsafe fns

[lints.clippy]
# Panic-prone constructs — banned everywhere except test code.
unwrap_used = "deny"
expect_used = "deny"
panic = "deny"
unreachable = "deny"
todo = "deny"
unimplemented = "deny"
indexing_slicing = "deny"         # `a[i]` / `&a[i..j]` panic on OOB; use .get()
string_slice = "deny"             # `&s[a..b]` panics on a non-char boundary
unwrap_in_result = "deny"
# Silently-overflowing arithmetic — banned; be explicit instead.
arithmetic_side_effects = "deny"
# Catch one common way to drop a Result. Gate 5 also requires semantic review:
# this lint does not catch `_ignored`, `.ok()`, default substitution, or ignored flags.
let_underscore_must_use = "deny"
# Ban `as`; force TryFrom/From so lossy/wrapping casts can't hide.
as_conversions = "deny"
cast_possible_truncation = "deny"
cast_possible_wrap = "deny"
cast_sign_loss = "deny"
cast_lossless = "warn"
# Float foot-guns.
float_cmp = "deny"                # `==` on floats; compare with an epsilon
lossy_float_literal = "deny"
# Suppression hygiene — every allow/expect must justify itself, and prefer #[expect].
allow_attributes = "warn"               # nudge #[allow] -> #[expect] (self-cleaning)
allow_attributes_without_reason = "deny" # no silent allow: reason = "…" is mandatory
# Raise the floor.
pedantic = { level = "warn", priority = -1 }
```

Always also enable overflow checks in *every* profile (debug already does; release does not):

```toml
[profile.release]
overflow-checks = true
```

`overflow-checks` is the runtime backstop; `arithmetic_side_effects` is the compile-time one.
Keep both — the lint prevents the operation from existing, the profile catches anything that
slips through (e.g. in dependencies' inlined generics).

**unsafe / FFI.** `unsafe_code = "deny"` (not `forbid`) keeps unsafe an opt-in exception: every
`unsafe` block must carry a `#[allow(unsafe_code)]` plus a `// SAFETY:` comment justifying why
the invariants hold, so each one is a reviewed, documented decision rather than an accident. For
the FFI surface itself — validating foreign values, pointers, ownership, and layout against
Rust's invariants — follow the **rust-c-ffi-safety** skill, and run `cargo +nightly miri test`
(below) to catch the UB those bindings can introduce.

## Gate 1 & 2 — warnings and clippy are errors, never noise

- **Never** silence a finding without justification, and never blanket-`allow`. Suppression is a
  rare, scoped, self-cleaning exception governed by its own policy — see
  "Suppressing a lint — the allow/expect policy" below.

- **Run the full surface**, not just the default target:

  ```sh
  cargo clippy --all-targets --all-features -- -D warnings
  ```

- A clippy finding is a real defect until proven otherwise. Read the message and the lint's
  rationale; fix the code, don't pacify the linter.

## Suppressing a lint — the allow/expect policy

A suppression is a hole in the gates. The policy keeps every hole **rare, narrow, justified, and
self-cleaning**, and it differs by where the code comes from.

**Default: don't suppress — fix.** The first response to a finding is to remove the construct that
triggers it: `.get()`/iterators instead of indexing, `checked_*` instead of fallible bare
arithmetic (or documented saturating/wrapping semantics when the contract requires them),
`TryFrom` instead of `as`, a `Result` instead of `unwrap`. A module-wide
`#![allow(clippy::indexing_slicing)]` doesn't just excuse the one provably-safe index — it silently
excuses every future panic-capable index in that module. Reach for a suppression only after a
finding is shown to be a genuine false positive.

**Prefer `#[expect]` over `#[allow]`.** `#[expect(lint, reason = "…")]` warns when the lint *stops*
firing, so a suppression that is no longer needed (because the code was refactored) surfaces itself
instead of rotting in place. The `allow_attributes`/`allow_attributes_without_reason` lints in the
config above enforce this: `#[allow]` is nudged toward `#[expect]`, and **every** suppression must
carry a `reason = "…"`.

```rust
// false positive: constant index into a fixed-size 4-vector, statically in bounds.
#[expect(clippy::indexing_slicing, reason = "constant index into [_; 4], in bounds")]
let w = quat[3];
```

**Three tiers — where a suppression is allowed:**

| Tier | Policy | Form |
|---|---|---|
| **Generated code** (bindgen, prost, `build.rs` output) | Free to relax — you don't own the style. | one module-scoped `#[allow(…, reason = "bindgen-generated")]`, or have the generator emit `#![allow(...)]` |
| **Test code** (`#[cfg(test)]`, `tests/`, `benches/`, `examples/`, `build.rs`) | Free to relax — `unwrap`/`expect`/`panic`/indexing are idiomatic assertions. | scoped `#[allow(…, reason = "test code")]` on the module/file (see "Test code is the exception") |
| **Production** (everything else) | **Forbidden by default.** A suppression is allowed only for a lint on the project's **explicit allowlist**, at the **narrowest** scope (expression/statement/fn — *never* module-wide), via `#[expect(…, reason = "…")]`. | `#[expect(clippy::<allowlisted>, reason = "…")]` |

**Never a module-wide `#![allow]` in production — no exception, not even for numeric kernels.**
Decompose it to the specific items (functions/expressions) that actually trip the lint, each with
its own reasoned `#[expect]`/`#[allow]`. A file-level `#![allow]` is forbidden because it also
silently covers any non-kernel helper added to the file later (and it suppresses the lint inside the
file's `#[cfg(test)] mod tests`, hiding what the test module really relies on). Per-function scope
keeps the blast radius to the function that needs it. (The generated-code and test tiers below may
still use a single block `#[allow]` on the generated module / `mod tests`.)

**The production allowlist.** The project pins, in one place (`Cargo.toml` comment),
the short list of lints that *may* be excepted in production and the condition that makes each
legitimate. A reasonable default:

| Lint | May be excepted only for | Why narrow |
|---|---|---|
| `arithmetic_side_effects` | **f64/f32 float math** | floats can't integer-overflow. Integer arithmetic must use `checked_*` — `overflow-checks = true` makes an integer `allow` a *panic* source, not a silent one |
| `indexing_slicing` | **constant indices into fixed-size `[_; N]` / `SMatrix`** | provably in bounds; any *dynamic* index must use `.get()` |
| `as_conversions`, `cast_*` | a **deliberate, documented** conversion (e.g. an f32 pipeline mirroring C++) | a lossy cast on a length/size is a memory-safety bug; keep `TryFrom` elsewhere |

**Absolute-never (no allowlist entry, ever, in production):** `unwrap_used`, `expect_used`,
`panic`, `unreachable`, `todo`, `unimplemented`, `string_slice`. These are the constructs the gates
exist to remove; suppressing them defeats the point.

**Enforcement.** `allow_attributes_without_reason = "deny"` is the first line — no suppression
compiles without a reason. The second line is a CI check (a `grep` over the production sources,
excluding `#[cfg(test)]` blocks and the generated module, or a `dylint` lint) that **rejects any
production `allow`/`expect` of a lint not on the allowlist**. Together they make "allow is the rare,
justified exception" mechanically true rather than a matter of discipline.

## Gate 3 — no hidden panics in non-test code

Every `unwrap`/`expect`/`panic!`/`a[i]` is a panic waiting for the wrong input. Express
fallibility instead (this applies to all non-test code — libraries, binaries, helpers alike):

| Don't (panics) | Do (explicit) |
|---|---|
| `opt.unwrap()` | `opt.ok_or(Error::Missing)?` |
| `res.unwrap()` / `.expect("…")` | `res?` (or `.map_err(...)?`) |
| `slice[i]` | `slice.get(i).ok_or(Error::OutOfRange)?` |
| `&slice[a..b]` / `&s[a..b]` | `slice.get(a..b).ok_or(Error::OutOfRange)?` (`str` slicing also validates char boundaries) |
| `vec.remove(i)` / `insert` / `swap_remove` / `split_at(n)` | check `len` and return `Err` when invalid, or use a checked API and propagate failure |
| `a / b` / `a % b` | `a.checked_div(b).ok_or(Error::InvalidDivision)?` / `checked_rem(...).ok_or(...)?` |
| `cell.borrow_mut()` | `cell.try_borrow_mut()?` (panics on an active borrow) |
| `panic!("bad state")` | `return Err(Error::BadState)` |
| `unreachable!()` on external input | model the case and return `Err` |
| `Mutex::lock().unwrap()` | propagate or recover from `PoisonError` |

- Use a typed error (`thiserror` for libraries, `anyhow`/`eyre` only at application
  boundaries) and the `?` operator. Make functions return `Result<_, E>` rather than panicking.
- A locally proven invariant does not justify `unreachable!` or `unwrap` in production. Preserve
  the proof in a comment, but still model the branch and return a typed internal-invariant error.
- `assert!`/`debug_assert!` for internal invariants is fine, but it is not error handling for
  untrusted input — validate and return `Err` instead.
- Mind the panics the lints can't always see: length-mismatch methods like
  `copy_from_slice`/`clone_from_slice`, `chunks(0)`/`windows(0)`, and `slice::concat` on huge
  inputs. And remember **stack overflow from unbounded recursion aborts the process and is not
  catchable** — bound recursion depth on untrusted input.

## Gate 4 — arithmetic without silent overflow

Bare `+ - * / %` (and `<< >>`, negation, `+=` …) on integers either panic in debug or wrap in
release — both are bugs. `arithmetic_side_effects` denies them. For values derived at runtime,
failure propagation is the default:

| Need | Use | Result |
|---|---|---|
| Runtime overflow is an error (default) | `a.checked_add(b)` | `Option<T>` → `.ok_or(Error::Overflow)?` |
| Clamping is the documented result | `a.saturating_add(b)` | `T`, pinned to `MIN`/`MAX` |
| Modular arithmetic is the documented algorithm | `a.wrapping_add(b)` | `T`, documented wrap |
| The caller needs the overflow status | `a.overflowing_add(b)` | inspect and propagate the flag; never discard it |

```rust
// Don't: silently wraps in release, panics in debug.
let total = price * qty + fee;

// Do: every step states its overflow policy.
let total = price
    .checked_mul(qty)
    .and_then(|s| s.checked_add(fee))
    .ok_or(Error::Overflow)?;
```

- Division/remainder also panic on divide-by-zero and on `MIN / -1`: use `checked_div`/
  `checked_rem` and convert `None` to a typed error with `ok_or(...)?`. If validating the divisor
  first, the invalid branch must likewise return an error.
- Prefer `usize`/`u*` for counts and indices, but a subtraction like `len - n` still
  underflows — use `checked_sub().ok_or(Error::Underflow)?`.
- For float arithmetic, guard against `NaN`/`inf` where the result feeds a decision; floats
  don't overflow-panic but produce silently-poisonous values. Return a typed error unless the
  documented domain explicitly defines those values.
- `saturating_*`, `wrapping_*`, and `overflowing_*` are not generic escape hatches from error
  handling. Use them only when that behavior is required by the documented algorithm or API
  contract. Add a nearby comment naming that contract; for `overflowing_*`, inspect the flag and
  propagate an error unless overflow itself is an intended output.
- **Ban `as` for numeric casts.** `as_conversions` forbids `x as T`, which silently truncates,
  wraps, or loses sign. Use `T::try_from(x)?` when the value might not fit, or `T::from(x)` when
  it always does. This matters most for allocation sizes and lengths crossing an FFI or
  network boundary, where a truncating `usize as u32` is a memory-safety bug.
  - `as` is still legitimate where no `From`/`TryFrom` applies — pointer casts (`p as usize`,
    `p as *const U`), `enum`-to-integer, and *intentional* truncation. There, keep the cast but
    scope a `#[allow(clippy::as_conversions)]` with a one-line reason (e.g. `// truncation is
    intended: low 8 bits only`), exactly as for any other suppressed lint.

## Gate 5 — propagate failures unless recovery fulfills the contract

Not panicking is only half of error handling; the other half is preserving failure information.
An operation that cannot produce its promised result must return a typed error to its caller.
Handle a failure locally only when a bounded recovery action succeeds and the function can still
fulfill its documented contract. Logging, recording a metric, or continuing with partial/default
data is not recovery unless loss tolerance and the fallback are explicitly part of that contract.

```rust
// Don't: each form erases a failure.
let _ = file.write_all(&buf);
let _ignored = file.write_all(&buf);
let item = slice.get(index).copied().unwrap_or_default();
let maybe_value = parse_value(input).ok();
let (total, _) = lhs.overflowing_add(rhs);

// Do: preserve the failure and propagate it.
file.write_all(&buf)?;
let item = slice
    .get(index)
    .copied()
    .ok_or(Error::OutOfRange { index })?;
let value = parse_value(input)?;
let total = lhs.checked_add(rhs).ok_or(Error::Overflow)?;
```

- `?` is the default for failures caused by external input, runtime state, arithmetic,
  indexing, conversion, I/O, synchronization, or allocation.
- Use `Option` for normal domain absence ("not found" is a valid answer), not to erase the cause
  of a failed operation. Do not call `.ok()` merely to discard a `Result`'s error.
- Do not turn a failure-bearing `Option`/`Result` into a successful value with
  `unwrap_or_default`, `unwrap_or`, `map_or`, or an equivalent fallback. Such a fallback is valid
  only when the public contract names it as the intended result for that condition.
- Do not discard a `Result` through `let _ =`, `_ignored`/other underscore-prefixed bindings,
  `drop`, or a closure/callback that ignores the return value. Do not discard the boolean from
  `overflowing_*`.
- Local recovery must be real and bounded: retry/reconnect/rebuild using a documented policy,
  verify that recovery succeeded, and propagate the final error if it did not. A log line followed
  by normal continuation is swallowed failure, not recovery.
- `let_underscore_must_use` denies only one common spelling,
  `let _ = <expr returning a #[must_use] type>`. Compiler and Clippy lints do **not** prove this
  gate: review every fallible call and use a project-specific Dylint/Semgrep/AST check when
  mechanical enforcement is required.
- Annotate functions whose return value must not be ignored with `#[must_use]`, and mark public
  error enums `#[non_exhaustive]` so adding a variant isn't a breaking change.
- Convert between error types with `From`/thiserror's `#[from]` rather than
  `.map_err(|_| ...)` that throws away the cause.

## Test code and generated code are the exceptions

Hardening is the default for **all** Rust. The two tiers that may relax freely (see the policy
table above) are **test code** and **generated code** — both still require a `reason = "…"` on the
suppression, but the *what* is unrestricted there.

**Test code** — `unwrap`/`expect`/`panic!` are the idiomatic, clearest way to assert a precondition
or fail a test, and bare arithmetic on small known constants is fine:

- Applies to: `#[cfg(test)]` modules, the `tests/` directory, `benches/`, `examples/`, and
  `build.rs`.
- Scope the relaxation to the test code, never globally:

  ```rust
  #[cfg(test)]
  #[allow(
      clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing,
      reason = "test code"
  )]
  mod tests { /* unwrap/expect/panic freely here */ }
  ```

- Integration tests under `tests/` and `examples/` can be exempted per-file with an inner
  attribute: `#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, reason = "test code")]`.

**Generated code** — bindgen/prost output and other generated modules don't follow your style and
shouldn't be hand-edited. Wrap the generated module in a single suppression with a reason, or have
the generator emit it:

```rust
#[allow(clippy::all, clippy::pedantic, reason = "bindgen-generated")]
mod ffi_bindings { include!(concat!(env!("OUT_DIR"), "/bindings.rs")); }
```

Everything else — including `main()`, CLI glue, and one-off helpers — is held to the full bans
(and to the production allowlist for any suppression). A `main()` that `?`-propagates into
`fn main() -> anyhow::Result<()>` is preferred over one that unwraps.

## Verification — run before declaring done

Run all four commands, in order; treat any non-zero exit as a failure to fix, not to suppress:

```sh
cargo fmt --all                                              # 1. format (apply)
cargo build --all-targets --all-features 2>&1               # 2. zero warnings
cargo clippy --all-targets --all-features -- -D warnings    # 3. zero clippy findings
cargo test --all-features                                    # 4. tests pass
```

In CI, additionally enforce formatting without mutating the tree, and harden the supply chain
and any unsafe code:

```sh
cargo fmt --all -- --check       # fails if anything is unformatted
cargo +nightly miri test         # detect UB — required if the crate has unsafe/FFI
cargo deny check                 # advisories, licenses, banned/duplicate deps, sources
cargo audit                      # RUSTSEC vulnerability advisories
```

Pre-merge checklist:

- [ ] `cargo fmt --all` applied; `cargo fmt --all -- --check` is clean.
- [ ] `cargo build` and `cargo clippy -- -D warnings` produce **zero** warnings across
      `--all-targets --all-features`.
- [ ] No `unwrap`/`expect`/`panic!`/`unreachable!`/`a[i]`/`&a[i..j]` outside test code.
- [ ] No module-wide `#![allow]` in production; suppressions are narrow `#[expect(…, reason = "…")]`
      from the project allowlist only. Generated/test code carries a scoped, reasoned `#[allow]`.
- [ ] `allow_attributes` + `allow_attributes_without_reason` are in the `[lints]` config (every
      suppression carries a `reason`); the allowlist CI check passes.
- [ ] No bare `+ - * / %` on integers in non-test code. Runtime-dependent arithmetic uses
      `checked_*` and propagates failure; saturating/wrapping behavior is documented as part of
      the algorithm/API contract; every `overflowing_*` flag is inspected.
- [ ] No failure-bearing `Result`/`Option` is erased via `let _ =`, underscore bindings, `drop`,
      `.ok()`, default substitution, ignored flags, logging-only handlers, or callbacks. Failures
      propagate unless verified, bounded recovery fulfills the documented contract.
- [ ] `[lints]` config and `overflow-checks = true` are present in `Cargo.toml`.
- [ ] `Cargo.lock` is committed and `rust-version` (MSRV) is pinned; `cargo deny`/`cargo audit`
      pass.

## Context-dependent additional checks

Beyond the gates above, harden these when the project calls for it — they depend on the domain
rather than applying universally:

- **Concurrency.** Watch for deadlocks and define a lock ordering; verify `Send`/`Sync` bounds
  and atomic `Ordering` are correct (not reflexively `SeqCst` nor `Relaxed`). Test concurrent
  code under `loom`, and consider ThreadSanitizer.
- **Resource exhaustion from untrusted input.** Don't `Vec::with_capacity(n)` /
  `reserve(n)` on an attacker-controlled `n` (OOM/abort); cap sizes and stream instead. Bound
  recursion depth in parsers.
- **Deeper testing.** Add property tests (`proptest`/`quickcheck`) for invariants and fuzzing
  (`cargo-fuzz`) for parsers and any code handling untrusted bytes.
- **Release profile.** If the crate is called over FFI, set `panic = "abort"` so a panic can't
  unwind across the language boundary (which is UB).

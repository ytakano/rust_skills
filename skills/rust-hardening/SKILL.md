---
name: rust-hardening
description: Use whenever writing, reviewing, or generating Rust code — hardening is the default for all Rust, not just production. Enforces a zero-warning / zero-clippy-finding build, bans panicking constructs (unwrap/expect/panic/indexing/slicing) in non-test code, forbids silently-overflowing arithmetic and lossy `as` casts in favor of explicit checked/saturating/wrapping ops and TryFrom, requires that no Result is discarded with `let _`, and requires rustfmt. Test code (#[cfg(test)], tests/, benches/, examples/) may freely use unwrap/expect/panic.
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
4. **No silent overflow.** Bare `+ - * / %` on integers are forbidden; every arithmetic
   operation states its overflow behavior (`checked_*`, `saturating_*`, `wrapping_*`).
5. **No swallowed errors.** A `Result` is never discarded with `let _ =`; fallibility is
   propagated or handled, not dropped.

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
# Don't drop a Result on the floor.
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

- **Never** silence a finding without justification. Do not blanket-`allow`; do not delete the
  lint. If a finding is a genuine false positive, suppress it at the **narrowest** scope with
  a written reason:

  ```rust
  // SAFETY/REASON: index is bounded by the `for i in 0..v.len()` above.
  #[allow(clippy::indexing_slicing)]
  let x = v[i];
  ```

- **Run the full surface**, not just the default target:

  ```sh
  cargo clippy --all-targets --all-features -- -D warnings
  ```

- A clippy finding is a real defect until proven otherwise. Read the message and the lint's
  rationale; fix the code, don't pacify the linter.

## Gate 3 — no hidden panics in non-test code

Every `unwrap`/`expect`/`panic!`/`a[i]` is a panic waiting for the wrong input. Express
fallibility instead (this applies to all non-test code — libraries, binaries, helpers alike):

| Don't (panics) | Do (explicit) |
|---|---|
| `opt.unwrap()` | `opt.ok_or(Error::Missing)?` |
| `res.unwrap()` / `.expect("…")` | `res?` (or `.map_err(...)?`) |
| `slice[i]` | `slice.get(i).ok_or(Error::OutOfRange)?` |
| `&slice[a..b]` / `&s[a..b]` | `slice.get(a..b)` (`str` slicing also panics off a char boundary) |
| `vec.remove(i)` / `insert` / `swap_remove` / `split_at(n)` | check `len` first, or use `get`/`split_at_checked` |
| `a / b` / `a % b` | `a.checked_div(b)` / `checked_rem` (zero / `MIN`-by-`-1` panic) |
| `cell.borrow_mut()` | `cell.try_borrow_mut()?` (panics on an active borrow) |
| `panic!("bad state")` | `return Err(Error::BadState)` |
| `unreachable!()` on external input | model the case and return `Err` |
| `Mutex::lock().unwrap()` | propagate or recover from `PoisonError` |

- Use a typed error (`thiserror` for libraries, `anyhow`/`eyre` only at application
  boundaries) and the `?` operator. Make functions return `Result<_, E>` rather than panicking.
- `unreachable!`/`unwrap` is acceptable **only** when the invariant is locally proven and
  cannot depend on external input — and then it must carry a comment proving it and a scoped
  `#[allow(...)]`. Default to returning an error.
- `assert!`/`debug_assert!` for internal invariants is fine, but it is not error handling for
  untrusted input — validate and return `Err` instead.
- Mind the panics the lints can't always see: length-mismatch methods like
  `copy_from_slice`/`clone_from_slice`, `chunks(0)`/`windows(0)`, and `slice::concat` on huge
  inputs. And remember **stack overflow from unbounded recursion aborts the process and is not
  catchable** — bound recursion depth on untrusted input.

## Gate 4 — arithmetic without silent overflow

Bare `+ - * / %` (and `<< >>`, negation, `+=` …) on integers either panic in debug or wrap in
release — both are bugs. `arithmetic_side_effects` denies them. Choose the behavior explicitly:

| Need | Use | Result |
|---|---|---|
| Overflow is an error | `a.checked_add(b)` | `Option<T>` → `.ok_or(Error::Overflow)?` |
| Clamp at the bound | `a.saturating_add(b)` | `T`, pinned to `MIN`/`MAX` |
| Modular/wrapping is intended | `a.wrapping_add(b)` | `T`, documented wrap |
| Need both value and flag | `a.overflowing_add(b)` | `(T, bool)` |

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
  `checked_rem`, or validate the divisor first.
- Prefer `usize`/`u*` for counts and indices, but a subtraction like `len - n` still
  underflows — use `checked_sub`.
- For float arithmetic, guard against `NaN`/`inf` where the result feeds a decision; floats
  don't overflow-panic but produce silently-poisonous values.
- **Ban `as` for numeric casts.** `as_conversions` forbids `x as T`, which silently truncates,
  wraps, or loses sign. Use `T::try_from(x)?` when the value might not fit, or `T::from(x)` when
  it always does. This matters most for allocation sizes and lengths crossing an FFI or
  network boundary, where a truncating `usize as u32` is a memory-safety bug.
  - `as` is still legitimate where no `From`/`TryFrom` applies — pointer casts (`p as usize`,
    `p as *const U`), `enum`-to-integer, and *intentional* truncation. There, keep the cast but
    scope a `#[allow(clippy::as_conversions)]` with a one-line reason (e.g. `// truncation is
    intended: low 8 bits only`), exactly as for any other suppressed lint.

## Gate 5 — never swallow a `Result`

Not panicking is only half of error handling; the other half is not *dropping* the error.

```rust
// Don't: the error is silently discarded — the write may have failed.
let _ = file.write_all(&buf);

// Do: propagate it...
file.write_all(&buf)?;
// ...or handle it deliberately.
if let Err(e) = file.write_all(&buf) {
    log::warn!("write failed, retrying: {e}");
    // ...recover...
}
```

- `let_underscore_must_use` denies `let _ = <expr returning a #[must_use] type>`. Don't reach
  for `let _ =` to silence "unused `Result`" — propagate with `?` or handle the error.
- Annotate functions whose return value must not be ignored with `#[must_use]`, and mark public
  error enums `#[non_exhaustive]` so adding a variant isn't a breaking change.
- `?` is the default. Convert between error types with `From`/`thiserror`'s `#[from]` rather
  than `.map_err(|_| ...)` that throws away the cause.

## Test code is the exception

Hardening is the default for **all** Rust. The one relaxation is **test code**, where
`unwrap`/`expect`/`panic!` are the idiomatic, clearest way to assert a precondition or fail a
test, and bare arithmetic on small known constants is fine:

- Applies to: `#[cfg(test)]` modules, the `tests/` directory, `benches/`, `examples/`, and
  `build.rs`.
- Scope the relaxation to the test code, never globally:

  ```rust
  #[cfg(test)]
  #[allow(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::indexing_slicing)]
  mod tests { /* unwrap/expect/panic freely here */ }
  ```

- Integration tests under `tests/` and `examples/` can be exempted per-file with an inner
  attribute: `#![allow(clippy::unwrap_used, clippy::expect_used, clippy::panic)]`.

Everything else — including `main()`, CLI glue, and one-off helpers — is held to the full bans.
A `main()` that `?`-propagates into `fn main() -> anyhow::Result<()>` is preferred over one that
unwraps.

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
- [ ] No `unwrap`/`expect`/`panic!`/`unreachable!`/`a[i]`/`&a[i..j]` outside test code; test
      modules carry a scoped `#[allow(...)]`, any other exception a narrow `#[allow]` with a
      written justification.
- [ ] No bare `+ - * / %` on integers in non-test code; every op is `checked_*`/
      `saturating_*`/`wrapping_*` with the intended policy; no `as` numeric casts.
- [ ] No `Result` discarded via `let _ =`; errors are propagated or handled.
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

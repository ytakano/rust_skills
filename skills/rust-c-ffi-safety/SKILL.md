---
name: rust-c-ffi-safety
description: Use when writing, reviewing, or generating Rust code that calls C (or C that is called from Rust) over FFI — extern "C" declarations, unsafe wrappers, pointer/struct marshaling, or the C side of a Rust binding. Enforces the 26 FFI soundness rules so foreign data and pointers are validated against Rust's safety invariants.
---

# Rust ↔ C FFI safety

## Core principle

The C ABI preserves **calling conventions and sizes — not Rust's safety invariants.**
Every value, pointer, and struct that crosses the FFI boundary is *untrusted* until it is
validated against the **assumed Rust-side binding** (the Rust type/contract the foreign
value is bound to). A function can be perfectly valid C and still be *unsound* the instant
its result is interpreted as a Rust `bool`, `&T`, `NonNull<T>`, `str`, enum, or
`#[repr(C)]` struct.

Two duties, always paired:

- **C side must** uphold the contract the Rust binding assumes.
- **Rust side must** assume the C side might violate it, and validate / type defensively —
  because Rust UB (invalid value, dangling/misaligned pointer, aliasing violation) is
  *immediate and unrecoverable*, not a runtime error you can catch later.

## Pre-merge checklist for any FFI surface

Before finalizing an `extern "C"` block, an `unsafe` wrapper, or a C function exposed to
Rust, confirm:

- [ ] **Bit-patterns** — every returned/out scalar is a valid value for its Rust type
      (`bool` ∈ {0,1}; `char` is a non-surrogate scalar value; enum is a declared
      discriminant; the value is actually initialized). #1 #2 #3 #23 #24
- [ ] **Non-null / non-zero** — `NonNull`/`&`/`&mut`/`NonZero*` bindings never receive
      0 or NULL. #4 #5
- [ ] **Pointer validity** — every pointer Rust will deref is live, correctly aligned for
      its pointee, in-bounds of a real allocation, and has real provenance (not forged from
      an integer, not a freed/stale address). #6 #7 #8 #9 #11 #26
- [ ] **Slice metadata** — any `(ptr, len)` describes memory that is actually that large. #10
- [ ] **Ownership** — who frees, and with which allocator, is explicit and honored; "owned"
      returns are really heap-owned; success means the out-param was written. #12 #13 #14
- [ ] **Layout** — Rust `repr` matches C field order, packing, and alignment exactly. #15 #16
- [ ] **Aliasing XOR mutability** — no shared and mutable references to the same bytes; no
      two `&mut` to the same object; `const` inputs are not written; non-overlap contracts
      hold. #17 #18 #19 #25
- [ ] **Temporal / control flow** — the callee returns normally and does not keep mutating
      memory after return via background threads, signals, retained borrows, or `longjmp`. #12 #20 #21 #22

## Rules by category

> Each rule below carries the same number used in
> [EvaluationCatalog.md](EvaluationCatalog.md), where every rule has a concrete
> legal/illegal C code pair.

### Valid-value violations — #1, #2, #3, #5, #23, #24

A Rust type with restricted valid values (`bool`, `char`, field-less enum, `NonZero*`,
`str`) makes any out-of-domain bit-pattern *instant UB* when read at that type. Read these
as raw integers/bytes and validate before forming the Rust type:

```rust
// #1 bool — never read a foreign byte directly as `bool`.
let mut byte: u8 = 0;
unsafe { fill_flag(&mut byte) };
let flag: bool = match byte { 0 => false, 1 => true, _ => return Err(..) };
```

- **#1 bool** — *C must* write only `0`/`1`. *Rust must* take the byte as `u8` and check
  `∈ {0,1}` (or `!= 0`) before treating it as `bool`.
- **#2 char** — *C must* produce a valid Unicode scalar value (no surrogates `0xD800–0xDFFF`,
  ≤ `0x10FFFF`). *Rust must* go through `char::from_u32(x)` and handle `None`.
- **#3 enum** — *C must* return only declared discriminants. *Rust must* receive the raw
  integer and `match`/`try_from` it into the enum rather than transmuting.
- **#5 NonZero handle** — *C must* never return `0` for a `NonZeroU32`-bound handle. *Rust
  must* take the raw integer and use `NonZeroU32::new(x)` → `Option`.
- **#23 UTF-8 / str** — *C must* return valid UTF-8 if Rust binds the result as `str`. *Rust
  must* use `CStr` + `str::from_utf8`/`to_str()` and handle the error; don't assume
  `&[u8]` → `str`.
- **#24 uninitialized scalar** — *C must* fully initialize any value it returns/exposes.
  *Rust must* never read possibly-uninitialized memory at a typed value; use
  `MaybeUninit<T>` until provably written.

### Pointer-validity violations — #4, #6, #7, #8, #9, #11, #26

Every pointer Rust dereferences (or turns into `&`/`&mut`) must be **live, aligned,
in-bounds, and real**.

- **#4 null** — *C must* never return NULL for a non-null binding. *Rust must* model
  nullable returns as `*mut T` → `Option<NonNull<T>>` (or `Option<&T>`), not `&T`.
- **#6 dangling heap** — *C must not* return already-`free`d memory. *Rust must* deref only
  before the documented free point and treat the C deallocator as the sole owner-transfer.
- **#7 stack address** — *C must not* return `&local`; return `static`/heap. *Rust must*
  not trust pointers whose lifetime ends at the C function's return.
- **#8 misaligned** — *C must* return pointers aligned for the pointee (no
  `(uint32_t*)(buf+1)`). *Rust must* check `ptr.align_offset` / use `read_unaligned` if
  alignment can't be guaranteed; a misaligned `&u32` is UB even if never written.
- **#9 out-of-bounds** — *C must* return pointers within a real allocation. *Rust must*
  bound any pointer arithmetic and slice construction to the true object size.
- **#11 forged pointer** — *C must* derive pointers from real allocations, not integer
  literals. *Rust must* treat integer-derived addresses as opaque, never deref without
  provenance.
- **#26 stale provenance** — *C must not* hand back a `uintptr_t` of freed memory as if it
  were live. *Rust must* treat numeric handles as opaque tokens, not re-materialize them
  into pointers and deref.

### Ownership and lifetime violations — #12, #13, #14

- **#12 retained borrow** — *C must not* stash an input pointer for use after return. *Rust
  must* pass borrows whose lifetime ends at the call, and assume the callee won't keep them;
  if C needs to retain, transfer ownership explicitly.
- **#13 owned vs static** — *C must* return real heap memory if the contract says "owned /
  caller frees", and pair it with a matching deallocator. *Rust must* free returned-owned
  pointers only through that C deallocator (never Rust's allocator), and not free
  static-backed returns.
- **#14 uninit out-param on success** — *C must* write the out-param whenever it reports
  success. *Rust must* use `MaybeUninit` for out-params and `assume_init` only after a
  success code.

### Layout / ABI violations — #15, #16

The Rust `repr` must reproduce the C layout **byte for byte**.

```rust
// #15 — match natural vs packed layout to the C declaration.
#[repr(C)]         struct Pair       { tag: u32, value: u64 } // normal C struct
#[repr(C, packed)] struct PairPacked { tag: u32, value: u64 } // only if C is #pragma pack(1)
```

- **#15 packing/alignment** — *C must* use the layout Rust expects. *Rust must* mark the
  struct `#[repr(C)]` for natural C layout, or `#[repr(C, packed)]` only if the C side is
  actually `#pragma pack`ed — and the two must agree.
- **#16 field order** — *C must* keep the field order Rust declares. *Rust must* declare
  fields in the same order with matching types; same-size fields (e.g. two `u32`) in the
  wrong order compile cleanly and silently swap values at runtime.

### Aliasing XOR mutability violations — #17, #18, #19, #25

Rust references obey aliasing XOR mutability *globally*, including across FFI. Violations
are UB even if nothing is written.

- **#17 shared aliases mutable** — *C must not* return an "immutable" output that aliases a
  buffer Rust still holds `&mut`. *Rust must* not simultaneously hold `&mut src` and a
  `&`/slice derived from a C output that may point into `src`.
- **#18 two mutable aliases** — *C must not* hand back two writable pointers to the same
  object. *Rust must* not turn both into `&mut`; if they may overlap, keep them as `*mut`.
- **#19 mutation through const** — *C must not* cast away `const` and write. *Rust must*
  remember `*const`/`&[u8]` inputs may be cast-and-written by buggy C; pass `&mut`/`*mut`
  when mutation is intended and treat shared borrows as a hard contract.
- **#25 overlapping buffers** — *C must* honor non-overlap contracts (`memcpy`, not
  overlapping `memmove` semantics). *Rust must* not pass aliasing/overlapping regions to an
  API documented as non-overlapping (e.g. `copy_nonoverlapping`-style).

### Temporal / concurrency / control-flow violations — #20, #21, #22

- **#20 background mutation** — *C must not* spawn a detached thread that keeps mutating
  passed memory after return. *Rust must* assume passed memory is quiescent only if the C
  contract guarantees no background writers; otherwise it can't safely re-borrow it.
- **#21 signal-handler mutation** — *C must not* mutate shared memory asynchronously via a
  signal handler. *Rust must* treat such memory as concurrently modified (no plain `&`).
- **#22 longjmp** — *C must* return normally, not `longjmp` across Rust frames (skips
  destructors → leaks/UB). *Rust must* not call C that may `longjmp` past it; require the C
  side to convert non-local exits into ordinary error returns.

## Idiomatic Rust mappings

Reach for the safe construct by default:

| Hazard | Don't | Do |
|---|---|---|
| #1 bool | read byte as `bool` | read `u8`, check `∈ {0,1}` |
| #2 char | transmute `u32`→`char` | `char::from_u32(x)?` |
| #3 enum | transmute int→enum | `match`/`TryFrom` on the raw int |
| #4 null | `-> &T` / bare `*mut T` deref | `Option<NonNull<T>>` / `Option<&T>` |
| #5 handle | use `0` as valid | `NonZeroU32::new(x)` |
| #10 slice | trust returned `len` | `slice::from_raw_parts` after checking `len` |
| #13/#6 owned | free with Rust allocator | pair with the C deallocator; never double-free |
| #14 out-param | read raw out-param | `MaybeUninit<T>` + `assume_init` after success |
| #15/#16 struct | guess layout | `#[repr(C)]` / `#[repr(C, packed)]`, fields in C order |
| #23 str | `&[u8]` → `str` | `CStr` + `str::from_utf8` |
| #24 scalar | read uninit | `MaybeUninit<T>` until written |
| #8 align | `&*ptr` on any address | check alignment or `read_unaligned` |

## Verifying FFI bindings

- **Test both paths.** For each binding, exercise a known-good call *and* a known-bad one,
  and assert the Rust-side validation rejects the bad value instead of forming the unsound
  type. A binding with only happy-path tests is unverified.
- **Run under Miri** — `cargo +nightly miri test`. Miri detects the UB that ordinary tests
  pass over silently: invalid bit-patterns, dangling/misaligned pointers, out-of-bounds and
  aliasing violations, and uninitialized reads. Treat a Miri error as a real bug, not noise.
- **Pin struct layout.** Don't eyeball `repr`. Verify field offsets and size with
  `core::mem::{size_of, align_of, offset_of!}` assertions (or the `static_assertions`
  crate), or generate the bindings from the C headers with `bindgen` so layout, field order,
  and types can't drift.
- **Keep the C contract written down.** For each `extern "C"` symbol, document the assumed
  Rust-side binding (nullability, ownership/who-frees, valid-value range, aliasing, lifetime)
  next to the declaration, so reviewers can check the C side against it.
- **Concrete C test cases.** For a legal/illegal C code pair per rule — plus a
  suggested test grouping and per-case metadata schema — see
  [EvaluationCatalog.md](EvaluationCatalog.md), and use it to build the
  both-paths suite above.

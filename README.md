# rust_skills

A collection of **skills for coding agents** that write, review, and verify Rust — with
a focus on soundness, robustness, and correct C/C++ interop.

A *skill* is a Markdown file (`SKILL.md`) with YAML frontmatter that a compatible coding
agent loads on demand. Its `description` tells the agent *when* the skill applies; the
agent reads the body (and any referenced files) only when a task matches, then follows
the guidance. These skills are prescriptive checklists and patterns, not runnable code.

## Skills

| Skill | Use it when… |
|---|---|
| [`rust-hardening`](skills/rust-hardening/) | Writing or reviewing **any** Rust. Enforces a zero-warning / zero-clippy build, bans hidden panics (`unwrap`/`expect`/`panic!`/indexing/slicing), forbids silently-overflowing arithmetic and lossy `as` casts, and requires runtime failures to propagate as `Result` unless verified local recovery fulfills the documented contract. Also rejects erased failures such as underscore bindings, default substitution, `Result`-to-`Option` conversion, and ignored overflow flags. Requires `rustfmt`; test and generated code may use scoped exceptions. |
| [`rust-c-ffi-safety`](skills/rust-c-ffi-safety/) | Writing Rust that calls C (or C called from Rust) over FFI — `extern "C"`, unsafe wrappers, pointer/struct marshaling. Enforces 26 FFI soundness rules so foreign data is validated against Rust's safety invariants. |
| [`rust-coverage-meaningful-tests`](skills/rust-coverage-meaningful-tests/) | Measuring or improving test coverage for a Rust crate. Uses coverage as a diagnostic map, not the objective: targets behavior, invariants, edge cases, error paths, `unsafe` contracts, and regression protection instead of shallow line-execution tests. |
| [`trace-state-machine-port-verification`](skills/trace-state-machine-port-verification/) | Porting a C++ implementation to Rust and needing confidence the port is behavior-equivalent. Inventories all specification-level observables, validates a fail-closed trace/outcome/side-effect contract, supports field-specific floating-point policies, and requires complete contract coverage plus comparator mutation audit before declaring observable equivalence. |
| [`rust-realtime-implementation`](skills/rust-realtime-implementation/) | Implementing or writing RT-critical Rust where predictable WCET matters — ISRs, schedulers, drivers, packet fast paths, async poll loops, control loops, allocators, sync code. Favors bounded, allocation-free, panic-free, blocking-free designs with explicit WCET contracts over fast average-case code. |
| [`rust-realtime-review`](skills/rust-realtime-review/) | Reviewing Rust patches, PRs, or files for real-time safety and WCET predictability — bounded execution, allocation-/panic-free RT paths, synchronization and async-poll bounds, hidden `Drop` work, and residual timing risks. Offers a quick-review mode and a deeper WCET-audit mode. |

`rust-hardening` and `rust-c-ffi-safety` are complementary: the FFI skill cross-references
the hardening skill, and the hardening skill points at the FFI skill for `unsafe`/FFI surfaces.
`rust-realtime-implementation` and `rust-realtime-review` are likewise complementary: the
review skill points at the implementation skill for guidance, and the implementation skill
defers patch/PR review to the review skill.

## Layout

```
skills/
  rust-hardening/
    SKILL.md                     # the guidance a coding agent loads
    templates/Cargo-lints.toml   # copy-paste lint config enforcing the gates
  rust-c-ffi-safety/
    SKILL.md
    EvaluationCatalog.md         # legal/illegal C code pair per rule
  rust-coverage-meaningful-tests/
    SKILL.md                     # coverage-as-diagnostic test guidance
  trace-state-machine-port-verification/
    SKILL.md
    reference/                   # detailed sub-guides (normalization, triage, …)
    templates/                   # C++/Rust/Python trace + diff harness scaffolding
  rust-realtime-implementation/
    SKILL.md
    rust-realtime-implementation-notes.md   # detail dropped from the compact SKILL.md
  rust-realtime-review/
    SKILL.md
    rust-realtime-review-notes.md            # review examples + WCET audit templates
```

Each skill is self-contained in its own directory. `SKILL.md` is the entry point; everything
else is read only when the guidance references it.

## Using these skills

Make the skills discoverable by placing or symlinking them in a skills directory supported
by your coding agent. The exact location and whether project-level and user-level installation
are supported depend on the agent, so consult its documentation.

For example, if your agent uses `<agent-skills-dir>` as its skills directory:

```sh
mkdir -p <agent-skills-dir>
cp -r skills/rust-hardening <agent-skills-dir>/
```

Once installed, a compatible agent can invoke a skill automatically when a task matches its
`description`; you can also request it explicitly (for example, "use the rust-hardening
skill"). The skills are also useful as standalone checklists for human reviewers.

## Contributing

When adding a skill, follow the existing conventions:

- One directory per skill under `skills/`, with a `SKILL.md` whose frontmatter has a `name`
  and an actionable, trigger-oriented `description` (state *when* to use it).
- Keep `SKILL.md` focused; move long examples, references, and scaffolding into
  `reference/`/`templates/` and link to them so they load only on demand.

# rust_skills

A collection of [Claude Code](https://claude.com/claude-code) **Skills** for writing,
reviewing, and verifying Rust — with a focus on soundness, robustness, and correct
C/C++ interop.

A *skill* is a Markdown file (`SKILL.md`) with YAML frontmatter that Claude loads on demand.
Its `description` tells Claude *when* the skill applies; Claude reads the body (and any
referenced files) only when a task matches, then follows the guidance. These skills are
prescriptive checklists and patterns, not runnable code.

## Skills

| Skill | Use it when… |
|---|---|
| [`rust-hardening`](skills/rust-hardening/) | Writing or reviewing **any** Rust. Enforces a zero-warning / zero-clippy build, bans hidden panics (`unwrap`/`expect`/`panic!`/indexing/slicing), forbids silently-overflowing arithmetic and lossy `as` casts, requires that no `Result` is dropped, and requires `rustfmt`. Test code is the only exception. |
| [`rust-c-ffi-safety`](skills/rust-c-ffi-safety/) | Writing Rust that calls C (or C called from Rust) over FFI — `extern "C"`, unsafe wrappers, pointer/struct marshaling. Enforces 26 FFI soundness rules so foreign data is validated against Rust's safety invariants. |
| [`rust-coverage-meaningful-tests`](skills/rust-coverage-meaningful-tests/) | Measuring or improving test coverage for a Rust crate. Uses coverage as a diagnostic map, not the objective: targets behavior, invariants, edge cases, error paths, `unsafe` contracts, and regression protection instead of shallow line-execution tests. |
| [`trace-state-machine-port-verification`](skills/trace-state-machine-port-verification/) | Porting a C++ implementation to Rust and needing confidence the port is behavior-equivalent. Drives the full workflow: C++ baseline → spec-level state machine + abstract trace → instrument both sides → port → prove observable equivalence by differential testing. |

`rust-hardening` and `rust-c-ffi-safety` are complementary: the FFI skill cross-references
the hardening skill, and the hardening skill points at the FFI skill for `unsafe`/FFI surfaces.

## Layout

```
skills/
  rust-hardening/
    SKILL.md                     # the guidance Claude loads
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
```

Each skill is self-contained in its own directory. `SKILL.md` is the entry point; everything
else is read only when the guidance references it.

## Using these skills

Make the skills discoverable to Claude Code by placing (or symlinking) them where it looks for
skills:

- **Per project:** copy a skill directory into the project's `.claude/skills/`.
- **All projects (user-level):** copy it into `~/.claude/skills/`.

For example:

```sh
mkdir -p ~/.claude/skills
cp -r skills/rust-hardening ~/.claude/skills/
```

Once installed, Claude invokes a skill automatically when a task matches its `description`, or
you can request it explicitly (e.g. "use the rust-hardening skill"). The skills are also useful
as standalone checklists for human reviewers.

## Contributing

When adding a skill, follow the existing conventions:

- One directory per skill under `skills/`, with a `SKILL.md` whose frontmatter has a `name`
  and an actionable, trigger-oriented `description` (state *when* to use it).
- Keep `SKILL.md` focused; move long examples, references, and scaffolding into
  `reference/`/`templates/` and link to them so they load only on demand.

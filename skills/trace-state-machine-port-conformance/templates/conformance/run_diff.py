#!/usr/bin/env python3
"""Fail-closed C++/Rust conformance and equivalence checking harness.

Each implementation receives:

* TRACE_OUT: JSON Lines semantic trace path
* SIDE_EFFECTS_OUT: canonical JSON side-effect manifest path
* RUN_ID: deterministic id for this implementation/case

The two implementations run in separate temporary working directories. The
equivalence contract controls trace, outcome, and side-effect comparison.

Usage:
    python run_diff.py \
        --cpp-bin build/original \
        --rust-bin target/debug/ported \
        --state-machine conformance/state_machine.yaml \
        --contract conformance/equivalence_contract.json \
        --cases conformance/corpus \
        --coverage-out conformance/coverage.json \
        --repro-dir conformance/repro
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import diff_trace

HERE = Path(__file__).resolve().parent


@dataclass
class ImplRun:
    impl: str
    workdir: Path
    stdout: bytes
    stderr: bytes
    returncode: int
    trace_path: Path
    side_effects_path: Path
    normalized_trace_path: Path | None = None


@dataclass
class CaseResult:
    case: Path
    ok: bool = True
    observed: set[str] = field(default_factory=set)
    ignored: dict[str, str] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    audit_failures: list[str] = field(default_factory=list)
    repro_path: Path | None = None

    def add_comparison(self, label, comparison):
        self.observed.update(comparison.observed)
        self.ignored.update(comparison.ignored)
        self.failures.extend(
            f"{label}: {message}" for message in comparison.mismatches
        )
        self.audit_failures.extend(
            f"{label}: {message}" for message in comparison.audit_failures
        )


def run_impl(binary, impl, input_path, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    trace_path = workdir / "trace.jsonl"
    side_effects_path = workdir / "side_effects.json"
    env = dict(
        os.environ,
        TRACE_OUT=str(trace_path),
        SIDE_EFFECTS_OUT=str(side_effects_path),
        RUN_ID=f"{impl}-{input_path.name}",
    )
    try:
        with open(input_path, "rb") as stdin:
            proc = subprocess.run(
                [str(binary)],
                stdin=stdin,
                env=env,
                capture_output=True,
                cwd=workdir,
                check=False,
            )
    except OSError as exc:
        raise diff_trace.InputError(
            f"cannot launch {impl} binary {binary}: {exc}"
        ) from exc
    return ImplRun(
        impl=impl,
        workdir=workdir,
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
        trace_path=trace_path,
        side_effects_path=side_effects_path,
    )


def normalize(run):
    if not run.trace_path.is_file():
        raise diff_trace.InputError(
            f"{run.impl}: TRACE_OUT was not created: {run.trace_path}"
        )
    output = run.workdir / "normalized_trace.jsonl"
    try:
        with open(output, "w", encoding="utf-8") as stdout:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "normalize_trace.py"),
                    str(run.trace_path),
                ],
                check=False,
                stdout=stdout,
                stderr=subprocess.PIPE,
                text=True,
            )
    except OSError as exc:
        raise diff_trace.InputError(
            f"{run.impl}: normalization failed to start: {exc}"
        ) from exc
    if proc.returncode != 0:
        raise diff_trace.InputError(
            f"{run.impl}: normalization failed: {proc.stderr.strip()}"
        )
    run.normalized_trace_path = output
    return output


def run_monitor(state_machine, normalized_trace):
    try:
        return subprocess.run(
            [
                sys.executable,
                str(HERE / "trace_monitor.py"),
                str(state_machine),
                str(normalized_trace),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise diff_trace.InputError(
            f"cannot run trace monitor: {exc}"
        ) from exc


def load_side_effects(contract, run):
    mode = contract["side_effects"]["mode"]
    if mode == "out_of_scope":
        if run.side_effects_path.exists():
            raise diff_trace.InputError(
                f"{run.impl}: side-effect manifest was emitted while the "
                "contract declares side effects out of scope"
            )
        return None
    if not run.side_effects_path.is_file():
        raise diff_trace.InputError(
            f"{run.impl}: SIDE_EFFECTS_OUT was not created: "
            f"{run.side_effects_path}"
        )
    return diff_trace.load_json(run.side_effects_path)


def _safe_case_name(case):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", case.name).strip(".-")
    if not safe:
        safe = "case"
    digest = hashlib.sha256(case.read_bytes()).hexdigest()[:12]
    return f"{safe}-{digest}"


def _copy_if_present(source, destination):
    if source is not None and source.is_file():
        shutil.copy2(source, destination)


def save_repro(repro_dir, case_result, cpp, rust, report):
    destination = repro_dir / _safe_case_name(case_result.case)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(case_result.case, destination / "input")

    for run in (cpp, rust):
        prefix = run.impl
        (destination / f"{prefix}.stdout").write_bytes(run.stdout)
        (destination / f"{prefix}.stderr").write_bytes(run.stderr)
        (destination / f"{prefix}.exit_code").write_text(
            f"{run.returncode}\n", encoding="utf-8"
        )
        _copy_if_present(
            run.trace_path, destination / f"{prefix}.trace.jsonl"
        )
        _copy_if_present(
            run.normalized_trace_path,
            destination / f"{prefix}.normalized.jsonl",
        )
        _copy_if_present(
            run.side_effects_path,
            destination / f"{prefix}.side_effects.json",
        )

    with open(destination / "report.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return destination


def save_input_repro(repro_dir, case, failure):
    destination = repro_dir / _safe_case_name(case)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(case, destination / "input")
    with open(destination / "report.json", "w", encoding="utf-8") as handle:
        json.dump(
            {"case": str(case), "failures": [failure]},
            handle,
            indent=2,
            sort_keys=True,
        )
        handle.write("\n")
    return destination


def _comparison_report(result):
    return {
        "mismatches": list(result.mismatches),
        "observed": sorted(result.observed),
        "ignored": dict(sorted(result.ignored.items())),
        "audit_failures": list(result.audit_failures),
    }


def check_case(args, contract, case):
    case_result = CaseResult(case=case)
    report = {"case": str(case), "checks": {}}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            cpp = run_impl(
                args.cpp_bin, "cpp", case, root / "cpp"
            )
            rust = run_impl(
                args.rust_bin, "rust", case, root / "rust"
            )
        except diff_trace.InputError as exc:
            case_result.ok = False
            case_result.failures.append(str(exc))
            case_result.repro_path = save_input_repro(
                args.repro_dir, case, str(exc)
            )
            print(
                f"[FAIL] {case}: {exc} "
                f"(repro: {case_result.repro_path})"
            )
            return case_result

        try:
            cpp_normalized = normalize(cpp)
            rust_normalized = normalize(rust)

            cpp_monitor = run_monitor(args.state_machine, cpp_normalized)
            rust_monitor = run_monitor(args.state_machine, rust_normalized)
            report["checks"]["cpp_state_machine"] = {
                "returncode": cpp_monitor.returncode,
                "stdout": cpp_monitor.stdout,
                "stderr": cpp_monitor.stderr,
            }
            report["checks"]["rust_state_machine"] = {
                "returncode": rust_monitor.returncode,
                "stdout": rust_monitor.stdout,
                "stderr": rust_monitor.stderr,
            }
            if cpp_monitor.returncode != 0:
                case_result.failures.append(
                    "C++ trace rejected by state machine: "
                    + (cpp_monitor.stderr or cpp_monitor.stdout).strip()
                )
            if rust_monitor.returncode != 0:
                case_result.failures.append(
                    "Rust trace rejected by state machine: "
                    + (rust_monitor.stderr or rust_monitor.stdout).strip()
                )

            cpp_events = diff_trace.read_trace(cpp_normalized)
            rust_events = diff_trace.read_trace(rust_normalized)
            trace_comparison = diff_trace.compare_traces(
                contract, cpp_events, rust_events
            )
            trace_comparison.audit_failures.extend(
                diff_trace.audit_trace(contract, cpp_events)
            )
            case_result.add_comparison("trace", trace_comparison)
            report["checks"]["trace"] = _comparison_report(trace_comparison)

            outcomes_cpp = {
                "stdout": cpp.stdout,
                "stderr": cpp.stderr,
                "exit_code": cpp.returncode,
            }
            outcomes_rust = {
                "stdout": rust.stdout,
                "stderr": rust.stderr,
                "exit_code": rust.returncode,
            }
            outcome_comparison = diff_trace.compare_outcomes(
                contract, outcomes_cpp, outcomes_rust
            )
            for name, value in outcomes_cpp.items():
                outcome_comparison.audit_failures.extend(
                    diff_trace.audit_value(
                        contract["outcomes"][name],
                        value,
                        f"outcomes.{name}",
                    )
                )
            case_result.add_comparison("outcomes", outcome_comparison)
            report["checks"]["outcomes"] = _comparison_report(
                outcome_comparison
            )

            cpp_side_effects = load_side_effects(contract, cpp)
            rust_side_effects = load_side_effects(contract, rust)
            side_effect_comparison = diff_trace.compare_side_effects(
                contract, cpp_side_effects, rust_side_effects
            )
            if contract["side_effects"]["mode"] == "manifest":
                side_effect_comparison.audit_failures.extend(
                    diff_trace.audit_value(
                        contract["side_effects"]["schema"],
                        cpp_side_effects,
                        "side_effects",
                    )
                )
            case_result.add_comparison(
                "side_effects", side_effect_comparison
            )
            report["checks"]["side_effects"] = _comparison_report(
                side_effect_comparison
            )
        except (diff_trace.ContractError, diff_trace.InputError) as exc:
            case_result.failures.append(str(exc))

        case_result.ok = not (
            case_result.failures or case_result.audit_failures
        )
        report["failures"] = list(case_result.failures)
        report["audit_failures"] = list(case_result.audit_failures)
        if not case_result.ok:
            case_result.repro_path = save_repro(
                args.repro_dir, case_result, cpp, rust, report
            )

    status = "PASS" if case_result.ok else "FAIL"
    suffix = (
        ""
        if case_result.repro_path is None
        else f" (repro: {case_result.repro_path})"
    )
    print(f"[{status}] {case}{suffix}")
    for failure in case_result.failures:
        print(f"  - {failure}")
    for failure in case_result.audit_failures:
        print(f"  - {failure}")
    return case_result


def _resolve_cases(path):
    if path.is_dir():
        return sorted(item.resolve() for item in path.iterdir() if item.is_file())
    if path.is_file():
        return [path.resolve()]
    raise diff_trace.InputError(f"cases path does not exist: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp-bin", required=True, type=Path)
    parser.add_argument("--rust-bin", required=True, type=Path)
    parser.add_argument("--state-machine", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument(
        "--cases", required=True, type=Path, help="input file or corpus directory"
    )
    parser.add_argument(
        "--coverage-out",
        type=Path,
        help="write aggregate semantic-field coverage as JSON",
    )
    parser.add_argument(
        "--repro-dir",
        type=Path,
        default=Path("conformance/repro"),
    )
    args = parser.parse_args(argv)

    args.cpp_bin = args.cpp_bin.resolve()
    args.rust_bin = args.rust_bin.resolve()
    args.state_machine = args.state_machine.resolve()
    args.contract = args.contract.resolve()
    args.cases = args.cases.resolve()
    args.repro_dir = args.repro_dir.resolve()
    if args.coverage_out is not None:
        args.coverage_out = args.coverage_out.resolve()

    try:
        contract = diff_trace.load_contract(args.contract)
        cases = _resolve_cases(args.cases)
        if not cases:
            raise diff_trace.InputError(f"no input cases found under {args.cases}")
        for binary, label in (
            (args.cpp_bin, "C++"),
            (args.rust_bin, "Rust"),
        ):
            if not binary.is_file():
                raise diff_trace.InputError(
                    f"{label} binary does not exist: {binary}"
                )
        if not args.state_machine.is_file():
            raise diff_trace.InputError(
                f"state machine does not exist: {args.state_machine}"
            )
    except (diff_trace.ContractError, diff_trace.InputError) as exc:
        print(f"configuration/input error: {exc}", file=sys.stderr)
        return 2

    results = [check_case(args, contract, case) for case in cases]
    observed = set().union(*(result.observed for result in results))
    coverage = diff_trace.coverage_summary(contract, observed, scope="all")
    if args.coverage_out is not None:
        args.coverage_out.parent.mkdir(parents=True, exist_ok=True)
        try:
            diff_trace.write_coverage(args.coverage_out, coverage)
        except diff_trace.InputError as exc:
            print(f"configuration/input error: {exc}", file=sys.stderr)
            return 2

    failures = sum(not result.ok for result in results)
    if coverage["missing"]:
        failures += 1
        print("[FAIL] contract coverage incomplete")
        for path in coverage["missing"]:
            print(f"  - never observed: {path}")

    passed = sum(result.ok for result in results)
    print(f"\n{passed}/{len(results)} cases passed")
    print(
        "contract coverage: "
        f"{len(set(coverage['observed']) & set(coverage['required']))}/"
        f"{len(coverage['required'])} semantic paths observed"
    )
    print(f"explicitly ignored paths: {len(coverage['ignored'])}")
    print(f"coverage waivers: {len(coverage['waived'])}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

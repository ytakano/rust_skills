#!/usr/bin/env python3
"""Differential test harness: run C++ and Rust on identical inputs and compare.

Template — copy into the target repo's verification/ and adapt to the real
commands, side-effect capture, and corpus layout. See
../../reference/differential-checks.md.

Each implementation must emit a JSON Lines trace to the path given by TRACE_OUT.

Usage:
    python run_diff.py \
        --cpp-bin build/original \
        --rust-bin target/debug/ported \
        --state-machine verification/state_machine.yaml \
        --cases verification/corpus
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_impl(binary, impl, input_path, workdir):
    """Run one implementation; return (stdout, stderr, returncode, trace_path)."""
    trace_path = workdir / f"{impl}.trace.jsonl"
    env = dict(os.environ, TRACE_OUT=str(trace_path), RUN_ID=f"{impl}-run")
    with open(input_path, "rb") as stdin:
        # Adapt argument passing to the real CLI contract.
        proc = subprocess.run([binary], stdin=stdin, env=env,
                              capture_output=True, cwd=workdir)
    return proc.stdout, proc.stderr, proc.returncode, trace_path


def normalize(raw_trace, workdir, impl):
    out = workdir / f"{impl}.norm.jsonl"
    with open(out, "w") as f:
        subprocess.run([sys.executable, str(HERE / "normalize_trace.py"),
                        str(raw_trace)], check=True, stdout=f)
    return out


def py(script, *args):
    return subprocess.run([sys.executable, str(HERE / script), *map(str, args)])


def verify_case(args, case):
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        out_cpp, err_cpp, rc_cpp, tr_cpp = run_impl(args.cpp_bin, "cpp", case, workdir)
        out_rs, err_rs, rc_rs, tr_rs = run_impl(args.rust_bin, "rust", case, workdir)

        norm_cpp = normalize(tr_cpp, workdir, "cpp")
        norm_rs = normalize(tr_rs, workdir, "rust")

        ok = True
        ok &= py("trace_monitor.py", args.state_machine, norm_cpp).returncode == 0
        ok &= py("trace_monitor.py", args.state_machine, norm_rs).returncode == 0
        ok &= py("diff_trace.py", norm_cpp, norm_rs).returncode == 0
        ok &= (out_cpp == out_rs)
        ok &= (rc_cpp == rc_rs)
        # TODO: compare captured side effects (files/db/network) here.

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case}")
        if not ok:
            # TODO: persist a repro under verification/repro/<issue-name>/.
            pass
        return ok


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cpp-bin", required=True)
    p.add_argument("--rust-bin", required=True)
    p.add_argument("--state-machine", required=True)
    p.add_argument("--cases", required=True, help="file or directory of input cases")
    args = p.parse_args()

    cases_path = Path(args.cases)
    cases = sorted(cases_path.iterdir()) if cases_path.is_dir() else [cases_path]

    failures = sum(0 if verify_case(args, c) else 1 for c in cases)
    print(f"\n{len(cases) - failures}/{len(cases)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

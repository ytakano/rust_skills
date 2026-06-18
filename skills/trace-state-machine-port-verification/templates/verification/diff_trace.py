#!/usr/bin/env python3
"""Compare two normalized JSON Lines traces for spec-level equivalence.

Template — copy into the target repo's verification/ and adapt.
See ../../reference/differential-checks.md.

Usage:
    python diff_trace.py normalized_cpp.jsonl normalized_rust.jsonl

Exit code 0 = equivalent, 1 = mismatch, 2 = usage error.

For non-concurrent programs a normalized event-sequence comparison is usually enough.
For concurrent/async programs, replace `compare` with per-session / per-resource /
happens-before comparison — do NOT use naive total-order equality.
"""
import json
import sys

# Fields that identify an event for comparison. `impl`, `run_id` and raw `seq`
# are intentionally excluded (they differ by construction).
KEY_FIELDS = ("component", "event", "params", "session", "resource", "task")


def read(path):
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def key(ev):
    return tuple(json.dumps(ev.get(f), sort_keys=True) for f in KEY_FIELDS)


def compare(a, b):
    mismatches = []
    for i in range(max(len(a), len(b))):
        ka = key(a[i]) if i < len(a) else None
        kb = key(b[i]) if i < len(b) else None
        if ka != kb:
            mismatches.append((i, a[i] if i < len(a) else None,
                               b[i] if i < len(b) else None))
    return mismatches


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: diff_trace.py normalized_cpp.jsonl normalized_rust.jsonl")
    cpp, rust = read(argv[1]), read(argv[2])
    mismatches = compare(cpp, rust)
    if not mismatches:
        print(f"Traces equivalent ({len(cpp)} events)")
        return 0
    print("Trace mismatch")
    for idx, ce, re in mismatches:
        print(f"  event index: {idx}")
        print(f"    cpp:  {json.dumps(ce)}")
        print(f"    rust: {json.dumps(re)}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

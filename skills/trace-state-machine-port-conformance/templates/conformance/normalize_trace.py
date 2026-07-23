#!/usr/bin/env python3
"""Normalize a JSON Lines trace into a comparable canonical form.

Template — copy into the target repo's conformance/ and adapt the rules.
See ../../reference/normalization.md.

Normalization removes NOISE only. It must never erase a meaningful spec difference
(a missing close, a different outcome, commit vs rollback, ...), and it must
never round floating-point values. Numeric tolerances belong exclusively in
equivalence_contract.json and diff_trace.py.

Usage:
    python normalize_trace.py raw.trace.jsonl > normalized.jsonl
"""
import json
import sys

# Map each implementation's native error representation to a shared code.
# An unmapped error must fail loudly (see below) — never silently pass through.
ERROR_CODE_MAP = {
    ("cpp", "2"): "not_found",
    ("rust", "NotFound"): "not_found",
}

# Fields that are pure noise and should be dropped before comparison.
DROP_FIELDS = {"ts", "timestamp", "ptr", "addr", "thread_name"}

# Params that carry nondeterministic ids to be stabilized per scope.
ID_PARAMS = ("session", "resource", "tx", "task")


def reject_nonstandard_constant(value):
    raise ValueError(
        f"non-standard JSON number {value!r}; encode as "
        '"nan", "+inf", or "-inf"'
    )


def normalize_error(impl, params):
    if "code" in params:
        return params  # already a shared code
    raw = params.get("errno") or params.get("kind")
    if raw is None:
        return params
    key = (impl, str(raw))
    if key not in ERROR_CODE_MAP:
        sys.exit(f"unmapped error {key!r}; add it to ERROR_CODE_MAP")
    out = {k: v for k, v in params.items() if k not in ("errno", "kind")}
    out["code"] = ERROR_CODE_MAP[key]
    return out


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: normalize_trace.py raw.trace.jsonl")

    id_maps = {scope: {} for scope in ID_PARAMS}  # scope -> {raw_id: stable_id}
    seq = 0
    for line in open(argv[1]):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(
                line, parse_constant=reject_nonstandard_constant
            )
        except (json.JSONDecodeError, ValueError) as exc:
            sys.exit(f"{argv[1]}:{seq + 1}: invalid JSON event: {exc}")
        if not isinstance(ev, dict):
            sys.exit(f"{argv[1]}:{seq + 1}: event must be a JSON object")

        for f in DROP_FIELDS:
            ev.pop(f, None)

        impl = ev.get("impl", "")
        params = dict(ev.get("params", {}))
        if ev.get("event") == "ErrorRaised":
            params = normalize_error(impl, params)

        # Stabilize nondeterministic ids in first-appearance order, per scope.
        for scope in ID_PARAMS:
            for holder in (ev, params):
                if scope in holder:
                    m = id_maps[scope]
                    raw = holder[scope]
                    if raw not in m:
                        m[raw] = f"{scope[:1].upper()}{len(m) + 1}"
                    holder[scope] = m[raw]

        ev["params"] = params
        seq += 1
        ev["seq"] = seq  # re-sequence after dropping non-semantic events
        # Keep `impl`; the contract accounts for it as an explicit, reasoned ignore.
        try:
            encoded = json.dumps(ev, sort_keys=True, allow_nan=False)
        except ValueError as exc:
            sys.exit(
                f"{argv[1]}:{seq}: non-finite numeric value: {exc}; "
                'encode as "nan", "+inf", or "-inf"'
            )
        sys.stdout.write(encoded + "\n")


if __name__ == "__main__":
    main(sys.argv)

#!/usr/bin/env python3
"""Validate a normalized JSON Lines trace against a YAML state machine.

Template — copy into the target repo's conformance/ and adapt.
See ../../reference/state-machine-format.md.

Usage:
    python trace_monitor.py state_machine.yaml trace.jsonl

Exit code 0 = accepted, 1 = rejected, 2 = usage/load error.
Guards are evaluated as Python expressions over a `params` dict; keep them simple
(e.g. "params.get('bytes', 0) >= 0"). Replace eval with a real expression parser
if guards become untrusted input.
"""
import json
import sys


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML required: pip install pyyaml")
    with open(path) as f:
        return yaml.safe_load(f)


def read_trace(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def as_list(x):
    return x if isinstance(x, list) else [x]


def check_guard(guard, params):
    if not guard:
        return True
    try:
        return bool(eval(guard, {"__builtins__": {}}, {"params": params}))
    except Exception as e:
        raise RuntimeError(f"guard error {guard!r}: {e}")


def reject(input_path, idx, state, event, reason):
    print("Trace rejected")
    print(f"  input: {input_path}")
    print(f"  event index: {idx}")
    print(f"  current state: {state}")
    print(f"  event: {event}")
    print(f"  reason: {reason}")
    return 1


def run(sm, events, input_path):
    state = sm["initial"]
    terminal = set(sm.get("terminal", []))
    accepting = set(sm.get("accepting", []))
    transitions = sm.get("transitions", [])
    forbidden = sm.get("forbidden", [])

    for idx, ev in enumerate(events):
        name = ev.get("event")
        params = ev.get("params", {})

        for fb in forbidden:
            if state in as_list(fb["state"]) and name == fb["event"]:
                return reject(input_path, idx, state, name, fb.get("reason", "forbidden"))

        if state in terminal:
            return reject(input_path, idx, state, name,
                          f"no events allowed after terminal state {state}")

        match = None
        for t in transitions:
            if state in as_list(t["from"]) and t["event"] == name:
                if check_guard(t.get("guard"), params):
                    match = t
                    break
        if match is None:
            return reject(input_path, idx, state, name,
                          f"no allowed transition from {state} on {name}")
        state = match["to"]

    if accepting and state not in accepting:
        return reject(input_path, len(events), state, "<end>",
                      f"run ended in non-accepting state {state}")
    print(f"Trace accepted (final state: {state})")
    return 0


def main(argv):
    if len(argv) != 3:
        sys.exit("usage: trace_monitor.py state_machine.yaml trace.jsonl")
    sm = load_yaml(argv[1])
    events = read_trace(argv[2])
    return run(sm, events, argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))

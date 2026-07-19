#!/usr/bin/env python3
"""Fail-closed comparison of normalized C++ and Rust JSON Lines traces.

The equivalence contract is the single machine-readable source of truth. Every
semantic scalar must have a comparison policy; unknown events/fields, missing
required fields, invalid types, and unconfigured values are errors.

Usage:
    python diff_trace.py \
        --contract equivalence_contract.json \
        --audit \
        --coverage-out coverage.json \
        normalized_cpp.jsonl normalized_rust.jsonl

Exit code 0 = equivalent, 1 = mismatch/audit/coverage failure,
exit code 2 = invalid usage, contract, or input.

The template implements exact total-order event comparison. Concurrent targets
must replace that ordering relation with a documented and tested per-scope or
happens-before comparator; they must not silently weaken this comparator.
"""

import argparse
import copy
import json
import math
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

SPECIAL_FLOATS = {"nan", "+inf", "-inf"}
SCALAR_TYPES = {"string", "integer", "float", "boolean", "null", "bytes"}
COMPARE_KINDS = {"exact", "abs_rel", "ulp", "bit_exact", "ignore"}


class ContractError(ValueError):
    """The equivalence contract is incomplete or invalid."""


class InputError(ValueError):
    """A trace or side-effect manifest is malformed."""


@dataclass
class ComparisonResult:
    mismatches: list[str] = field(default_factory=list)
    observed: set[str] = field(default_factory=set)
    ignored: dict[str, str] = field(default_factory=dict)
    audit_failures: list[str] = field(default_factory=list)

    @property
    def equivalent(self):
        return not self.mismatches and not self.audit_failures

    def merge(self, other):
        self.mismatches.extend(other.mismatches)
        self.observed.update(other.observed)
        self.ignored.update(other.ignored)
        self.audit_failures.extend(other.audit_failures)


def _reject_nonstandard_constant(value):
    raise ValueError(
        f"non-standard JSON number {value!r}; encode as "
        '"nan", "+inf", or "-inf"'
    )


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle, parse_constant=_reject_nonstandard_constant)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"cannot load JSON {path}: {exc}") from exc


def read_trace(path):
    events = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    event = json.loads(
                        stripped, parse_constant=_reject_nonstandard_constant
                    )
                except (json.JSONDecodeError, ValueError) as exc:
                    raise InputError(
                        f"{path}:{line_number}: invalid JSON event: {exc}"
                    ) from exc
                if not isinstance(event, dict):
                    raise InputError(
                        f"{path}:{line_number}: event must be a JSON object"
                    )
                events.append(event)
    except OSError as exc:
        raise InputError(f"cannot read trace {path}: {exc}") from exc
    return events


def _expect_keys(value, required, allowed, path):
    if not isinstance(value, dict):
        raise ContractError(f"{path}: must be an object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ContractError(f"{path}: missing keys {missing}")
    if unknown:
        raise ContractError(f"{path}: unknown keys {unknown}")


def _nonempty_reason(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path}: a non-empty reason is required")


def _validate_compare(compare, value_type, path):
    if not isinstance(compare, dict):
        raise ContractError(f"{path}: compare must be an object")
    kind = compare.get("kind")
    if kind not in COMPARE_KINDS:
        raise ContractError(f"{path}.kind: unsupported comparison {kind!r}")

    if kind == "ignore":
        _expect_keys(compare, {"kind", "reason"}, {"kind", "reason"}, path)
        _nonempty_reason(compare["reason"], f"{path}.reason")
        return

    if value_type == "float":
        if kind == "exact":
            raise ContractError(
                f"{path}: float fields must use abs_rel, ulp, or bit_exact "
                "and declare special-value policies"
            )
        common_required = {"kind", "nan", "infinity", "signed_zero"}
        common_allowed = set(common_required)
        if compare.get("nan") not in {"reject", "both_equal"}:
            raise ContractError(f"{path}.nan: use 'reject' or 'both_equal'")
        if compare.get("infinity") not in {"reject", "same_sign"}:
            raise ContractError(
                f"{path}.infinity: use 'reject' or 'same_sign'"
            )
        if compare.get("signed_zero") not in {"equal", "distinct"}:
            raise ContractError(
                f"{path}.signed_zero: use 'equal' or 'distinct'"
            )

        if kind == "abs_rel":
            required = common_required | {"abs_tol", "rel_tol"}
            allowed = common_allowed | {"abs_tol", "rel_tol"}
            _expect_keys(compare, required, allowed, path)
            for name in ("abs_tol", "rel_tol"):
                tolerance = compare[name]
                if (
                    isinstance(tolerance, bool)
                    or not isinstance(tolerance, (int, float))
                    or not math.isfinite(tolerance)
                    or tolerance < 0
                ):
                    raise ContractError(
                        f"{path}.{name}: must be a finite non-negative number"
                    )
            return

        required = common_required | {"precision"}
        allowed = common_allowed | {"precision"}
        if compare.get("precision") not in {"f32", "f64"}:
            raise ContractError(f"{path}.precision: use 'f32' or 'f64'")
        if kind == "ulp":
            required.add("max_ulps")
            allowed.add("max_ulps")
            max_ulps = compare.get("max_ulps")
            if (
                isinstance(max_ulps, bool)
                or not isinstance(max_ulps, int)
                or max_ulps < 0
            ):
                raise ContractError(
                    f"{path}.max_ulps: must be a non-negative integer"
                )
        _expect_keys(compare, required, allowed, path)
        return

    if kind != "exact":
        raise ContractError(
            f"{path}: {kind!r} is only valid for float fields"
        )
    _expect_keys(compare, {"kind"}, {"kind"}, path)


def validate_schema(schema, path="$schema", allow_event_params=False):
    if not isinstance(schema, dict):
        raise ContractError(f"{path}: schema must be an object")
    value_type = schema.get("type")
    allowed_types = SCALAR_TYPES | {"object", "array"}
    if allow_event_params:
        allowed_types.add("event_params")
    if value_type not in allowed_types:
        raise ContractError(f"{path}.type: unsupported type {value_type!r}")

    if value_type not in SCALAR_TYPES and (
        "coverage" in schema or "coverage_reason" in schema
    ):
        raise ContractError(
            f"{path}: declare coverage on scalar leaves, not containers"
        )
    common = {"type", "coverage", "coverage_reason"}
    coverage = schema.get("coverage", "required")
    if coverage not in {"required", "waived"}:
        raise ContractError(
            f"{path}.coverage: use 'required' or 'waived'"
        )
    if coverage == "waived":
        _nonempty_reason(
            schema.get("coverage_reason"), f"{path}.coverage_reason"
        )
    elif "coverage_reason" in schema:
        raise ContractError(
            f"{path}.coverage_reason: only valid when coverage is waived"
        )

    if value_type in SCALAR_TYPES:
        allowed = common | {"compare"}
        _expect_keys(schema, {"type", "compare"}, allowed, path)
        _validate_compare(schema["compare"], value_type, f"{path}.compare")
        if schema["compare"]["kind"] == "ignore" and "coverage" in schema:
            raise ContractError(
                f"{path}: ignored fields must not declare coverage"
            )
        return

    if value_type == "event_params":
        _expect_keys(schema, {"type"}, {"type"}, path)
        return

    if value_type == "array":
        allowed = common | {"items"}
        _expect_keys(schema, {"type", "items"}, allowed, path)
        validate_schema(
            schema["items"], f"{path}.items", allow_event_params=False
        )
        return

    allowed = common | {"required", "properties", "additional_properties"}
    _expect_keys(
        schema,
        {"type", "required", "properties", "additional_properties"},
        allowed,
        path,
    )
    if not isinstance(schema["properties"], dict):
        raise ContractError(f"{path}.properties: must be an object")
    required = schema["required"]
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in required
    ):
        raise ContractError(f"{path}.required: must be a list of strings")
    if len(required) != len(set(required)):
        raise ContractError(f"{path}.required: contains duplicates")
    unknown_required = sorted(set(required) - set(schema["properties"]))
    if unknown_required:
        raise ContractError(
            f"{path}.required: unknown properties {unknown_required}"
        )
    additional = schema["additional_properties"]
    if additional is True:
        raise ContractError(
            f"{path}.additional_properties: true is not fail-closed; "
            "use false or a schema"
        )
    if additional is not False and not isinstance(additional, dict):
        raise ContractError(
            f"{path}.additional_properties: use false or a schema"
        )
    for name, child in schema["properties"].items():
        if not isinstance(name, str):
            raise ContractError(f"{path}.properties: keys must be strings")
        validate_schema(
            child,
            f"{path}.properties.{name}",
            allow_event_params=allow_event_params and name == "params",
        )
    if isinstance(additional, dict):
        validate_schema(
            additional,
            f"{path}.additional_properties",
            allow_event_params=False,
        )


def validate_contract(contract):
    _expect_keys(
        contract,
        {"version", "trace", "outcomes", "side_effects"},
        {"version", "trace", "outcomes", "side_effects"},
        "$contract",
    )
    if contract["version"] != 1:
        raise ContractError("$contract.version: only version 1 is supported")

    trace = contract["trace"]
    _expect_keys(
        trace,
        {"ordering", "event_schema", "events"},
        {"ordering", "event_schema", "events"},
        "$contract.trace",
    )
    if trace["ordering"] != "total":
        raise ContractError(
            "$contract.trace.ordering: this template implements only "
            "'total'; implement and test a target-specific comparator for "
            "per-scope or happens-before ordering"
        )
    validate_schema(
        trace["event_schema"],
        "$contract.trace.event_schema",
        allow_event_params=True,
    )
    event_schema = trace["event_schema"]
    if event_schema.get("type") != "object":
        raise ContractError(
            "$contract.trace.event_schema: must be an object schema"
        )
    properties = event_schema["properties"]
    params_schema = properties.get("params")
    if params_schema != {"type": "event_params"}:
        raise ContractError(
            "$contract.trace.event_schema.properties.params: must be "
            '{"type": "event_params"}'
        )
    if "event" not in properties:
        raise ContractError(
            "$contract.trace.event_schema: must declare the event field"
        )
    events = trace["events"]
    if not isinstance(events, dict) or not events:
        raise ContractError("$contract.trace.events: must be a non-empty object")
    for name, event in events.items():
        if not isinstance(name, str) or not name:
            raise ContractError(
                "$contract.trace.events: event names must be non-empty strings"
            )
        _expect_keys(
            event,
            {"description", "params"},
            {"description", "params", "coverage", "coverage_reason"},
            f"$contract.trace.events.{name}",
        )
        _nonempty_reason(
            event["description"],
            f"$contract.trace.events.{name}.description",
        )
        event_coverage = event.get("coverage", "required")
        if event_coverage not in {"required", "waived"}:
            raise ContractError(
                f"$contract.trace.events.{name}.coverage: use "
                "'required' or 'waived'"
            )
        if event_coverage == "waived":
            _nonempty_reason(
                event.get("coverage_reason"),
                f"$contract.trace.events.{name}.coverage_reason",
            )
        elif "coverage_reason" in event:
            raise ContractError(
                f"$contract.trace.events.{name}.coverage_reason: only "
                "valid when coverage is waived"
            )
        validate_schema(
            event["params"],
            f"$contract.trace.events.{name}.params",
            allow_event_params=False,
        )
        if event["params"].get("type") != "object":
            raise ContractError(
                f"$contract.trace.events.{name}.params: must be an object schema"
            )

    outcomes = contract["outcomes"]
    _expect_keys(
        outcomes,
        {"stdout", "stderr", "exit_code"},
        {"stdout", "stderr", "exit_code"},
        "$contract.outcomes",
    )
    for name, schema in outcomes.items():
        validate_schema(schema, f"$contract.outcomes.{name}")

    side_effects = contract["side_effects"]
    if not isinstance(side_effects, dict):
        raise ContractError("$contract.side_effects: must be an object")
    mode = side_effects.get("mode")
    if mode == "out_of_scope":
        _expect_keys(
            side_effects,
            {"mode", "reason"},
            {"mode", "reason"},
            "$contract.side_effects",
        )
        _nonempty_reason(
            side_effects["reason"], "$contract.side_effects.reason"
        )
    elif mode == "manifest":
        _expect_keys(
            side_effects,
            {"mode", "schema"},
            {"mode", "schema"},
            "$contract.side_effects",
        )
        validate_schema(
            side_effects["schema"], "$contract.side_effects.schema"
        )
    else:
        raise ContractError(
            "$contract.side_effects.mode: use 'manifest' or "
            "'out_of_scope' with a reason"
        )
    return contract


def load_contract(path):
    contract = load_json(path)
    if not isinstance(contract, dict):
        raise ContractError("$contract: root must be an object")
    return validate_contract(contract)


def _is_float_value(value):
    return (type(value) is float and math.isfinite(value)) or (
        isinstance(value, str) and value in SPECIAL_FLOATS
    )


def validate_value(schema, value, path, event_params_schema=None):
    issues = []
    value_type = schema["type"]
    compare = schema.get("compare", {})
    ignored = compare.get("kind") == "ignore"

    valid_type = False
    if value_type == "string":
        valid_type = isinstance(value, str)
    elif value_type == "integer":
        valid_type = type(value) is int
    elif value_type == "float":
        valid_type = _is_float_value(value)
    elif value_type == "boolean":
        valid_type = type(value) is bool
    elif value_type == "null":
        valid_type = value is None
    elif value_type == "bytes":
        valid_type = isinstance(value, bytes)
    elif value_type in {"object", "event_params"}:
        valid_type = isinstance(value, dict)
    elif value_type == "array":
        valid_type = isinstance(value, list)

    if not valid_type:
        issues.append(
            f"{path}: expected {value_type}, got {type(value).__name__}"
        )
        return issues
    if ignored:
        return issues

    if value_type == "event_params":
        if event_params_schema is None:
            issues.append(f"{path}: no event params schema selected")
            return issues
        return validate_value(event_params_schema, value, path)

    if value_type == "object":
        required = set(schema["required"])
        properties = schema["properties"]
        additional = schema["additional_properties"]
        missing = sorted(required - set(value))
        if missing:
            issues.append(f"{path}: missing required fields {missing}")
        for name, child_value in value.items():
            child_schema = properties.get(name)
            if child_schema is None:
                if additional is False:
                    issues.append(f"{path}: unknown field {name!r}")
                    continue
                child_schema = additional
            issues.extend(
                validate_value(
                    child_schema,
                    child_value,
                    f"{path}.{name}",
                    event_params_schema,
                )
            )
    elif value_type == "array":
        for index, child_value in enumerate(value):
            issues.extend(
                validate_value(
                    schema["items"],
                    child_value,
                    f"{path}[{index}]",
                    event_params_schema,
                )
            )
    return issues


def _float_class(value):
    if isinstance(value, str):
        return value
    if value == 0.0:
        return "-zero" if math.copysign(1.0, value) < 0 else "+zero"
    return "finite"


def _special_float_mismatch(compare, left, right):
    left_class = _float_class(left)
    right_class = _float_class(right)

    if left_class == "nan" or right_class == "nan":
        if (
            left_class == right_class == "nan"
            and compare["nan"] == "both_equal"
        ):
            return None
        return f"NaN policy {compare['nan']!r} rejects {left!r} vs {right!r}"

    infinity_classes = {"+inf", "-inf"}
    if left_class in infinity_classes or right_class in infinity_classes:
        if (
            left_class == right_class
            and compare["infinity"] == "same_sign"
        ):
            return None
        return (
            f"infinity policy {compare['infinity']!r} rejects "
            f"{left!r} vs {right!r}"
        )

    zero_classes = {"+zero", "-zero"}
    if left_class in zero_classes and right_class in zero_classes:
        if compare["signed_zero"] == "equal" or left_class == right_class:
            return None
        return f"signed zero differs: {left_class} vs {right_class}"

    if left_class in zero_classes:
        left_class = "finite"
    if right_class in zero_classes:
        right_class = "finite"
    if left_class != "finite" or right_class != "finite":
        return f"float classes differ: {left_class} vs {right_class}"
    return False


def _float_bytes(value, precision):
    try:
        return struct.pack(">f" if precision == "f32" else ">d", value)
    except (OverflowError, struct.error) as exc:
        raise ValueError(
            f"{value!r} is not representable as {precision}"
        ) from exc


def _ordered_float_bits(value, precision):
    packed = _float_bytes(value, precision)
    if precision == "f32":
        bits = struct.unpack(">I", packed)[0]
        sign = 1 << 31
        mask = (1 << 32) - 1
    else:
        bits = struct.unpack(">Q", packed)[0]
        sign = 1 << 63
        mask = (1 << 64) - 1
    return ((~bits) & mask) if bits & sign else (bits | sign)


def compare_float(compare, left, right):
    special = _special_float_mismatch(compare, left, right)
    if special is None:
        return None
    if special is not False:
        return special

    kind = compare["kind"]
    if kind == "abs_rel":
        difference = abs(left - right)
        limit = max(
            float(compare["abs_tol"]),
            float(compare["rel_tol"]) * max(abs(left), abs(right)),
        )
        if difference <= limit:
            return None
        return f"difference {difference!r} exceeds abs/rel limit {limit!r}"

    precision = compare["precision"]
    if kind == "bit_exact":
        try:
            if _float_bytes(left, precision) == _float_bytes(right, precision):
                return None
        except ValueError as exc:
            return str(exc)
        return f"{precision} bit patterns differ"

    try:
        distance = abs(
            _ordered_float_bits(left, precision)
            - _ordered_float_bits(right, precision)
        )
    except ValueError as exc:
        return str(exc)
    if distance <= compare["max_ulps"]:
        return None
    return (
        f"ULP distance {distance} exceeds max_ulps "
        f"{compare['max_ulps']} ({precision})"
    )


def _schema_child(schema, name):
    child = schema["properties"].get(name)
    if child is not None:
        return child
    additional = schema["additional_properties"]
    return None if additional is False else additional


def compare_value(
    schema,
    left,
    right,
    path,
    schema_path,
    result,
    event_params_schema=None,
    event_params_schema_path=None,
):
    left_issues = validate_value(
        schema, left, f"cpp:{path}", event_params_schema
    )
    right_issues = validate_value(
        schema, right, f"rust:{path}", event_params_schema
    )
    result.mismatches.extend(left_issues)
    result.mismatches.extend(right_issues)
    if left_issues or right_issues:
        return

    compare = schema.get("compare")
    if compare and compare["kind"] == "ignore":
        result.ignored[schema_path] = compare["reason"]
        return

    value_type = schema["type"]
    if value_type == "event_params":
        compare_value(
            event_params_schema,
            left,
            right,
            path,
            event_params_schema_path or schema_path,
            result,
        )
        return

    if value_type == "object":
        keys = set(left) | set(right)
        for name in sorted(keys):
            child_schema = _schema_child(schema, name)
            if child_schema is None:
                # Validation already reports unknown keys.
                continue
            child_schema_path = (
                f"{schema_path}.{name}"
                if name in schema["properties"]
                else f"{schema_path}.*"
            )
            if name not in left or name not in right:
                child_compare = child_schema.get("compare", {})
                if child_compare.get("kind") != "ignore":
                    missing_side = "cpp" if name not in left else "rust"
                    result.mismatches.append(
                        f"{path}.{name}: field missing from {missing_side}"
                    )
                else:
                    result.ignored[child_schema_path] = child_compare["reason"]
                continue
            compare_value(
                child_schema,
                left[name],
                right[name],
                f"{path}.{name}",
                child_schema_path,
                result,
                event_params_schema=event_params_schema,
                event_params_schema_path=event_params_schema_path,
            )
        return

    if value_type == "array":
        if len(left) != len(right):
            result.mismatches.append(
                f"{path}: array length differs: {len(left)} vs {len(right)}"
            )
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            compare_value(
                schema["items"],
                left_item,
                right_item,
                f"{path}[{index}]",
                f"{schema_path}[*]",
                result,
                event_params_schema=event_params_schema,
                event_params_schema_path=event_params_schema_path,
            )
        return

    result.observed.add(schema_path)
    kind = compare["kind"]
    if value_type == "float":
        mismatch = compare_float(compare, left, right)
        if mismatch is not None:
            result.mismatches.append(
                f"{path}: float mismatch ({mismatch}); "
                f"cpp={left!r}, rust={right!r}"
            )
    elif kind == "exact" and left != right:
        result.mismatches.append(
            f"{path}: exact mismatch: cpp={left!r}, rust={right!r}"
        )


def _event_params_schema(contract, event_name):
    event = contract["trace"]["events"].get(event_name)
    return None if event is None else event["params"]


def _validate_event(contract, event, index, impl):
    name = event.get("event")
    if not isinstance(name, str):
        return [f"{impl}:trace[{index}].event: must be a string"]
    params_schema = _event_params_schema(contract, name)
    if params_schema is None:
        return [f"{impl}:trace[{index}]: unknown event {name!r}"]
    return validate_value(
        contract["trace"]["event_schema"],
        event,
        f"{impl}:trace[{index}]",
        params_schema,
    )


def compare_traces(contract, cpp_events, rust_events):
    result = ComparisonResult()
    for index, event in enumerate(cpp_events):
        result.mismatches.extend(_validate_event(contract, event, index, "cpp"))
    for index, event in enumerate(rust_events):
        result.mismatches.extend(
            _validate_event(contract, event, index, "rust")
        )

    if len(cpp_events) != len(rust_events):
        result.mismatches.append(
            "trace length differs: "
            f"cpp={len(cpp_events)}, rust={len(rust_events)}"
        )

    event_schema = contract["trace"]["event_schema"]
    for index, (cpp_event, rust_event) in enumerate(
        zip(cpp_events, rust_events)
    ):
        cpp_name = cpp_event.get("event")
        rust_name = rust_event.get("event")
        if cpp_name != rust_name:
            result.mismatches.append(
                f"trace[{index}].event: cpp={cpp_name!r}, rust={rust_name!r}"
            )
            continue
        params_schema = _event_params_schema(contract, cpp_name)
        if params_schema is None:
            continue
        result.observed.add(f"trace.events.{cpp_name}")
        compare_value(
            event_schema,
            cpp_event,
            rust_event,
            f"trace[{index}]",
            "trace.common",
            result,
            params_schema,
            f"trace.events.{cpp_name}.params",
        )
    return result


def compare_outcomes(contract, cpp, rust):
    result = ComparisonResult()
    for name in ("stdout", "stderr", "exit_code"):
        compare_value(
            contract["outcomes"][name],
            cpp[name],
            rust[name],
            f"outcomes.{name}",
            f"outcomes.{name}",
            result,
        )
    return result


def compare_side_effects(contract, cpp_manifest, rust_manifest):
    result = ComparisonResult()
    side_effects = contract["side_effects"]
    if side_effects["mode"] == "out_of_scope":
        result.ignored["side_effects"] = side_effects["reason"]
        return result
    compare_value(
        side_effects["schema"],
        cpp_manifest,
        rust_manifest,
        "side_effects",
        "side_effects",
        result,
    )
    return result


def _walk_declared(schema, path, required, waived, ignored):
    compare = schema.get("compare")
    if compare and compare["kind"] == "ignore":
        ignored[path] = compare["reason"]
        return
    value_type = schema["type"]
    if value_type in SCALAR_TYPES:
        if schema.get("coverage", "required") == "waived":
            waived[path] = schema["coverage_reason"]
        else:
            required.add(path)
        return
    if value_type == "array":
        _walk_declared(
            schema["items"], f"{path}[*]", required, waived, ignored
        )
        return
    if value_type == "object":
        for name, child in schema["properties"].items():
            _walk_declared(
                child, f"{path}.{name}", required, waived, ignored
            )
        additional = schema["additional_properties"]
        if isinstance(additional, dict):
            _walk_declared(
                additional, f"{path}.*", required, waived, ignored
            )


def declared_coverage(contract, scope="all"):
    required = set()
    waived = {}
    ignored = {}
    if scope in {"trace", "all"}:
        event_schema = contract["trace"]["event_schema"]
        for name, child in event_schema["properties"].items():
            if name != "params":
                _walk_declared(
                    child,
                    f"trace.common.{name}",
                    required,
                    waived,
                    ignored,
                )
        for event_name, event in contract["trace"]["events"].items():
            event_path = f"trace.events.{event_name}"
            if event.get("coverage", "required") == "waived":
                waived[event_path] = event["coverage_reason"]
            else:
                required.add(event_path)
            _walk_declared(
                event["params"],
                f"trace.events.{event_name}.params",
                required,
                waived,
                ignored,
            )
    if scope in {"outcomes", "all"}:
        for name, schema in contract["outcomes"].items():
            _walk_declared(
                schema,
                f"outcomes.{name}",
                required,
                waived,
                ignored,
            )
    if scope in {"side_effects", "all"}:
        side_effects = contract["side_effects"]
        if side_effects["mode"] == "out_of_scope":
            ignored["side_effects"] = side_effects["reason"]
        else:
            _walk_declared(
                side_effects["schema"],
                "side_effects",
                required,
                waived,
                ignored,
            )
    return required, waived, ignored


def coverage_summary(contract, observed, scope="all"):
    required, waived, ignored = declared_coverage(contract, scope)
    return {
        "required": sorted(required),
        "observed": sorted(observed),
        "missing": sorted(required - set(observed)),
        "waived": dict(sorted(waived.items())),
        "ignored": dict(sorted(ignored.items())),
    }


def write_coverage(path, summary):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        raise InputError(f"cannot write coverage {path}: {exc}") from exc


def _get_at(value, value_path):
    current = value
    for part in value_path:
        current = current[part]
    return current


def _set_at(value, value_path, replacement):
    current = value
    for part in value_path[:-1]:
        current = current[part]
    current[value_path[-1]] = replacement


def _delete_at(value, value_path):
    current = value
    for part in value_path[:-1]:
        current = current[part]
    last = value_path[-1]
    if isinstance(last, int):
        current.pop(last)
    else:
        del current[last]


def _mutated_scalar(schema, value):
    value_type = schema["type"]
    if value_type == "string":
        return value + "__audit_mutation__"
    if value_type == "integer":
        return value + 1
    if value_type == "float":
        return "+inf" if type(value) is float else 0.0
    if value_type == "boolean":
        return not value
    if value_type == "bytes":
        return value + b"\x00"
    if value_type == "null":
        return 0
    return None


def _sample_value(schema):
    compare = schema.get("compare")
    value_type = schema["type"]
    if value_type == "string":
        return "__audit_value__"
    if value_type == "integer":
        return 0
    if value_type == "float":
        return 0.0
    if value_type == "boolean":
        return False
    if value_type == "null":
        return None
    if value_type == "bytes":
        return b""
    if compare and compare["kind"] == "ignore":
        raise ValueError("ignored schema has no structural sample")
    if value_type == "array":
        return []
    if value_type == "object":
        return {
            name: _sample_value(schema["properties"][name])
            for name in schema["required"]
        }
    raise ValueError(f"cannot synthesize audit value for {value_type}")


def _schema_is_ignored(schema):
    return schema.get("compare", {}).get("kind") == "ignore"


def _iter_leaf_locations(
    schema,
    value,
    value_path=(),
    schema_path="$",
    event_params_schema=None,
    event_params_schema_path=None,
):
    compare = schema.get("compare")
    if compare:
        yield value_path, schema, schema_path
        return
    value_type = schema["type"]
    if value_type == "event_params":
        yield from _iter_leaf_locations(
            event_params_schema,
            value,
            value_path,
            event_params_schema_path or schema_path,
        )
    elif value_type == "object":
        for name, child_value in value.items():
            child_schema = _schema_child(schema, name)
            if child_schema is None:
                continue
            child_schema_path = (
                f"{schema_path}.{name}"
                if name in schema["properties"]
                else f"{schema_path}.*"
            )
            yield from _iter_leaf_locations(
                child_schema,
                child_value,
                value_path + (name,),
                child_schema_path,
                event_params_schema,
                event_params_schema_path,
            )
    elif value_type == "array":
        for index, child_value in enumerate(value):
            yield from _iter_leaf_locations(
                schema["items"],
                child_value,
                value_path + (index,),
                f"{schema_path}[*]",
                event_params_schema,
                event_params_schema_path,
            )


def _semantic_mismatch_detected(contract, original, mutated):
    return bool(compare_traces(contract, original, mutated).mismatches)


def audit_trace(contract, events):
    failures = []
    if not events:
        return ["audit: cannot audit an empty trace"]

    for event_index, event in enumerate(events):
        name = event.get("event")
        params_schema = _event_params_schema(contract, name)
        if params_schema is None:
            continue
        for value_path, schema, schema_path in _iter_leaf_locations(
            contract["trace"]["event_schema"],
            event,
            (),
            "trace.common",
            params_schema,
            f"trace.events.{name}.params",
        ):
            value = _get_at(event, value_path)
            replacement = _mutated_scalar(schema, value)
            compare = schema["compare"]
            if replacement is not None:
                mutated = copy.deepcopy(events)
                _set_at(mutated[event_index], value_path, replacement)
                detected = _semantic_mismatch_detected(
                    contract, events, mutated
                )
                if compare["kind"] == "ignore":
                    if detected:
                        failures.append(
                            f"audit: ignored path {schema_path} was compared"
                        )
                elif not detected:
                    failures.append(
                        f"audit: mutation at {schema_path} was not detected"
                    )

            if compare["kind"] != "ignore" and value_path:
                mutated = copy.deepcopy(events)
                _delete_at(mutated[event_index], value_path)
                if not _semantic_mismatch_detected(contract, events, mutated):
                    failures.append(
                        f"audit: deletion at {schema_path} was not detected"
                    )

        for object_path, object_schema in _iter_object_locations(
            contract["trace"]["event_schema"],
            event,
            event_params_schema=params_schema,
        ):
            if object_schema["additional_properties"] is not False:
                continue
            mutated = copy.deepcopy(events)
            mutated_target = (
                _get_at(mutated[event_index], object_path)
                if object_path
                else mutated[event_index]
            )
            original_target = (
                _get_at(event, object_path) if object_path else event
            )
            for name in list(original_target):
                child_schema = _schema_child(object_schema, name)
                if child_schema is None or _schema_is_ignored(child_schema):
                    continue
                deleted = copy.deepcopy(events)
                deleted_target = (
                    _get_at(deleted[event_index], object_path)
                    if object_path
                    else deleted[event_index]
                )
                del deleted_target[name]
                if not _semantic_mismatch_detected(
                    contract, events, deleted
                ):
                    failures.append(
                        "audit: required/present field deletion was not "
                        f"detected at trace[{event_index}].{name}"
                    )

            sentinel = "__audit_unknown__"
            if sentinel not in mutated_target:
                additional = object_schema["additional_properties"]
                if additional is False:
                    mutated_target[sentinel] = 1
                    should_detect = True
                else:
                    mutated_target[sentinel] = _sample_value(additional)
                    should_detect = not _schema_is_ignored(additional)
                detected = _semantic_mismatch_detected(
                    contract, events, mutated
                )
                if should_detect and not detected:
                    failures.append(
                        "audit: field insertion was not detected at "
                        f"trace[{event_index}]"
                        + "".join(
                            f"[{part}]"
                            if isinstance(part, int)
                            else f".{part}"
                            for part in object_path
                        )
                    )
                if not should_detect and detected:
                    failures.append(
                        "audit: explicitly ignored dynamic field was compared"
                    )

    if len(events) >= 1:
        deleted = copy.deepcopy(events)
        deleted.pop(0)
        if not _semantic_mismatch_detected(contract, events, deleted):
            failures.append("audit: event deletion was not detected")
        added = copy.deepcopy(events)
        added.append(copy.deepcopy(events[-1]))
        if not _semantic_mismatch_detected(contract, events, added):
            failures.append("audit: event addition was not detected")

    if len(events) >= 2:
        for index in range(len(events) - 1):
            if events[index] != events[index + 1]:
                reordered = copy.deepcopy(events)
                reordered[index], reordered[index + 1] = (
                    reordered[index + 1],
                    reordered[index],
                )
                if not _semantic_mismatch_detected(
                    contract, events, reordered
                ):
                    failures.append("audit: event reordering was not detected")
                break
    return failures


def _compare_schema_value(schema, original, mutated, path):
    result = ComparisonResult()
    compare_value(schema, original, mutated, path, path, result)
    return result


def _iter_object_locations(
    schema, value, value_path=(), event_params_schema=None
):
    compare = schema.get("compare")
    if compare:
        return
    value_type = schema["type"]
    if value_type == "event_params":
        yield from _iter_object_locations(
            event_params_schema, value, value_path
        )
    elif value_type == "object":
        yield value_path, schema
        for name, child_value in value.items():
            child_schema = _schema_child(schema, name)
            if child_schema is not None:
                yield from _iter_object_locations(
                    child_schema,
                    child_value,
                    value_path + (name,),
                    event_params_schema,
                )
    elif value_type == "array":
        for index, child_value in enumerate(value):
            yield from _iter_object_locations(
                schema["items"],
                child_value,
                value_path + (index,),
                event_params_schema,
            )


def audit_value(schema, value, path):
    """Mutation-audit one outcome or side-effect value against its schema."""
    failures = []
    for value_path, child_schema, schema_path in _iter_leaf_locations(
        schema, value, (), path
    ):
        current = _get_at(value, value_path) if value_path else value
        replacement = _mutated_scalar(child_schema, current)
        compare = child_schema["compare"]
        if replacement is not None:
            if value_path:
                mutated = copy.deepcopy(value)
                _set_at(mutated, value_path, replacement)
            else:
                mutated = replacement
            detected = bool(
                _compare_schema_value(schema, value, mutated, path).mismatches
            )
            if compare["kind"] == "ignore":
                if detected:
                    failures.append(
                        f"audit: ignored path {schema_path} was compared"
                    )
            elif not detected:
                failures.append(
                    f"audit: mutation at {schema_path} was not detected"
                )
        if compare["kind"] != "ignore" and value_path:
            deleted = copy.deepcopy(value)
            _delete_at(deleted, value_path)
            if not _compare_schema_value(
                schema, value, deleted, path
            ).mismatches:
                failures.append(
                    f"audit: deletion at {schema_path} was not detected"
                )

    for object_path, object_schema in _iter_object_locations(schema, value):
        mutated = copy.deepcopy(value)
        target = _get_at(mutated, object_path) if object_path else mutated
        original_target = (
            _get_at(value, object_path) if object_path else value
        )
        for name in list(original_target):
            child_schema = _schema_child(object_schema, name)
            if child_schema is None or _schema_is_ignored(child_schema):
                continue
            deleted = copy.deepcopy(value)
            deleted_target = (
                _get_at(deleted, object_path) if object_path else deleted
            )
            del deleted_target[name]
            if not _compare_schema_value(
                schema, value, deleted, path
            ).mismatches:
                failures.append(
                    f"audit: present field deletion at {path}.{name} "
                    "was not detected"
                )

        sentinel = "__audit_unknown__"
        if sentinel in target:
            continue
        additional = object_schema["additional_properties"]
        if additional is False:
            target[sentinel] = 1
            should_detect = True
        else:
            target[sentinel] = _sample_value(additional)
            should_detect = not _schema_is_ignored(additional)
        detected = bool(
            _compare_schema_value(schema, value, mutated, path).mismatches
        )
        if should_detect and not detected:
            failures.append(
                f"audit: field insertion at {path} was not detected"
            )
        if not should_detect and detected:
            failures.append(
                f"audit: explicitly ignored dynamic field at {path} "
                "was compared"
            )
    return failures


def _print_result(result):
    if result.mismatches:
        print("Trace mismatch")
        for mismatch in result.mismatches:
            print(f"  - {mismatch}")
    if result.audit_failures:
        print("Comparator audit failed")
        for failure in result.audit_failures:
            print(f"  - {failure}")
    if result.equivalent:
        print("Traces equivalent")
        print(f"  semantic paths observed: {len(result.observed)}")
        print(f"  explicitly ignored paths: {len(result.ignored)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--coverage-out")
    parser.add_argument("--require-complete-coverage", action="store_true")
    parser.add_argument("cpp_trace")
    parser.add_argument("rust_trace")
    args = parser.parse_args(argv)

    try:
        contract = load_contract(args.contract)
        cpp_events = read_trace(args.cpp_trace)
        rust_events = read_trace(args.rust_trace)
        result = compare_traces(contract, cpp_events, rust_events)
        if args.audit:
            result.audit_failures.extend(audit_trace(contract, cpp_events))
        summary = coverage_summary(contract, result.observed, scope="trace")
        if args.coverage_out:
            write_coverage(args.coverage_out, summary)
        if args.require_complete_coverage and summary["missing"]:
            result.mismatches.append(
                "trace contract coverage incomplete: "
                + ", ".join(summary["missing"])
            )
    except (ContractError, InputError) as exc:
        print(f"configuration/input error: {exc}", file=sys.stderr)
        return 2

    _print_result(result)
    return 0 if result.equivalent else 1


if __name__ == "__main__":
    sys.exit(main())

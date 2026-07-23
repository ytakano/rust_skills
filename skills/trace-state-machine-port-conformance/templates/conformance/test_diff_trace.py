#!/usr/bin/env python3
"""Tests for the fail-closed equivalence comparator and harness."""

import copy
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import diff_trace  # noqa: E402
import run_diff  # noqa: E402

CONTRACT_PATH = HERE / "equivalence_contract.json"


def exact(value_type):
    return {"type": value_type, "compare": {"kind": "exact"}}


def object_schema(properties, required=None, additional=False):
    return {
        "type": "object",
        "required": list(properties) if required is None else required,
        "properties": properties,
        "additional_properties": additional,
    }


def array_schema(items):
    return {"type": "array", "items": items}


def float_schema(kind, **overrides):
    compare = {
        "kind": kind,
        "nan": "reject",
        "infinity": "reject",
        "signed_zero": "equal",
    }
    compare.update(overrides)
    return {"type": "float", "compare": compare}


def event(name, params=None, impl="cpp", seq=1):
    return {
        "version": 1,
        "run_id": f"{impl}-run",
        "seq": seq,
        "impl": impl,
        "component": "parser",
        "event": name,
        "params": {} if params is None else params,
    }


def contract_with_event(name, params_schema):
    contract = copy.deepcopy(diff_trace.load_contract(CONTRACT_PATH))
    contract["trace"]["events"] = {
        name: {
            "description": f"{name} test event",
            "params": params_schema,
        }
    }
    return diff_trace.validate_contract(contract)


class ContractAndTraceTests(unittest.TestCase):
    def setUp(self):
        self.contract = diff_trace.load_contract(CONTRACT_PATH)

    def test_sample_contract_is_valid(self):
        self.assertEqual(self.contract["version"], 1)
        self.assertEqual(
            set(self.contract["trace"]["events"]),
            {"Start", "HeaderParsed", "BodyAccepted", "Finish", "ErrorRaised"},
        )

    def test_nested_objects_and_arrays_compare_every_leaf(self):
        params = object_schema(
            {
                "state": object_schema(
                    {
                        "name": exact("string"),
                        "values": array_schema(exact("integer")),
                    }
                )
            }
        )
        contract = contract_with_event("Snapshot", params)
        cpp = [
            event(
                "Snapshot",
                {"state": {"name": "ready", "values": [1, 2, 3]}},
            )
        ]
        rust = copy.deepcopy(cpp)
        rust[0]["impl"] = "rust"
        self.assertTrue(diff_trace.compare_traces(contract, cpp, rust).equivalent)

        rust[0]["params"]["state"]["values"][1] = 9
        result = diff_trace.compare_traces(contract, cpp, rust)
        self.assertFalse(result.equivalent)
        self.assertIn(
            "trace[0].params.state.values[1]",
            "\n".join(result.mismatches),
        )

    def test_missing_extra_unknown_type_and_order_are_rejected(self):
        cpp = [
            event("Start", seq=1),
            event("Finish", seq=2),
        ]
        rust = copy.deepcopy(cpp)
        for item in rust:
            item["impl"] = "rust"
        self.assertTrue(
            diff_trace.compare_traces(self.contract, cpp, rust).equivalent
        )

        missing = copy.deepcopy(rust)
        del missing[0]["component"]
        self.assertFalse(
            diff_trace.compare_traces(self.contract, cpp, missing).equivalent
        )

        extra = copy.deepcopy(rust)
        extra[0]["unexpected"] = 1
        self.assertFalse(
            diff_trace.compare_traces(self.contract, cpp, extra).equivalent
        )

        wrong_type = copy.deepcopy(rust)
        wrong_type[0]["version"] = "1"
        self.assertFalse(
            diff_trace.compare_traces(
                self.contract, cpp, wrong_type
            ).equivalent
        )

        unknown = copy.deepcopy(rust)
        unknown[0]["event"] = "Unknown"
        self.assertFalse(
            diff_trace.compare_traces(self.contract, cpp, unknown).equivalent
        )

        reordered = list(reversed(rust))
        self.assertFalse(
            diff_trace.compare_traces(
                self.contract, cpp, reordered
            ).equivalent
        )

        deleted = rust[:-1]
        self.assertFalse(
            diff_trace.compare_traces(self.contract, cpp, deleted).equivalent
        )

        added = rust + [copy.deepcopy(rust[-1])]
        self.assertFalse(
            diff_trace.compare_traces(self.contract, cpp, added).equivalent
        )

    def test_comparison_policy_and_coverage_must_be_explicit(self):
        schema = {"type": "string"}
        with self.assertRaises(diff_trace.ContractError):
            diff_trace.validate_schema(schema)

        ignored = {
            "type": "string",
            "compare": {"kind": "ignore", "reason": ""},
        }
        with self.assertRaises(diff_trace.ContractError):
            diff_trace.validate_schema(ignored)

        waived = exact("string")
        waived["coverage"] = "waived"
        with self.assertRaises(diff_trace.ContractError):
            diff_trace.validate_schema(waived)

    def test_unknown_contract_keys_are_rejected(self):
        contract = copy.deepcopy(self.contract)
        contract["unknown"] = True
        with self.assertRaises(diff_trace.ContractError):
            diff_trace.validate_contract(contract)

    def test_coverage_reports_unobserved_and_reasoned_waivers(self):
        cpp = [event("Start")]
        rust = [event("Start", impl="rust")]
        result = diff_trace.compare_traces(self.contract, cpp, rust)
        summary = diff_trace.coverage_summary(
            self.contract, result.observed, scope="trace"
        )
        self.assertIn("trace.events.Finish", summary["missing"])
        self.assertIn("trace.events.Start", summary["observed"])

        contract = copy.deepcopy(self.contract)
        contract["trace"]["events"]["Finish"]["coverage"] = "waived"
        contract["trace"]["events"]["Finish"][
            "coverage_reason"
        ] = "error-only corpus for this conformance stage"
        diff_trace.validate_contract(contract)
        summary = diff_trace.coverage_summary(
            contract, result.observed, scope="trace"
        )
        self.assertNotIn("trace.events.Finish", summary["missing"])
        self.assertIn("trace.events.Finish", summary["waived"])

    def test_mutation_audit_checks_semantic_and_ignored_fields(self):
        trace = [
            event("Start", seq=1),
            event("HeaderParsed", {"kind": "v2"}, seq=2),
            event("BodyAccepted", {"bytes": 4}, seq=3),
            event("Finish", seq=4),
        ]
        self.assertEqual(diff_trace.audit_trace(self.contract, trace), [])

    def test_cli_audits_and_writes_complete_trace_coverage(self):
        contract = copy.deepcopy(self.contract)
        contract["trace"]["events"] = {
            "Start": contract["trace"]["events"]["Start"]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps(contract) + "\n", encoding="utf-8"
            )
            cpp_path = root / "cpp.jsonl"
            rust_path = root / "rust.jsonl"
            cpp_path.write_text(
                json.dumps(event("Start")) + "\n", encoding="utf-8"
            )
            rust_path.write_text(
                json.dumps(event("Start", impl="rust")) + "\n",
                encoding="utf-8",
            )
            coverage_path = root / "coverage.json"
            with contextlib.redirect_stdout(io.StringIO()):
                result = diff_trace.main(
                    [
                        "--contract",
                        str(contract_path),
                        "--audit",
                        "--coverage-out",
                        str(coverage_path),
                        "--require-complete-coverage",
                        str(cpp_path),
                        str(rust_path),
                    ]
                )
            self.assertEqual(result, 0)
            coverage = json.loads(
                coverage_path.read_text(encoding="utf-8")
            )
            self.assertEqual(coverage["missing"], [])


class FloatComparisonTests(unittest.TestCase):
    def compare(self, schema, left, right):
        diff_trace.validate_schema(schema)
        result = diff_trace.ComparisonResult()
        diff_trace.compare_value(
            schema, left, right, "value", "value", result
        )
        return result

    def test_abs_rel_near_zero_and_large_scale(self):
        schema = float_schema(
            "abs_rel", abs_tol=1.0e-9, rel_tol=1.0e-7
        )
        self.assertTrue(self.compare(schema, 0.0, 5.0e-10).equivalent)
        self.assertTrue(
            self.compare(schema, 1.0e6, 1.0e6 + 0.05).equivalent
        )
        self.assertFalse(self.compare(schema, 0.0, 2.0e-9).equivalent)
        self.assertFalse(
            self.compare(schema, 1.0e6, 1.0e6 + 1.0).equivalent
        )

    def test_ulp_inside_and_outside_limit(self):
        schema = float_schema(
            "ulp", precision="f64", max_ulps=1
        )
        adjacent = math.nextafter(1.0, math.inf)
        two_away = math.nextafter(adjacent, math.inf)
        self.assertTrue(self.compare(schema, 1.0, adjacent).equivalent)
        self.assertFalse(self.compare(schema, 1.0, two_away).equivalent)

    def test_bit_exact_and_signed_zero(self):
        schema = float_schema(
            "bit_exact",
            precision="f64",
            signed_zero="distinct",
        )
        self.assertTrue(self.compare(schema, 1.5, 1.5).equivalent)
        self.assertFalse(self.compare(schema, 0.0, -0.0).equivalent)

    def test_nan_infinity_and_signed_zero_policies(self):
        schema = float_schema(
            "abs_rel",
            abs_tol=0.0,
            rel_tol=0.0,
            nan="both_equal",
            infinity="same_sign",
            signed_zero="equal",
        )
        self.assertTrue(self.compare(schema, "nan", "nan").equivalent)
        self.assertTrue(self.compare(schema, "+inf", "+inf").equivalent)
        self.assertFalse(self.compare(schema, "+inf", "-inf").equivalent)
        self.assertTrue(self.compare(schema, 0.0, -0.0).equivalent)

    def test_nonstandard_json_nan_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"value": NaN}\n', encoding="utf-8")
            with self.assertRaises(diff_trace.InputError):
                diff_trace.load_json(path)


class NormalizationTests(unittest.TestCase):
    def test_normalization_preserves_finite_float_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            value = 0.30000000000000004
            trace.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "run_id": "r",
                        "seq": 1,
                        "impl": "cpp",
                        "component": "numeric",
                        "event": "Measurement",
                        "params": {"value": value},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "normalize_trace.py"),
                    str(trace),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            normalized = json.loads(proc.stdout)
            self.assertEqual(normalized["params"]["value"], value)

    def test_normalization_rejects_non_finite_json_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            trace.write_text(
                '{"version":1,"run_id":"r","seq":1,"impl":"cpp",'
                '"component":"numeric","event":"Measurement",'
                '"params":{"value":1e999}}\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "normalize_trace.py"),
                    str(trace),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("non-finite numeric value", proc.stderr)


class SideEffectTests(unittest.TestCase):
    def test_manifest_is_compared_recursively(self):
        contract = diff_trace.load_contract(CONTRACT_PATH)
        contract["side_effects"] = {
            "mode": "manifest",
            "schema": object_schema(
                {
                    "files": array_schema(
                        object_schema(
                            {
                                "path": exact("string"),
                                "sha256": exact("string"),
                            }
                        )
                    )
                }
            ),
        }
        diff_trace.validate_contract(contract)
        left = {
            "files": [
                {"path": "out.bin", "sha256": "abc"},
            ]
        }
        right = copy.deepcopy(left)
        self.assertTrue(
            diff_trace.compare_side_effects(
                contract, left, right
            ).equivalent
        )
        right["files"][0]["sha256"] = "def"
        self.assertFalse(
            diff_trace.compare_side_effects(
                contract, left, right
            ).equivalent
        )
        self.assertEqual(
            diff_trace.audit_value(
                contract["side_effects"]["schema"], left, "side_effects"
            ),
            [],
        )

    def test_dynamic_map_keys_are_semantic_and_audited(self):
        contract = diff_trace.load_contract(CONTRACT_PATH)
        dynamic_schema = object_schema({}, additional=exact("integer"))
        contract["side_effects"] = {
            "mode": "manifest",
            "schema": dynamic_schema,
        }
        diff_trace.validate_contract(contract)
        left = {"alpha": 1}
        right = {"alpha": 1, "beta": 2}
        self.assertFalse(
            diff_trace.compare_side_effects(
                contract, left, right
            ).equivalent
        )
        self.assertEqual(
            diff_trace.audit_value(
                dynamic_schema, left, "side_effects"
            ),
            [],
        )

    def test_out_of_scope_requires_reason(self):
        contract = diff_trace.load_contract(CONTRACT_PATH)
        contract["side_effects"] = {"mode": "out_of_scope", "reason": ""}
        with self.assertRaises(diff_trace.ContractError):
            diff_trace.validate_contract(contract)


FAKE_PROGRAM = """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

impl = os.environ["RUN_ID"].split("-", 1)[0]
events = [
    {
        "version": 1,
        "run_id": os.environ["RUN_ID"],
        "seq": 1,
        "impl": impl,
        "component": "parser",
        "event": "Start",
        "params": {},
    },
    {
        "version": 1,
        "run_id": os.environ["RUN_ID"],
        "seq": 2,
        "impl": impl,
        "component": "parser",
        "event": "Finish",
        "params": {},
    },
]
Path(os.environ["TRACE_OUT"]).write_text(
    "\\n".join(json.dumps(event) for event in events) + "\\n",
    encoding="utf-8",
)
Path("workdir-marker").write_text(impl, encoding="utf-8")
__SIDE_EFFECT_CODE__
sys.stdout.write(__STDOUT__)
sys.stderr.write(__STDERR__)
raise SystemExit(__EXIT_CODE__)
"""


class HarnessIntegrationTests(unittest.TestCase):
    def make_program(
        self,
        directory,
        name,
        stdout,
        stderr="same-stderr",
        exit_code=0,
        side_effects=None,
    ):
        if side_effects is None:
            side_effect_code = ""
        else:
            side_effect_code = (
                "Path(os.environ[\"SIDE_EFFECTS_OUT\"]).write_text("
                + repr(json.dumps(side_effects) + "\n")
                + ', encoding="utf-8")'
            )
        path = directory / name
        program = FAKE_PROGRAM
        program = program.replace("__STDOUT__", repr(stdout))
        program = program.replace("__STDERR__", repr(stderr))
        program = program.replace("__EXIT_CODE__", str(exit_code))
        program = program.replace("__SIDE_EFFECT_CODE__", side_effect_code)
        path.write_text(program, encoding="utf-8")
        path.chmod(0o755)
        return path

    def make_contract(self, directory):
        contract = diff_trace.load_contract(CONTRACT_PATH)
        contract["trace"]["events"] = {
            name: contract["trace"]["events"][name]
            for name in ("Start", "Finish")
        }
        path = directory / "contract.json"
        path.write_text(
            json.dumps(contract, indent=2) + "\n", encoding="utf-8"
        )
        return contract, path

    def args(self, directory, cpp, rust, contract_path):
        state_machine = directory / "state_machine.yaml"
        state_machine.write_text("name: mocked\n", encoding="utf-8")
        return SimpleNamespace(
            cpp_bin=cpp,
            rust_bin=rust,
            state_machine=state_machine,
            contract=contract_path,
            cases=directory,
            coverage_out=None,
            repro_dir=directory / "repro",
        )

    @mock.patch.object(run_diff, "run_monitor")
    def test_harness_compares_outputs_and_uses_separate_workdirs(
        self, monitor
    ):
        monitor.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="accepted", stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpp_program = self.make_program(root, "cpp.py", "same-stdout")
            rust_program = self.make_program(root, "rust.py", "same-stdout")
            case = root / "case.bin"
            case.write_bytes(b"input")
            contract, contract_path = self.make_contract(root)
            args = self.args(
                root, cpp_program, rust_program, contract_path
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_diff.check_case(args, contract, case)
            self.assertTrue(result.ok, result.failures)
            self.assertFalse(result.audit_failures)
            self.assertIn("outcomes.stdout", result.observed)

            cpp_dir = root / "manual-cpp"
            rust_dir = root / "manual-rust"
            cpp_run = run_diff.run_impl(
                cpp_program, "cpp", case, cpp_dir
            )
            rust_run = run_diff.run_impl(
                rust_program, "rust", case, rust_dir
            )
            self.assertNotEqual(cpp_run.workdir, rust_run.workdir)
            self.assertEqual(
                (cpp_dir / "workdir-marker").read_text(encoding="utf-8"),
                "cpp",
            )
            self.assertEqual(
                (rust_dir / "workdir-marker").read_text(encoding="utf-8"),
                "rust",
            )

    @mock.patch.object(run_diff, "run_monitor")
    def test_harness_preserves_repro_on_mismatch(self, monitor):
        monitor.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="accepted", stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpp_program = self.make_program(root, "cpp.py", "cpp-output")
            rust_program = self.make_program(root, "rust.py", "rust-output")
            case = root / "case.bin"
            case.write_bytes(b"input")
            contract, contract_path = self.make_contract(root)
            args = self.args(
                root, cpp_program, rust_program, contract_path
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_diff.check_case(args, contract, case)
            self.assertFalse(result.ok)
            self.assertIsNotNone(result.repro_path)
            self.assertTrue((result.repro_path / "report.json").is_file())
            self.assertEqual(
                (result.repro_path / "cpp.stdout").read_bytes(),
                b"cpp-output",
            )
            self.assertEqual(
                (result.repro_path / "rust.stdout").read_bytes(),
                b"rust-output",
            )

    @mock.patch.object(run_diff, "run_monitor")
    def test_harness_compares_side_effect_manifest(self, monitor):
        monitor.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="accepted", stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                "files": [{"path": "out.bin", "sha256": "abc"}]
            }
            cpp_program = self.make_program(
                root, "cpp.py", "same", side_effects=manifest
            )
            rust_program = self.make_program(
                root, "rust.py", "same", side_effects=manifest
            )
            case = root / "case.bin"
            case.write_bytes(b"input")
            contract, contract_path = self.make_contract(root)
            contract["side_effects"] = {
                "mode": "manifest",
                "schema": object_schema(
                    {
                        "files": array_schema(
                            object_schema(
                                {
                                    "path": exact("string"),
                                    "sha256": exact("string"),
                                }
                            )
                        )
                    }
                ),
            }
            diff_trace.validate_contract(contract)
            contract_path.write_text(
                json.dumps(contract, indent=2) + "\n", encoding="utf-8"
            )
            args = self.args(
                root, cpp_program, rust_program, contract_path
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_diff.check_case(args, contract, case)
            self.assertTrue(result.ok, result.failures)
            self.assertIn("side_effects.files[*].path", result.observed)
            self.assertIn("side_effects.files[*].sha256", result.observed)

    @mock.patch.object(run_diff, "run_monitor")
    def test_harness_detects_stderr_and_exit_code(self, monitor):
        monitor.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="accepted", stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cpp_program = self.make_program(
                root, "cpp.py", "same", stderr="cpp-error", exit_code=1
            )
            rust_program = self.make_program(
                root, "rust.py", "same", stderr="rust-error", exit_code=2
            )
            case = root / "case.bin"
            case.write_bytes(b"input")
            contract, contract_path = self.make_contract(root)
            args = self.args(
                root, cpp_program, rust_program, contract_path
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = run_diff.check_case(args, contract, case)
            self.assertFalse(result.ok)
            failures = "\n".join(result.failures)
            self.assertIn("outcomes.stderr", failures)
            self.assertIn("outcomes.exit_code", failures)


if __name__ == "__main__":
    unittest.main()

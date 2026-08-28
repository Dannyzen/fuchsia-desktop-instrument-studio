#!/usr/bin/env python3
"""Self-tests for the NativeThemeV1 sq-01 source-quality harness."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools/native_theme/sq01_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("sq01_harness", MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sq01 harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Sq01HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load_harness()

    def test_canonical_json_rejects_nonfinite_and_is_stable(self):
        self.assertEqual(self.h.canonical_json_bytes({"b": 2, "a": 1}), b'{"a":1,"b":2}\n')
        with self.assertRaisesRegex(ValueError, "non-finite"):
            self.h.canonical_json_bytes({"bad": float("nan")})

    def test_output_path_accepts_gate_and_explicit_temp_only(self):
        self.assertEqual(
            self.h.validate_output_path(ROOT, ROOT / "artifacts/quality/sq-01"),
            ROOT / "artifacts/quality/sq-01",
        )
        with tempfile.TemporaryDirectory() as td:
            safe = Path(td).resolve() / "receipts"
            self.assertEqual(self.h.validate_output_path(ROOT, safe, safe_temp_root=Path(td)), safe)
        for unsafe in (ROOT, ROOT / "artifacts", ROOT.parent / "escape", Path("/")):
            with self.subTest(path=unsafe), self.assertRaisesRegex(ValueError, "unsafe output"):
                self.h.validate_output_path(ROOT, unsafe)

    def test_symlink_output_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            safe = Path(td) / "safe"
            safe.mkdir()
            target = Path(td) / "target"
            target.mkdir()
            link = safe / "receipts"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.h.validate_output_path(ROOT, link, safe_temp_root=safe)

    def test_helper_suite_does_not_collide_with_existing_canonical_output(self):
        canonical = ROOT / "artifacts/quality/sq-01"
        before = ({p.name: p.read_bytes() for p in canonical.iterdir()}
                  if canonical.is_dir() else None)
        with tempfile.TemporaryDirectory() as td:
            safe = Path(td)
            output = safe / "receipts"
            self.assertEqual(self.h.validate_output_path(ROOT, output, safe_temp_root=safe), output)
            output.mkdir()
            for name, raw in self.h.build_synthetic_bundle(self.h.synthetic_test_context("1" * 40)).items():
                (output / name).write_bytes(raw)
            self.assertEqual({p.name for p in output.iterdir()}, set(self.h.ALL_RECEIPTS))
        after = ({p.name: p.read_bytes() for p in canonical.iterdir()}
                 if canonical.is_dir() else None)
        self.assertEqual(after, before)

    def test_source_identity_rejects_wrong_dirty_and_moving(self):
        clean = self.h.SourceIdentity("a" * 40, "b" * 40, ())
        self.h.assert_source_identity(clean, clean.sha, clean)
        with self.assertRaisesRegex(RuntimeError, "SHA"):
            self.h.assert_source_identity(clean, "c" * 40, clean)
        with self.assertRaisesRegex(RuntimeError, "dirty"):
            self.h.assert_source_identity(clean._replace(dirty=("x",)), clean.sha, clean)
        with self.assertRaisesRegex(RuntimeError, "moved"):
            self.h.assert_source_identity(clean, clean.sha, clean._replace(tree="d" * 40))

    def test_network_denial_blocks_socket_and_http_paths(self):
        undo = self.h.install_network_denial()
        try:
            import socket
            import urllib.request
            with self.assertRaisesRegex(PermissionError, "sq-01 network denied"):
                socket.create_connection(("127.0.0.1", 9))
            with self.assertRaisesRegex(PermissionError, "sq-01 network denied"):
                urllib.request.urlopen("http://127.0.0.1:9")
        finally:
            undo()

    def test_subprocess_allowlist_is_exact_and_never_shell(self):
        self.assertTrue(self.h.allowed_subprocess(["python3", "scripts/test-native-theme-v1.py"], ROOT))
        self.assertTrue(self.h.allowed_subprocess(["git", "rev-parse", "HEAD"], ROOT))
        for argv in (["sh", "-c", "true"], ["git", "push"], ["python3", "-c", "print(1)"], "git status"):
            with self.subTest(argv=argv):
                self.assertFalse(self.h.allowed_subprocess(argv, ROOT))

    def test_git_diff_allowlist_requires_config_immune_pinned_ref_shape(self):
        source_sha = "1" * 40
        command = [
            "git", "diff", "--binary", "--full-index", "--no-color", "--no-ext-diff",
            "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/",
            "--diff-algorithm=myers", "--no-renames", self.h.BASE_SHA, source_sha, "--",
        ]
        self.assertTrue(self.h.allowed_subprocess(command, ROOT))
        denied = (
            ["git", "diff", "--binary", self.h.BASE_SHA, source_sha],
            command[:5] + command[6:],
            command[:-1],
            command + ["--stat"],
            command[:-3] + ["HEAD", source_sha, "--"],
            command[:-2] + ["HEAD", "--"],
            ["git", "clone", "https://example.invalid/repository"],
            ["git", "fetch", "origin"],
            ["git", "push", "origin", "HEAD"],
            ["git", "describe", "--always"],
        )
        for argv in denied:
            with self.subTest(argv=argv):
                self.assertFalse(self.h.allowed_subprocess(argv, ROOT))

    def test_ci_pins_exact_python_and_preserves_clean_source_before_gate(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text("utf-8")
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python-version: '3.12.9'", workflow)
        self.assertIn("run: bash scripts/secret-scan.sh", workflow)
        self.assertNotIn("chmod +x scripts/*.sh scripts/*.py", workflow)

    def test_receipt_shape_canonicality_and_hash_are_enforced(self):
        receipt = {"schema_version": "1.0.0", "status": "PASS"}
        raw = self.h.canonical_json_bytes(receipt)
        self.h.validate_receipt_bytes(raw, {"schema_version", "status"})
        for bad in (b'{"status":"PASS","schema_version":"1.0.0"}\n', raw[:-1],
                    b'{"schema_version":"1.0.0","status":"PASS","extra":1}\n'):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                self.h.validate_receipt_bytes(bad, {"schema_version", "status"})
        self.assertFalse(self.h.verify_receipt_hash(raw, "0" * 64))

    def test_machine_limit_contract_extraction_is_exact_and_mutation_sensitive(self):
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        extracted = self.h.extract_machine_limit_contract(schema)
        self.assertEqual(extracted, {
            "limit_relations": [{
                "additive_bytes": 0,
                "dominated": "runtime_snapshot_bytes",
                "proof": "compiled_pack_bytes <= runtime_snapshot_bytes",
                "stricter": "compiled_pack_bytes",
            }],
            "limit_units": self.h.EXPECTED_LIMIT_UNITS,
            "limits": self.h.EXPECTED_LIMITS,
        })

        def candidate():
            return json.loads(json.dumps(schema))

        required_mutations = []
        changed_runtime = candidate()
        changed_runtime["x-native-theme-v1-contract"]["limits"]["runtime_snapshot_bytes"] += 1
        required_mutations.append(changed_runtime)
        deleted_runtime = candidate()
        del deleted_runtime["x-native-theme-v1-contract"]["limits"]["runtime_snapshot_bytes"]
        required_mutations.append(deleted_runtime)
        changed_unit = candidate()
        changed_unit["x-native-theme-v1-contract"]["limit_units"]["runtime_snapshot_bytes"] = "heap_bytes"
        required_mutations.append(changed_unit)
        reversed_relation = candidate()
        reversed_relation["x-native-theme-v1-contract"]["limit_relations"] = [{
            "additive_bytes": 0,
            "dominated": "compiled_pack_bytes",
            "proof": "runtime_snapshot_bytes <= compiled_pack_bytes",
            "stricter": "runtime_snapshot_bytes",
        }]
        required_mutations.append(reversed_relation)
        failed_dominance = candidate()
        failed_dominance["x-native-theme-v1-contract"]["limits"]["compiled_pack_bytes"] = 524289
        required_mutations.append(failed_dominance)
        unaccounted = candidate()
        unaccounted["x-native-theme-v1-contract"]["limits"]["new_limit"] = 1
        required_mutations.append(unaccounted)
        for mutation in required_mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.h.extract_machine_limit_contract(mutation)

    def test_machine_limit_extractor_rejects_every_malformed_structure(self):
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())

        def mutate(change):
            value = json.loads(json.dumps(schema))
            change(value["x-native-theme-v1-contract"])
            return value

        malformed = [
            [],
            {},
            mutate(lambda policy: policy.__setitem__("limits", [])),
            mutate(lambda policy: policy["limits"].__setitem__("aliases", True)),
            mutate(lambda policy: policy["limits"].__setitem__("aliases", 0)),
            mutate(lambda policy: policy.__setitem__("limit_units", [])),
            mutate(lambda policy: policy["limit_units"].pop("compiled_pack_bytes")),
            mutate(lambda policy: policy["limit_units"].__setitem__("extra", "bytes")),
            mutate(lambda policy: policy["limit_units"].__setitem__("compiled_pack_bytes", 1)),
            mutate(lambda policy: policy.__setitem__("limit_relations", {})),
            mutate(lambda policy: policy.__setitem__("limit_relations", [None])),
            mutate(lambda policy: policy["limit_relations"][0].pop("proof")),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("stricter", 1)),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("dominated", "unknown")),
            mutate(lambda policy: policy["limit_relations"].append(dict(policy["limit_relations"][0]))),
            mutate(lambda policy: policy["limit_relations"].append({
                "additive_bytes": 0,
                "dominated": "compiled_pack_bytes",
                "proof": "runtime_snapshot_bytes <= compiled_pack_bytes",
                "stricter": "runtime_snapshot_bytes",
            })),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("additive_bytes", True)),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("additive_bytes", -1)),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("proof", "asserted")),
            mutate(lambda policy: policy["limit_relations"][0].__setitem__("proof", 1)),
            mutate(lambda policy: policy.__setitem__("limit_relations", [])),
            mutate(lambda policy: policy["limits"].__setitem__("aliases", 2049)),
            mutate(lambda policy: policy.__setitem__("limit_relations", [{
                "additive_bytes": 0,
                "dominated": "compiled_pack_bytes",
                "proof": "compiled_pack_bytes <= compiled_pack_bytes",
                "stricter": "compiled_pack_bytes",
            }])),
        ]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.h.extract_machine_limit_contract(value)

    def test_source_manifest_deep_machine_contract_validation_rejects_all_nested_mutations(self):
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        expected = self.h.extract_machine_limit_contract(schema)

        def manifest(contract):
            value = {field: None for field in self.h.SOURCE_MANIFEST_FIELDS}
            value["machine_limit_contract"] = contract
            return value

        self.assertEqual(
            self.h.validate_source_manifest_bytes(self.h.canonical_json_bytes(manifest(expected))),
            manifest(expected),
        )

        def changed(change):
            contract = json.loads(json.dumps(expected))
            change(contract)
            return manifest(contract)

        mutations = [
            manifest(None),
            changed(lambda contract: contract.pop("limits")),
            changed(lambda contract: contract.__setitem__("extra", {})),
            changed(lambda contract: contract["limits"].pop("runtime_snapshot_bytes")),
            changed(lambda contract: contract["limits"].__setitem__("extra", 1)),
            changed(lambda contract: contract["limits"].__setitem__("runtime_snapshot_bytes", 524289)),
            changed(lambda contract: contract["limit_units"].pop("runtime_snapshot_bytes")),
            changed(lambda contract: contract["limit_units"].__setitem__("extra", "bytes")),
            changed(lambda contract: contract["limit_units"].__setitem__(
                "runtime_snapshot_bytes", "heap_bytes")),
            changed(lambda contract: contract.__setitem__("limit_relations", {})),
            changed(lambda contract: contract["limit_relations"][0].pop("proof")),
            changed(lambda contract: contract["limit_relations"][0].__setitem__("extra", True)),
            changed(lambda contract: contract["limit_relations"][0].__setitem__("proof", "malformed")),
            changed(lambda contract: contract.__setitem__("limit_relations", [{
                "additive_bytes": 0,
                "dominated": "compiled_pack_bytes",
                "proof": "runtime_snapshot_bytes <= compiled_pack_bytes",
                "stricter": "runtime_snapshot_bytes",
            }])),
            changed(lambda contract: contract["limits"].__setitem__("compiled_pack_bytes", 524289)),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.h.validate_source_manifest_bytes(self.h.canonical_json_bytes(mutation))

    def test_verdict_fails_for_each_failed_component_and_skips(self):
        names = self.h.VERDICT_INPUT_RECEIPTS
        passing = {name: {"status": "PASS", "skipped_required": 0} for name in names}
        self.assertEqual(self.h.derive_status(passing), "PASS")
        for name in names:
            candidate = json.loads(json.dumps(passing)); candidate[name]["status"] = "FAIL"
            self.assertEqual(self.h.derive_status(candidate), "FAIL", name)
        candidate = json.loads(json.dumps(passing)); candidate[names[0]]["skipped_required"] = 1
        self.assertEqual(self.h.derive_status(candidate), "FAIL")

    def test_source_manifest_failure_and_skip_force_verdict_fail(self):
        passing = {name: {"status": "PASS", "skipped_required": 0}
                   for name in self.h.VERDICT_INPUT_RECEIPTS}
        for change in ({"status": "FAIL"}, {"skipped_required": 1}):
            candidate = json.loads(json.dumps(passing))
            candidate["source-manifest.json"].update(change)
            self.assertEqual(self.h.derive_status(candidate), "FAIL")

    def test_deterministic_bundle_is_byte_identical(self):
        context = self.h.synthetic_test_context("1" * 40)
        self.assertEqual(self.h.build_synthetic_bundle(context), self.h.build_synthetic_bundle(context))

    def test_command_schema_is_canonical_for_local_and_ci(self):
        schema = self.h.command_schema()
        self.assertEqual(schema[0:2], ["python3", "scripts/test-native-theme-sq01.py"])
        self.assertEqual(schema[2:], ["--source-sha", "${SOURCE_SHA}", "--output-dir", "artifacts/quality/sq-01"])

    def test_case_result_requires_exact_executed_provenance(self):
        row = self.h.case_result(
            case_id="bad", requirement_ids=["schema.nativePackage.schema_version"],
            validator_name="probe", validator_version="1", input_bytes=b"{}",
            expected_layer="schema", expected_code="E_VERSION",
            execution_return=2, actual_layer="schema", actual_code="E_VERSION",
            execution_result="rejected")
        self.assertEqual(set(row), {
            "id", "requirement_ids", "validator_name", "validator_version", "input_hash",
            "expected_layer", "expected_code", "actual_layer", "actual_code",
            "execution_return", "execution_result", "pass", "skipped", "skipped_required",
        })
        self.assertTrue(row["pass"])
        self.assertFalse(row["skipped"])

    def test_auto_accept_executor_kills_mutation_and_verdict(self):
        receipt = self.h.execute_mutations(ROOT, executor=lambda *_a, **_k: (0, "accepted", None, None))
        self.assertEqual(receipt["status"], "FAIL")
        self.assertGreater(receipt["failed"], 0)
        self.assertEqual(self.h.derive_status({
            name: (receipt if name == "mutation-results.json" else {"status": "PASS", "skipped_required": 0})
            for name in self.h.VERDICT_INPUT_RECEIPTS
        }), "FAIL")

    def test_mutation_inventory_executes_all_required_cases(self):
        receipt = self.h.execute_mutations(ROOT)
        cases = receipt["cases"]
        self.assertEqual({case["id"] for case in cases}, set(self.h.REQUIRED_MUTATIONS))
        executed = [case for case in cases if not case["skipped"]]
        skipped = [case for case in cases if case["skipped"]]
        self.assertEqual(len(executed), 37)
        self.assertEqual({case["id"] for case in executed if case["expected_layer"] == "bounds"},
                         {"bounds.overlong-string", "bounds.deep-nesting", "bounds.oversized-input"})
        self.assertEqual(receipt["skipped_required"], len(skipped))
        self.assertTrue(all(not case["pass"] and case["execution_result"] == "not-executed"
                            and case["validator_name"] is None and case["actual_layer"] is None
                            and case["actual_code"] is None and case["skipped_required"] == 1
                            for case in skipped))
        self.assertEqual(receipt["total"], len(cases))
        self.assertEqual(receipt["passed"], sum(case["pass"] for case in cases))
        self.assertEqual(receipt["failed"], sum(not case["pass"] for case in cases))
        self.assertEqual(skipped, [])
        self.assertEqual(receipt["status"], "PASS")

    def test_schema_receipt_executes_all_three_bounds(self):
        class Draft202012Validator:
            @staticmethod
            def check_schema(_schema): pass
            def __init__(self, _schema): pass
            def validate(self, _instance): pass
        fake = types.SimpleNamespace(Draft202012Validator=Draft202012Validator)
        with mock.patch.dict("sys.modules", {"jsonschema": fake}):
            receipt = self.h._schema_validation(ROOT)
        bounds = [case for case in receipt["negative_cases"] if case["id"] in {"overlong", "deep", "oversized"}]
        self.assertEqual(len(bounds), 3)
        self.assertTrue(all(case["pass"] and not case["skipped"] for case in bounds))
        self.assertEqual({case["actual_code"] for case in bounds},
                         {"E_LIMIT_STRING", "E_LIMIT_NESTING", "E_LIMIT_SOURCE"})
        self.assertEqual(receipt["skipped_required"], 0)
        self.assertEqual(receipt["status"], "PASS")

    def test_contract_mutations_execute_real_production_validator(self):
        receipt = self.h.execute_mutations(ROOT)
        cases = {case["id"]: case for case in receipt["cases"]}
        self.assertEqual(set(cases), set(self.h.REQUIRED_MUTATIONS))
        self.assertEqual((receipt["total"], receipt["passed"], receipt["failed"],
                          receipt["skipped_required"], receipt["status"]),
                         (37, 37, 0, 0, "PASS"))
        for case_id, (layer, code) in self.h.REQUIRED_MUTATIONS.items():
            with self.subTest(case_id=case_id):
                case = cases[case_id]
                self.assertTrue(case["pass"])
                self.assertEqual((case["actual_layer"], case["actual_code"]), (layer, code))
                self.assertIsNotNone(case["input_hash"])
                self.assertFalse(case["skipped"])

    def test_unconditional_contract_acceptance_exposes_exact_survivors(self):
        def accept(_root, _raw, _kind):
            return 0, "accepted", None, None
        receipt = self.h.execute_mutations(ROOT, contract_executor=accept)
        survivors = [case for case in receipt["cases"] if case["id"].startswith("contract.") and not case["pass"]]
        self.assertEqual(len(survivors), 27)
        self.assertEqual(receipt["passed"], 10)
        self.assertEqual(receipt["status"], "FAIL")

    def test_machine_contract_receipt_executor_runs_real_extractor(self):
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        self.assertEqual(
            self.h._machine_contract_executor(self.h.canonical_json_bytes(schema)),
            (0, "accepted", None, None),
        )
        self.assertEqual(
            self.h._machine_contract_executor(b"not-json"),
            (2, "rejected", "source-manifest", "E_MACHINE_LIMIT_CONTRACT"),
        )

    def test_public_scan_finds_private_identifiers_paths_and_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture = root / "docs/native-theme-v1-profile.md"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("Beads ID: sq-01\nKanban ID: KAN-42\n/tmp/private\napi_key=secret\n")
            receipt = self.h._public_scan(root)
        self.assertTrue({"beads_id", "kanban_id", "absolute_path", "credential"} <=
                        {row["kind"] for row in receipt["unclassified_findings"]})

    def test_public_scan_reports_missing_license_and_attribution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "tools/native_theme/fixtures/native-theme-v1-package.json"
            package.parent.mkdir(parents=True)
            package.write_text('{"metadata":{"license":{},"provenance":{}}}')
            receipt = self.h._public_scan(root)
        failed = {row["id"] for row in receipt["checks"] if not row["pass"]}
        self.assertIn("package.spdx", failed)
        self.assertIn("package.attribution", failed)
        self.assertEqual(receipt["status"], "FAIL")

    def test_public_scan_does_not_scan_scanner_literals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scanner = root / "tools/native_theme/sq01_harness.py"
            scanner.parent.mkdir(parents=True)
            scanner.write_text("api_key=/tmp/private Beads ID: sq-01 Kanban ID: KAN-42")
            receipt = self.h._public_scan(root)
        self.assertEqual(receipt["unclassified_findings"], [])

    def test_verdict_skip_count_recomputes_leaf_evidence_once(self):
        receipts = {
            "source-manifest.json": {"status": "FAIL", "skipped_required": 2},
            "profile-fixture-inventory.json": {"status": "FAIL", "uncovered": ["a", "b"]},
            "schema-validation.json": {"status": "FAIL", "negative_cases": [
                {"skipped_required": 1}, {"skipped_required": 0}]},
            "semantic-conformance.json": {"status": "FAIL", "skipped_required": 3},
            "mutation-results.json": {"status": "FAIL", "cases": [
                {"skipped_required": 1}, {"skipped_required": 1}]},
            "public-boundary-and-license-scan.json": {"status": "FAIL", "checks": [
                {"skipped_required": 1}, {"skipped_required": 0}]},
        }
        expected = 2 + 2 + 1 + 3 + 2 + 1
        self.assertEqual(self.h.skipped_required_evidence(receipts), expected)

    def test_receipt_hash_map_includes_manifest_and_five_components_only(self):
        receipts = {name: self.h.canonical_json_bytes({"name": name})
                    for name in self.h.VERDICT_INPUT_RECEIPTS}
        hashes = self.h.receipt_hash_map(receipts)
        self.assertEqual(set(hashes), set(self.h.VERDICT_INPUT_RECEIPTS))
        self.assertNotIn("verdict.json", hashes)

    def test_requirements_inventory_reports_exact_item_holes(self):
        inventory = self.h.build_requirements_inventory(ROOT)
        required = {row["id"] for row in inventory["rows"]}
        for prefix in ("role.light.", "type.", "diagnostic.", "derivation.", "schema.nativePackage."):
            item = next(value for value in required if value.startswith(prefix))
            evidenced = [dict(row, positive_case_ids=["executed-positive"],
                              negative_case_ids=["executed-negative"]) for row in inventory["rows"]]
            broken = self.h.evaluate_completeness(evidenced, omit_evidence_for={item})
            self.assertEqual(broken["status"], "FAIL")
            self.assertEqual(broken["uncovered"], [item])

    def test_inventory_never_fabricates_unexecuted_evidence(self):
        inventory = self.h.build_requirements_inventory(ROOT)
        self.assertEqual(inventory["status"], "FAIL")
        self.assertEqual(len(inventory["uncovered"]), len(inventory["rows"]))

    def test_executed_registry_is_complete_and_deterministic(self):
        first = self.h._inventory(ROOT)
        second = self.h._inventory(ROOT)
        self.assertEqual(self.h.canonical_json_bytes(first), self.h.canonical_json_bytes(second))
        self.assertEqual((len(first["rows"]), first["completeness_percent"], first["uncovered"],
                          first["skipped_required"], first["status"]),
                         (234, 100, [], 0, "PASS"))
        self.assertEqual(first["category_counts"], {"derivation": 8, "diagnostic": 19,
                         "layer": 3, "profile": 5, "role": 105, "schema": 86,
                         "type": 5, "variant": 3})
        self.assertEqual(first["executed_counts"], {"negative": 234, "positive": 234})
        self.assertEqual(len(first["case_registry"]), 468)
        self.assertTrue(all(c["pass"] and not c["skipped"] for c in first["case_registry"]))

    def test_deleting_each_category_polarity_exposes_exactly_one_row(self):
        receipt = self.h._inventory(ROOT)
        examples = {}
        for row in receipt["rows"]:
            examples.setdefault(row["id"].split(".", 1)[0], row)
        self.assertEqual(set(examples), {"schema", "role", "diagnostic", "derivation",
                                        "profile", "type", "layer", "variant"})
        for category, row in examples.items():
            for polarity in ("positive", "negative"):
                mutated = json.loads(json.dumps(receipt["case_registry"]))
                target = row[polarity + "_case_ids"][0]
                mutated = [case for case in mutated if case["id"] != target]
                checked = self.h.attach_registry_evidence(self.h.build_requirements_inventory(ROOT)["rows"], mutated)
                self.assertEqual(checked["uncovered"], [row["id"]], (category, polarity))

    def test_raw_negative_catalog_marker_never_dispatches_diagnostic(self):
        raw = json.loads((ROOT / "tools/native_theme/fixtures/profiles/dtcg-negative-cases.json").read_text())
        for item in raw if isinstance(raw, list) else raw.values():
            if isinstance(item, dict):
                self.assertIsNone(self.h.execute_diagnostic_rule("E_ALIAS_CYCLE", item))

    def test_inventory_resolves_roles_not_role_map_characters(self):
        inventory = self.h.build_requirements_inventory(ROOT)
        ids = {row["id"] for row in inventory["rows"]}
        self.assertIn("role.light.surface.canvas", ids)
        self.assertNotIn("role_map.c", ids)

    def test_semantic_legacy_mapping_does_not_require_light(self):
        semantic = load_module(ROOT / "tools/native_theme/sq01_semantic_validator.py", "sq01_semantic_test")
        package = json.loads((ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json").read_text())
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        oracle = json.loads((ROOT / "docs/native-theme-v1-legacy-oracle.json").read_text())
        result = semantic.validate(package, schema, oracle)
        self.assertNotIn("E_SETTINGS_MAPPING", {e["code"] for e in result["errors"]})

    def test_semantic_selection_thresholds_are_variant_specific(self):
        semantic = load_module(ROOT / "tools/native_theme/sq01_semantic_validator.py", "sq01_selection_thresholds")
        package = json.loads((ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json").read_text())
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        oracle = json.loads((ROOT / "docs/native-theme-v1-legacy-oracle.json").read_text())
        ordinary = json.loads(json.dumps(package))
        ordinary["variants"]["dark"]["semantic"]["interaction.selection"] = "#55406fff"
        errors = semantic.validate(ordinary, schema, oracle)["errors"]
        self.assertIn({"code": "E_CONTRAST_SELECTION", "detail": "dark"}, errors)
        high_contrast = json.loads(json.dumps(package))
        high_contrast["variants"]["high-contrast"]["semantic"]["interaction.selection"] = "#005fccff"
        errors = semantic.validate(high_contrast, schema, oracle)["errors"]
        self.assertIn({"code": "E_CONTRAST_SELECTION", "detail": "high-contrast"}, errors)

    def test_guarded_subprocess_rejects_unknown_and_shell(self):
        with self.assertRaises(PermissionError):
            self.h.run_allowed(["curl", "https://example.invalid"], ROOT)
        with self.assertRaises(PermissionError):
            self.h.run_allowed(["git", "status"], ROOT, shell=True)

    def test_child_python_network_probe_is_denied(self):
        result = self.h.run_child_network_probe(ROOT)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sq-01 network denied", result.stderr)

    def test_structural_bounds_are_executed_and_mutants_survive(self):
        receipt = self.h.execute_mutations(ROOT)
        bounds = [case for case in receipt["cases"] if case["expected_layer"] == "bounds"]
        self.assertEqual(len(bounds), 3)
        self.assertTrue(all(case["pass"] and case["validator_name"] == "sq01-declared-bounds-executor"
                            for case in bounds))
        for case_id, raw in self.h._bound_inputs().items():
            self.assertEqual(self.h._bounds_executor(b'{}', case_id)[1], "accepted")
            self.assertEqual(self.h._bounds_executor(raw, case_id)[1], "rejected")

    def test_repair_exact_roles_match_every_package_variant(self):
        semantic = load_module(ROOT / "tools/native_theme/sq01_semantic_validator.py", "sq01_roles")
        package = json.loads((ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json").read_text())
        self.assertEqual(len(semantic.ROLES), 35)
        for variant in package["variants"].values():
            self.assertEqual(semantic.ROLES, set(variant["semantic"]))

    def test_repair_public_scan_executes_and_passes_all_sixteen_checks(self):
        receipt = self.h._public_scan(ROOT)
        self.assertEqual((len(receipt["checks"]), sum(c["pass"] for c in receipt["checks"])), (16, 16))
        self.assertEqual(receipt["unclassified_findings"], [])
        self.assertEqual(receipt["status"], "PASS")

    def test_repair_coverage_temp_is_outside_output_and_removed(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "receipts"
            output.mkdir()
            (output / "stale").write_text("stale")
            source_manifest = {field: None for field in self.h.SOURCE_MANIFEST_FIELDS}
            source_manifest.update({"status": "PASS", "skipped_required": 0})
            source_manifest["machine_limit_contract"] = self.h.extract_machine_limit_contract(
                json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
            )
            with mock.patch.object(self.h, "source_identity", return_value=self.h.SourceIdentity("1" * 40, "2" * 40, ())):
                with mock.patch.object(self.h, "assert_source_identity"), mock.patch.object(
                        self.h, "_source_manifest", return_value=source_manifest), mock.patch.object(
                        self.h, "_inventory", return_value={"status": "PASS", "skipped_required": 0, "completeness_percent": 100, "uncovered": []}), mock.patch.object(
                        self.h, "_schema_validation", return_value={"status": "PASS", "skipped_required": 0, "negative_cases": []}), mock.patch.object(
                        self.h, "execute_mutations", return_value={"status": "PASS", "skipped_required": 0, "cases": [], "total": 37, "passed": 37, "failed": 0}), mock.patch.object(
                        self.h, "_public_scan", return_value={"status": "PASS", "skipped_required": 0, "checks": []}), mock.patch.object(
                        self.h, "_coverage", return_value={"tests": [], "modules": [], "function_coverage": {"covered": 1, "total": 1, "percent": 100}, "branch_coverage": {"covered": 1, "total": 1, "percent": 100}, "target_met": True}), mock.patch.dict(
                        "sys.modules", {"sq01_semantic_validator": types.SimpleNamespace(validate_paths=lambda *_: {"status": "PASS", "errors": []})}):
                    self.assertEqual(self.h.run_gate(ROOT, "1" * 40, output, safe_temp_root=Path(td)), 0)
            self.assertEqual({p.name for p in output.iterdir()}, set(self.h.ALL_RECEIPTS))

    def test_coverage_environment_measures_real_grandchild_module(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scripts").mkdir()
            native = root / "tools/native_theme"
            native.mkdir(parents=True)
            (native / "child_only.py").write_text("def child_only():\n    return 17\n\nchild_only()\n")
            (root / "scripts/test-native-theme-v1.py").write_text(
                "import subprocess, sys\n"
                "raise SystemExit(subprocess.run([sys.executable, 'tools/native_theme/child_only.py']).returncode)\n")
            temp = root / "private-coverage"
            temp.mkdir()
            runner = (
                "import importlib.util,json,sys; from pathlib import Path; "
                "p=Path(sys.argv[1]); s=importlib.util.spec_from_file_location('coverage_probe',p); "
                "h=importlib.util.module_from_spec(s); s.loader.exec_module(h); "
                "print(json.dumps(h._coverage_run(Path(sys.argv[2]),Path(sys.argv[3]),"
                "['scripts/test-native-theme-v1.py'])))"
            )
            env = dict(os.environ)
            env.pop("COVERAGE_PROCESS_START", None)
            env.pop("COVERAGE_FILE", None)
            result = subprocess.run([sys.executable, "-c", runner, str(ROOT / "tools/native_theme/sq01_harness.py"), str(root), str(temp)],
                                    cwd=root, env=env, check=True, capture_output=True, text=True)
            report = json.loads(result.stdout)
            row = next(item for item in report["modules"] if item["path"] == "tools/native_theme/child_only.py")
            self.assertEqual(row["statements"], {"covered": 3, "total": 3, "missing_lines": []})

    def test_coverage_config_is_exact_and_has_no_omissions(self):
        with tempfile.TemporaryDirectory() as td:
            config = self.h._write_coverage_support(Path(td))
            text = config.read_text()
        self.assertIn("source = tools/native_theme", text)
        self.assertIn("branch = true", text)
        self.assertIn("parallel = true", text)
        self.assertIn("relative_files = true", text)
        self.assertNotRegex(text, r"(?im)^\s*(omit|exclude_lines)\s*=")

    def test_coverage_missing_child_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(self.h, "run_allowed", return_value=subprocess.CompletedProcess([], 0, "", "")):
                with self.assertRaisesRegex(RuntimeError, "coverage data"):
                    self.h._coverage_run(ROOT, Path(td), ["scripts/test-native-theme-v1.py"])

    def test_coverage_support_is_private_and_cleaned_without_receipt_changes(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "receipts"
            output.mkdir()
            originals = {}
            for index, name in enumerate(self.h.ALL_RECEIPTS):
                raw = f"receipt-{index}".encode()
                (output / name).write_bytes(raw)
                originals[name] = raw
            private = base / "coverage-private"
            private.mkdir()
            self.assertFalse(private.is_relative_to(output))
            fake_parent = mock.Mock()
            fake_coverage = types.SimpleNamespace(Coverage=mock.Mock(return_value=fake_parent))
            with mock.patch.dict(sys.modules, {"coverage": fake_coverage}), mock.patch.object(
                    self.h, "_coverage_run", return_value={"target_met": True}):
                self.assertEqual(self.h._coverage(ROOT, private), {"target_met": True})
            fake_parent.start.assert_called_once_with()
            fake_parent.stop.assert_called_once_with()
            self.assertFalse(private.exists())
            self.assertEqual({name: (output / name).read_bytes() for name in originals}, originals)

    def test_coverage_semantic_validator_all_observable_rejections_and_paths(self):
        semantic = load_module(ROOT / "tools/native_theme/sq01_semantic_validator.py", "sq01_semantic_coverage")
        package = json.loads((ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json").read_text())
        schema = json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        oracle = json.loads((ROOT / "docs/native-theme-v1-legacy-oracle.json").read_text())
        result = semantic.validate_paths(ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json",
                                         ROOT / "tools/native_theme/native-theme-v1.schema.json",
                                         ROOT / "docs/native-theme-v1-legacy-oracle.json")
        self.assertEqual(result["status"], "PASS")
        with mock.patch.object(semantic, "jsonschema", None):
            self.assertEqual(semantic.validate(package, schema, oracle)["status"], "PASS")
        cases = [
            ("E_VARIANT_REQUIRED", lambda p, s, o: p["variants"].pop("light")),
            ("E_SEMANTIC_ROLES", lambda p, s, o: p["variants"]["dark"]["semantic"].pop("text.normal")),
            ("E_COLOR_CANONICAL", lambda p, s, o: p["variants"]["dark"]["semantic"].__setitem__("text.normal", "#FFFFFFff")),
            ("E_FOCUS_COLLAPSE", lambda p, s, o: p["variants"]["dark"]["semantic"].__setitem__("interaction.selection", p["variants"]["dark"]["semantic"]["border.focusConfirmed"])),
            ("E_CONTRAST_TEXT", lambda p, s, o: p["variants"]["dark"]["semantic"].__setitem__("text.normal", p["variants"]["dark"]["semantic"]["surface.canvas"])),
            ("E_CONTRAST_FOCUS", lambda p, s, o: p["variants"]["dark"]["semantic"].__setitem__("border.focusConfirmed", p["variants"]["dark"]["semantic"]["surface.canvas"])),
            ("E_CONTRAST_STATUS", lambda p, s, o: p["variants"]["dark"]["semantic"].__setitem__("status.danger", p["variants"]["dark"]["semantic"]["surface.canvas"])),
            ("E_STATUS_NONCOLOR", lambda p, s, o: p["variants"]["dark"]["assets"]["items"].pop("status.error")),
            ("E_ASSET_LICENSE", lambda p, s, o: p["variants"]["dark"]["assets"]["items"]["status.error"].__setitem__("spdx", "")),
            ("E_PROVENANCE", lambda p, s, o: p["metadata"]["provenance"].pop("attribution")),
            ("E_LEGACY_FOCUS", lambda p, s, o: o["policies"]["focus"].__setitem__("selection_target", o["policies"]["focus"]["confirmed_target"])),
            ("E_SETTINGS_MAPPING", lambda p, s, o: o["policies"]["settings_migration"].pop("Dark")),
            ("E_ORACLE_HASH", lambda p, s, o: o.__setitem__("semantic_sha256", "short")),
        ]
        for code, mutate in cases:
            p, s, o = json.loads(json.dumps(package)), json.loads(json.dumps(schema)), json.loads(json.dumps(oracle))
            mutate(p, s, o)
            with self.subTest(code=code):
                self.assertIn(code, {row["code"] for row in semantic.validate(p, s, o)["errors"]})

    def test_coverage_harness_identity_manifest_and_executor_edges(self):
        completed = subprocess.CompletedProcess([], 0, stdout=b"binary")
        with mock.patch.object(self.h, "run_allowed", return_value=completed) as guarded:
            self.assertEqual(self.h.git(ROOT, "diff", binary=True), b"binary")
            self.assertFalse(guarded.call_args.kwargs["text"])
        responses = ["?? artifacts/quality/sq-01/file\n M kept\n", "a" * 40 + "\n", "b" * 40 + "\n"]
        with mock.patch.object(self.h, "git", side_effect=responses):
            ident = self.h.source_identity(ROOT, ROOT / "artifacts/quality/sq-01")
        self.assertEqual(ident.dirty, (" M kept",))
        with mock.patch.object(self.h, "git", side_effect=["", "a" * 40, "b" * 40]):
            self.assertEqual(self.h.source_identity(ROOT).dirty, ())
        record = self.h._file_record(ROOT, ROOT / "versions.env")
        self.assertEqual(record["sha256"], self.h.sha256((ROOT / "versions.env").read_bytes()))
        with mock.patch.object(self.h, "git", side_effect=["", b"diff-bytes"]):
            manifest = self.h._source_manifest(ROOT, self.h.SourceIdentity("a" * 40, "b" * 40, ()))
        self.assertEqual((manifest["status"], manifest["tracked_files"]), ("PASS", []))
        self.assertEqual(manifest["machine_limit_contract"], self.h.extract_machine_limit_contract(
            json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
        ))
        raw_manifest = self.h.canonical_json_bytes(manifest)
        self.assertEqual(self.h.validate_source_manifest_bytes(raw_manifest), manifest)
        missing_contract = dict(manifest); missing_contract.pop("machine_limit_contract")
        with self.assertRaisesRegex(ValueError, "receipt fields differ"):
            self.h.validate_source_manifest_bytes(self.h.canonical_json_bytes(missing_contract))
        extra_contract = dict(manifest); extra_contract["extra"] = True
        with self.assertRaisesRegex(ValueError, "receipt fields differ"):
            self.h.validate_source_manifest_bytes(self.h.canonical_json_bytes(extra_contract))
        self.assertEqual(self.h._schema_property_rows({"$defs": {"x": None}}, "x"), [])
        self.assertEqual(self.h._bounds_executor(b"not-json", "bounds.overlong-string")[3], "E_BOUND_EXECUTOR")
        self.assertEqual(self.h._bounds_executor(b"{}", "unknown")[1], "accepted")
        with mock.patch.object(importlib.util, "spec_from_file_location", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "cannot load"):
                self.h._load_contract_validator(ROOT)
        self.assertEqual(self.h._contract_executor(ROOT, b"not-json", "package")[1], "executor-error")

    def test_coverage_harness_registry_scan_and_fail_closed_edges(self):
        with mock.patch.dict(self.h.REQUIRED_MUTATIONS, {"synthetic.unimplemented": ("x", "E_X")}):
            receipt = self.h.execute_mutations(ROOT)
        skipped = next(row for row in receipt["cases"] if row["id"] == "synthetic.unimplemented")
        self.assertTrue(skipped["skipped"])
        with self.assertRaisesRegex(ValueError, "receipt hash inputs differ"):
            self.h.receipt_hash_map({})
        with tempfile.TemporaryDirectory() as td:
            duplicate = Path(td) / "duplicate.json"; duplicate.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, "E_JSON_DUPLICATE"): self.h._strict_load(duplicate)
        self.assertEqual(self.h._resolve_path({"rows": [{"value": 7}]}, ["rows", "[]", "value"]), 7)
        rows = [{"id": "schema.nativePackage.schema_version:optional", "_definition": "nativePackage",
                 "_property_path": ["schema_version"], "_mode": "optional"}]
        with self.assertRaisesRegex(RuntimeError, "optional schema row"):
            self.h._schema_registry_cases(ROOT, rows)
        self.assertIsNone(self.h.execute_diagnostic_rule("E_HASH", {"actual": 1, "expected": 1}))
        self.assertIsNone(self.h.execute_diagnostic_rule("E_HASH", None))
        self.assertIsNone(self.h.execute_diagnostic_rule("UNKNOWN", {}))
        checked = self.h.attach_registry_evidence([{"id": "r", "positive_case_ids": [], "negative_case_ids": []}],
                                                   [{"pass": False, "skipped": False}])
        self.assertEqual(checked["uncovered"], ["r"])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); fixture = root / "docs/native-theme-v1-large.md"; fixture.parent.mkdir()
            fixture.write_bytes(b"x" * 2_000_001)
            scan = self.h._public_scan(root)
        self.assertIn("docs/native-theme-v1-large.md", scan["scope"])
        self.assertEqual(scan["unclassified_findings"], [])
        self.assertTrue(all(check["skipped"] for check in scan["checks"]))
        self.assertEqual(scan["status"], "FAIL")
        with mock.patch.object(importlib.metadata, "version", return_value="wrong"):
            with self.assertRaisesRegex(RuntimeError, "dependency version mismatch"):
                self.h.run_gate(ROOT, "a" * 40, Path(tempfile.gettempdir()) / "sq01-never-created", safe_temp_root=Path(tempfile.gettempdir()))

    def test_coverage_derivation_fallback_and_coverage_report_iteration(self):
        original_load = self.h._strict_load
        def altered(path):
            value = original_load(path)
            if path.name == "native-theme-v1-legacy-oracle.json":
                value["policies"]["legacy_token_roles"] = {}
            return value
        with mock.patch.object(self.h, "_strict_load", side_effect=altered):
            cases = self.h._derivation_registry_cases(ROOT, [{"id": "derivation.unknown"}])
        self.assertEqual(cases[1]["actual_code"], "E_DERIVATION_MISMATCH")

        with tempfile.TemporaryDirectory() as td:
            root, temp = Path(td) / "root", Path(td) / "coverage"
            root.mkdir(); temp.mkdir(); (root / "mod.py").write_text("def hit():\n    return 1\n\ndef missed():\n    return 2\n")
            (temp / ".coverage-sq01.part").write_text("data")
            report = {"files": {"mod.py": {"executed_lines": [2], "missing_lines": [5],
                      "summary": {"covered_lines": 2, "num_statements": 4, "num_branches": 0,
                                  "covered_branches": 0, "missing_branches": 0}, "missing_branches": []}}}
            class Measured:
                def combine(self, **_kwargs): pass
                def load(self): pass
                def json_report(self, outfile): Path(outfile).write_text(json.dumps(report))
            fake = types.SimpleNamespace(Coverage=lambda **_kwargs: Measured(), CoverageException=Exception)
            with mock.patch.dict(sys.modules, {"coverage": fake}):
                result = self.h._coverage_run(root, temp, [], ("mod.py",))
        rows = result["modules"][0]["functions"]
        self.assertEqual([(row["name"], row["covered"]) for row in rows], [("hit", True), ("missed", False)])

    def test_coverage_run_gate_marks_failed_coverage_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "receipts"
            passing = {"status": "PASS", "skipped_required": 0}
            source_passing = {field: None for field in self.h.SOURCE_MANIFEST_FIELDS}
            source_passing.update(passing)
            source_passing["machine_limit_contract"] = self.h.extract_machine_limit_contract(
                json.loads((ROOT / "tools/native_theme/native-theme-v1.schema.json").read_text())
            )
            with mock.patch.object(self.h.importlib.metadata, "version", side_effect=lambda name: self.h.PINNED[name]), mock.patch.object(
                    self.h, "source_identity", return_value=self.h.SourceIdentity("1" * 40, "2" * 40, ())), mock.patch.object(
                    self.h, "assert_source_identity"), mock.patch.object(self.h, "_source_manifest", return_value=source_passing), mock.patch.object(
                    self.h, "_inventory", return_value={**passing, "completeness_percent": 100}), mock.patch.object(
                    self.h, "_schema_validation", return_value=passing.copy()), mock.patch.object(
                    self.h, "execute_mutations", return_value={**passing, "cases": [], "total": 37, "passed": 37, "failed": 0}), mock.patch.object(
                    self.h, "_public_scan", return_value=passing.copy()), mock.patch.object(
                    self.h, "_coverage", return_value={"tests": [], "modules": [], "function_coverage": {"covered": 0, "total": 1}, "branch_coverage": {"covered": 0, "total": 1}, "target_met": False}), mock.patch.dict(
                    sys.modules, {"sq01_semantic_validator": types.SimpleNamespace(validate_paths=lambda *_: {"status": "PASS", "errors": []})}):
                self.assertEqual(self.h.run_gate(ROOT, "1" * 40, output, safe_temp_root=Path(td)), 1)
            mutation = json.loads((output / "mutation-results.json").read_text())
            self.assertTrue(mutation["coverage_failure"])


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main(verbosity=2)

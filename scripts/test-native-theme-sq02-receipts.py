#!/usr/bin/env python3
"""Negative tests for the independent SQ-02 receipt verifier."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))
import sq02_receipt_verifier as v  # noqa: E402


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def mapping() -> list[dict[str, object]]:
    rows = []
    for operator in v.OPERATORS:
        accepted = operator in ("byte-flip", "valid-inert-metadata")
        python_code: object = None if accepted else "E_JSON_NONCANONICAL"
        rust_code: object = python_code
        if operator == "hash-tamper":
            python_code, rust_code = "E_PROVENANCE", "E_HASH"
        if operator == "provenance-tamper":
            python_code, rust_code = "E_PROVENANCE", "E_IDENTITY"
        rows.append({"mutation_operator": operator, "python_accepted": [accepted],
                     "python_codes": [python_code], "rust_accepted": [accepted], "rust_codes": [rust_code]})
    return rows


def fixture() -> dict[str, dict[str, object]]:
    sha, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    files = git("ls-files").splitlines()
    tracked = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    isolation = {"child_raw_socket_blocked": True, "error_class": "ENETUNREACH", "namespace_changed": True,
                 "namespace_mode": "unprivileged-user-network", "parent_identity_compared": True}
    binary = "0" * 64
    manifest = {
        "authority": "non-authoritative-harness", "base_sha": "036944123fa15d5b5fac5718899b08a44691727c",
        "command_schema": "repository command v1", "environment": {"CARGO_NET_OFFLINE": "true", "LANG": "C", "LC_ALL": "C",
        "NATIVE_THEME_SQ02_NETWORK": "deny", "PYTHONHASHSEED": "0", "RUSTUP_NO_UPDATE_CHECK": "1", "TZ": "UTC"},
        "fuchsia_pinned_revision": "7f75b7f6ffdacf5a818dd8d207263edd45126ddd", "os_isolation": isolation,
        "python_dependencies": {"coverage": "7.6.12", "jsonschema": "4.25.1"}, "python_version": "3.12.9",
        "source_sha": sha, "source_tree": tree,
        "toolchain": {"cargo": {"binary_sha256": binary, "name": "cargo", "version": "cargo 1.99.0-nightly"},
                      "origin": "project-fuchsia-prebuilt", "rust_channel": "nightly-2026-08-13",
                      "rustc": {"binary_sha256": binary, "name": "rustc", "version": "rustc 1.99.0-nightly"}},
        "tracked_source_hashes": tracked,
    }
    packages = [{"bytes": 10000 + index, "file": f"package-{index}.json", "id": f"package-{index}",
                 "semantic_sha256": f"{index + 1:064x}", "sha256": f"{index + 10:064x}"} for index in range(5)]
    parity = {"diagnostic_mapping": mapping(), "package_count": 5, "packages": packages,
              "python_rust_corpus_accepted": 32, "python_rust_corpus_executed": 256,
              "python_rust_corpus_rejected": 224, "requirement_ids": list(v.REQUIREMENTS),
              "rust_record_sha256": "1" * 64, "schema_version": "sq02-cross-language-parity-v1", "status": "PASS"}
    manifest["qualification_inputs"] = {"catalog": {"catalog-index.json": {"bytes": 1, "sha256": "7" * 64}},
                                        "corpus_bytes_sha256": "8" * 64, "corpus_manifest_sha256": "3" * 64,
                                        "packages": packages, "rust_record_sha256": "1" * 64}
    fuzz = {"duplicate_hashes": 0, "duplicate_ids": 0, "executed": 256, "generator_source_sha256": "2" * 64,
            "generator_version": "sq02-corpus-v1", "manifest_sha256": "3" * 64,
            "operator_counts": {operator: 16 for operator in v.OPERATORS}, "python_rust_parity": 256,
            "seed": 0, "skipped": 0, "total_generated": 256}
    accepted = lambda size: {"accepted": True, "code": None, "layer": "accepted", "package_sha256": "4" * 64,
                             "semantic_sha256": "5" * 64}
    rows = [{"bytes": 262143, "compiler": accepted(262143), "contract": accepted(262143)},
            {"bytes": 262144, "compiler": accepted(262144), "contract": accepted(262144)},
            {"bytes": 262145, "compiler": {"accepted": False, "code": "E_CANONICAL_SIZE", "layer": "compiler"},
             "contract": {"accepted": False, "code": "E_LIMIT_PACK", "layer": "bounds"}}]
    bounds = {"dominated_relations": [{"dominated": "runtime_snapshot_bytes", "proof": "compiled_pack_bytes <= runtime_snapshot_bytes",
                                        "stricter": "compiled_pack_bytes"}],
              "limits": {"assets": 64, "catalog_bytes": 8388608, "compiled_pack_bytes": 262144, "receipt_bytes": 16384,
                         "runtime_snapshot_bytes": 524288, "source_bytes": 1048576, "string_bytes": 4096, "tokens": 1024},
              "observations": {"catalog_bytes": 100000, "executed_asset_plus_one_cases": 16,
                               "executed_string_plus_one_or_more_cases": 16, "executed_token_plus_one_cases": 16,
                               "largest_catalog_receipt_bytes": 1000, "largest_package_bytes": 20000,
                               "largest_source_bytes": 2000},
              "rows": rows, "runtime_accounting": "same-retained-canonical-bytes-no-second-snapshot",
              "rust_rows": [{"accepted": True, "bytes": 262143, "code": None},
                            {"accepted": True, "bytes": 262144, "code": None},
                            {"accepted": False, "bytes": 262145, "code": "E_LIMIT_PACK"}],
              "schema_version": "sq02-resource-bounds-v1", "status": "PASS"}
    metric = {"branches_covered": 1, "branches_total": 1, "functions_with_body_execution": 1,
              "functions_total": 1, "statements_covered": 1, "statements_total": 1}
    coverage = {"claim_scope": "Python safety-bearing statement/branch/function execution; Rust requirement completeness only",
                "machine_artifact_sha256": "6" * 64,
                "production_modules": {"gate": "established-source-bound", "reported_separately": True},
                "python_safety_modules": {"tools/native_theme/sq02_harness.py": metric,
                                          "tools/native_theme/sq02_receipt_verifier.py": copy.deepcopy(metric)},
                "rust_claim": "executed-requirement-ID-completeness-not-source-or-function-coverage",
                "rust_requirement_ids": list(v.REQUIREMENTS), "schema_version": "sq02-coverage-v1", "status": "PASS"}
    reproducible = {"archive_materializations": 2, "cargo_binary_equality_required": False,
                    "comparisons": {"catalog_equal": True, "corpus_bytes_equal": True, "corpus_manifest_equal": True,
                                    "package_bytes_equal": True, "rust_payload_equal": True},
                    "schema_version": "sq02-reproducible-builds-v1", "status": "PASS"}
    scan = {"bounded_lexical_scan": True, "catalog_copy_only": True, "catalog_entry_count": 4,
            "audited_authority_files": ["scripts/run-native-theme-sq02.py"], "changed_files_scanned": 13,
            "findings": [], "fuchsia_forbidden_edges": [], "qualification_testonly": True, "receipts_scanned": 8,
            "schema_version": "sq02-package-catalog-scan-v1", "status": "PASS", "tracked_files_considered": len(files)}
    values = dict(zip(v.INPUTS, (manifest, parity, fuzz, bounds, coverage, reproducible, scan)))
    raw = {name: v.canonical(values[name]) for name in v.INPUTS}
    values["verdict.json"] = {"authority": "non-authoritative-harness", "cheapest_next_proof": "parent then independent tester",
                              "claims_excluded": ["deploy", "independent approval", "merge", "Product Assembly/runtime inclusion", "release"],
                              "failure_classification": None, "receipt_hashes": {name: v.digest(raw[name]) for name in v.INPUTS},
                              "required_skips": 0, "residual_risks": ["parent target gap"], "root_cause_status": "none",
                              "source_sha": sha, "source_tree": tree, "status": "PASS"}
    return values


def write(directory: Path, values: dict[str, dict[str, object]], *, overrides: dict[str, bytes] | None = None) -> None:
    directory.mkdir()
    for name in v.RECEIPTS:
        raw = (overrides or {}).get(name, v.canonical(values[name]))
        (directory / name).write_bytes(raw)


class ReceiptTests(unittest.TestCase):
    def assert_bad(self, function, *args):
        with self.assertRaises(v.ReceiptError):
            function(*args)

    def test_helper_and_every_manifest_rejection_branch(self):
        self.assert_bad(v.canonical, {"x": object()})
        self.assert_bad(v.parse, b"[]\n", "array")
        self.assert_bad(v.exact, [], {"x"}, "exact")
        self.assert_bad(v.integer, True, "integer")
        self.assert_bad(v.integer, -1, "integer")
        self.assert_bad(v.text, "", "text")
        self.assert_bad(v.hash_text, "x", "hash")
        self.assert_bad(v.git, ROOT, "push")
        base = fixture()["source-toolchain-manifest.json"]
        sha, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        mutations = []
        for path, replacement in (
            (("base_sha",), "0" * 40), (("fuchsia_pinned_revision",), "0" * 40),
            (("python_dependencies",), {}), (("environment", "TZ"), "local"),
            (("os_isolation", "namespace_changed"), False), (("os_isolation", "namespace_mode"), "none"),
            (("toolchain", "rust_channel"), "nightly"), (("toolchain", "origin"), "unknown"),
            (("toolchain", "cargo", "name"), "other"), (("toolchain", "rustc", "version"), "rustc unknown"),
            (("tracked_source_hashes",), {}), (("qualification_inputs", "catalog"), []),
        ):
            value = copy.deepcopy(base); cursor = value
            for key in path[:-1]: cursor = cursor[key]
            cursor[path[-1]] = replacement; mutations.append(value)
        value = copy.deepcopy(base); first = next(iter(value["tracked_source_hashes"])); value["tracked_source_hashes"][first] = "f" * 64; mutations.append(value)
        value = copy.deepcopy(base); value["qualification_inputs"]["catalog"] = {"../bad": {"bytes": 1, "sha256": "0" * 64}}; mutations.append(value)
        for value in mutations:
            self.assert_bad(v._manifest, ROOT, value, sha, tree)

    def test_every_component_rejection_branch(self):
        values = fixture()
        parity = values["cross-language-parity.json"]
        parity_mutations = []
        for mutate in (
            lambda x: x.update(status="FAIL"), lambda x: x.update(package_count=4),
            lambda x: x["packages"][0].update(file="../bad"),
            lambda x: x["packages"][1].update(id=x["packages"][0]["id"]),
            lambda x: x.update(diagnostic_mapping=[]),
            lambda x: x["diagnostic_mapping"][0].update(rust_accepted=[not x["diagnostic_mapping"][0]["python_accepted"][0]]),
            lambda x: x["diagnostic_mapping"][0].update(python_codes=[]),
            lambda x: x["diagnostic_mapping"][0].update(python_codes=["E_ONE"], rust_codes=["E_TWO"]),
            lambda x: x.update(python_rust_corpus_executed=255),
            lambda x: x.update(requirement_ids=list(v.REQUIREMENTS[:-1])),
        ):
            item = copy.deepcopy(parity); mutate(item); parity_mutations.append(item)
        for item in parity_mutations: self.assert_bad(v._parity, item)

        fuzz = values["fuzz-corpus-manifest.json"]
        for mutate in (
            lambda x: x.update(duplicate_ids=1), lambda x: x.update(seed=1),
            lambda x: x.update(executed=255), lambda x: x.update(executed=257),
            lambda x: x.update(operator_counts={}),
        ):
            item = copy.deepcopy(fuzz); mutate(item); self.assert_bad(v._fuzz, item, parity)
        other_parity = copy.deepcopy(parity); other_parity["python_rust_corpus_executed"] = 255
        self.assert_bad(v._fuzz, fuzz, other_parity)

        bounds = values["resource-bounds.json"]
        for mutate in (
            lambda x: x.update(status="FAIL"), lambda x: x.update(limits={}),
            lambda x: x.update(runtime_accounting="rss"), lambda x: x.update(dominated_relations=[]),
            lambda x: x["observations"].update(catalog_bytes=999999999),
            lambda x: x["observations"].update(executed_asset_plus_one_cases=15),
            lambda x: x.update(rows=[]), lambda x: x["rows"][0]["contract"].update(accepted=False),
            lambda x: x["rows"][2]["compiler"].update(code="E_OTHER"),
            lambda x: x["rust_rows"][2].update(code="E_OTHER"),
        ):
            item = copy.deepcopy(bounds); mutate(item); self.assert_bad(v._bounds, item)

        coverage = values["coverage.json"]
        for mutate in (
            lambda x: x.update(status="FAIL"), lambda x: x.update(claim_scope="overclaim"),
            lambda x: x.update(production_modules={}), lambda x: x.update(python_safety_modules={}),
            lambda x: x["python_safety_modules"]["tools/native_theme/sq02_harness.py"].update(statements_total=0),
            lambda x: x["python_safety_modules"]["tools/native_theme/sq02_harness.py"].update(statements_covered=0),
            lambda x: x.update(rust_claim="line coverage"),
        ):
            item = copy.deepcopy(coverage); mutate(item); self.assert_bad(v._coverage, item)

    def test_repro_scan_verdict_and_cross_receipt_rejections(self):
        values = fixture()
        reproducible = values["reproducible-builds.json"]
        item = copy.deepcopy(reproducible); item["archive_materializations"] = 1; self.assert_bad(v._reproducible, item)
        item = copy.deepcopy(reproducible); item["comparisons"]["catalog_equal"] = False; self.assert_bad(v._reproducible, item)
        scan = values["package-and-catalog-scan.json"]
        item = copy.deepcopy(scan); item["status"] = "FAIL"; self.assert_bad(v._scan, item)
        item = copy.deepcopy(scan); item["catalog_entry_count"] = 3; self.assert_bad(v._scan, item)
        item = copy.deepcopy(scan); item["audited_authority_files"] = ["../bad"]; self.assert_bad(v._scan, item)
        raw = {name: v.canonical(values[name]) for name in v.INPUTS}
        verdict = values["verdict.json"]
        for mutate in (
            lambda x: x.update(status="FAIL"), lambda x: x.update(required_skips=1),
            lambda x: x.update(claims_excluded=[]), lambda x: x.update(residual_risks=[]),
            lambda x: x.update(receipt_hashes={}),
            lambda x: x["receipt_hashes"].update({v.INPUTS[0]: "f" * 64}),
        ):
            item = copy.deepcopy(verdict); mutate(item)
            self.assert_bad(v._verdict, item, raw, verdict["source_sha"], verdict["source_tree"])
        def package_cross_mutation(value):
            value["qualification_inputs"]["packages"] = copy.deepcopy(value["qualification_inputs"]["packages"])
            value["qualification_inputs"]["packages"][0]["id"] = "changed"
        for receipt, mutate in (
            ("source-toolchain-manifest.json", package_cross_mutation),
            ("fuzz-corpus-manifest.json", lambda x: x.update(manifest_sha256="f" * 64)),
        ):
            changed = fixture(); mutate(changed[receipt])
            with tempfile.TemporaryDirectory() as td:
                directory = Path(td) / "receipts"; write(directory, changed)
                self.assert_bad(v.verify_directory, ROOT, directory)

    def test_valid_exact_eight_receipts(self):
        values = fixture()
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td) / "receipts"; write(directory, values)
            parsed = v.verify_directory(ROOT, directory)
        self.assertEqual(len(parsed), 8)

    def test_duplicate_noncanonical_private_and_extra_receipts_fail(self):
        values = fixture()
        bad_inputs = (
            b'{"a":1,"a":2}\n', b'{"a": 1}\n',
            b'{"path":"/' + b'home/example/private"}\n', b'{"a":1}', b'\xff\n')
        for raw in bad_inputs:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as td:
                directory = Path(td) / "receipts"; write(directory, values, overrides={v.RECEIPTS[0]: raw})
                with self.assertRaises(v.ReceiptError): v.verify_directory(ROOT, directory)
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td) / "receipts"; write(directory, values); (directory / "extra.json").write_text("{}\n")
            with self.assertRaises(v.ReceiptError): v.verify_directory(ROOT, directory)

    def test_nested_counts_requirements_coverage_and_bounds_fail(self):
        mutations = []
        value = fixture(); value["fuzz-corpus-manifest.json"]["operator_counts"][v.OPERATORS[0]] = 15; mutations.append(value)
        value = fixture(); value["cross-language-parity.json"]["requirement_ids"] = list(v.REQUIREMENTS[:-1]); mutations.append(value)
        value = fixture(); value["coverage.json"]["python_safety_modules"]["tools/native_theme/sq02_harness.py"]["branches_covered"] = 0; mutations.append(value)
        value = fixture(); value["resource-bounds.json"]["rust_rows"][2]["code"] = "E_OTHER"; mutations.append(value)
        value = fixture(); value["reproducible-builds.json"]["comparisons"]["catalog_equal"] = False; mutations.append(value)
        value = fixture(); value["package-and-catalog-scan.json"]["findings"] = [{"code": "E_SECRET"}]; mutations.append(value)
        for index, values in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as td:
                directory = Path(td) / "receipts"; write(directory, values)
                with self.assertRaises(v.ReceiptError): v.verify_directory(ROOT, directory)

    def test_stale_source_unknown_tool_and_cross_hash_fail(self):
        variants = []
        values = fixture(); values["source-toolchain-manifest.json"]["source_sha"] = "f" * 40; variants.append(values)
        values = fixture(); values["source-toolchain-manifest.json"]["toolchain"]["rustc"]["version"] = "rustc unknown"; variants.append(values)
        values = fixture(); values["verdict.json"]["receipt_hashes"][v.INPUTS[0]] = "f" * 64; variants.append(values)
        values = fixture(); values["verdict.json"]["receipt_hashes"]["verdict.json"] = "0" * 64; variants.append(values)
        for index, values in enumerate(variants):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as td:
                directory = Path(td) / "receipts"; write(directory, values)
                with self.assertRaises(v.ReceiptError): v.verify_directory(ROOT, directory)


if __name__ == "__main__":
    unittest.main(verbosity=2)

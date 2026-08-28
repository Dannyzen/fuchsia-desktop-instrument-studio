#!/usr/bin/env python3
"""Executable contract tests for the deterministic NativeTheme catalog."""

from __future__ import annotations

import ast
import copy
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
NATIVE_THEME = ROOT / "tools/native_theme"
TOOL = NATIVE_THEME / "catalog.py"
DESCRIPTOR = NATIVE_THEME / "catalog/catalog-source.json"
GENERATED = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog/catalog"
BUILD = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog/BUILD.gn"
sys.path.insert(0, str(NATIVE_THEME))


def load_catalog():
    spec = importlib.util.spec_from_file_location("native_theme_catalog", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


catalog = load_catalog()


class BinaryOutput:
    def __init__(self):
        self.buffer = io.BytesIO()

    def write(self, value):
        return len(value)

    def flush(self):
        return None


class CatalogContractTests(unittest.TestCase):
    maxDiff = None
    mutation_count = 0

    @classmethod
    def setUpClass(cls):
        cls.descriptor_raw = DESCRIPTOR.read_bytes()
        cls.descriptor = catalog.parse_descriptor_bytes(cls.descriptor_raw)
        cls.sources = {
            entry["source_path"]: (ROOT / entry["source_path"]).read_bytes()
            for entry in cls.descriptor["entries"]
        }
        template_path = cls.descriptor["template_path"]
        cls.sources[template_path] = (ROOT / template_path).read_bytes()
        cls.expected = catalog.generate_catalog(cls.descriptor, cls.sources)
        cls.actual = {name: (GENERATED / name).read_bytes() for name in cls.expected}

    def assert_code(self, code, function, *args):
        type(self).mutation_count += 1
        with self.assertRaises(catalog.CatalogError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(caught.exception.message)
        self.assertEqual(str(caught.exception), f"{code}: {caught.exception.message}")
        return caught.exception

    @classmethod
    def tearDownClass(cls):
        print(f"catalog mutation gates: {cls.mutation_count}", file=sys.stderr)

    def descriptor_bytes(self, value):
        return catalog.canonical_json_bytes(value) + b"\n"

    def mutate_descriptor(self, mutation, code):
        value = copy.deepcopy(self.descriptor)
        mutation(value)
        self.assert_code(code, catalog.parse_descriptor_bytes, self.descriptor_bytes(value))

    def test_red_was_missing_tool_then_checked_in_generation_is_exact_and_repeatable(self):
        first = catalog.generate_catalog(self.descriptor, self.sources)
        second = catalog.generate_catalog(copy.deepcopy(self.descriptor), dict(self.sources))
        self.assertEqual(first, second)
        self.assertEqual(self.actual, first)
        for raw in first.values():
            self.assertEqual(raw, catalog.canonical_json_bytes(json.loads(raw)) + b"\n")

    def test_accepted_hashes_and_four_semantically_equal_profiles(self):
        accepted = "sha256:5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a"
        index = json.loads(self.actual["catalog-index.json"])
        self.assertEqual(index["schema_version"], catalog.CATALOG_SCHEMA)
        self.assertEqual(
            [entry["id"] for entry in index["entries"]],
            ["instrument-studio-base16", "instrument-studio-base24",
             "instrument-studio-dtcg", "instrument-studio-omarchy"],
        )
        self.assertEqual({entry["semantic_hash"] for entry in index["entries"]}, {accepted})
        expected_sources = {
            "instrument-studio-base16": "sha256:22a25a494702c1d51888c5d14bcadf5809502adc4fc9808407e806cf627d0619",
            "instrument-studio-base24": "sha256:1a04aade003c9b8582afd61ed9585deebb69521889fce340e3f6ad994ef15119",
            "instrument-studio-dtcg": "sha256:1c8b07fb5d159258e4f9501dd5ecc47e807440bb7946cb203554eccb44444dc1",
            "instrument-studio-omarchy": "sha256:f64f3f08fa4e54e82e48d75897b8667bd2c24d9d476122c390bb96fa53eeabcc",
        }
        self.assertEqual({entry["id"]: entry["source_hash"] for entry in index["entries"]}, expected_sources)
        self.assertEqual(index["budgets"], self.descriptor["budgets"])
        self.assertEqual(index["aggregate"], {
            "asset_count": 20,
            "entry_count": 4,
            "largest_decoded_asset_bytes": 4096,
            "package_bytes": sum(len(self.actual[f"{entry['id']}.package.json"])
                                 for entry in self.descriptor["entries"]),
            "receipt_bytes": sum(len(self.actual[f"{entry['id']}.receipt.json"])
                                 for entry in self.descriptor["entries"]),
            "token_count": 684,
            "total_decoded_asset_bytes": 245760,
        })
        entry_keys = {
            "adapter", "attribution", "compiler_version", "id", "license_spdx", "notice",
            "package_file", "package_hash", "package_schema_version", "profile_version",
            "receipt_file", "receipt_hash", "semantic_hash", "source_format", "source_hash",
            "source_identity",
        }
        for entry in index["entries"]:
            self.assertEqual(set(entry), entry_keys)
            self.assertEqual(entry["license_spdx"], "BSD-3-Clause")
            self.assertEqual(entry["compiler_version"], catalog.SUPPORTED_COMPILER_VERSION)
            self.assertEqual(entry["package_schema_version"], catalog.SUPPORTED_PACKAGE_SCHEMA)
            self.assertTrue(entry["attribution"])
            self.assertTrue(entry["notice"])

    def test_inspect_and_compare_schemas_separate_metadata_from_rendering(self):
        packages = [self.actual[f"{entry['id']}.package.json"] for entry in self.descriptor["entries"]]
        inspected = catalog.inspect_package(packages[0])
        self.assertEqual(set(inspected), {
            "attribution", "compiler_version", "license", "metrics", "package_hash",
            "package_schema_version", "profile", "schema_version", "semantic_hash", "source",
            "theme", "token_provenance_counts", "variants",
        })
        self.assertEqual(inspected["schema_version"], "native-theme-inspect-v1")
        self.assertEqual(inspected["package_hash"], catalog._hash(packages[0]))
        package = json.loads(packages[0])
        self.assertEqual(inspected["profile"], package["profile"])
        self.assertEqual(inspected["theme"], package["theme"])
        self.assertEqual(inspected["source"], {
            "content_hash": package["metadata"]["provenance"]["content_hash"],
            "format": package["metadata"]["provenance"]["source_format"],
            "identity": package["metadata"]["provenance"]["source_identity"],
            "profile_version": package["metadata"]["provenance"]["profile_version"],
        })
        self.assertEqual(set(inspected["metrics"]), {
            "asset_count", "largest_decoded_asset_bytes", "token_count",
            "total_decoded_asset_bytes",
        })
        self.assertEqual(set(inspected["token_provenance_counts"]),
                         {"derived", "explicit", "inherited", "total"})
        self.assertEqual(inspected["token_provenance_counts"]["total"], sum(
            inspected["token_provenance_counts"][kind]
            for kind in ("explicit", "inherited", "derived")))
        self.assertNotIn("tokens", json.dumps(inspected))
        for right in packages[1:]:
            comparison = catalog.compare_packages(packages[0], right)
            self.assertEqual(set(comparison), {
                "inert_metadata_differences", "left", "renderable_differences", "right",
                "schema_version", "semantically_equal",
            })
            self.assertEqual(set(comparison["left"]), {"package_hash", "semantic_hash"})
            self.assertEqual(set(comparison["right"]), {"package_hash", "semantic_hash"})
            self.assertEqual(comparison["left"]["package_hash"], catalog._hash(packages[0]))
            self.assertEqual(comparison["right"]["package_hash"], catalog._hash(right))
            self.assertEqual(comparison["schema_version"], "native-theme-compare-v1")
            self.assertTrue(comparison["semantically_equal"])
            self.assertEqual(comparison["renderable_differences"], [])
            pointers = [item["pointer"] for item in comparison["inert_metadata_differences"]]
            self.assertEqual(pointers, sorted(pointers))
            self.assertTrue(all(pointer.startswith("/metadata/") for pointer in pointers))

        left = json.loads(packages[0])
        metadata = copy.deepcopy(left)
        metadata["metadata"]["provenance"]["attribution"] = "Alternate BSD attribution"
        metadata_diff = catalog.compare_packages(left, metadata)
        self.assertTrue(metadata_diff["semantically_equal"])
        self.assertEqual(metadata_diff["renderable_differences"], [])
        self.assertEqual(metadata_diff["inert_metadata_differences"][0]["pointer"],
                         "/metadata/provenance/attribution")

        rendered = copy.deepcopy(left)
        rendered["theme"]["display_name"] = "Instrument Studio Alternate"
        rendered["metadata"]["provenance"]["semantic_hash"] = catalog.package_semantic_identity(rendered)
        render_diff = catalog.compare_packages(left, rendered)
        self.assertFalse(render_diff["semantically_equal"])
        self.assertEqual(render_diff["renderable_differences"][0]["pointer"], "/theme/display_name")

        with mock.patch.object(catalog, "package_semantic_identity",
                               return_value="sha256:" + "1" * 64):
            self.assert_code("E_COMPARE_SEMANTIC", catalog.compare_packages, left, rendered)
        with mock.patch.object(catalog, "package_semantic_identity",
                               side_effect=["sha256:" + "1" * 64, "sha256:" + "2" * 64]):
            self.assert_code("E_COMPARE_SEMANTIC", catalog.compare_packages, left, left)

    def test_descriptor_expected_hashes_are_final_nonzero_and_mutation_sensitive(self):
        zero = "sha256:" + "0" * 64
        for entry in self.descriptor["entries"]:
            package = self.actual[f"{entry['id']}.package.json"]
            receipt = self.actual[f"{entry['id']}.receipt.json"]
            for field, raw in (("package_hash", package), ("receipt_hash", receipt)):
                expected = entry["expected"][field]
                self.assertNotEqual(expected, zero)
                self.assertEqual(expected, catalog._hash(raw))
                self.assertNotEqual(expected, catalog._hash(raw + b"mutated"))

    def test_descriptor_mutation_matrix(self):
        cases = [
            (lambda d: d.__setitem__("extra", True), "E_DESCRIPTOR_FIELDS"),
            (lambda d: d.__setitem__("schema_version", "future"), "E_VERSION_DESCRIPTOR"),
            (lambda d: d.__setitem__("compiler_version", "future"), "E_VERSION_COMPILER"),
            (lambda d: d.__setitem__("package_schema_version", "future"), "E_VERSION_SCHEMA"),
            (lambda d: d.__setitem__("template_path", "/private/template"), "E_PATH_OUTSIDE_ROOT"),
            (lambda d: d.__setitem__("template_path", "a/../template"), "E_PATH_TRAVERSAL"),
            (lambda d: d.__setitem__("template_path", "a/./b"), "E_PATH_TRAVERSAL"),
            (lambda d: d.__setitem__("template_path", "a//b"), "E_PATH_TRAVERSAL"),
            (lambda d: d.__setitem__("template_path", "a/b/"), "E_PATH_TRAVERSAL"),
            (lambda d: d.__setitem__("template_path", "./a"), "E_PATH_TRAVERSAL"),
            (lambda d: d.__setitem__("template_path", "a\\template"), "E_PATH"),
            (lambda d: d.__setitem__("template_hash", "bad"), "E_HASH_FORMAT"),
            (lambda d: d["budgets"].__setitem__("extra", 1), "E_BUDGET_FIELDS"),
            (lambda d: d["budgets"].__setitem__("max_entries", 5), "E_BUDGET_INCOMPATIBLE"),
            (lambda d: d.__setitem__("entries", d["entries"][:3]), "E_ENTRY_COUNT"),
            (lambda d: d["entries"][0].__setitem__("extra", True), "E_ENTRY_FIELDS"),
            (lambda d: d["entries"][0].__setitem__("id", "Bad ID"), "E_ID"),
            (lambda d: d["entries"][1].__setitem__("id", d["entries"][0]["id"]), "E_ID_DUPLICATE"),
            (lambda d: d["entries"].reverse(), "E_ENTRY_ORDER"),
            (lambda d: d["entries"][0].__setitem__("adapter", "plugin"), "E_ADAPTER_UNKNOWN"),
            (lambda d: d["entries"][0].__setitem__("source_path", "different.json"), "E_SOURCE_IDENTITY"),
            (lambda d: d["entries"][1].update({
                "source_path": d["entries"][0]["source_path"],
                "source_identity": d["entries"][0]["source_identity"]}), "E_SOURCE_IDENTITY_DUPLICATE"),
            (lambda d: d["entries"][1].update({
                "source_path": d["entries"][0]["source_path"] + "/../" + d["entries"][0]["source_path"].split("/")[-1],
                "source_identity": d["entries"][0]["source_identity"] + "/../" + d["entries"][0]["source_identity"].split("/")[-1]}),
             "E_PATH_TRAVERSAL"),
            (lambda d: d["entries"][0].__setitem__("source_format", ""), "E_IDENTITY"),
            (lambda d: d["entries"][0].__setitem__("source_format", "base24-json"), "E_SOURCE_FORMAT"),
            (lambda d: d["entries"][0].__setitem__("profile_version", "base24-v1"), "E_PROFILE_IDENTITY"),
            (lambda d: d["entries"][0]["license"].__setitem__("extra", "x"), "E_LICENSE_FIELDS"),
            (lambda d: d["entries"][0]["license"].__setitem__("spdx", "MIT"), "E_LICENSE"),
            (lambda d: d["entries"][0]["license"].__setitem__("attribution", ""), "E_ATTRIBUTION"),
            (lambda d: d["entries"][0]["license"].__setitem__("notice", ""), "E_LICENSE_NOTICE"),
            (lambda d: d["entries"][0]["expected"].__setitem__("extra", "x"), "E_EXPECTED_FIELDS"),
            (lambda d: d["entries"][0]["expected"].__setitem__("source_hash", "bad"), "E_HASH_FORMAT"),
            (lambda d: d["entries"][0].__setitem__("id", "instrument-studio-base17"), "E_ID_SET"),
        ]
        for index, (mutation, code) in enumerate(cases):
            with self.subTest(mutation=index, code=code):
                self.mutate_descriptor(mutation, code)

    def test_descriptor_raw_json_and_type_failures(self):
        bad_inputs = [
            ("E_BYTES_REQUIRED", "not bytes"),
            ("E_LIMIT_DESCRIPTOR", b" " * (256 * 1024 + 1)),
            ("E_UTF8", b"\xff"),
            ("E_JSON_PARSE", b"{"),
            ("E_JSON_ROOT", b"[]"),
            ("E_JSON_DUPLICATE", b'{"a":1,"a":2}'),
            ("E_NUMBER_NONFINITE", b'{"a":NaN}'),
            ("E_NONCANONICAL", self.descriptor_raw[:-1]),
        ]
        for code, raw in bad_inputs:
            with self.subTest(code=code):
                self.assert_code(code, catalog.parse_descriptor_bytes, raw)
        overlong = copy.deepcopy(self.descriptor)
        overlong["entries"][0]["license"]["notice"] = "x" * 4097
        self.assert_code("E_LIMIT_STRING", catalog.parse_descriptor_bytes,
                         json.dumps(overlong, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        self.assert_code("E_CANONICAL", catalog._canonical, {"bad": object()})
        with mock.patch.object(catalog, "canonical_json_bytes",
                               side_effect=catalog.ContractError("plain canonical failure")):
            self.assert_code("E_CANONICAL", catalog._canonical, {})
        self.assert_code("E_JSON_PARSE", catalog.parse_descriptor_bytes,
                         b'{"integer":' + b"9" * 5000 + b"}\n")
        self.assert_code("E_LIMIT_NESTING", catalog.parse_descriptor_bytes,
                         b'{"nested":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}\n")

    def test_package_provenance_binding_mutation_matrix(self):
        entry = self.descriptor["entries"][0]
        source = self.sources[entry["source_path"]]
        template = self.sources[self.descriptor["template_path"]]
        real_compile = catalog.compile_normalized
        mutations = [
            ("source_identity", "different/source.json"),
            ("source_format", "different-format"),
            ("profile_version", "different-profile"),
            ("compiler_version", "9.9.9"),
            ("content_hash", "sha256:" + "1" * 64),
            ("semantic_hash", "sha256:" + "2" * 64),
            ("license", "MIT"),
            ("attribution", "Different attribution"),
        ]
        for field, value in mutations:
            def changed(normalized, field=field, value=value):
                result = real_compile(normalized)
                package = copy.deepcopy(result.package)
                package["metadata"]["provenance"][field] = value
                return replace(result, package=package)
            with self.subTest(field=field), \
                 mock.patch.object(catalog, "compile_normalized", side_effect=changed), \
                 mock.patch.object(catalog, "validate_package", return_value=None):
                self.assert_code("E_PROVENANCE_BINDING", catalog.build_entry_artifacts,
                                 entry, source, template, self.descriptor["budgets"])

        for field, value in (("spdx", "MIT"), ("notice", "Different notice")):
            def changed_license(normalized, field=field, value=value):
                result = real_compile(normalized)
                package = copy.deepcopy(result.package)
                package["metadata"]["license"][field] = value
                return replace(result, package=package)
            with self.subTest(license_field=field), \
                 mock.patch.object(catalog, "compile_normalized", side_effect=changed_license), \
                 mock.patch.object(catalog, "validate_package", return_value=None):
                self.assert_code("E_PROVENANCE_BINDING", catalog.build_entry_artifacts,
                                 entry, source, template, self.descriptor["budgets"])

        def inert_provenance_change(normalized):
            result = real_compile(normalized)
            package = copy.deepcopy(result.package)
            package["metadata"]["provenance"]["attribution"] = "Valid but unbound attribution"
            catalog.validate_package(package)
            return replace(result, package=package)
        with mock.patch.object(catalog, "compile_normalized", side_effect=inert_provenance_change):
            self.assert_code("E_PROVENANCE_BINDING", catalog.build_entry_artifacts,
                             entry, source, template, self.descriptor["budgets"])

    def test_generation_drift_source_inventory_and_type_gates(self):
        self.assert_code("E_DESCRIPTOR_TYPE", catalog.generate_catalog, [], self.sources)
        self.assert_code("E_SOURCE_MAP", catalog.generate_catalog, self.descriptor, [])
        bad_map = dict(self.sources); bad_map["unexpected"] = b"x"
        self.assert_code("E_SOURCE_INVENTORY", catalog.generate_catalog, self.descriptor, bad_map)
        bad_map = dict(self.sources); bad_map[self.descriptor["template_path"]] += b" "
        self.assert_code("E_TEMPLATE_HASH_DRIFT", catalog.generate_catalog, self.descriptor, bad_map)
        bad_map = dict(self.sources); bad_map[self.descriptor["entries"][0]["source_path"]] += b" "
        self.assert_code("E_SOURCE_HASH_DRIFT", catalog.generate_catalog, self.descriptor, bad_map)

        for field, code in (("semantic_hash", "E_SEMANTIC_HASH_DRIFT"),
                            ("package_hash", "E_PACKAGE_HASH_DRIFT"),
                            ("receipt_hash", "E_RECEIPT_HASH_DRIFT")):
            changed = copy.deepcopy(self.descriptor)
            changed["entries"][0]["expected"][field] = "sha256:" + "0" * 64
            self.assert_code(code, catalog.generate_catalog, changed, self.sources)

    def test_build_entry_and_all_catalog_budget_gates(self):
        entry = self.descriptor["entries"][0]
        source = self.sources[entry["source_path"]]
        template = self.sources[self.descriptor["template_path"]]
        self.assert_code("E_ENTRY_FIELDS", catalog.build_entry_artifacts, {}, source, template,
                         self.descriptor["budgets"])
        self.assert_code("E_BUDGET_FIELDS", catalog.build_entry_artifacts, entry, source, template, {})
        self.assert_code("E_BYTES_REQUIRED", catalog.build_entry_artifacts, entry, "text", template,
                         self.descriptor["budgets"])
        self.assert_code("E_JSON_PARSE", catalog.build_entry_artifacts, entry, b"{", template,
                         self.descriptor["budgets"])
        budget_cases = [
            ("max_package_bytes", 1, "E_LIMIT_PACK"),
            ("max_tokens", 1, "E_LIMIT_TOKENS"),
            ("max_assets", 1, "E_LIMIT_ASSETS"),
            ("max_decoded_asset_bytes", 1, "E_LIMIT_ASSET_BYTES"),
            ("max_decoded_assets_total_bytes", 1, "E_LIMIT_ASSETS_TOTAL"),
            ("max_receipt_bytes", 1, "E_LIMIT_RECEIPT"),
        ]
        for field, value, code in budget_cases:
            limits = dict(self.descriptor["budgets"]); limits[field] = value
            with self.subTest(field=field):
                self.assert_code(code, catalog.build_entry_artifacts, entry, source, template, limits)

        low = copy.deepcopy(self.descriptor); low["budgets"]["max_catalog_bytes"] = 1
        with mock.patch.object(catalog, "parse_descriptor_bytes", return_value=low):
            self.assert_code("E_LIMIT_CATALOG", catalog.generate_catalog, low, self.sources)

    def test_runtime_snapshot_limit_is_an_internal_dominated_invariant(self):
        self.assertLessEqual(
            catalog.LIMITS["compiled_pack_bytes"],
            catalog.LIMITS["runtime_snapshot_bytes"],
        )
        catalog._assert_runtime_snapshot_dominance(catalog.LIMITS["compiled_pack_bytes"])
        with mock.patch.dict(catalog.LIMITS, {
            "compiled_pack_bytes": 2,
            "runtime_snapshot_bytes": 1,
        }):
            self.assert_code(
                "E_INTERNAL_LIMIT_CONTRACT",
                catalog._assert_runtime_snapshot_dominance,
                1,
            )
        with mock.patch.dict(catalog.LIMITS, {
            "compiled_pack_bytes": 1,
            "runtime_snapshot_bytes": 2,
        }):
            self.assert_code(
                "E_INTERNAL_LIMIT_CONTRACT",
                catalog._assert_runtime_snapshot_dominance,
                3,
            )

    def test_verify_missing_unexpected_noncanonical_and_drift(self):
        verified = catalog.verify_catalog(self.descriptor, self.sources, self.actual)
        self.assertEqual(verified["schema_version"], "native-theme-catalog-generation-v1")
        self.assert_code("E_ARTIFACT_MAP", catalog.verify_catalog, self.descriptor, self.sources, [])
        self.assert_code("E_DESCRIPTOR_TYPE", catalog.verify_catalog, [], self.sources, self.actual)
        missing = dict(self.actual); missing.pop(next(iter(missing)))
        self.assert_code("E_ARTIFACT_INVENTORY", catalog.verify_catalog,
                         self.descriptor, self.sources, missing)
        name = "catalog-index.json"
        noncanonical = dict(self.actual); noncanonical[name] = noncanonical[name][:-1]
        self.assert_code("E_NONCANONICAL", catalog.verify_catalog,
                         self.descriptor, self.sources, noncanonical)
        drift = dict(self.actual)
        value = json.loads(drift[name]); value["entries"][0]["adapter"] = "different"
        drift[name] = catalog.canonical_json_bytes(value) + b"\n"
        self.assert_code("E_ARTIFACT_DRIFT", catalog.verify_catalog,
                         self.descriptor, self.sources, drift)
        invalid = dict(self.actual); invalid[name] = b"{"
        self.assert_code("E_JSON_PARSE", catalog.verify_catalog,
                         self.descriptor, self.sources, invalid)

    def test_verification_budget_matrix_library_and_cli_reads(self):
        budget_cases = [
            ("instrument-studio-base16.package.json", "max_package_bytes", "E_LIMIT_PACK"),
            ("instrument-studio-base16.receipt.json", "max_receipt_bytes", "E_LIMIT_RECEIPT"),
            ("catalog-index.json", None, "E_LIMIT_ARTIFACT_METADATA"),
        ]
        for name, field, code in budget_cases:
            maximum = (self.descriptor["budgets"][field] if field
                       else catalog.ARTIFACT_METADATA_MAX_BYTES)
            oversized = dict(self.actual); oversized[name] = b"x" * (maximum + 1)
            with self.subTest(api="library", code=code):
                self.assert_code(code, catalog.verify_catalog,
                                 self.descriptor, self.sources, oversized)

        cumulative = {
            f"metadata-{index:02d}.json": b"x" * catalog.ARTIFACT_METADATA_MAX_BYTES
            for index in range(33)
        }
        self.assert_code("E_LIMIT_CATALOG", catalog.verify_catalog,
                         self.descriptor, self.sources, cumulative)

        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td)
            for name, field, code in budget_cases:
                maximum = (self.descriptor["budgets"][field] if field
                           else catalog.ARTIFACT_METADATA_MAX_BYTES)
                path = root / name; path.write_bytes(b"x" * (maximum + 1))
                with self.subTest(api="cli-read", code=code):
                    self.assert_code(code, catalog._read_artifacts, root, root, [name],
                                     self.descriptor["budgets"])
                path.unlink()
            names = []
            for index in range(33):
                name = f"metadata-{index:02d}.json"
                (root / name).write_bytes(b"x" * catalog.ARTIFACT_METADATA_MAX_BYTES)
                names.append(name)
            self.assert_code("E_LIMIT_CATALOG", catalog._read_artifacts,
                             root, root, names, self.descriptor["budgets"])

    def test_inspect_package_input_and_validation_gates(self):
        package = self.actual["instrument-studio-base24.package.json"]
        self.assertEqual(catalog.inspect_package(json.loads(package))["schema_version"], catalog.INSPECT_SCHEMA)
        self.assert_code("E_PACKAGE_TYPE", catalog.inspect_package, [])
        self.assert_code("E_NONCANONICAL", catalog.inspect_package, package[:-1])
        invalid = json.loads(package); invalid["schema_version"] = "future"
        self.assert_code("E_VERSION_REQUIRED", catalog.inspect_package, invalid)
        invalid = json.loads(package)
        invalid["metadata"]["provenance"]["semantic_hash"] = "sha256:" + "0" * 64
        self.assert_code("E_PROVENANCE", catalog.inspect_package, invalid)

    def test_deterministic_json_pointer_diff_all_shapes(self):
        differences = catalog._diff(
            {"a": [1, {"x/y~": True}], "gone": 1, "type": 1},
            {"a": [1, {"x/y~": False}, 3], "new": 2, "type": "1"},
        )
        pointers = [item["pointer"] for item in differences]
        self.assertEqual(pointers, ["/a/1/x~1y~0", "/a/2", "/gone", "/new", "/type"])
        self.assertEqual(catalog._diff([1, 2], [1])[0]["pointer"], "/1")
        self.assertEqual(catalog._diff({"same": True}, {"same": True}), [])

    def test_cli_generate_verify_inspect_compare_bytes_codes_and_atomic_failure(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            temporary = Path(td)
            output_root = temporary / "out"; output_root.mkdir()
            output = output_root / "catalog"
            stdout = BinaryOutput()
            with mock.patch.object(sys, "stdout", stdout):
                code = catalog.main(["generate", "--descriptor", str(DESCRIPTOR),
                                     "--source-root", str(ROOT), "--catalog-dir", "catalog",
                                     "--catalog-root", str(output_root)])
            self.assertEqual(code, 0)
            self.assertEqual(stdout.buffer.getvalue(), self.expected["generation-manifest.json"])
            before = {path.name: path.read_bytes() for path in output.iterdir()}

            stdout = BinaryOutput()
            with mock.patch.object(sys, "stdout", stdout):
                self.assertEqual(catalog.main(["verify", "--descriptor", str(DESCRIPTOR),
                    "--source-root", str(ROOT), "--catalog-dir", "catalog",
                    "--catalog-root", str(output_root)]), 0)
            self.assertEqual(stdout.buffer.getvalue(), self.expected["generation-manifest.json"])

            package = output / "instrument-studio-base16.package.json"
            stdout = BinaryOutput()
            with mock.patch.object(sys, "stdout", stdout):
                self.assertEqual(catalog.main(["inspect", "--package", package.name,
                    "--package-root", str(output)]), 0)
            self.assertEqual(json.loads(stdout.buffer.getvalue())["schema_version"], catalog.INSPECT_SCHEMA)

            stdout = BinaryOutput()
            with mock.patch.object(sys, "stdout", stdout):
                self.assertEqual(catalog.main(["compare", "--left", package.name,
                    "--right", "instrument-studio-base24.package.json",
                    "--package-root", str(output)]), 0)
            self.assertTrue(json.loads(stdout.buffer.getvalue())["semantically_equal"])

            bad_descriptor = temporary / "bad.json"; bad_descriptor.write_bytes(b"{}\n")
            stderr = io.StringIO()
            with mock.patch.object(sys, "stderr", stderr):
                self.assertEqual(catalog.main(["generate", "--descriptor", str(bad_descriptor),
                    "--source-root", str(ROOT), "--catalog-dir", "catalog",
                    "--catalog-root", str(output_root)]), 2)
            self.assertRegex(stderr.getvalue(), r"^E_[A-Z0-9_]+:")
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_dirfd_reads_reject_aliases_symlinks_types_growth_and_leaks(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td)
            nested = root / "nested"; nested.mkdir()
            good = nested / "good"; good.write_bytes(b"exact")
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("path read used")):
                self.assertEqual(catalog._read("nested/good", root, 5), b"exact")
                descriptor, sources = catalog._load_cli_inputs(DESCRIPTOR, ROOT)
            self.assertEqual(descriptor, self.descriptor)
            self.assertEqual(sources, self.sources)

            for alias in ("nested/./good", "nested//good", "nested/good/", "./nested/good"):
                with self.subTest(alias=alias):
                    self.assert_code("E_PATH_TRAVERSAL", catalog._read, alias, root, 10)
            self.assert_code("E_PATH", catalog._read, "nested\\good", root, 10)
            self.assert_code("E_PATH_OUTSIDE_ROOT", catalog._read, ROOT / "README.md", root, 10)
            self.assert_code("E_PATH_TRAVERSAL", catalog._read, "../outside", root, 10)

            final_link = nested / "final-link"; final_link.symlink_to(good)
            self.assert_code("E_SYMLINK", catalog._read, "nested/final-link", root, 10)
            real = root / "real"; real.mkdir(); (real / "leaf").write_bytes(b"x")
            intermediate = root / "intermediate"; intermediate.symlink_to(real, target_is_directory=True)
            self.assert_code("E_SYMLINK", catalog._read, "intermediate/leaf", root, 10)

            swap = nested / "swap"; swap.write_bytes(b"safe")
            real_open = os.open
            swapped = False
            def swap_before_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == "swap" and kwargs.get("dir_fd") is not None and not swapped:
                    swapped = True
                    swap.unlink()
                    swap.symlink_to(good)
                return real_open(path, flags, *args, **kwargs)
            with mock.patch.object(catalog.os, "open", side_effect=swap_before_open):
                self.assert_code("E_SYMLINK", catalog._read, "nested/swap", root, 10)

            oversized = nested / "oversized"; oversized.write_bytes(b"xx")
            self.assert_code("E_LIMIT_SOURCE", catalog._read, "nested/oversized", root, 1)
            directory_leaf = nested / "directory"; directory_leaf.mkdir()
            self.assert_code("E_IO", catalog._read, "nested/directory", root, 10)
            self.assert_code("E_IO", catalog._read, "nested/missing", root, 10)
            self.assert_code("E_IO", catalog._read, root, root, 10)

            real_fstat = os.fstat
            def hide_growth(fd):
                result = real_fstat(fd)
                if stat.S_ISREG(result.st_mode):
                    return os.stat_result((result.st_mode, *result[1:6], 0, *result[7:]))
                return result
            with mock.patch.object(catalog.os, "fstat", side_effect=hide_growth):
                self.assert_code("E_LIMIT_SOURCE", catalog._read, "nested/oversized", root, 1)

            root_link = root / "root-link"; root_link.symlink_to(root, target_is_directory=True)
            self.assert_code("E_SYMLINK", catalog._resolved_root, root_link)
            self.assert_code("E_ROOT", catalog._resolved_root, good)
            self.assert_code("E_IO", catalog._resolved_root, root / "missing")
            self.assert_code("E_PATH", catalog._resolved_root, object())

            catalog_dir = root / "catalog"; catalog_dir.mkdir()
            (catalog_dir / "one.json").write_bytes(b"{}\n")
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("path read used")):
                self.assertEqual(catalog._read_artifacts(
                    "catalog", root, ["one.json"], self.descriptor["budgets"]),
                    {"one.json": b"{}\n"})
            (catalog_dir / "unexpected").write_bytes(b"x")
            self.assert_code("E_ARTIFACT_INVENTORY", catalog._read_artifacts,
                             "catalog", root, ["one.json"], self.descriptor["budgets"])
            (catalog_dir / "unexpected").unlink()
            (catalog_dir / "one.json").unlink()
            (catalog_dir / "one.json").symlink_to(good)
            self.assert_code("E_SYMLINK", catalog._read_artifacts,
                             "catalog", root, ["one.json"], self.descriptor["budgets"])
            self.assert_code("E_IO", catalog._read_artifacts, "nested/good", root, [],
                             self.descriptor["budgets"])

            if Path("/proc/self/fd").is_dir():
                baseline = len(os.listdir("/proc/self/fd"))
                for _ in range(100):
                    self.assert_code("E_SYMLINK", catalog._read,
                                     "nested/final-link", root, 10)
                self.assertLessEqual(len(os.listdir("/proc/self/fd")), baseline + 1)

    def test_atomic_dirfd_preflight_fixed_names_and_lexical_matrix(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td)
            for artifacts, code in (([], "E_ARTIFACT_MAP"),
                                    ({"../escape.json": b"x"}, "E_OUTPUT_NAME"),
                                    ({"nested/file.json": b"x"}, "E_OUTPUT_NAME"),
                                    ({"nested\\file.json": b"x"}, "E_OUTPUT_NAME"),
                                    ({".hidden.json": b"x"}, "E_OUTPUT_NAME"),
                                    ({"bad..json": b"x"}, "E_OUTPUT_NAME"),
                                    ({"file.txt": b"x"}, "E_OUTPUT_NAME"),
                                    ({"file.json": "x"}, "E_ARTIFACT_MAP")):
                with self.subTest(code=code, artifacts=repr(artifacts)):
                    self.assert_code(code, catalog._atomic_write, "untouched", root, artifacts)
                    self.assertEqual(list(root.iterdir()), [])
            for alias in ("a/./catalog", "a//catalog", "a/catalog/", "./catalog"):
                self.assert_code("E_PATH_TRAVERSAL", catalog._atomic_write,
                                 alias, root, {"new.json": b"candidate"})
            self.assert_code("E_OUTPUT_ROOT", catalog._atomic_write,
                             root, root, {"new.json": b"candidate"})

            destination = root / "catalog"; destination.write_bytes(b"preserve")
            self.assert_code("E_OUTPUT_TYPE", catalog._atomic_write, "catalog", root,
                             {"new.json": b"candidate"})
            self.assertEqual(destination.read_bytes(), b"preserve")
            destination.unlink()
            target = root / "target"; target.mkdir()
            destination.symlink_to(target, target_is_directory=True)
            self.assert_code("E_OUTPUT_TYPE", catalog._atomic_write, "catalog", root,
                             {"new.json": b"candidate"})
            destination.unlink()
            parent_file = root / "parent-file"; parent_file.write_bytes(b"parent")
            self.assert_code("E_OUTPUT_TYPE", catalog._atomic_write,
                             "parent-file/catalog", root, {"new.json": b"candidate"})
            parent_link = root / "parent-link"; parent_link.symlink_to(target, target_is_directory=True)
            self.assert_code("E_SYMLINK", catalog._atomic_write,
                             "parent-link/catalog", root, {"new.json": b"candidate"})

            for fixed in (".catalog.stage", ".catalog.previous"):
                for kind in ("file", "directory", "symlink"):
                    node = root / fixed
                    if kind == "file":
                        node.write_bytes(b"ambient")
                    elif kind == "directory":
                        node.mkdir()
                    else:
                        node.symlink_to(target, target_is_directory=True)
                    with self.subTest(fixed=fixed, kind=kind):
                        self.assert_code("E_ATOMIC_STATE", catalog._atomic_write,
                                         "catalog", root, {"new.json": b"candidate"})
                    if node.is_symlink() or node.is_file():
                        node.unlink()
                    else:
                        node.rmdir()

            real_mkdir = os.mkdir
            def fail_stage(name, *args, **kwargs):
                if name == ".catalog.stage":
                    raise OSError("injected stage mkdir")
                return real_mkdir(name, *args, **kwargs)
            with mock.patch.object(catalog.os, "mkdir", side_effect=fail_stage):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})

    def test_atomic_replace_restore_write_and_false_failure_matrix(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td); destination = root / "catalog"
            real_replace = os.replace

            def seed():
                if destination.exists():
                    shutil.rmtree(destination)
                for recovery in (root / ".catalog.stage", root / ".catalog.previous"):
                    if recovery.exists():
                        shutil.rmtree(recovery)
                destination.mkdir(); (destination / "old.json").write_bytes(b"preserved")

            def assert_old():
                self.assertEqual((destination / "old.json").read_bytes(), b"preserved")
                self.assertEqual(sorted(path.name for path in root.iterdir()), ["catalog"])

            seed()
            with mock.patch.object(catalog.os, "replace", side_effect=OSError("old move failure")):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            assert_old()

            def move_old_then_fail(source, target, **kwargs):
                real_replace(source, target, **kwargs)
                raise OSError("reported failure after old move")
            with mock.patch.object(catalog.os, "replace", side_effect=move_old_then_fail):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            assert_old()

            calls = 0
            def fail_promotion(source, target, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("promotion failure")
                return real_replace(source, target, **kwargs)
            with mock.patch.object(catalog.os, "replace", side_effect=fail_promotion):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            assert_old()

            calls = 0
            def promote_then_fail(source, target, **kwargs):
                nonlocal calls
                calls += 1
                result = real_replace(source, target, **kwargs)
                if calls == 2:
                    raise OSError("reported failure after exact promotion")
                return result
            with mock.patch.object(catalog.os, "replace", side_effect=promote_then_fail):
                catalog._atomic_write("catalog", root, {"promoted.json": b"promoted"})
            self.assertEqual((destination / "promoted.json").read_bytes(), b"promoted")
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["catalog"])

            seed()
            calls = 0
            def fail_promotion_and_restore(source, target, **kwargs):
                nonlocal calls
                calls += 1
                if calls in {2, 3}:
                    raise OSError("promotion or restore failure")
                return real_replace(source, target, **kwargs)
            with mock.patch.object(catalog.os, "replace", side_effect=fail_promotion_and_restore):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            self.assertEqual((root / ".catalog.previous" / "old.json").read_bytes(), b"preserved")
            recovery_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                real_replace(".catalog.previous", "catalog",
                             src_dir_fd=recovery_fd, dst_dir_fd=recovery_fd)
            finally:
                os.close(recovery_fd)

            shutil.rmtree(destination)
            with mock.patch.object(catalog.os, "replace", side_effect=OSError("new promotion failure")):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            self.assertEqual(list(root.iterdir()), [])

            def move_new_then_fail(source, target, **kwargs):
                result = real_replace(source, target, **kwargs)
                raise OSError("reported failure after new promotion")
            with mock.patch.object(catalog.os, "replace", side_effect=move_new_then_fail):
                catalog._atomic_write("catalog", root, {"new.json": b"promoted"})
            self.assertEqual((destination / "new.json").read_bytes(), b"promoted")

            seed()
            with mock.patch.object(catalog.os, "write", side_effect=OSError("write failure")):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            assert_old()

            real_open = os.open
            def fail_stage_open(name, flags, *args, **kwargs):
                if name == ".catalog.stage" and kwargs.get("dir_fd") is not None:
                    raise OSError("stage open failure")
                return real_open(name, flags, *args, **kwargs)
            with mock.patch.object(catalog.os, "open", side_effect=fail_stage_open):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            self.assert_code("E_ATOMIC_STATE", catalog._atomic_write,
                             "catalog", root, {"new.json": b"candidate"})
            (root / ".catalog.stage").rmdir()
            assert_old()

            real_fsync = os.fsync
            fsync_calls = 0
            def fail_first_fsync(fd):
                nonlocal fsync_calls
                fsync_calls += 1
                if fsync_calls == 1:
                    raise OSError("fsync failure")
                return real_fsync(fd)
            with mock.patch.object(catalog.os, "fsync", side_effect=fail_first_fsync):
                self.assert_code("E_ATOMIC_WRITE", catalog._atomic_write,
                                 "catalog", root, {"new.json": b"candidate"})
            assert_old()

    def test_atomic_cleanup_is_flat_fail_closed_and_post_promotion_successful(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td); destination = root / "catalog"; destination.mkdir()
            nested = destination / "unexpected"; nested.mkdir()
            (nested / "preserve").write_bytes(b"operator recovery")
            catalog._atomic_write("catalog", root, {"final.json": b"promoted"})
            self.assertEqual((destination / "final.json").read_bytes(), b"promoted")
            backup = root / ".catalog.previous"
            self.assertEqual((backup / "unexpected" / "preserve").read_bytes(),
                             b"operator recovery")
            self.assert_code("E_ATOMIC_STATE", catalog._atomic_write,
                             "catalog", root, {"next.json": b"blocked"})
            shutil.rmtree(backup)

            real_unlink = os.unlink
            def fail_backup_unlink(name, *args, **kwargs):
                directory_fd = kwargs.get("dir_fd")
                if name == "old.json" and directory_fd is not None:
                    raise OSError("cleanup failure")
                return real_unlink(name, *args, **kwargs)
            shutil.rmtree(destination); destination.mkdir()
            (destination / "old.json").write_bytes(b"preserved")
            with mock.patch.object(catalog.os, "unlink", side_effect=fail_backup_unlink):
                catalog._atomic_write("catalog", root, {"final.json": b"promoted despite cleanup"})
            self.assertEqual((destination / "final.json").read_bytes(), b"promoted despite cleanup")
            self.assertEqual((backup / "old.json").read_bytes(), b"preserved")
            self.assert_code("E_ATOMIC_STATE", catalog._atomic_write,
                             "catalog", root, {"next.json": b"blocked"})

    def test_private_data_absence_and_static_no_authority_boundary(self):
        public = [*self.actual.values(), self.descriptor_raw, BUILD.read_bytes()]
        joined = b"".join(public).decode("utf-8").lower()
        private_markers = (
            str(ROOT).lower(), "/" + "srv/", "/" + "home/", "/" + "private/",
            ".work" + "trees", "cred" + "ential", "host" + "name",
            "time" + "stamp", "git_" + "commit", "environ" + "ment",
            "orches" + "tration", "kan" + "ban", "bea" + "ds", "code" + "x",
        )
        for forbidden in private_markers:
            self.assertNotIn(forbidden, joined.lower())
        forbidden_imports = {
            "socket", "subprocess", "importlib", "urllib", "requests", "time", "random",
        }
        forbidden_calls = {
            "glob", "rglob", "system", "popen", "Popen", "run", "call", "getenv",
            "__import__",
        }
        def authority_findings(tree):
            imports = set()
            calls = set()
            direct_forbidden = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
                    direct_forbidden.update({alias.asname or alias.name: alias.name
                                             for alias in node.names
                                             if alias.name in forbidden_calls})
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        calls.add(node.func.attr)
                    elif isinstance(node.func, ast.Name):
                        calls.add(direct_forbidden.get(node.func.id, node.func.id))
            return imports & forbidden_imports, calls & forbidden_calls

        tree = ast.parse(TOOL.read_text(encoding="utf-8"))
        self.assertEqual(authority_findings(tree), (set(), set()))
        fixture = ast.parse("""
from urllib import request
import json, subprocess as process
from subprocess import run as execute
execute(['forbidden'])
process.Popen(['forbidden'])
__import__('forbidden')
""")
        fixture_imports, fixture_calls = authority_findings(fixture)
        self.assertEqual(fixture_imports, {"urllib", "subprocess"})
        self.assertEqual(fixture_calls, {"Popen", "run", "__import__"})
        text = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("os.environ", text)
        self.assertNotIn("dynamic_import", text)
        self.assertNotIn("template", " ".join(sorted(catalog.ADAPTERS)))

    def test_exact_gn_source_output_inventory_and_forbidden_constructs(self):
        build = BUILD.read_text(encoding="utf-8")
        self.assertEqual(build.count('copy("catalog_artifacts")'), 1)
        sources_block = re.search(r"sources = \[(.*?)\]", build, re.DOTALL).group(1)
        sources = re.findall(r'"([^"]+)"', sources_block)
        expected = [f"catalog/{name}" for name in sorted(self.expected)]
        self.assertEqual(sources, expected)
        self.assertEqual(build.count('outputs = [ "${target_gen_dir}/catalog/{{source_file_part}}" ]'), 1)
        forbidden = (r"\baction\s*\(", r"\baction_foreach\s*\(", r"\bgroup\s*\(",
                     r"\bresource\s*\(", r"\bpackage\s*\(", r"\bcomponent\s*\(",
                     r"\bscript\s*=", r"\bdeps\s*=", r"\bpublic_deps\s*=")
        for pattern in forbidden:
            self.assertIsNone(re.search(pattern, build))
        self.assertFalse((ROOT / "tools/native_theme/BUILD.gn").exists())

    def test_internal_error_mapping_collision_and_manifest_branches(self):
        self.assert_code("E_PACKAGE_VALIDATION", catalog._adapter_error, RuntimeError("broken"))
        self.assert_code("E_PACKAGE_VALIDATION", catalog._adapter_error, catalog.ContractError("plain"))
        duplicate = copy.deepcopy(self.descriptor)
        duplicate["entries"][1]["id"] = duplicate["entries"][0]["id"]
        entry_result = catalog.build_entry_artifacts(
            duplicate["entries"][0], self.sources[duplicate["entries"][0]["source_path"]],
            self.sources[duplicate["template_path"]], duplicate["budgets"])
        duplicate["entries"][1]["expected"]["semantic_hash"] = entry_result[2]["semantic_hash"]
        duplicate["entries"][1]["expected"]["package_hash"] = entry_result[2]["package_hash"]
        duplicate["entries"][1]["expected"]["receipt_hash"] = catalog._hash(entry_result[1])
        with mock.patch.object(catalog, "parse_descriptor_bytes", return_value=duplicate), \
             mock.patch.object(catalog, "build_entry_artifacts", return_value=entry_result):
            self.assert_code("E_OUTPUT_COLLISION", catalog.generate_catalog, duplicate, self.sources)

    def test_defensive_oserror_cli_and_descriptor_branches_are_stable(self):
        with mock.patch.object(catalog.json, "loads", side_effect=RecursionError):
            self.assert_code("E_LIMIT_NESTING", lambda: catalog._parse_json(
                b"{}", code="E_LIMIT_DESCRIPTOR", max_bytes=10))

        for invalid in (b"bytes", "", "bad\\root", "a//root", "//double-root"):
            with self.subTest(root=repr(invalid)):
                self.assert_code(
                    "E_PATH" if invalid in (b"bytes", "", "bad\\root") else "E_PATH_TRAVERSAL",
                    catalog._resolved_root, invalid)
        self.assert_code("E_PATH", catalog._relative_parts, object(), ROOT)
        for invalid in (b"bytes", "", "bad\\path"):
            self.assert_code("E_PATH", catalog._relative_parts, invalid, ROOT)
        with mock.patch.object(Path, "resolve", side_effect=OSError("resolve failure")):
            self.assert_code("E_IO", catalog._resolved_root, ROOT)
        with mock.patch.object(catalog.os, "open", side_effect=OSError("open failure")):
            self.assert_code("E_IO", catalog._open_root, ROOT)
        with mock.patch.object(catalog.os, "fstat", side_effect=OSError("fstat failure")):
            self.assert_code("E_IO", catalog._open_root, ROOT)
        real_fstat = os.fstat
        with mock.patch.object(catalog.os, "fstat",
                               return_value=os.stat_result((stat.S_IFREG, 0, 0, 0, 0, 0, 0, 0, 0, 0))):
            self.assert_code("E_ROOT", catalog._open_root, ROOT)
        self.assertIsNotNone(real_fstat)
        with mock.patch.object(catalog.os, "close", side_effect=OSError("close failure")):
            catalog._close(123)

        root_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with mock.patch.object(catalog.os, "dup", side_effect=OSError("dup failure")):
                self.assert_code("E_IO", lambda: catalog._walk_directories(
                    root_fd, (), create=False, type_code="E_IO"))
            with mock.patch.object(catalog.os, "mkdir", side_effect=OSError("mkdir failure")):
                self.assert_code("E_ATOMIC_WRITE", lambda: catalog._walk_directories(
                    root_fd, ("new-parent",), create=True, type_code="E_OUTPUT_TYPE"))
            self.assert_code("E_IO", catalog._node_at, -1, "node")
        finally:
            os.close(root_fd)

        with mock.patch.object(catalog.os, "write", return_value=0):
            with self.assertRaises(OSError):
                catalog._write_all(1, b"x")

        with tempfile.TemporaryDirectory(dir=ROOT) as td:
            root = Path(td); promoted = root / "promoted"; promoted.mkdir()
            (promoted / "one.json").write_bytes(b"wrong")
            parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertFalse(catalog._flat_directory_matches(
                    parent_fd, "promoted", {"different.json": b"wrong"}))
                self.assertFalse(catalog._flat_directory_matches(
                    parent_fd, "promoted", {"one.json": b"right"}))
                self.assertFalse(catalog._flat_directory_matches(
                    parent_fd, "missing", {"one.json": b"right"}))
            finally:
                os.close(parent_fd)

            catalog_dir = root / "catalog"; catalog_dir.mkdir()
            with mock.patch.object(catalog.os, "listdir", side_effect=OSError("list failure")):
                self.assert_code("E_IO", catalog._read_artifacts,
                                 "catalog", root, [], self.descriptor["budgets"])

            with mock.patch.object(catalog, "_write_all",
                                   side_effect=catalog.CatalogError("E_TEST", "injected")):
                self.assert_code("E_TEST", catalog._atomic_write,
                                 "output", root, {"one.json": b"x"})
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["catalog", "promoted"])

        for argv in ([], ["unknown"], ["inspect"], ["inspect", "--unknown"]):
            stdout = BinaryOutput(); stderr = io.StringIO()
            with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
                self.assertEqual(catalog.main(argv), 2)
            self.assertEqual(stdout.buffer.getvalue(), b"")
            self.assertRegex(stderr.getvalue(), r"^E_CLI_ARGUMENT:")
        stderr = io.StringIO()
        parser = mock.Mock(); parser.parse_args.side_effect = OSError("injected")
        with mock.patch.object(catalog, "_parser", return_value=parser), \
             mock.patch.object(sys, "stderr", stderr):
            self.assertEqual(catalog.main([]), 2)
        self.assertEqual(stderr.getvalue(), "E_IO: filesystem operation failed\n")

    def test_direct_script_entrypoint_is_covered(self):
        package = GENERATED / "instrument-studio-base16.package.json"
        stdout = BinaryOutput()
        old_argv = sys.argv
        sys.argv = [str(TOOL), "inspect", "--package", str(package),
                    "--package-root", str(GENERATED)]
        try:
            with mock.patch.object(sys, "stdout", stdout), self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(TOOL), run_name="__main__")
        finally:
            sys.argv = old_argv
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(json.loads(stdout.buffer.getvalue())["schema_version"], catalog.INSPECT_SCHEMA)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Focused tests for the parser-neutral NativeThemeV1 compiler core."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))

import compiler_core as core  # noqa: E402
import native_theme_v1 as contract  # noqa: E402


FIXTURE = ROOT / "tools/native_theme/fixtures/native-theme-v1-package.json"
PRODUCTION = ROOT / "tools/native_theme/compiler_core.py"
VALIDATOR = ROOT / "tools/native_theme/validate_native_theme_v1.py"
EXPECTED_PACKAGE_VALIDATION_LINE = (
    "VALID NativeThemeV1 "
    "semantic_hash=sha256:5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a "
    "package_sha256=sha256:f1975d2511b5b4c711ef8b299389a07793b3113077cad32bb8272dcde7b1738b"
)


def fixture_package() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def normalized(package: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "normalized_version": "1.0.0",
        "required_versions": {
            "schema": "1.0.0",
            "profile": "2025.10",
            "compiler": "1.0.0",
        },
        "source_content_hash": (
            fixture_package() if package is None else package
        )["metadata"]["provenance"]["content_hash"],
        "package": fixture_package() if package is None else package,
        "tokens": [],
        "aliases": [],
        "derivations": [],
    }


def refresh_semantic_hash(package: dict[str, object]) -> None:
    package["metadata"]["provenance"]["semantic_hash"] = contract.package_semantic_identity(package)


def package_with_canonical_body_size(size: int) -> dict[str, object]:
    package = fixture_package()
    extensions = package["metadata"]["extensions"]
    extensions.clear()
    prior_key = None
    index = 0
    while True:
        body = contract.canonical_json_bytes(package)
        remaining = size - len(body)
        if remaining == 0:
            return package
        if remaining < 0:
            raise AssertionError(f"cannot construct canonical body of {size} bytes")
        key = f"org.constructresearch.instrumentstudio.padding-{index:03d}"
        extensions[key] = ""
        overhead = len(contract.canonical_json_bytes(package)) - len(body)
        if remaining >= overhead:
            extensions[key] = "x" * min(4000, remaining - overhead)
            prior_key = key
            index += 1
        else:
            extensions.pop(key)
            if prior_key is None:
                raise AssertionError("target leaves no room for canonical padding")
            extensions[prior_key] = extensions[prior_key][:-(overhead - remaining)]
            extensions[key] = ""


class CompilerCoreTests(unittest.TestCase):
    def assert_code(self, expected: str, candidate: object) -> core.CompilerError:
        with self.assertRaises(core.CompilerError) as caught:
            core.compile_normalized(candidate)
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(caught.exception.diagnostic.code, expected)
        self.assertTrue(caught.exception.message)
        return caught.exception

    def test_full_package_compilation_is_exact_fresh_and_hash_equivalent(self):
        source = normalized()
        before = copy.deepcopy(source)
        result = core.compile_normalized(source)
        expected = contract.canonical_json_bytes(source["package"]) + b"\n"
        self.assertEqual(result.canonical_bytes, expected)
        self.assertEqual(result.package, source["package"])
        self.assertIsNot(result.package, source["package"])
        self.assertEqual(source, before)
        self.assertEqual(result.semantic_hash, contract.package_semantic_identity(result.package))
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.receipt["package_bytes"], len(expected))
        self.assertEqual(result.receipt["package_sha256"], "sha256:" + hashlib.sha256(expected).hexdigest())
        self.assertEqual(result.receipt_bytes, contract.canonical_json_bytes(result.receipt))

    def test_future_full_file_serialization_obeys_exact_pack_boundary(self):
        for raw_size in (262143, 262144):
            with self.subTest(raw_size=raw_size):
                package = package_with_canonical_body_size(raw_size - 1)
                result = core.compile_normalized(normalized(package))
                self.assertEqual(len(result.canonical_bytes), raw_size)
        package = package_with_canonical_body_size(262144)
        self.assertEqual(len(contract.canonical_json_bytes(package)) + 1, 262145)
        self.assert_code("E_CANONICAL_SIZE", normalized(package))

    def test_reserved_namespaced_extension_metadata_is_preserved_without_capability_inference(self):
        source = normalized()
        extension = {"content": "human note", "payload": {"label": "safe"}}
        source["package"]["metadata"]["extensions"][
            "org.constructresearch.instrumentstudio.notes"
        ] = extension
        refresh_semantic_hash(source["package"])
        result = core.compile_normalized(source)
        self.assertEqual(
            result.package["metadata"]["extensions"][
                "org.constructresearch.instrumentstudio.notes"
            ],
            extension,
        )

    def test_source_content_hash_is_bound_to_package_provenance_and_receipt(self):
        source = normalized()
        content_hash = source["package"]["metadata"]["provenance"]["content_hash"]
        source["source_content_hash"] = content_hash
        result = core.compile_normalized(source)
        self.assertEqual(result.receipt["source_content_hash"], content_hash)

        bad = copy.deepcopy(source)
        bad["source_content_hash"] = "sha256:" + "0" * 64
        self.assert_code("E_PROVENANCE_HASH_MISMATCH", bad)

        bad = copy.deepcopy(source)
        bad["source_content_hash"] = "not-a-hash"
        self.assert_code("E_PROVENANCE_HASH", bad)

    def test_alias_chain_resolves_without_mutating_input(self):
        source = normalized()
        source["tokens"] = [{"name": "accent.raw", "type": "color", "value": "#9e66faff"}]
        source["aliases"] = [
            {"name": "accent.middle", "type": "color", "target": "accent.raw"},
            {"name": "accent.final", "type": "color", "target": "accent.middle"},
        ]
        source["package"]["variants"]["dark"]["primitives"]["accent"] = {"$token": "accent.final"}
        before = copy.deepcopy(source)
        result = core.compile_normalized(source)
        self.assertEqual(result.package["variants"]["dark"]["primitives"]["accent"], "#9e66faff")
        self.assertEqual(source, before)

    def test_declared_half_up_derivation(self):
        source = normalized()
        source["tokens"] = [
            {"name": "r", "type": "number", "value": 158 / 255},
            {"name": "g", "type": "number", "value": 102 / 255},
            {"name": "b", "type": "number", "value": 250 / 255},
            {"name": "a", "type": "number", "value": 1},
        ]
        source["derivations"] = [{
            "name": "accent.derived", "type": "color",
            "operation": "legacy-quantize-half-up", "operands": ["r", "g", "b", "a"],
        }]
        source["package"]["variants"]["dark"]["primitives"]["accent"] = {"$token": "accent.derived"}
        result = core.compile_normalized(source)
        self.assertEqual(result.package["variants"]["dark"]["primitives"]["accent"], "#9e66faff")

    def test_declared_alpha_preservation_derivation(self):
        source = normalized()
        source["tokens"] = [{"name": "color", "type": "color", "value": "#9e66fa80"}]
        source["derivations"] = [{
            "name": "preserved", "type": "color",
            "operation": "srgb-alpha-preservation", "operands": ["color"],
        }]
        source["package"]["variants"]["dark"]["primitives"]["accent"] = {"$token": "preserved"}
        resolved = copy.deepcopy(source["package"])
        resolved["variants"]["dark"]["primitives"]["accent"] = "#9e66fa80"
        source["package"]["metadata"]["provenance"]["semantic_hash"] = contract.package_semantic_identity(resolved)
        result = core.compile_normalized(source)
        self.assertEqual(result.package["variants"]["dark"]["primitives"]["accent"], "#9e66fa80")

    def test_malformed_normalized_root_type_fields_and_version(self):
        self.assert_code("E_NORMALIZED_ROOT", [])
        bad = normalized(); bad["tokens"] = {}
        self.assert_code("E_NORMALIZED_TYPE", bad)
        bad = normalized(); bad["extra"] = True
        self.assert_code("E_NORMALIZED_FIELDS", bad)
        bad = normalized(); bad["normalized_version"] = "2.0.0"
        self.assert_code("E_NORMALIZED_VERSION", bad)

    def test_unsupported_required_versions(self):
        for field, code in (
            ("schema", "E_VERSION_SCHEMA"),
            ("profile", "E_VERSION_PROFILE"),
            ("compiler", "E_VERSION_COMPILER"),
        ):
            with self.subTest(field=field):
                bad = normalized(); bad["required_versions"][field] = "future"
                self.assert_code(code, bad)

    def test_duplicate_unknown_and_over_count_tokens(self):
        bad = normalized(); bad["tokens"] = [
            {"name": "same", "type": "color", "value": "#000000ff"},
            {"name": "same", "type": "color", "value": "#000000ff"},
        ]
        self.assert_code("E_TOKEN_DUPLICATE", bad)
        bad = normalized()
        bad["package"]["variants"]["dark"]["primitives"]["accent"] = {"$token": "missing"}
        self.assert_code("E_TOKEN_UNKNOWN", bad)
        bad = normalized(); bad["tokens"] = [
            {"name": f"t{i}", "type": "boolean", "value": True}
            for i in range(contract.LIMITS["tokens"] + 1)
        ]
        self.assert_code("E_LIMIT_TOKENS", bad)

    def test_alias_failure_categories(self):
        bad = normalized(); bad["aliases"] = [{"name": "a", "type": "color", "target": "missing"}]
        self.assert_code("E_ALIAS_UNRESOLVED", bad)
        bad = normalized(); bad["aliases"] = [
            {"name": "a", "type": "color", "target": "b"},
            {"name": "b", "type": "color", "target": "a"},
        ]
        self.assert_code("E_ALIAS_CYCLE", bad)
        bad = normalized()
        bad["tokens"] = [{"name": "end", "type": "color", "value": "#000000ff"}]
        bad["aliases"] = [
            {"name": f"a{i}", "type": "color", "target": f"a{i + 1}"}
            for i in range(contract.LIMITS["alias_depth"] + 1)
        ] + [{"name": f"a{contract.LIMITS['alias_depth'] + 1}", "type": "color", "target": "end"}]
        self.assert_code("E_LIMIT_ALIAS_DEPTH", bad)
        bad = normalized(); bad["aliases"] = [
            {"name": f"a{i}", "type": "color", "target": "base"}
            for i in range(contract.LIMITS["aliases"] + 1)
        ]
        self.assert_code("E_LIMIT_ALIASES", bad)

    def test_resolution_depth_is_bounded_before_python_recursion(self):
        bad = normalized()
        bad["tokens"] = [{"name": "base", "type": "color", "value": "#000000ff"}]
        bad["derivations"] = [
            {
                "name": f"d{i}", "type": "color",
                "operation": "srgb-alpha-preservation",
                "operands": ["base" if i == 40 else f"d{i + 1}"],
            }
            for i in range(41)
        ]
        self.assert_code("E_LIMIT_NESTING", bad)

    def test_type_conflicts_across_alias_and_derivation(self):
        bad = normalized()
        bad["tokens"] = [{"name": "n", "type": "number", "value": 1}]
        bad["aliases"] = [{"name": "c", "type": "color", "target": "n"}]
        self.assert_code("E_TOKEN_TYPE_CONFLICT", bad)
        bad = normalized()
        bad["tokens"] = [{"name": "c", "type": "color", "value": "#000000ff"}]
        bad["derivations"] = [{
            "name": "wrong", "type": "number",
            "operation": "srgb-alpha-preservation", "operands": ["c"],
        }]
        self.assert_code("E_TOKEN_TYPE_CONFLICT", bad)

    def test_unknown_derivation_and_invalid_operands(self):
        bad = normalized(); bad["derivations"] = [{
            "name": "x", "type": "color", "operation": "evaluate-expression", "operands": [],
        }]
        self.assert_code("E_DERIVATION_UNKNOWN", bad)
        bad = normalized()
        bad["tokens"] = [{"name": "c", "type": "color", "value": "#000000ff"}]
        bad["derivations"] = [{
            "name": "x", "type": "color",
            "operation": "legacy-quantize-half-up", "operands": ["c"],
        }]
        self.assert_code("E_DERIVATION_OPERANDS", bad)

    def test_source_string_nesting_pack_and_asset_limits(self):
        bad = normalized(); bad["tokens"] = [
            {"name": f"s{i}", "type": "string", "value": "x" * 4090}
            for i in range(270)
        ]
        self.assert_code("E_LIMIT_SOURCE", bad)
        bad = normalized(); bad["tokens"] = [{"name": "s", "type": "string", "value": "x" * 4097}]
        self.assert_code("E_LIMIT_STRING", bad)
        bad = normalized(); nested: object = "leaf"
        for _ in range(contract.LIMITS["nesting"] + 1): nested = [nested]
        bad["package"]["metadata"]["extensions"]["org.constructresearch.instrumentstudio.deep"] = nested
        self.assert_code("E_LIMIT_NESTING", bad)
        bad = normalized()
        bad["package"]["metadata"]["extensions"].update({
            f"org.constructresearch.instrumentstudio.pad{i}": "x" * 4090 for i in range(64)
        })
        self.assert_code("E_CANONICAL_SIZE", bad)
        bad = normalized()
        items = bad["package"]["variants"]["dark"]["assets"]["items"]
        sample = copy.deepcopy(items["status.error"])
        items.update({f"extra.{i}": copy.deepcopy(sample) for i in range(60)})
        refresh_semantic_hash(bad["package"])
        self.assert_code("E_LIMIT_ASSETS", bad)
        bad = normalized()
        for variant in bad["package"]["variants"].values():
            for asset in variant["assets"]["items"].values(): asset["decoded_bytes"] = 300_000
        refresh_semantic_hash(bad["package"])
        self.assert_code("E_LIMIT_ASSETS_TOTAL", bad)
        bad = normalized()
        bad["package"]["variants"]["dark"]["assets"]["items"]["status.error"]["decoded_bytes"] = contract.LIMITS["decoded_asset_bytes"] + 1
        refresh_semantic_hash(bad["package"])
        self.assert_code("E_LIMIT_ASSET_BYTES", bad)

    def test_unsafe_paths_content_and_capabilities(self):
        cases = (
            ({"url": "https://example.invalid/theme"}, "E_NETWORK_URI"),
            ({"path": "/etc/theme"}, "E_ABSOLUTE_PATH"),
            ({"path": "../theme"}, "E_PATH_TRAVERSAL"),
            ({"script": "print('x')"}, "E_SCRIPT"),
            ({"shell": "sh -c true"}, "E_SHELL"),
            ({"executable": "theme.bin"}, "E_EXECUTABLE"),
            ({"plugin": "theme-loader"}, "E_PLUGIN"),
            ({"template": "{{ value }}"}, "E_TEMPLATE"),
            ({"runtime_path": "themes/current"}, "E_RUNTIME_PATH"),
            ({"runtime_content": "opaque payload"}, "E_RUNTIME_CONTENT"),
        )
        for extra, code in cases:
            with self.subTest(code=code):
                bad = normalized(); bad.update(extra)
                self.assert_code(code, bad)
        bad = normalized(); bad["tokens"] = [{"name": "value", "type": "string", "value": "themes/current"}]
        self.assert_code("E_RUNTIME_PATH", bad)

    def test_token_names_and_nested_package_cannot_smuggle_capabilities(self):
        bad = normalized()
        bad["aliases"] = [{"name": "safe", "type": "color", "target": "plugin.loader"}]
        self.assert_code("E_PLUGIN", bad)
        bad = normalized(); bad["package"]["theme"]["script"] = "print('x')"
        self.assert_code("E_SCRIPT", bad)
        bad = normalized(); bad["package"]["policy"]["executable_content"] = "allowed"
        self.assert_code("E_EXECUTABLE", bad)

    def test_asset_and_provenance_path_safety(self):
        for value, code in (
            ("https://example.invalid/icon.svg", "E_NETWORK_URI"),
            ("/tmp/icon.svg", "E_ABSOLUTE_PATH"),
            ("icons/../icon.svg", "E_PATH_TRAVERSAL"),
            ("file:///tmp/icon.svg", "E_RUNTIME_PATH"),
        ):
            with self.subTest(value=value):
                bad = normalized()
                bad["package"]["variants"]["dark"]["assets"]["items"]["status.error"]["path"] = value
                refresh_semantic_hash(bad["package"])
                self.assert_code(code, bad)

    def test_complete_package_semantic_and_provenance_failures(self):
        bad = normalized(); bad["package"]["variants"]["dark"]["semantic"].pop("text.normal")
        refresh_semantic_hash(bad["package"])
        self.assert_code("E_PACKAGE_VALIDATION", bad)
        bad = normalized(); bad["package"]["metadata"]["provenance"]["semantic_hash"] = "sha256:" + "0" * 64
        self.assert_code("E_SEMANTIC_HASH_MISMATCH", bad)
        bad = normalized(); bad["package"]["metadata"]["provenance"]["content_hash"] = "not-a-hash"
        self.assert_code("E_PROVENANCE_HASH", bad)

    def test_failed_compile_never_promotes_or_changes_existing_output(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "theme.json"
            output.write_bytes(b"existing\n")
            bad = normalized(); bad["normalized_version"] = "future"
            with self.assertRaises(core.CompilerError):
                core.compile_normalized_to_path(bad, output)
            self.assertEqual(output.read_bytes(), b"existing\n")

    def test_promotion_failure_leaves_no_partial_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "theme.json"
            output.write_bytes(b"existing\n")
            with mock.patch.object(core.os, "replace", side_effect=OSError("denied")):
                with self.assertRaises(core.CompilerError) as caught:
                    core.compile_normalized_to_path(normalized(), output)
            self.assertEqual(caught.exception.code, "E_OUTPUT_PROMOTION")
            self.assertEqual(output.read_bytes(), b"existing\n")
            self.assertEqual(list(Path(td).iterdir()), [output])

    def test_three_clean_directory_runs_have_identical_package_and_receipt_bytes(self):
        outputs: list[bytes] = []
        receipts: list[bytes] = []
        for _ in range(3):
            with tempfile.TemporaryDirectory() as td:
                result = core.compile_normalized_to_path(normalized(), Path(td) / "theme.json")
                outputs.append((Path(td) / "theme.json").read_bytes())
                receipts.append(result.receipt_bytes)
                self.assertEqual(outputs[-1], result.canonical_bytes)
                self.assertTrue(outputs[-1].endswith(b"\n"))
                self.assertFalse(outputs[-1].endswith(b"\n\n"))
                self.assertEqual(outputs[-1].count(b"\n"), 1)
                self.assertEqual(result.receipt["package_bytes"], len(outputs[-1]))
                self.assertEqual(
                    result.receipt["package_sha256"],
                    "sha256:" + hashlib.sha256(outputs[-1]).hexdigest(),
                )
                validated = subprocess.run(
                    [sys.executable, str(VALIDATOR), str(Path(td) / "theme.json")],
                    cwd=ROOT,
                    check=False,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(validated.returncode, 0, validated.stderr)
                self.assertEqual(validated.stdout, EXPECTED_PACKAGE_VALIDATION_LINE + "\n")
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(receipts[1], receipts[2])

    def test_internal_canonical_and_copy_fail_closed_edges(self):
        with mock.patch.object(
            core, "canonical_json_bytes", side_effect=contract.ContractError("E_SYNTHETIC: bad")
        ):
            with self.assertRaises(core.CompilerError) as caught:
                core._canonical({})
        self.assertEqual(caught.exception.code, "E_SYNTHETIC")
        with mock.patch.object(core, "canonical_json_bytes", side_effect=TypeError("bad")):
            with self.assertRaises(core.CompilerError) as caught:
                core._canonical({})
        self.assertEqual(caught.exception.code, "E_NORMALIZED_TYPE")
        self.assertEqual(core._contract_code(contract.ContractError("plain"))[0], "E_CONTRACT")

        mapping_cycle: dict[str, object] = {}
        mapping_cycle["self"] = mapping_cycle
        sequence_cycle: list[object] = []
        sequence_cycle.append(sequence_cycle)
        cases = [
            ({"value": float("inf")}, "E_NUMBER_NONFINITE"),
            (mapping_cycle, "E_LIMIT_NESTING"),
            ({1: "bad"}, "E_NORMALIZED_TYPE"),
            ({"bad": {1, 2}}, "E_NORMALIZED_TYPE"),
        ]
        for candidate, code in cases:
            with self.subTest(candidate_type=type(candidate).__name__, code=code):
                self.assert_code(code, candidate)
        with self.assertRaises(core.CompilerError) as caught:
            core._fresh_json_value(sequence_cycle)
        self.assertEqual(caught.exception.code, "E_LIMIT_NESTING")

    def test_identifier_and_literal_failure_matrix(self):
        identifier_cases = (
            ("https://example.invalid/x", "E_NETWORK_URI"),
            ("/absolute", "E_ABSOLUTE_PATH"),
            ("../traverse", "E_PATH_TRAVERSAL"),
            ("#!script", "E_SCRIPT"),
            ("script:value", "E_SCRIPT"),
            ("shell:value", "E_SHELL"),
            ("exec:value", "E_EXECUTABLE"),
            ("plugin:value", "E_PLUGIN"),
            ("template:value", "E_TEMPLATE"),
            ("file:value", "E_RUNTIME_PATH"),
            ("folder/value", "E_RUNTIME_PATH"),
            ("", "E_TOKEN_NAME"),
        )
        for value, code in identifier_cases:
            with self.subTest(value=value):
                with self.assertRaises(core.CompilerError) as caught:
                    core._token_name(value, "test")
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(core.CompilerError) as caught:
            core._token_name(3, "test")
        self.assertEqual(caught.exception.code, "E_NORMALIZED_TYPE")
        with self.assertRaises(core.CompilerError) as caught:
            core._token_type("image", "test")
        self.assertEqual(caught.exception.code, "E_TOKEN_TYPE")
        literal_cases = (
            ("color", "#ABCDEFff", "E_COLOR_CANONICAL"),
            ("string", 3, "E_TOKEN_TYPE"),
            ("number", True, "E_TOKEN_TYPE"),
            ("boolean", 1, "E_TOKEN_TYPE"),
        )
        for token_type, value, code in literal_cases:
            with self.subTest(token_type=token_type):
                with self.assertRaises(core.CompilerError) as caught:
                    core._literal(token_type, value, "test")
                self.assertEqual(caught.exception.code, code)

    def test_normalized_symbol_shape_and_derivation_failure_matrix(self):
        bad = normalized(); bad["required_versions"] = {}
        self.assert_code("E_NORMALIZED_VERSION", bad)
        bad = normalized(); bad["tokens"] = [None]
        self.assert_code("E_NORMALIZED_TYPE", bad)
        bad = normalized(); bad["tokens"] = [
            {"name": "x", "type": "color", "value": "#000000ff", "note": "safe"}
        ]
        self.assert_code("E_TOKEN_SHAPE", bad)
        bad = normalized(); bad["aliases"] = [None]
        self.assert_code("E_NORMALIZED_TYPE", bad)
        bad = normalized(); bad["aliases"] = [
            {"name": "x", "type": "color", "target": "y", "note": "safe"}
        ]
        self.assert_code("E_ALIAS_SHAPE", bad)
        bad = normalized(); bad["derivations"] = [None]
        self.assert_code("E_NORMALIZED_TYPE", bad)
        bad = normalized(); bad["derivations"] = [
            {"name": "x", "type": "color", "operation": "srgb-alpha-preservation", "operands": ()}
        ]
        self.assert_code("E_DERIVATION_OPERANDS", bad)
        bad = normalized(); bad["derivations"] = [
            {"name": "x", "type": "color", "operation": 7, "operands": []}
        ]
        self.assert_code("E_DERIVATION_UNKNOWN", bad)
        bad = normalized(); bad["derivations"] = [
            {"name": "x", "type": "color", "operation": "srgb-alpha-preservation", "operands": ["missing"]}
        ]
        self.assert_code("E_DERIVATION_OPERANDS", bad)
        bad = normalized()
        bad["tokens"] = [{"name": "c", "type": "color", "value": "#000000ff"}]
        bad["derivations"] = [{
            "name": "x", "type": "color", "operation": "srgb-alpha-preservation", "operands": [],
        }]
        self.assert_code("E_DERIVATION_OPERANDS", bad)
        with self.assertRaises(core.CompilerError) as caught:
            core._derive(
                "legacy-quantize-half-up",
                "color",
                [core._ResolvedToken("number", object())] * 4,
            )
        self.assertEqual(caught.exception.code, "E_DERIVATION_OPERANDS")
        with self.assertRaises(core.CompilerError) as caught:
            core._derive(
                "legacy-quantize-half-up",
                "color",
                [core._ResolvedToken("number", 2)] * 4,
            )
        self.assertEqual(caught.exception.code, "E_DERIVATION_OPERANDS")

    def test_token_reference_versions_and_defensive_package_walk_edges(self):
        bad = normalized()
        bad["package"]["variants"]["dark"]["primitives"]["accent"] = {
            "$token": "missing", "extra": True,
        }
        self.assert_code("E_TOKEN_REFERENCE", bad)
        for path, value, code in (
            (("schema_version",), "2.0.0", "E_VERSION_SCHEMA"),
            (("profile", "version"), "future", "E_VERSION_PROFILE"),
            (("metadata", "provenance", "compiler_version"), "future", "E_VERSION_COMPILER"),
        ):
            candidate = normalized()
            target = candidate["package"]
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            self.assert_code(code, candidate)

        for package in (
            {"variants": []},
            {"variants": {"dark": []}},
            {"variants": {"dark": {"assets": []}}},
            {"variants": {"dark": {"assets": {"items": []}}}},
            {"variants": {"dark": {"assets": {"items": {"x": []}}}}},
            {"variants": {"dark": {"assets": {"items": {"x": {"decoded_bytes": "unknown"}, "y": {}}}}}},
            {"metadata": {"provenance": {"source_identity": 7}}, "variants": {}},
        ):
            core._check_package_safety(package)

        with mock.patch.object(core, "_fresh_json_value", return_value=[]):
            self.assert_code("E_NORMALIZED_ROOT", normalized())
        with mock.patch.object(core, "_substitute_tokens", return_value=[]):
            self.assert_code("E_NORMALIZED_TYPE", normalized())

    def test_output_cleanup_failure_is_still_a_stable_compiler_error(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "theme.json"
            output.write_bytes(b"existing\n")
            for cleanup_error in (FileNotFoundError(), OSError("cleanup denied")):
                with self.subTest(error=type(cleanup_error).__name__), mock.patch.object(
                    core.os, "replace", side_effect=OSError("promotion denied")
                ), mock.patch.object(core.Path, "unlink", side_effect=cleanup_error):
                    with self.assertRaises(core.CompilerError) as caught:
                        core.compile_normalized_to_path(normalized(), output)
                    self.assertEqual(caught.exception.code, "E_OUTPUT_PROMOTION")
                    self.assertEqual(output.read_bytes(), b"existing\n")
            for temporary in Path(td).glob(".theme.json.*.tmp"):
                temporary.unlink()

    def test_remaining_depth_and_shape_guards(self):
        self.assertTrue(core._literal("boolean", True, "test"))
        bad = normalized(); bad["derivations"] = [{
            "name": "x", "type": "color",
            "operation": "srgb-alpha-preservation", "operands": "not-a-list",
        }]
        self.assert_code("E_DERIVATION_OPERANDS", bad)
        bad = normalized(); bad["package"] = []
        self.assert_code("E_NORMALIZED_TYPE", bad)

        alias_symbols: dict[str, dict[str, object]] = {
            "base": {"kind": "literal", "type": "color", "value": "#000000ff"},
        }
        for index in reversed(range(contract.LIMITS["alias_depth"])):
            alias_symbols[f"a{index:02d}"] = {
                "kind": "alias", "type": "color",
                "target": "base" if index == contract.LIMITS["alias_depth"] - 1 else f"a{index + 1:02d}",
            }
        alias_symbols["zouter"] = {
            "kind": "alias", "type": "color", "target": "a00",
        }
        with self.assertRaises(core.CompilerError) as caught:
            core._resolve_symbols(alias_symbols)
        self.assertEqual(caught.exception.code, "E_LIMIT_ALIAS_DEPTH")

        depth_symbols: dict[str, dict[str, object]] = {
            "base": {"kind": "literal", "type": "color", "value": "#000000ff"},
        }
        for index in reversed(range(contract.LIMITS["nesting"])):
            depth_symbols[f"d{index:02d}"] = {
                "kind": "derivation", "type": "color",
                "operation": "srgb-alpha-preservation",
                "operands": ["base" if index == contract.LIMITS["nesting"] - 1 else f"d{index + 1:02d}"],
            }
        depth_symbols["outer"] = {
            "kind": "derivation", "type": "color",
            "operation": "srgb-alpha-preservation", "operands": ["d00"],
        }
        with self.assertRaises(core.CompilerError) as caught:
            core._resolve_symbols(depth_symbols)
        self.assertEqual(caught.exception.code, "E_LIMIT_NESTING")

    def test_remaining_provenance_walk_and_output_parent_edges(self):
        core._check_package_safety({"metadata": {"provenance": []}, "variants": {}})
        candidate = fixture_package()
        candidate["metadata"]["provenance"] = []
        with self.assertRaises(core.CompilerError) as caught:
            core._validate_complete_package(candidate)
        self.assertEqual(caught.exception.code, "E_PACKAGE_VALIDATION")
        candidate = fixture_package()
        candidate["metadata"]["provenance"].pop("semantic_hash")
        with self.assertRaises(core.CompilerError) as caught:
            core._validate_complete_package(candidate)
        self.assertEqual(caught.exception.code, "E_PACKAGE_VALIDATION")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(core.CompilerError) as caught:
                core.compile_normalized_to_path(normalized(), Path(td) / "missing" / "theme.json")
            self.assertEqual(caught.exception.code, "E_OUTPUT_PROMOTION")

    def test_maximum_declared_symbol_graph_fits_resource_budget(self):
        source = normalized()
        source["tokens"] = [
            {"name": "base", "type": "color", "value": "#000000ff"}
        ] + [
            {"name": f"token{i:04d}", "type": "boolean", "value": True}
            for i in range(contract.LIMITS["tokens"] - 1)
        ]
        source["aliases"] = [
            {"name": f"alias{i:04d}", "type": "color", "target": "base"}
            for i in range(contract.LIMITS["aliases"])
        ]
        started = time.process_time()
        result = core.compile_normalized(source)
        cpu_seconds = time.process_time() - started
        rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        self.assertLessEqual(cpu_seconds, core.MAX_COMPILE_CPU_SECONDS)
        self.assertLessEqual(rss_bytes, core.MAX_COMPILE_RSS_BYTES)
        self.assertEqual(
            result.receipt["resource_budget"],
            {
                "cpu_milliseconds": int(core.MAX_COMPILE_CPU_SECONDS * 1000),
                "rss_bytes": core.MAX_COMPILE_RSS_BYTES,
            },
        )

    def test_production_has_no_network_subprocess_or_dynamic_execution_capability(self):
        tree = ast.parse(PRODUCTION.read_text(), filename=str(PRODUCTION))
        forbidden_modules = {"subprocess", "socket", "urllib", "http", "requests"}
        forbidden_calls = {"eval", "exec", "compile"}
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(alias.name for alias in node.names if alias.name.split(".")[0] in forbidden_modules)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in forbidden_modules:
                violations.append(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                    violations.append(node.func.id)
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "Popen"}:
                    violations.append(node.func.attr)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

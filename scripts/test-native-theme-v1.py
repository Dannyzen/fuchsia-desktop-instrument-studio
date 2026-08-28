#!/usr/bin/env python3
"""Phase 1 proof tests for the bounded NativeThemeV1 color contract."""

from __future__ import annotations

import copy
import hashlib
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))
import native_theme_v1 as contract
TOOL = ROOT / "tools/native_theme/native_theme_v1.py"
VALIDATOR = ROOT / "tools/native_theme/validate_native_theme_v1.py"
FIXTURE = ROOT / "tools/native_theme/fixtures/base24-instrument-studio.yaml"
GOLDEN = ROOT / "tools/native_theme/fixtures/base24-instrument-studio.golden.json"
SCHEMA = ROOT / "tools/native_theme/native-theme-v1.schema.json"
MANIFEST = ROOT / "tools/native_theme/fixtures/profile-fixture-manifest.json"
LEGACY = ROOT / "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs"
EXPECTED_SEMANTIC_HASH = "sha256:455014e692f51a536550a1e0368b66b1758bdfb7e7037f35acc2dc570aa24051"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *map(str, args)], cwd=ROOT, check=check, text=True, capture_output=True
    )


class NativeThemeV1ProofTests(unittest.TestCase):
    maxDiff = None

    def compile_base24(self, source: Path, output: Path, *, check: bool = True):
        return run(TOOL, "compile-base24", "--input", source, "--output", output, check=check)

    def compile_legacy(self, output: Path):
        return run(TOOL, "compile-legacy", "--tokens-rs", LEGACY, "--output", output)

    def test_base24_compiles_to_exact_golden_and_independent_validator_accepts(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "theme.json"
            self.compile_base24(FIXTURE, output)
            self.assertEqual(output.read_bytes(), GOLDEN.read_bytes())
            result = run(VALIDATOR, output)
            self.assertEqual(result.stdout.strip(), "VALID NativeThemeV1")

    def test_clean_compiles_are_byte_identical_with_stable_semantic_hash(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.json"
            b = Path(td) / "b.json"
            self.compile_base24(FIXTURE, a)
            self.compile_base24(FIXTURE, b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            snapshot = json.loads(a.read_text())
            semantic = {"schema_version": snapshot["schema_version"], "variant": snapshot["variant"], "colors": snapshot["colors"]}
            canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            expected = "sha256:" + hashlib.sha256(canonical).hexdigest()
            self.assertEqual(snapshot["semantic_hash"], expected)
            self.assertEqual(snapshot["semantic_hash"], EXPECTED_SEMANTIC_HASH)

    def test_legacy_constants_and_base24_fixture_are_semantically_equivalent(self):
        with tempfile.TemporaryDirectory() as td:
            base24 = Path(td) / "base24.json"
            legacy = Path(td) / "legacy.json"
            self.compile_base24(FIXTURE, base24)
            self.compile_legacy(legacy)
            a = json.loads(base24.read_text())
            b = json.loads(legacy.read_text())
            self.assertEqual(a["colors"], b["colors"])
            self.assertEqual(a["semantic_hash"], b["semantic_hash"])
            self.assertEqual(b["source"]["identity"], "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs")

    def assert_rejected(self, body: str, expected: str):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "invalid.yaml"
            output = Path(td) / "out.json"
            source.write_text(body)
            result = self.compile_base24(source, output, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)
            self.assertFalse(output.exists())

    def test_alias_unknown_missing_invalid_and_low_contrast_inputs_fail_deterministically(self):
        good = FIXTURE.read_text()
        self.assert_rejected(good.replace('base00: "12141a"', 'base00: *canvas'), "aliases are forbidden")
        self.assert_rejected(good + 'surprise: "nope"\n', "unsupported key: surprise")
        self.assert_rejected(good.replace('base17: "e99bff"\n', ''), "missing required key: base17")
        self.assert_rejected(good.replace('base08: "f25966"', 'base08: "nothex"'), "base08 must be exactly six hexadecimal digits")
        self.assert_rejected(good.replace('base07: "edf2fa"', 'base07: "12141a"'), "text.bright contrast")

    def test_successful_compile_requires_repository_bound_source(self):
        with tempfile.TemporaryDirectory() as td:
            external = Path(td) / "external.yaml"
            output = Path(td) / "out.json"
            external.write_bytes(FIXTURE.read_bytes())
            result = self.compile_base24(external, output, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source must be inside repository", result.stderr)
            self.assertFalse(output.exists())

    def test_source_size_bound_fails_before_parsing(self):
        self.assert_rejected("#" * (64 * 1024 + 1), "source exceeds 65536 bytes")

    def test_schema_encodes_exact_bounded_source_and_provenance_profiles(self):
        schema = json.loads(SCHEMA.read_text())
        legacy = schema["$defs"]["legacySnapshot"]
        properties = legacy["properties"]
        self.assertEqual(properties["compiler_version"]["const"], "0.1.0-proof")
        self.assertEqual(
            properties["source"]["properties"]["format"]["enum"],
            ["base24-yaml-flat-v1", "rust-theme-tokens-v1"],
        )
        self.assertEqual(
            properties["provenance"]["properties"]["surface.canvas"]["properties"]["kind"]["enum"],
            ["derived", "explicit", "legacy-quantized"],
        )
        self.assertEqual(len(legacy["allOf"]), 2)
        formats = [entry["if"]["properties"]["source"]["properties"]["format"]["const"] for entry in legacy["allOf"]]
        self.assertEqual(formats, ["base24-yaml-flat-v1", "rust-theme-tokens-v1"])

    def test_independent_validator_enforces_schema_and_source_provenance(self):
        golden = json.loads(GOLDEN.read_text())
        cases = {
            "wrong compiler version": lambda data: data.__setitem__("compiler_version", "999"),
            "compiler version wrong type": lambda data: data.__setitem__("compiler_version", 999),
            "empty source identity": lambda data: data["source"].__setitem__("identity", ""),
            "empty source format": lambda data: data["source"].__setitem__("format", ""),
            "empty source profile": lambda data: data["source"].__setitem__("profile_version", ""),
            "unknown provenance kind": lambda data: data["provenance"]["surface.canvas"].__setitem__("kind", "unknown"),
            "unknown provenance token": lambda data: data["provenance"]["surface.canvas"].__setitem__("source_token", "unknown"),
            "overlong source identity": lambda data: data["source"].__setitem__("identity", "x" * 129),
            "overlong source format": lambda data: data["source"].__setitem__("format", "x" * 129),
            "overlong source profile": lambda data: data["source"].__setitem__("profile_version", "x" * 129),
            "overlong provenance kind": lambda data: data["provenance"]["surface.canvas"].__setitem__("kind", "x" * 129),
            "overlong provenance token": lambda data: data["provenance"]["surface.canvas"].__setitem__("source_token", "x" * 129),
            "tampered source content hash": lambda data: data["source"].__setitem__("content_sha256", "sha256:" + "0" * 64),
        }
        accepted = []
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                data = json.loads(json.dumps(golden))
                mutate(data)
                snapshot = Path(td) / "tampered.json"
                snapshot.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
                result = run(VALIDATOR, snapshot, check=False)
                if result.returncode == 0:
                    accepted.append(name)
        self.assertEqual(accepted, [], "validator accepted schema/provenance tampering")

    def test_independent_validator_rejects_hash_tampering_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "theme.json"
            self.compile_base24(FIXTURE, output)
            data = json.loads(output.read_text())
            data["semantic_hash"] = "sha256:" + "0" * 64
            output.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
            bad_hash = run(VALIDATOR, output, check=False)
            self.assertNotEqual(bad_hash.returncode, 0)
            self.assertIn("semantic_hash mismatch", bad_hash.stderr)
            data = json.loads(GOLDEN.read_text())
            data["unexpected"] = True
            output.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
            extra = run(VALIDATOR, output, check=False)
            self.assertNotEqual(extra.returncode, 0)
            self.assertIn("unexpected top-level fields", extra.stderr)


class NativeThemeV1ContractTests(unittest.TestCase):
    FIXTURES = ROOT / "tools/native_theme/fixtures"

    def package(self):
        return contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")

    def assert_package_code(self, code, mutate):
        candidate = json.loads(json.dumps(self.package()))
        mutate(candidate)
        with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
            contract.validate_package(candidate)

    def test_coverage_strict_loading_canonical_limits_and_structural_dispatch(self):
        schema = contract.load_json_strict(SCHEMA)
        package = self.package()
        contract.validate_root_schema_structural(schema, package)
        contract.validate_root_schema_structural(schema, {"colors": {}})
        with self.assertRaisesRegex(contract.ContractError, "^E_SCHEMA_ROOT:"):
            contract.validate_root_schema_structural({}, {})
        with self.assertRaisesRegex(contract.ContractError, "^E_SCHEMA_ROOT:"):
            contract.validate_root_schema_structural(schema, {})
        contract._exact_object({"a": 1}, {"a"}, "E_SHAPE")
        with self.assertRaisesRegex(contract.ContractError, "^E_SHAPE:"):
            contract._exact_object([], {"a"}, "E_SHAPE")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "value.json"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(contract.ContractError, "^E_UTF8:"):
                contract.load_json_strict(path)
            path.write_text("[]")
            with self.assertRaisesRegex(contract.ContractError, "^E_JSON_ROOT:"):
                contract.load_json_strict(path)
            path.write_bytes(b" " * (contract.LIMITS["source_bytes"] + 1))
            with self.assertRaisesRegex(contract.ContractError, "^E_LIMIT_SOURCE:"):
                contract.load_json_strict(path)
        with self.assertRaisesRegex(contract.ContractError, "^E_LIMIT_STRING:"):
            contract.canonical_json_bytes("x" * (contract.LIMITS["string_bytes"] + 1))
        nested = None
        for _ in range(contract.LIMITS["nesting"] + 2):
            nested = [nested]
        with self.assertRaisesRegex(contract.ContractError, "^E_LIMIT_NESTING:"):
            contract.canonical_json_bytes(nested)

    def test_coverage_profile_and_manifest_rejections_are_exact(self):
        good = contract.load_json_strict(self.FIXTURES / "profiles/base24-positive.json")
        cases = [
            ("E_PROFILE_FIELDS", lambda d: d.__setitem__("extra", 1)),
            ("E_VERSION_PROFILE", lambda d: d.__setitem__("profile_version", "future")),
            ("E_PROFILE_TOKENS", lambda d: d.__setitem__("tokens", {})),
        ]
        for code, mutate in cases:
            candidate = json.loads(json.dumps(good)); mutate(candidate)
            with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
                contract.validate_profile_fixture(candidate)
        manifest = contract.load_json_strict(MANIFEST)
        for mutate, code in (
            (lambda d: d.__setitem__("schema_version", "0"), "E_MANIFEST"),
            (lambda d: d.__setitem__("profiles", []), "E_MANIFEST"),
            (lambda d: d["profiles"][0].pop("type"), "E_MANIFEST"),
            (lambda d: d["profiles"][0].__setitem__("complete_package", {}), "E_MANIFEST_COVERAGE"),
            (lambda d: d["profiles"][0]["positive_cases"].append({"file": "missing.json"}), "E_MANIFEST_COVERAGE"),
            (lambda d: d["profiles"][0]["diagnostics"].append("E_NOT_CATALOGED"), "E_MANIFEST_COVERAGE"),
        ):
            candidate = json.loads(json.dumps(manifest)); mutate(candidate)
            with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
                contract.validate_profile_manifest(candidate, self.FIXTURES / "profiles")

    def test_coverage_package_rejection_matrix(self):
        cases = [
            ("E_FIELD_REQUIRED", lambda p: p.pop("theme")),
            ("E_VERSION_PROFILE", lambda p: p.__setitem__("profile", {})),
            ("E_METADATA_REQUIRED", lambda p: p.__setitem__("metadata", [])),
            ("E_PROVENANCE", lambda p: p["metadata"]["provenance"].__setitem__("source_identity", "/private")),
            ("E_PROVENANCE", lambda p: p["metadata"]["provenance"].__setitem__("tokens", {"x": {"kind": "bad"}})),
            ("E_COMPATIBILITY", lambda p: p.__setitem__("policy", [])),
            ("E_DOMAIN_REQUIRED", lambda p: p["variants"].__setitem__("dark", [])),
            ("E_LAYER_REQUIRED", lambda p: p["variants"]["dark"].__setitem__("components", {})),
            ("E_COLOR_CANONICAL", lambda p: p["variants"]["dark"]["semantic"].__setitem__("text.normal", 3)),
            ("E_LIMIT_ASSETS", lambda p: p["variants"]["dark"]["assets"]["items"].update({f"a{i}": {} for i in range(64)})),
            ("E_TYPOGRAPHY", lambda p: p["variants"]["dark"]["typography"].__setitem__("families", {"ui": []})),
            ("E_TYPOGRAPHY", lambda p: p["variants"]["dark"]["typography"]["roles"]["body"].pop("family")),
            ("E_GEOMETRY", lambda p: p["variants"]["dark"]["geometry"].__setitem__("density", "huge")),
            ("E_ELEVATION", lambda p: p["variants"]["dark"]["elevation"].__setitem__("levels", {})),
            ("E_ELEVATION", lambda p: p["variants"]["dark"]["elevation"]["levels"].__setitem__("flat", {})),
            ("E_OPACITY", lambda p: p["variants"]["dark"].__setitem__("opacity", [])),
            ("E_MOTION", lambda p: p["variants"]["dark"].__setitem__("motion", {})),
        ]
        for code, mutate in cases:
            with self.subTest(code=code): self.assert_package_code(code, mutate)

    def test_coverage_parser_legacy_and_atomic_write_failures(self):
        good = FIXTURE.read_text()
        malformed = [
            (" nested", "indentation"), ("plain", "expected key"),
            ("x" * 129 + ": v", "identifier exceeds"),
            ("scheme: a\nscheme: b", "duplicate key"),
            ("scheme: [x]", "structured YAML"),
            ("scheme: " + "x" * 129, "value exceeds"),
            (good.replace('variant: "dark"', 'variant: "light"'), "variant must be dark"),
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.yaml"
            path.write_bytes(b"\xff")
            with self.assertRaisesRegex(contract.ContractError, "valid UTF-8"):
                contract.read_bounded(path)
            for body, message in malformed:
                path.write_text(body)
                with self.assertRaisesRegex(contract.ContractError, message): contract.parse_flat_base24(path)
            legacy = Path(td) / "tokens.rs"
            legacy.write_text(LEGACY.read_text().replace("panel_bg:", "removed_panel_bg:"))
            with self.assertRaisesRegex(contract.ContractError, "missing legacy colors"):
                contract.compile_legacy(legacy)
            legacy.write_text(LEGACY.read_text().replace("panel_bg: ColorRgba::new(0.07", "panel_bg: ColorRgba::new(1.5"))
            with self.assertRaisesRegex(contract.ContractError, "outside 0..1"):
                contract.compile_legacy(legacy)
            legacy.write_text(LEGACY.read_text().replace(", 1.0),", ", 0.5),", 1))
            with self.assertRaisesRegex(contract.ContractError, "alpha must be 1.0"):
                contract.compile_legacy(legacy)
            self.assertEqual(contract.quantize_channel("0.5"), 128)
            output = Path(td) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(contract.main(["compile-base24", "--input", str(FIXTURE), "--output", str(output)]), 0)
            self.assertTrue(output.is_file())
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(contract.main(["compile-base24", "--input", str(path / "missing"), "--output", str(output)]), 2)

    def test_independent_validator_complete_failure_matrix_and_cli_usage(self):
        spec = importlib.util.spec_from_file_location("independent_validator_coverage", VALIDATOR)
        validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
        golden = json.loads(GOLDEN.read_text())
        cases = [
            "not-object", "oversized", "missing-top", "schema", "compiler", "variant", "identity",
            "colors-object", "colors-roles", "color", "source-object", "source-fields", "hash-format",
            "format", "source-missing", "provenance-roles", "provenance-entry", "provenance-mismatch", "bounds",
        ]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidate.json"
            for name in cases:
                data = json.loads(json.dumps(golden))
                if name == "not-object": data = []
                elif name == "oversized": path.write_bytes(b" " * (128 * 1024 + 1)); data = None
                elif name == "missing-top": data.pop("theme_id")
                elif name == "schema": data["schema_version"] = "2"
                elif name == "compiler": data["compiler_version"] = "2"
                elif name == "variant": data["variant"] = "light"
                elif name == "identity": data["theme_id"] = "other"
                elif name == "colors-object": data["colors"] = []
                elif name == "colors-roles": data["colors"].pop("text.muted")
                elif name == "color": data["colors"]["text.muted"] = "BAD"
                elif name == "source-object": data["source"] = []
                elif name == "source-fields": data["source"]["extra"] = 1
                elif name == "hash-format": data["source"]["content_sha256"] = "bad"
                elif name == "format": data["source"]["format"] = "unknown"
                elif name == "source-missing": data["source"]["identity"] = "missing.yaml"
                elif name == "provenance-roles": data["provenance"].pop("text.muted")
                elif name == "provenance-entry": data["provenance"]["text.muted"] = []
                elif name == "provenance-mismatch": data["provenance"]["text.muted"]["source_token"] = "base00"
                elif name == "bounds": data["bounds"]["tokens"] = 1
                if data is not None: path.write_text(json.dumps(data))
                with self.subTest(name=name), self.assertRaises(validator.ValidationError): validator.validate(path)
            duplicate = Path(td) / "duplicate.json"; duplicate.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(validator.ValidationError, "duplicate JSON key"):
                json.loads(duplicate.read_bytes(), object_pairs_hook=validator.no_duplicates)
            with self.assertRaisesRegex(validator.ValidationError, "must be a string"):
                validator.bounded_text(1, "field")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(validator.main(["validator"]), 2)

    def test_coverage_remaining_native_contract_limits_and_cleanup(self):
        manifest = contract.load_json_strict(MANIFEST)
        candidate = json.loads(json.dumps(manifest))
        candidate["profiles"][0]["complete_package"]["sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(contract.ContractError, "^E_MANIFEST_COVERAGE:"):
            contract.validate_profile_manifest(candidate, self.FIXTURES / "profiles")

        self.assert_package_code("E_LIMIT_TOKENS", lambda p: [
            p["variants"]["dark"]["components"].__setitem__(f"component{i}", "fixed")
            for i in range(contract.LIMITS["tokens"])
        ])
        self.assert_package_code("E_LIMIT_PACK", lambda p: [
            p["variants"]["dark"]["components"].__setitem__(f"component{i}", "x" * 4096)
            for i in range(64)
        ])
        self.assert_package_code("E_PROVENANCE", lambda p: p["metadata"]["provenance"].__setitem__("semantic_hash", "sha256:" + "0" * 64))

        class LateInvalid(dict):
            calls = 0
            def get(self, key, default=None):
                if key == "text.normal":
                    self.calls += 1
                    if self.calls >= 1: return 3
                return super().get(key, default)
        package = self.package()
        package["variants"]["dark"]["semantic"] = LateInvalid(package["variants"]["dark"]["semantic"])
        with self.assertRaisesRegex(contract.ContractError, "^E_COLOR_CANONICAL:"):
            contract.validate_package(package)

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "tokens.yaml"
            source.write_text("\n# comment\n" + FIXTURE.read_text())
            with mock.patch.object(contract, "MAX_TOKENS", 1):
                with self.assertRaisesRegex(contract.ContractError, "token count exceeds 1"):
                    contract.parse_flat_base24(source)
            output = Path(td) / "out.json"
            with mock.patch.object(contract.os, "replace", side_effect=OSError("replace denied")):
                with self.assertRaisesRegex(OSError, "replace denied"):
                    contract.write_canonical({"accepted": True}, output)
            self.assertEqual(list(Path(td).glob("out.json.*")), [])

    def test_independent_validator_remaining_source_and_package_cli_branches(self):
        spec = importlib.util.spec_from_file_location("independent_validator_tail", VALIDATOR)
        validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
        golden = json.loads(GOLDEN.read_text())
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidate.json"
            for mutate, message in (
                (lambda d: d["source"].__setitem__("profile_version", "wrong"), "profile_version does not match"),
            ):
                data = json.loads(json.dumps(golden)); mutate(data); path.write_text(json.dumps(data))
                with self.assertRaisesRegex(validator.ValidationError, message): validator.validate(path)
            data = json.loads(json.dumps(golden))
            missing = "tools/native_theme/fixtures/not-present.yaml"
            data["source"]["identity"] = missing; path.write_text(json.dumps(data))
            with mock.patch.dict(validator.PROFILES[data["source"]["format"]], {"identity": missing}):
                with self.assertRaisesRegex(validator.ValidationError, "source file unavailable"):
                    validator.validate(path)
            package = self.package()
            path.write_text(json.dumps(package, indent=2))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(validator.main(["validator", str(path)]), 2)

    def test_root_schema_explicitly_selects_legacy_or_complete_package(self):
        schema = contract.load_json_strict(SCHEMA)
        self.assertEqual(schema["oneOf"], [
            {"$ref": "#/$defs/legacySnapshot"}, {"$ref": "#/$defs/nativePackage"}
        ])
        self.assertIn("legacySnapshot", schema["$defs"])
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        try:
            import jsonschema
        except ImportError:
            contract.validate_root_schema_structural(schema, package)
        else:
            jsonschema.Draft202012Validator(schema).validate(package)

    def test_every_variant_has_exact_complete_semantic_color_taxonomy(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        for name, variant in package["variants"].items():
            self.assertEqual(set(variant["semantic"]), contract.SEMANTIC_COLOR_ROLES, name)
            self.assertNotEqual(variant["semantic"]["border.focusConfirmed"],
                                variant["semantic"]["interaction.selection"])
        for role in sorted(contract.SEMANTIC_COLOR_ROLES):
            candidate = json.loads(json.dumps(package)); candidate["variants"]["dark"]["semantic"].pop(role)
            with self.assertRaisesRegex(contract.ContractError, "^E_SEMANTIC_ROLES:"):
                contract.validate_package(candidate)

    def test_complete_typed_domains_and_representative_bounds(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        contract.validate_package(package)
        cases = [
            ("E_TYPOGRAPHY", lambda p: p["variants"]["dark"]["typography"]["roles"].pop("caption")),
            ("E_GEOMETRY", lambda p: p["variants"]["dark"]["geometry"]["responsive"].__setitem__("narrow_max_px", 900)),
            ("E_ELEVATION", lambda p: p["variants"]["dark"]["elevation"]["levels"]["raised"].__setitem__("blur_px", 99)),
            ("E_OPACITY", lambda p: p["variants"]["dark"]["opacity"].__setitem__("overlay", 1.1)),
            ("E_MOTION", lambda p: p["variants"]["dark"]["motion"]["durations_ms"].__setitem__("short", -1)),
            ("E_ASSET_METADATA", lambda p: p["variants"]["dark"]["assets"]["items"]["status.error"].pop("spdx")),
            ("E_PROVENANCE", lambda p: p["metadata"]["provenance"].pop("semantic_hash")),
            ("E_FALLBACK_REQUIRED", lambda p: p["fallback"].pop("last_known_good")),
            ("E_COMPATIBILITY", lambda p: p["policy"]["compatibility"].__setitem__("window", "N/N-2")),
        ]
        for code, mutate in cases:
            with self.subTest(code=code):
                candidate = json.loads(json.dumps(package)); mutate(candidate)
                with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
                    contract.validate_package(candidate)

    def test_profile_manifest_is_bidirectionally_complete(self):
        manifest = contract.load_json_strict(MANIFEST)
        report = contract.validate_profile_manifest(manifest, self.FIXTURES / "profiles")
        self.assertEqual(report["profiles"], 5)
        self.assertGreaterEqual(report["positive_cases"], 5)
        self.assertGreaterEqual(report["negative_cases"], 25)
        self.assertEqual(report["uncovered"], 0)
        outputs = [entry["complete_package"] for entry in manifest["profiles"]]
        self.assertEqual(len(outputs), 5)
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def test_complete_package_covers_required_variants_layers_and_domains(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        contract.validate_package(package)
        self.assertEqual(set(package["variants"]), {"light", "dark", "high-contrast"})
        for variant in package["variants"].values():
            self.assertEqual(set(variant), {
                "primitives", "semantic", "components", "typography", "geometry",
                "elevation", "opacity", "motion", "assets", "terminal",
            })
            self.assertEqual(len(variant["terminal"]), 16)
            self.assertNotEqual(variant["semantic"]["border.focusConfirmed"], variant["semantic"]["interaction.selection"])

    def test_complete_package_selection_meets_variant_ui_contrast_policy(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        for name, target in (("light", 3.0), ("dark", 3.0), ("high-contrast", 4.5)):
            with self.subTest(variant=name):
                semantic = package["variants"][name]["semantic"]
                ratio = contract.contrast(
                    semantic["interaction.selection"][1:7], semantic["surface.canvas"][1:7])
                self.assertGreaterEqual(ratio, target, f"{name} selection contrast {ratio} below {target}")

    def test_complete_package_bright_ansi_matches_base24_and_omarchy(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        base24 = contract.load_json_strict(self.FIXTURES / "profiles/base24-positive.json")
        omarchy = contract.load_json_strict(self.FIXTURES / "profiles/omarchy-positive.json")
        base24_bright = ["#" + base24["tokens"][f"base{i:02X}"].lower() + "ff" for i in range(0x10, 0x18)]
        omarchy_bright = [color.lower() + "ff" for color in omarchy["tokens"]["ansi.bright"]]
        self.assertEqual(base24_bright, omarchy_bright)
        for name, variant in package["variants"].items():
            with self.subTest(variant=name):
                actual = [variant["terminal"][f"ansi{i}"] for i in range(8, 16)]
                self.assertEqual(actual, base24_bright)

    def test_contract_rejections_have_stable_codes(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        cases = [
            ("E_VERSION_REQUIRED", lambda p: p.__setitem__("schema_version", "2.0.0")),
            ("E_VARIANT_REQUIRED", lambda p: p["variants"].pop("high-contrast")),
            ("E_FIELD_FORBIDDEN", lambda p: p.__setitem__("command", "run-me")),
            ("E_COLOR_CANONICAL", lambda p: p["variants"]["dark"]["primitives"].__setitem__("canvas", "#FFFFFF")),
            ("E_FALLBACK_REQUIRED", lambda p: p["fallback"].pop("built_in_theme_id")),
            ("E_STATUS_NONCOLOR", lambda p: p["variants"]["dark"]["assets"]["items"].pop("status.error")),
            ("E_CONTRAST_NORMAL", lambda p: p["variants"]["dark"]["semantic"].__setitem__("text.normal", "#12141aff")),
        ]
        for code, mutate in cases:
            with self.subTest(code=code):
                candidate = json.loads(json.dumps(package))
                mutate(candidate)
                with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
                    contract.validate_package(candidate)

    def test_complete_package_semantic_hash_excludes_inert_metadata_only(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        baseline_semantic = contract.package_semantic_identity(package)
        baseline_bytes = contract.canonical_json_bytes(package)

        metadata_only = copy.deepcopy(package)
        metadata_only["metadata"]["provenance"]["source_identity"] = "profiles/other-source.json"
        metadata_only["metadata"]["provenance"]["content_hash"] = "sha256:" + "1" * 64
        metadata_only["metadata"]["provenance"]["license"] = "MIT"
        metadata_only["metadata"]["provenance"]["attribution"] = "Other contributor"
        metadata_only["metadata"]["license"] = {"spdx": "MIT", "notice": "Other notice"}
        metadata_only["metadata"]["extensions"] = {
            "org.constructresearch.instrumentstudio.other": {"source": "different"}
        }
        self.assertEqual(contract.package_semantic_identity(metadata_only), baseline_semantic)
        self.assertNotEqual(contract.canonical_json_bytes(metadata_only), baseline_bytes)

        renderable = copy.deepcopy(package)
        renderable["variants"]["dark"]["semantic"]["surface.canvas"] = "#000000ff"
        self.assertNotEqual(contract.package_semantic_identity(renderable), baseline_semantic)

    def test_canonical_bytes_duplicate_keys_numbers_and_semantic_hash(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        canonical = contract.canonical_json_bytes(package)
        self.assertNotIn(b"\n", canonical)
        self.assertEqual(canonical, contract.canonical_json_bytes(json.loads(canonical)))
        self.assertEqual(contract.semantic_identity(package), "sha256:" + hashlib.sha256(canonical).hexdigest())
        with tempfile.TemporaryDirectory() as td:
            duplicate = Path(td) / "duplicate.json"
            duplicate.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(contract.ContractError, "E_JSON_DUPLICATE"):
                contract.load_json_strict(duplicate)
        with self.assertRaisesRegex(contract.ContractError, "E_NUMBER_NONFINITE"):
            contract.canonical_json_bytes({"bad": float("nan")})
        self.assertEqual(contract.canonical_json_bytes({"b": 1.0, "a": -0.0}), b'{"a":0,"b":1}')

    def test_all_import_profiles_have_positive_and_layer_negative_fixtures(self):
        profiles = ("dtcg", "base16", "base24", "omarchy", "legacy")
        for profile in profiles:
            with self.subTest(profile=profile):
                positive = self.FIXTURES / "profiles" / f"{profile}-positive.json"
                negative = self.FIXTURES / "profiles" / f"{profile}-negative-layer.json"
                contract.validate_profile_fixture(contract.load_json_strict(positive))
                with self.assertRaisesRegex(contract.ContractError, "E_PROFILE_LAYER"):
                    contract.validate_profile_fixture(contract.load_json_strict(negative))

    def test_limits_and_extension_namespace_are_machine_checkable(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        self.assertEqual(contract.LIMITS["source_bytes"], 1024 * 1024)
        self.assertEqual(contract.LIMITS["compiled_pack_bytes"], 256 * 1024)
        candidate = json.loads(json.dumps(package))
        candidate["metadata"]["extensions"] = {"com.example.private": True}
        with self.assertRaisesRegex(contract.ContractError, "E_EXTENSION_NAMESPACE"):
            contract.validate_package(candidate)

    def test_domain_shapes_assets_licensing_and_ui_contrast_are_enforced(self):
        package = contract.load_json_strict(self.FIXTURES / "native-theme-v1-package.json")
        cases = [
            ("E_LICENSE", lambda p: p["metadata"].__setitem__("license", {})),
            ("E_TYPOGRAPHY", lambda p: p["variants"]["dark"].__setitem__("typography", {})),
            ("E_GEOMETRY", lambda p: p["variants"]["dark"].__setitem__("geometry", {})),
            ("E_ASSET_PATH", lambda p: p["variants"]["dark"]["assets"]["items"]["status.error"].__setitem__("path", "../escape.svg")),
            ("E_REDUCED_MOTION", lambda p: p["variants"]["dark"]["motion"].__setitem__("reduced", {"duration_ms": 1, "essential_only": True})),
            ("E_CONTRAST_UI", lambda p: p["variants"]["dark"]["semantic"].__setitem__("border.focusConfirmed", "#12141aff")),
            ("E_CONTRAST_SELECTION", lambda p: p["variants"]["dark"]["semantic"].__setitem__("interaction.selection", "#12141aff")),
            ("E_FOCUS_DISTINCT", lambda p: p["variants"]["dark"]["semantic"].__setitem__("interaction.selection", p["variants"]["dark"]["semantic"]["border.focusConfirmed"])),
        ]
        for code, mutate in cases:
            with self.subTest(code=code):
                candidate = json.loads(json.dumps(package)); mutate(candidate)
                with self.assertRaisesRegex(contract.ContractError, "^" + code + ":"):
                    contract.validate_package(candidate)

    def test_validator_accepts_complete_package_and_is_deterministic_twice(self):
        fixture = self.FIXTURES / "native-theme-v1-package.json"
        first = run(VALIDATOR, fixture)
        second = run(VALIDATOR, fixture)
        self.assertEqual(first.stdout, second.stdout)
        self.assertRegex(first.stdout, r"VALID NativeThemeV1 sha256:[0-9a-f]{64}")

    def test_schema_publishes_machine_readable_contract_policy(self):
        schema = json.loads(SCHEMA.read_text())
        policy = schema["x-native-theme-v1-contract"]
        self.assertEqual(policy["required_variants"], ["light", "dark", "high-contrast"])
        self.assertEqual(policy["token_layers"], ["primitives", "semantic", "components"])
        self.assertEqual(policy["canonical_color"], "lowercase-rrggbbaa-srgb")
        self.assertEqual(policy["extension_namespace"], "org.constructresearch.instrumentstudio.*")
        self.assertEqual(policy["limits"], contract.LIMITS)
        self.assertEqual(policy["contrast_targets"], {
            "ordinary": {"normal_text": 4.5, "selection": 3.0, "focus": 3.0},
            "high-contrast": {"normal_text": 7.0, "selection": 4.5, "focus": 4.5},
        })
        self.assertIn("command", policy["forbidden_fields"])
        self.assertIn("semantic_hash", policy["derived_fields"])
        self.assertEqual(set(policy["import_profiles"]), set(contract.PROFILE_LAYERS))
        self.assertIn("nativePackage", schema["$defs"])

    def test_profile_and_decision_docs_cover_normative_conversion_and_policy(self):
        profile = (ROOT / "docs/native-theme-v1-profile.md").read_text()
        decisions = (ROOT / "docs/native-theme-v1-contract-decisions.md").read_text()
        for phrase in ("DTCG Format and Color Modules 2025.10", "Display-P3", "OKLCH", "clamp", "E_PROFILE_LAYER"):
            self.assertIn(phrase, profile)
        for phrase in ("restart-to-apply", "fail closed", "7.0", "4.5", "No external asset packs"):
            self.assertIn(phrase, decisions)


if __name__ == "__main__":
    unittest.main(verbosity=2)

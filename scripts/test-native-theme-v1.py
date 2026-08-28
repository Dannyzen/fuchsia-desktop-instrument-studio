#!/usr/bin/env python3
"""Phase 1 proof tests for the bounded NativeThemeV1 color contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/native_theme/native_theme_v1.py"
VALIDATOR = ROOT / "tools/native_theme/validate_native_theme_v1.py"
FIXTURE = ROOT / "tools/native_theme/fixtures/base24-instrument-studio.yaml"
GOLDEN = ROOT / "tools/native_theme/fixtures/base24-instrument-studio.golden.json"
SCHEMA = ROOT / "tools/native_theme/native-theme-v1.schema.json"
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
        properties = schema["properties"]
        self.assertEqual(properties["compiler_version"]["const"], "0.1.0-proof")
        self.assertEqual(
            properties["source"]["properties"]["format"]["enum"],
            ["base24-yaml-flat-v1", "rust-theme-tokens-v1"],
        )
        self.assertEqual(
            properties["provenance"]["properties"]["surface.canvas"]["properties"]["kind"]["enum"],
            ["derived", "explicit", "legacy-quantized"],
        )
        self.assertEqual(len(schema["allOf"]), 2)
        formats = [entry["if"]["properties"]["source"]["properties"]["format"]["const"] for entry in schema["allOf"]]
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


if __name__ == "__main__":
    unittest.main(verbosity=2)

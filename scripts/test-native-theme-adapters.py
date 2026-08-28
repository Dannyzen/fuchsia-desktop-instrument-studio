#!/usr/bin/env python3
"""Executable contract tests for the bounded NativeTheme external adapters."""

from __future__ import annotations

import ast
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE_THEME = ROOT / "tools/native_theme"
FIXTURES = NATIVE_THEME / "fixtures"
PROFILES = FIXTURES / "profiles"
ADAPTER_FIXTURES = FIXTURES / "adapters"
sys.path.insert(0, str(NATIVE_THEME))

from adapters import (  # noqa: E402
    AdapterError,
    AdapterProvenance,
    adapt_base16,
    adapt_base24,
    adapt_dtcg_2025_10,
    adapt_omarchy_palette,
)
from compiler_core import compile_normalized  # noqa: E402
from native_theme_v1 import package_semantic_identity  # noqa: E402


TARGET_SEMANTIC_HASH = "sha256:5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a"
SOURCE_IDENTITY = "tools/native_theme/fixtures/profiles/adapter-input"
PROVENANCE = AdapterProvenance(
    source_identity=SOURCE_IDENTITY,
    license_spdx="BSD-3-Clause",
    attribution="Construct Research contributors",
    notice="Copyright Construct Research contributors",
)


def raw(path: Path) -> bytes:
    return path.read_bytes()


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unchecked_provenance(**changes):
    values = {
        "source_identity": SOURCE_IDENTITY,
        "license_spdx": PROVENANCE.license_spdx,
        "attribution": PROVENANCE.attribution,
        "notice": PROVENANCE.notice,
    }
    values.update(changes)
    provenance = AdapterProvenance.__new__(AdapterProvenance)
    for field, value in values.items():
        object.__setattr__(provenance, field, value)
    return provenance


def omarchy_root_field(source: bytes, line: bytes) -> bytes:
    return source.replace(b"\n[status]\n", b"\n" + line + b"\n[status]\n", 1)


class PositiveAdapterTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.template_bytes = raw(FIXTURES / "native-theme-v1-package.json")
        cls.template_data = json.loads(cls.template_bytes)

    def assert_positive(self, adapter, source: bytes):
        normalized = adapter(source, self.template_bytes, PROVENANCE)
        result = compile_normalized(normalized)
        self.assertEqual(result.semantic_hash, TARGET_SEMANTIC_HASH)
        expected_content_hash = "sha256:" + hashlib.sha256(source).hexdigest()
        self.assertEqual(normalized["source_content_hash"], expected_content_hash)
        self.assertEqual(result.package["metadata"]["provenance"]["content_hash"], expected_content_hash)
        self.assertEqual(result.package["metadata"]["provenance"]["semantic_hash"], TARGET_SEMANTIC_HASH)
        self.assertEqual(result.package["metadata"]["provenance"]["source_identity"], SOURCE_IDENTITY)
        self.assertEqual(result.package["metadata"]["license"], {
            "spdx": PROVENANCE.license_spdx, "notice": PROVENANCE.notice,
        })
        self.assertIn("package_sha256", result.receipt)
        self.assertNotEqual(result.receipt["package_sha256"], result.receipt["source_content_hash"])
        return normalized, result

    def test_base16_positive_uses_declared_map_and_bright_fallback(self):
        source = raw(PROFILES / "base16-positive.json")
        normalized, result = self.assert_positive(adapt_base16, source)
        dark = result.package["variants"]["dark"]
        self.assertEqual(dark["semantic"]["surface.canvas"], "#12141aff")
        self.assertEqual(dark["terminal"]["ansi7"], "#d8e0ecff")
        self.assertEqual(dark["terminal"]["ansi8"], self.template_data["variants"]["dark"]["terminal"]["ansi8"])
        derivations = result.package["metadata"]["provenance"]["tokens"]
        self.assertEqual(derivations["terminal.ansi4"], {
            "derivation": "base16-bright-ansi-fallback-v1",
            "kind": "derived",
            "source_token": "builtin.terminal.ansi4",
        })
        self.assertEqual(derivations["terminal.ansi8"]["derivation"], "base16-bright-ansi-fallback-v1")
        self.assertIn("org.constructresearch.instrumentstudio.adapter_source", normalized["package"]["metadata"]["extensions"])

    def test_base24_positive_maps_base10_through_base17_to_bright_ansi(self):
        source = raw(PROFILES / "base24-positive.json")
        _, result = self.assert_positive(adapt_base24, source)
        dark = result.package["variants"]["dark"]
        expected = json.loads(source)["tokens"]
        self.assertEqual(
            [dark["terminal"][f"ansi{i}"] for i in range(8, 16)],
            ["#" + expected[f"base1{i - 8}"] + "ff" for i in range(8, 16)],
        )

    def test_omarchy_toml_is_value_equivalent_to_normative_json(self):
        source = raw(ADAPTER_FIXTURES / "omarchy-positive.colors.toml")
        normalized, result = self.assert_positive(adapt_omarchy_palette, source)
        authority = json.loads(raw(PROFILES / "omarchy-positive.json"))["tokens"]
        preserved = normalized["package"]["metadata"]["extensions"][
            "org.constructresearch.instrumentstudio.adapter_source"
        ]["tokens"]
        self.assertEqual(preserved, authority)
        dark = result.package["variants"]["dark"]
        self.assertEqual(dark["semantic"]["surface.deep"], authority["background.ramp"][0] + "ff")
        self.assertEqual(dark["terminal"]["ansi15"], authority["ansi.bright"][7] + "ff")
        self.assertEqual(
            result.package["metadata"]["provenance"]["tokens"]["semantic.interaction.selection"],
            {
                "derivation": "palette-owned-selection-policy-v1",
                "kind": "derived",
                "source_token": "selection",
            },
        )

    def test_dtcg_composite_coverage_aliases_and_inherited_color(self):
        source = raw(PROFILES / "dtcg-positive.json")
        normalized, result = self.assert_positive(adapt_dtcg_2025_10, source)
        extension = normalized["package"]["metadata"]["extensions"][
            "org.constructresearch.instrumentstudio.adapter_source"
        ]
        self.assertEqual(extension["tokens"], json.loads(source)["tokens"])
        self.assertEqual(result.package["variants"]["dark"]["semantic"]["surface.canvas"], "#12141aff")
        token_provenance = result.package["metadata"]["provenance"]["tokens"]
        self.assertEqual(token_provenance["group.canvas"]["kind"], "inherited")
        self.assertEqual(token_provenance["aliased"]["derivation"], "curly-alias-resolution")
        for name in (
            "types.border", "types.dimension", "types.duration", "types.easing",
            "types.fontFamily", "types.fontWeight", "types.gradient", "types.number",
            "types.shadow", "types.transition", "types.typography",
        ):
            self.assertIn(name, token_provenance)

    def test_dtcg_accepts_each_declared_profile_layer(self):
        authority = json.loads(raw(PROFILES / "dtcg-positive.json"))
        for layer in ("components", "primitives", "semantic"):
            with self.subTest(layer=layer):
                candidate = copy.deepcopy(authority)
                candidate["declared_layer"] = layer
                result = compile_normalized(adapt_dtcg_2025_10(encoded(candidate), self.template_bytes, PROVENANCE))
                self.assertEqual(result.semantic_hash, TARGET_SEMANTIC_HASH)

    def test_results_are_fresh_and_inputs_are_never_mutated(self):
        source = raw(PROFILES / "base24-positive.json")
        template = json.loads(self.template_bytes)
        before = copy.deepcopy(template)
        first = adapt_base24(source, template, PROVENANCE)
        second = adapt_base24(source, template, PROVENANCE)
        self.assertEqual(template, before)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["package"], second["package"])
        first["package"]["variants"]["dark"]["semantic"]["surface.canvas"] = "#000000ff"
        self.assertEqual(second["package"]["variants"]["dark"]["semantic"]["surface.canvas"], "#12141aff")

    def test_provenance_is_immutable_and_template_authority_is_exact(self):
        with self.assertRaises(FrozenInstanceError):
            PROVENANCE.source_identity = "changed"
        tampered = copy.deepcopy(self.template_data)
        tampered["variants"]["light"]["semantic"]["surface.canvas"] = "#000000ff"
        with self.assertRaises(AdapterError) as raised:
            adapt_base24(raw(PROFILES / "base24-positive.json"), tampered, PROVENANCE)
        self.assertEqual(raised.exception.code, "E_TEMPLATE_PACKAGE")


class ManifestNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = raw(FIXTURES / "native-theme-v1-package.json")
        cls.manifest = json.loads(raw(FIXTURES / "profile-fixture-manifest.json"))
        cls.adapters = {
            "dtcg-2025.10-instrument-studio-v1": adapt_dtcg_2025_10,
            "base16-v1": adapt_base16,
            "base24-v1": adapt_base24,
            "omarchy-colors-toml-v1": adapt_omarchy_palette,
        }
        cls.base16 = json.loads(raw(PROFILES / "base16-positive.json"))
        cls.base24 = json.loads(raw(PROFILES / "base24-positive.json"))
        cls.dtcg = json.loads(raw(PROFILES / "dtcg-positive.json"))
        cls.omarchy = raw(ADAPTER_FIXTURES / "omarchy-positive.colors.toml")

    def assert_code(self, code: str, callable_):
        with self.assertRaises(AdapterError) as raised:
            callable_()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(str(raised.exception), f"{code}: {raised.exception.message}")

    @staticmethod
    def json_mutation(authority, mutation):
        candidate = copy.deepcopy(authority)
        mutation(candidate)
        return encoded(candidate)

    def test_manifest_26_concrete_behavior_matrix(self):
        def dtcg_cycle(value):
            value["tokens"]["cycle_a"] = {"$type": "color", "$value": "{cycle_b}"}
            value["tokens"]["cycle_b"] = {"$type": "color", "$value": "{cycle_a}"}

        def dtcg_depth(value):
            for index in range(34):
                target = "group.canvas" if index == 33 else f"depth{index + 1}"
                value["tokens"][f"depth{index}"] = {"$type": "color", "$value": f"{{{target}}}"}

        def omarchy_root_field(line: bytes) -> bytes:
            return self.omarchy.replace(b"\n[status]\n", b"\n" + line + b"\n[status]\n", 1)

        builders = {
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-1"): (
                adapt_dtcg_2025_10, "E_PROFILE_STRUCTURE",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"].__setitem__("broken", "not-an-object")),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-2"): (
                adapt_dtcg_2025_10, "E_FIELD_FORBIDDEN",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"]["group"]["canvas"].__setitem__("$deprecated", True)),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-3"): (
                adapt_dtcg_2025_10, "E_ALIAS_CYCLE", lambda: self.json_mutation(self.dtcg, dtcg_cycle),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-4"): (
                adapt_dtcg_2025_10, "E_ALIAS_UNRESOLVED",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"]["aliased"].__setitem__("$value", "{missing}")),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-5"): (
                adapt_dtcg_2025_10, "E_LIMIT_ALIAS_DEPTH", lambda: self.json_mutation(self.dtcg, dtcg_depth),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-6"): (
                adapt_dtcg_2025_10, "E_TYPE_INHERITED",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"]["group"]["canvas"].__setitem__("$type", "dimension")),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-7"): (
                adapt_dtcg_2025_10, "E_EXTENSION_UNSUPPORTED",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"].__setitem__("$extensions", {"com.example.theme": True})),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-8"): (
                adapt_dtcg_2025_10, "E_COLOR_COMPONENT",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"]["group"]["canvas"]["$value"].__setitem__("components", [0, 2, 0])),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-9"): (
                adapt_dtcg_2025_10, "E_COLOR_SPACE",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"]["group"]["canvas"]["$value"].__setitem__("colorSpace", "display-p3")),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-10"): (
                adapt_dtcg_2025_10, "E_EXECUTABLE",
                lambda: self.json_mutation(self.dtcg, lambda value: value["tokens"].__setitem__("command", "theme-reload")),
            ),
            ("dtcg-2025.10-instrument-studio-v1", "dtcg-layer"): (
                adapt_dtcg_2025_10, "E_PROFILE_LAYER",
                lambda: self.json_mutation(self.dtcg, lambda value: value.__setitem__("declared_layer", "forbidden")),
            ),
            ("base16-v1", "base16-1"): (
                adapt_base16, "E_FIELD_REQUIRED",
                lambda: self.json_mutation(self.base16, lambda value: value["tokens"].pop("base00")),
            ),
            ("base16-v1", "base16-2"): (
                adapt_base16, "E_FIELD_EXTRA",
                lambda: self.json_mutation(self.base16, lambda value: value["tokens"].__setitem__("ordinary", "12141a")),
            ),
            ("base16-v1", "base16-3"): (
                adapt_base16, "E_COLOR_CANONICAL",
                lambda: self.json_mutation(self.base16, lambda value: value["tokens"].__setitem__("base00", "12141A")),
            ),
            ("base16-v1", "base16-4"): (
                adapt_base16, "E_FIELD_FORBIDDEN",
                lambda: self.json_mutation(self.base16, lambda value: value.__setitem__("command", "theme-reload")),
            ),
            ("base16-v1", "base16-5"): (
                adapt_base16, "E_PROFILE_LAYER",
                lambda: self.json_mutation(self.base16, lambda value: value.__setitem__("declared_layer", "semantic")),
            ),
            ("base24-v1", "base24-1"): (
                adapt_base24, "E_FIELD_REQUIRED",
                lambda: self.json_mutation(self.base24, lambda value: value["tokens"].pop("base00")),
            ),
            ("base24-v1", "base24-2"): (
                adapt_base24, "E_FIELD_EXTRA",
                lambda: self.json_mutation(self.base24, lambda value: value["tokens"].__setitem__("ordinary", "12141a")),
            ),
            ("base24-v1", "base24-3"): (
                adapt_base24, "E_COLOR_CANONICAL",
                lambda: self.json_mutation(self.base24, lambda value: value["tokens"].__setitem__("base00", "12141A")),
            ),
            ("base24-v1", "base24-4"): (
                adapt_base24, "E_PATH_TRAVERSAL",
                lambda: self.json_mutation(self.base24, lambda value: value.__setitem__("include", "../shared.json")),
            ),
            ("base24-v1", "base24-5"): (
                adapt_base24, "E_PROFILE_LAYER",
                lambda: self.json_mutation(self.base24, lambda value: value.__setitem__("declared_layer", "semantic")),
            ),
            ("omarchy-colors-toml-v1", "omarchy-1"): (
                adapt_omarchy_palette, "E_EXECUTABLE", lambda: omarchy_root_field(b'command = "theme-reload"'),
            ),
            ("omarchy-colors-toml-v1", "omarchy-2"): (
                adapt_omarchy_palette, "E_PATH_TRAVERSAL", lambda: omarchy_root_field(b'include = "../shared.toml"'),
            ),
            ("omarchy-colors-toml-v1", "omarchy-3"): (
                adapt_omarchy_palette, "E_FIELD_REQUIRED", lambda: self.omarchy.replace(b'accent = "#9e66fa"\n', b"", 1),
            ),
            ("omarchy-colors-toml-v1", "omarchy-4"): (
                adapt_omarchy_palette, "E_COLOR_CANONICAL", lambda: self.omarchy.replace(b"#9e66fa", b"#9E66FA", 1),
            ),
            ("omarchy-colors-toml-v1", "omarchy-5"): (
                adapt_omarchy_palette, "E_PROFILE_LAYER", lambda: omarchy_root_field(b'declared_layer = "semantic"'),
            ),
        }

        manifest_cases = {}
        for profile in self.manifest["profiles"]:
            if profile["profile"] not in self.adapters:
                continue
            for entry in profile["negative_cases"]:
                key = (profile["profile"], entry["id"])
                self.assertNotIn(key, manifest_cases)
                manifest_cases[key] = entry["code"]
        expected_codes = {key: specification[1] for key, specification in builders.items()}
        self.assertEqual(manifest_cases, expected_codes)
        self.assertEqual(len(builders), 26)

        for (profile, case_id), (adapter, code, builder) in builders.items():
            with self.subTest(profile=profile, case=case_id):
                source = builder()
                self.assert_code(code, lambda a=adapter, s=source: a(s, self.template, PROVENANCE))


class ParserAndSecurityNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = raw(FIXTURES / "native-theme-v1-package.json")
        cls.base24 = json.loads(raw(PROFILES / "base24-positive.json"))
        cls.dtcg = json.loads(raw(PROFILES / "dtcg-positive.json"))

    def assert_code(self, code: str, adapter, source: bytes, provenance=PROVENANCE):
        with self.assertRaises(AdapterError) as raised:
            adapter(source, self.template, provenance)
        self.assertEqual(raised.exception.code, code)

    def test_common_raw_json_parser_rejections(self):
        self.assert_code("E_SOURCE_TYPE", adapt_base24, "not-bytes")
        self.assert_code("E_UTF8", adapt_base24, b"\xff")
        self.assert_code("E_JSON_PARSE", adapt_base24, b"{")
        self.assert_code("E_JSON_ROOT", adapt_base24, b"[]")
        self.assert_code("E_JSON_DUPLICATE", adapt_base24, b'{"profile_version":"base24-v1","profile_version":"base24-v1"}')
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            self.assert_code("E_NUMBER_NONFINITE", adapt_base24, b'{"number":' + constant + b"}")
        self.assert_code("E_NUMBER_NONFINITE", adapt_base24, b'{"number":1e999}')
        nested = {}
        for _ in range(34):
            nested = {"nested": nested}
        self.assert_code("E_LIMIT_NESTING", adapt_base24, encoded(nested))
        self.assert_code("E_LIMIT_STRING", adapt_base24, encoded({"value": "x" * 4097}))
        self.assert_code("E_LIMIT_SOURCE", adapt_base24, b" " * (1024 * 1024 + 1))

    def test_raw_catalog_markers_receive_natural_rejections(self):
        marker = b'{"invalid":"E_ALIAS_CYCLE"}'
        self.assert_code("E_PROFILE_STRUCTURE", adapt_dtcg_2025_10, marker)
        self.assert_code("E_FIELD_REQUIRED", adapt_base16, marker)
        self.assert_code("E_FIELD_REQUIRED", adapt_base24, marker)

    def test_provenance_text_and_identity_rejections(self):
        source = raw(PROFILES / "base24-positive.json")
        cases = (
            ("E_PROVENANCE", {"source_identity": None}),
            ("E_UTF8", {"source_identity": "bad\ud800identity"}),
            ("E_LIMIT_STRING", {"source_identity": "x" * 4097}),
            ("E_PROVENANCE", {"source_identity": "bad\x01identity"}),
            ("E_SHELL", {"source_identity": "command:reload"}),
            ("E_SCRIPT", {"source_identity": "themes/reload.sh"}),
            ("E_SHELL", {"source_identity": "themes/theme file"}),
            ("E_PLUGIN", {"source_identity": "themes/plugin/theme"}),
            ("E_TEMPLATE", {"source_identity": "themes/theme.tmpl"}),
            ("E_RUNTIME_PATH", {"source_identity": "themes/proc/theme"}),
            ("E_PROVENANCE", {"source_identity": "themes//theme"}),
        )
        for code, changes in cases:
            with self.subTest(code=code, changes=changes):
                self.assert_code(code, adapt_base24, source, unchecked_provenance(**changes))
        self.assert_code("E_PROVENANCE", adapt_base24, source, provenance={})

    def test_source_identity_security_rejections(self):
        cases = {
            "E_NETWORK_URI": "https://example.invalid/theme.json",
            "E_ABSOLUTE_PATH": "/tmp/theme.json",
            "E_PATH_TRAVERSAL": "tools/../theme.json",
            "E_SCRIPT": "script:theme",
            "E_TEMPLATE": "template:{{theme}}",
            "E_PLUGIN": "plugin:theme-loader",
            "E_RUNTIME_PATH": "runtime:/tmp/theme",
        }
        source = raw(PROFILES / "base24-positive.json")
        for code, identity in cases.items():
            with self.subTest(identity=identity):
                provenance = AdapterProvenance.__new__(AdapterProvenance)
                object.__setattr__(provenance, "source_identity", identity)
                object.__setattr__(provenance, "license_spdx", "BSD-3-Clause")
                object.__setattr__(provenance, "attribution", "contributors")
                object.__setattr__(provenance, "notice", "notice")
                self.assert_code(code, adapt_base24, source, provenance)

    def test_common_capability_path_classification(self):
        good = raw(ADAPTER_FIXTURES / "omarchy-positive.colors.toml")
        cases = {
            "E_NETWORK_URI": omarchy_root_field(good, b'include = "https://example.invalid/theme"'),
            "E_ABSOLUTE_PATH": omarchy_root_field(good, b'include = "/themes/shared.toml"'),
            "E_RUNTIME_PATH": omarchy_root_field(good, b'include = "shared.toml"'),
            "E_SCRIPT": omarchy_root_field(good, b'script = "reload"'),
        }
        for code, source in cases.items():
            with self.subTest(code=code):
                self.assert_code(code, adapt_omarchy_palette, source)
        self.assert_code("E_RUNTIME_PATH", adapt_omarchy_palette, omarchy_root_field(good, b"include = 1"))

    def test_profile_version_layer_and_shape_are_exact(self):
        for field, value, code in (
            ("profile_version", "base24-v0", "E_VERSION_PROFILE"),
            ("declared_layer", "semantic", "E_PROFILE_LAYER"),
        ):
            candidate = copy.deepcopy(self.base24)
            candidate[field] = value
            self.assert_code(code, adapt_base24, encoded(candidate))
        candidate = copy.deepcopy(self.base24)
        candidate["extra"] = True
        self.assert_code("E_FIELD_EXTRA", adapt_base24, encoded(candidate))
        candidate = copy.deepcopy(self.base24)
        candidate.pop("tokens")
        self.assert_code("E_FIELD_REQUIRED", adapt_base24, encoded(candidate))
        candidate = copy.deepcopy(self.base24)
        candidate["tokens"] = []
        self.assert_code("E_FIELD_REQUIRED", adapt_base24, encoded(candidate))

    def test_template_input_and_semantic_authority_rejections(self):
        source = raw(PROFILES / "base24-positive.json")
        with self.assertRaises(AdapterError) as raised:
            adapt_base24(source, [], PROVENANCE)
        self.assertEqual(raised.exception.code, "E_TEMPLATE_PACKAGE")
        candidate = json.loads(raw(FIXTURES / "native-theme-v1-package.json"))
        candidate["variants"]["dark"]["semantic"]["surface.canvas"] = "#010101ff"
        candidate["metadata"]["provenance"]["semantic_hash"] = package_semantic_identity(candidate)
        with self.assertRaises(AdapterError) as raised:
            adapt_base24(source, candidate, PROVENANCE)
        self.assertEqual(raised.exception.code, "E_TEMPLATE_PACKAGE")

    def test_dtcg_real_alias_type_extension_color_and_capability_rejections(self):
        cases = []
        value = copy.deepcopy(self.dtcg); value["tokens"]["a"] = {"$type": "color", "$value": "{b}"}; value["tokens"]["b"] = {"$type": "color", "$value": "{a}"}; cases.append(("E_ALIAS_CYCLE", value))
        value = copy.deepcopy(self.dtcg); value["tokens"]["a"] = {"$type": "color", "$value": "{missing}"}; cases.append(("E_ALIAS_UNRESOLVED", value))
        value = copy.deepcopy(self.dtcg); value["tokens"]["group"]["canvas"]["$type"] = "dimension"; cases.append(("E_TYPE_INHERITED", value))
        value = copy.deepcopy(self.dtcg); value["tokens"]["$extensions"] = {"com.example.unsupported": True}; cases.append(("E_EXTENSION_UNSUPPORTED", value))
        value = copy.deepcopy(self.dtcg); value["tokens"]["group"]["canvas"]["$value"]["components"] = [0, 2, 0]; cases.append(("E_COLOR_COMPONENT", value))
        value = copy.deepcopy(self.dtcg); value["tokens"]["group"]["canvas"]["$value"]["colorSpace"] = "display-p3"; cases.append(("E_COLOR_SPACE", value))
        for key in ("command", "script", "template", "plugin"):
            value = copy.deepcopy(self.dtcg); value["tokens"][key] = "forbidden"; cases.append(("E_EXECUTABLE", value))
        for code, value in cases:
            with self.subTest(code=code):
                self.assert_code(code, adapt_dtcg_2025_10, encoded(value))

    def test_dtcg_alias_depth_is_bounded(self):
        value = copy.deepcopy(self.dtcg)
        for index in range(34):
            value["tokens"][f"depth{index}"] = {
                "$type": "color", "$value": "{group.canvas}" if index == 33 else f"{{depth{index + 1}}}",
            }
        self.assert_code("E_LIMIT_ALIAS_DEPTH", adapt_dtcg_2025_10, encoded(value))

    def test_dtcg_structural_rejection_branches(self):
        def candidate(mutation):
            value = copy.deepcopy(self.dtcg)
            mutation(value)
            return encoded(value)

        canvas_value = self.dtcg["tokens"]["group"]["canvas"]["$value"]
        cases = []
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["number"].__setitem__("$value", True)))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["duration"]["$value"].__setitem__("value", -1)))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["dimension"]["$value"].__setitem__("unit", "em")))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["duration"]["$value"].__setitem__("unit", "minutes")))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["dimension"].__setitem__("$value", {"unit": "px"})))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"].__setitem__("$description", "")))
        cases.append(("E_EXTENSION_UNSUPPORTED", lambda value: value["tokens"].__setitem__("$extensions", "unsupported")))
        cases.append(("E_COLOR_COMPONENT", lambda value: value["tokens"]["group"]["canvas"]["$value"].__setitem__("components", [0, 0])))
        cases.append(("E_COLOR_COMPONENT", lambda value: value["tokens"]["group"]["canvas"]["$value"].__setitem__("alpha", 2)))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["easing"].__setitem__("$value", [0, 1])))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["easing"].__setitem__("$value", [2, 0, 0, 1])))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["fontFamily"].__setitem__("$value", [])))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["gradient"].__setitem__("$value", [])))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["gradient"]["$value"].reverse()))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["shadow"].__setitem__("$value", [])))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["fontWeight"].__setitem__("$value", "heavy")))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"]["types"]["border"]["$value"].__setitem__("style", "groove")))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value.__setitem__("tokens", {"$type": "color", "$value": canvas_value})))
        cases.append(("E_FIELD_FORBIDDEN", lambda value: value["tokens"].__setitem__("$unknown", True)))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"].__setitem__("empty", {})))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value["tokens"].__setitem__("bad.name", {"$type": "number", "$value": 1})))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value.__setitem__("tokens", {"$description": "metadata only"})))
        cases.append(("E_FIELD_FORBIDDEN", lambda value: value.__setitem__("extra", True)))
        cases.append(("E_VERSION_PROFILE", lambda value: value.__setitem__("profile_version", "dtcg-v0")))
        cases.append(("E_PROFILE_STRUCTURE", lambda value: value.__setitem__("tokens", [])))

        def alias_type_mismatch(value):
            value["tokens"]["wrong_alias"] = {"$type": "number", "$value": "{group.canvas}"}

        cases.append(("E_TYPE_INHERITED", alias_type_mismatch))

        def missing_canvas(value):
            value["tokens"] = {"group": {"canvas": {"$type": "number", "$value": 1}}}

        cases.append(("E_FIELD_REQUIRED", missing_canvas))
        for index, (code, mutation) in enumerate(cases):
            with self.subTest(index=index, code=code):
                self.assert_code(code, adapt_dtcg_2025_10, candidate(mutation))

    def test_dtcg_valid_alternate_composite_forms(self):
        value = copy.deepcopy(self.dtcg)
        value["tokens"]["types"]["fontFamily"]["$value"] = "Inter"
        value["tokens"]["types"]["fontWeight"]["$value"] = "bold"
        shadow = value["tokens"]["types"]["shadow"]["$value"]
        value["tokens"]["types"]["shadow"]["$value"] = [shadow]
        result = compile_normalized(adapt_dtcg_2025_10(encoded(value), self.template, PROVENANCE))
        self.assertEqual(result.semantic_hash, TARGET_SEMANTIC_HASH)

    def test_dtcg_type_and_token_count_are_bounded(self):
        value = copy.deepcopy(self.dtcg)
        value["tokens"]["unsupported"] = {"$type": "strokeStyle", "$value": "solid"}
        self.assert_code("E_TYPE_UNSUPPORTED", adapt_dtcg_2025_10, encoded(value))
        value = copy.deepcopy(self.dtcg)
        value["tokens"] = {
            "group": value["tokens"]["group"],
            **{f"n{index}": {"$type": "number", "$value": index} for index in range(1024)},
        }
        self.assert_code("E_LIMIT_TOKENS", adapt_dtcg_2025_10, encoded(value))

    def test_omarchy_rejects_non_palette_runtime_machinery(self):
        good = raw(ADAPTER_FIXTURES / "omarchy-positive.colors.toml")
        cases = {
            "E_EXECUTABLE": good + b'\ncommand = "theme-reload"\n',
            "E_PATH_TRAVERSAL": good + b'\ninclude = "../shared.toml"\n',
            "E_TEMPLATE": good + b'\ntemplate = "{{ accent }}"\n',
            "E_PLUGIN": good + b'\nplugin = "palette-loader"\n',
            "E_RUNTIME_PATH": good + b'\nruntime_path = "themes/current"\n',
            "E_FIELD_EXTRA": good + b'\n[hooks]\non_change = "reload"\n',
        }
        for code, source in cases.items():
            with self.subTest(code=code):
                self.assert_code(code, adapt_omarchy_palette, source)
        self.assert_code("E_UTF8", adapt_omarchy_palette, b"\xff")
        self.assert_code("E_LIMIT_SOURCE", adapt_omarchy_palette, b" " * (1024 * 1024 + 1))

    def test_omarchy_declarations_and_shape_rejections(self):
        good = raw(ADAPTER_FIXTURES / "omarchy-positive.colors.toml")
        accepted = omarchy_root_field(
            good,
            b'profile_version = "omarchy-colors-toml-v1"\ndeclared_layer = "primitives"',
        )
        result = compile_normalized(adapt_omarchy_palette(accepted, self.template, PROVENANCE))
        self.assertEqual(result.semantic_hash, TARGET_SEMANTIC_HASH)
        cases = {
            "E_TOML_PARSE": good + b"\n[",
            "E_VERSION_PROFILE": omarchy_root_field(good, b'profile_version = "omarchy-v0"'),
            "E_FIELD_REQUIRED": good.replace(b'background.ramp = ["#08090c", "#12141a", "#1a1f29"]', b'background = "bad"', 1),
            "E_FIELD_REQUIRED_NESTED": good.replace(b'background.ramp = ["#08090c", "#12141a", "#1a1f29"]', b'background = { extra = true }', 1),
            "E_FIELD_EXTRA": good.replace(b'background.ramp = [', b'background.extra = true\nbackground.ramp = [', 1),
            "E_FIELD_REQUIRED_RAMP": good.replace(b'background.ramp = ["#08090c", "#12141a", "#1a1f29"]', b'background.ramp = ["#08090c"]', 1),
            "E_VERSION_PROFILE_MODE": good.replace(b'mode = "dark"', b'mode = "light"', 1),
            "E_VERSION_PROFILE_VARIANT": good.replace(b'variant = "instrument-studio"', b'variant = "other"', 1),
        }
        expected = {
            "E_TOML_PARSE": "E_TOML_PARSE",
            "E_VERSION_PROFILE": "E_VERSION_PROFILE",
            "E_FIELD_REQUIRED": "E_FIELD_REQUIRED",
            "E_FIELD_REQUIRED_NESTED": "E_FIELD_REQUIRED",
            "E_FIELD_EXTRA": "E_FIELD_EXTRA",
            "E_FIELD_REQUIRED_RAMP": "E_FIELD_REQUIRED",
            "E_VERSION_PROFILE_MODE": "E_VERSION_PROFILE",
            "E_VERSION_PROFILE_VARIANT": "E_VERSION_PROFILE",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                self.assert_code(expected[name], adapt_omarchy_palette, source)


class StaticAuthorityTests(unittest.TestCase):
    def test_production_adapters_have_no_io_or_dynamic_capability_authority(self):
        adapter_dir = NATIVE_THEME / "adapters"
        forbidden_import_roots = {
            "asyncio", "ctypes", "http", "importlib", "multiprocessing", "os",
            "pathlib", "requests", "runpy", "shlex", "socket", "subprocess",
            "urllib", "webbrowser",
        }
        forbidden_name_calls = {"compile", "eval", "exec", "open", "__import__", "getattr"}
        forbidden_attribute_calls = {"read_bytes", "read_text", "run", "Popen", "system"}
        inspected = []
        for path in sorted(adapter_dir.glob("*.py")):
            source = path.read_text()
            self.assertNotIn("profile-fixture-manifest", source, path)
            self.assertNotIn("reject_manifest_sentinel", source, path)
            tree = ast.parse(source, filename=str(path))
            inspected.append(path.name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({alias.name.split(".")[0] for alias in node.names} & forbidden_import_roots, path)
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn(node.module.split(".")[0], forbidden_import_roots, path)
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, forbidden_name_calls, path)
                    elif isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, forbidden_attribute_calls, path)
        self.assertEqual(inspected, ["__init__.py", "base16_base24.py", "common.py", "dtcg_2025_10.py", "omarchy_palette.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

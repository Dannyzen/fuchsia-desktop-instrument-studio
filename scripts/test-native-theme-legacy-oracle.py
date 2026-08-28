#!/usr/bin/env python3
"""Focused regression tests for the source-bound legacy theme oracle."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "docs/native-theme-v1-legacy-oracle.json"
GENERATOR = ROOT / "tools/native_theme/legacy_inventory.py"
VALIDATOR = ROOT / "tools/native_theme/validate_legacy_oracle.py"

TOKEN_ROLES = {
    "panel_bg": "surface.canvas",
    "panel_elevated": "surface.raised",
    "selected_focus": "interaction.selection",
    "text_secondary": "text.muted",
    "border_muted": "border.normal",
    "text_primary": "text.bright",
    "danger": "status.danger",
    "ok": "status.success",
    "confirmed_focus": "border.focusConfirmed",
    "accent_secondary": "interaction.accent",
}
GENERIC_TARGETS = {
    "NativeThemeV1.color", "NativeThemeV1.typography", "NativeThemeV1.geometry-density",
    "NativeThemeV1.settings-state", "NativeThemeV1.focus", "NativeThemeV1.interaction",
    "NativeThemeV1.icon-asset", "NativeThemeV1.motion-elevation",
}


def run(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, text=True,
                          capture_output=True, check=check)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LegacyOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_module(GENERATOR, "legacy_inventory")
        cls.validator = load_module(VALIDATOR, "validate_legacy_oracle")
        cls.good = json.loads(ORACLE.read_text())

    def validate_mutation(self, mutate, code: str):
        candidate = copy.deepcopy(self.good)
        mutate(candidate)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "oracle.json"
            path.write_text(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n")
            result = run(VALIDATOR, path, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(code, result.stderr)

    def test_two_exact_commit_generations_are_identical_and_validate(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.json", Path(td) / "b.json"
            run(GENERATOR, "--output", a)
            run(GENERATOR, "--output", b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            self.assertEqual(a.read_bytes(), ORACLE.read_bytes())
            result = run(VALIDATOR, a)
            self.assertIn("VALID legacy oracle", result.stdout)

    def test_manifest_is_complete_and_counts_close(self):
        data = self.good
        self.assertEqual(len(data["source_files"]), 21)
        self.assertEqual(data["coverage"]["total"], len(data["entries"]))
        self.assertEqual(data["coverage"]["unmapped"], 0)
        self.assertEqual(data["coverage"]["multiply_mapped"], 0)
        self.assertEqual(sum(data["coverage"]["by_category"].values()), len(data["entries"]))
        self.assertEqual(sum(data["coverage"]["by_file"].values()), len(data["entries"]))
        for dimension in ("by_target", "by_source_kind", "by_authority", "by_disposition"):
            self.assertEqual(sum(data["coverage"][dimension].values()), len(data["entries"]))

    def test_candidate_selection_is_semantic_not_every_nonblank_line(self):
        sample = """// ordinary comment
use crate::ordinary::Thing;
if ready {
}
const PANEL_COLOR: ColorRgba = ColorRgba::new(0.1, 0.2, 0.3, 1.0);
let icon_size = 24.0;
paint(PANEL_COLOR);
"""
        for selector in (self.generator.select_candidates, self.validator.select_candidates):
            selected = {number for number, _ in selector("synthetic.rs", sample)}
            self.assertEqual(selected, {5, 6, 7})
        self.assertNotIn("every nonblank", self.good["scanner_contract"]["candidate_unit"])

    def test_known_noise_absent_and_known_style_lines_present(self):
        identities = {(e["path"], e["line"]) for e in self.good["entries"]}
        tokens = "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs"
        settings = "overlays/fuchsia/src/fuchsia-desktop/settings/src/main.rs"
        self.assertNotIn((settings, 26), identities)  # ordinary use statement
        self.assertNotIn((tokens, 1), identities)  # copyright comment
        self.assertNotIn((tokens, 14), identities)  # closing brace
        self.assertIn((tokens, 46), identities)  # semantic color initializer
        self.assertIn((settings, 504), identities)  # production mutation call

    def test_exact_legacy_token_contract_and_live_mapping(self):
        token_entries = [e for e in self.good["entries"] if e["path"].endswith("desktop_ui/src/tokens.rs")]
        definitions = {e["declaration"] for e in token_entries if e["source_kind"] == "contract-field"}
        self.assertEqual(definitions, set(TOKEN_ROLES))
        live = [e for e in token_entries if e["authority_status"] == "authority" and e["target"] in set(TOKEN_ROLES.values())]
        self.assertEqual(len(live), 10)
        self.assertEqual({e["declaration"]: e["target"] for e in live}, TOKEN_ROLES)
        self.assertTrue(all(e["authority_key"] == e["target"] for e in live))
        self.assertTrue(all(e["disposition"] == "map-semantic" for e in live))
        self.assertFalse(any(e["declaration"] in {"ColorRgba", "ThemeTokens", "INSTRUMENT_STUDIO_THEME"} and e["authority_status"] == "authority" for e in token_entries))
        self.assertNotEqual(TOKEN_ROLES["confirmed_focus"], TOKEN_ROLES["selected_focus"])

    def test_specific_consumer_definitions_and_no_generic_targets(self):
        self.assertFalse(GENERIC_TARGETS & {e["target"] for e in self.good["entries"]})
        authorities = [e for e in self.good["entries"] if e["authority_status"] == "authority"]
        for category in ("color", "typography", "geometry-density", "interaction", "icon-asset"):
            representative = next(e for e in authorities if e["category"] == category)
            self.assertIn(representative["disposition"], {"map-semantic", "product-behavior-fixed"})
            self.assertTrue(representative["target"].startswith(("surface.", "text.", "border.", "status.", "interaction.", "product-policy.")))

    def test_settings_state_inventory_is_precise(self):
        state = [e for e in self.good["entries"] if e["disposition"] == "state-migrate"]
        self.assertEqual([(e["path"], e["line"]) for e in state], [tuple(site) for site in self.good["policies"]["settings_migration"]["state_sites"]])
        self.assertTrue(all(e["source_kind"] == "state" for e in state))
        corrupt = next(e for e in self.good["entries"] if e.get("declaration") == "corrupt_theme_state_falls_back_to_dark_without_exposing_junk")
        self.assertNotEqual(corrupt["source_kind"], "state")
        self.assertNotEqual(corrupt["disposition"], "state-migrate")

    def test_honest_candidate_and_authority_counts(self):
        retained = self.good["coverage"]["by_disposition"].get("retain-local-nontheme", 0)
        self.assertLess(retained / len(self.good["entries"]), 0.5)
        self.assertGreaterEqual(self.good["coverage"]["by_authority"].get("authority", 0), 15)
        live = [e["authority_key"] for e in self.good["entries"] if e["authority_status"] == "authority" and e["disposition"] != "retire-duplicate"]
        self.assertEqual(len(live), len(set(live)))

    def test_omitted_root_file_entry_and_added_candidate_fail(self):
        self.validate_mutation(lambda d: d["target_roots"].pop(), "E_TARGET_ROOTS")
        self.validate_mutation(lambda d: d["source_files"].pop(), "E_SOURCE_FILES")
        self.validate_mutation(lambda d: d["entries"].pop(), "E_CANDIDATES")
        def add_synthetic(d):
            extra = copy.deepcopy(d["entries"][0])
            extra["id"] = "legacy-000000000000000000000000"
            d["entries"].append(extra)
        self.validate_mutation(add_synthetic, "E_CANDIDATES")

    def test_hash_id_authority_and_disposition_tampering_fail(self):
        self.validate_mutation(lambda d: d["source_files"][0].__setitem__("sha256", "0" * 64), "E_FILE_HASH")
        self.validate_mutation(lambda d: d["entries"][0].__setitem__("source_line_sha256", "0" * 64), "E_LINE_HASH")
        self.validate_mutation(lambda d: d["entries"][1].__setitem__("id", d["entries"][0]["id"]), "E_DUPLICATE_ID")
        authority = next(e for e in self.good["entries"] if e["authority_status"] == "authority")
        def duplicate_authority(d):
            other = next(e for e in d["entries"] if e["authority_status"] == "authority" and e["id"] != authority["id"])
            other["authority_key"] = authority["authority_key"]
        self.validate_mutation(duplicate_authority, "E_DUPLICATE_AUTHORITY")
        self.validate_mutation(lambda d: d["entries"][0].pop("disposition"), "E_DISPOSITION")
        self.validate_mutation(lambda d: d["entries"][0].__setitem__("disposition", ["map-semantic", "consumer-reference"]), "E_DISPOSITION")
        self.validate_mutation(lambda d: d["entries"][0].__setitem__("disposition", "unknown"), "E_DISPOSITION")

    def test_policy_focus_settings_and_fallback_tampering_fail(self):
        self.validate_mutation(lambda d: d["policies"]["focus"].__setitem__("confirmed_target", d["policies"]["focus"]["selection_target"]), "E_FOCUS_COLLAPSE")
        self.validate_mutation(lambda d: d["policies"]["settings_migration"].pop("Dark"), "E_SETTINGS_MIGRATION")
        self.validate_mutation(lambda d: d["policies"]["settings_migration"].__setitem__("Contrast", "dark"), "E_SETTINGS_MIGRATION")
        self.validate_mutation(lambda d: d["policies"]["fallback"].__setitem__("storage_independent", False), "E_FALLBACK_DEPENDENCY")
        self.validate_mutation(lambda d: d["policies"]["fallback"].__setitem__("service_independent", False), "E_FALLBACK_DEPENDENCY")

    def test_public_safety_semantic_hash_and_canonical_form_fail(self):
        self.validate_mutation(lambda d: d["target_roots"].__setitem__(0, "/tmp/private"), "E_PATH_SAFETY")
        self.validate_mutation(lambda d: d["target_roots"].__setitem__(0, "../private"), "E_PATH_SAFETY")
        self.validate_mutation(lambda d: d.__setitem__("private_bead", "sq-01"), "E_SCHEMA")
        self.validate_mutation(lambda d: d["entries"][0].__setitem__("rationale", "private Beads sq-01"), "E_PUBLIC_SAFETY")
        self.validate_mutation(lambda d: d.__setitem__("semantic_sha256", "0" * 64), "E_SEMANTIC_HASH")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pretty.json"
            path.write_text(json.dumps(self.good, indent=2) + "\n")
            result = run(VALIDATOR, path, check=False)
        self.assertIn("E_NONCANONICAL", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""RED contract for the Phase 3 NativeTheme qualification boundary."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_service"
AUTHORITY = SERVICE / "src/authority.rs"
BUILD = SERVICE / "BUILD.gn"
RUNNER = ROOT / "scripts/test-native-theme-sq03.py"
BUILTIN = "instrument-studio-dtcg.package.json"


class NativeThemeSq03Contract(unittest.TestCase):
    def test_builtin_fallback_is_a_real_canonical_theme(self) -> None:
        source = AUTHORITY.read_text()
        build = BUILD.read_text()
        self.assertIn('pub const FALLBACK_THEME_ID: &str = "instrument-studio";', source)
        self.assertRegex(
            source,
            rf'(?s)const BUILTIN_PACKAGE: &\[u8\] = include_bytes!\(\s*"../../theme_catalog/catalog/{BUILTIN}"\s*\);',
        )
        self.assertIn("NativeThemeV1::decode_canonical(BUILTIN_PACKAGE)", source)
        self.assertNotIn("semantic_sha256: [0; 32]", source)
        self.assertNotIn("canonical_package: Arc::from([])", source)
        self.assertIn(f'"//src/fuchsia-desktop/theme_catalog/catalog/{BUILTIN}"', build)

    def test_sq03_runner_executes_every_phase3_contract(self) -> None:
        self.assertTrue(RUNNER.is_file(), "repository-owned sq-03 runner is missing")
        source = RUNNER.read_text()
        for script in (
            "test-native-theme-service.py",
            "test-native-theme-p3-s2.py",
            "test-native-theme-p3-s3.py",
        ):
            self.assertIn(script, source)
        self.assertIn("sq-03-verdict.json", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

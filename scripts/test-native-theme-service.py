#!/usr/bin/env python3
"""Source acceptance contract for P3-S1 NativeTheme read authority."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_service"
FIDL = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_service/fidl"
SESSION = ROOT / "overlays/fuchsia/products/workbench/workbench_session"
FEATURE = ROOT / "features/native-theme-live-journey.feature"


class NativeThemeServiceContract(unittest.TestCase):
    def text(self, path):
        return path.read_text(encoding="utf-8")

    def test_p3s1_read_only_fidl_surface(self):
        fidl = self.text(FIDL / "theme.fidl")
        self.assertTrue(fidl.startswith("// Copyright 2026 The Fuchsia Authors.\n"))
        self.assertIn("// found in the LICENSE file.", fidl)
        self.assertIn("@available(added=HEAD)\nlibrary fuchsia.instrumentstudio.theme;", fidl)
        self.assertIn("closed protocol NativeTheme", fidl)
        methods = re.findall(r"strict ([A-Z][A-Za-z0-9]+)\(", fidl)
        self.assertEqual(methods, ["ListThemes", "GetTheme", "GetCurrent", "WatchCurrent"])
        self.assertNotRegex(fidl, r"(?i)\b(set|select|activate|write|persist|store|save)[A-Za-z]*\s*\(")
        self.assertIn("vector<uint8>:MAX_SNAPSHOT_BYTES", fidl)
        self.assertIn("const MAX_SNAPSHOT_BYTES uint32 = 524288;", fidl)

    def test_p3s1_watch_and_generation_model(self):
        authority = self.text(SERVICE / "src/authority.rs")
        server = self.text(SERVICE / "src/main.rs")
        for marker in ["equal_generation_parks_exactly_one_responder",
                       "duplicate_outstanding_watch_is_bad_state",
                       "connections_retain_independent_responders",
                       "unequal_generation_returns_immediately",
                       "future_generation_drains_once",
                       "disconnect_drops_only_its_responder"]:
            self.assertIn(f"fn {marker}", authority)
        self.assertIn("pub struct ConnectionWatch", authority)
        self.assertIn("ConnectionWatch::default()", server)
        self.assertRegex(server, r"watch_state\.observe\(")
        self.assertIn("generation: 0", authority)

    def test_p3s1_codec_fallback_and_diagnostics(self):
        build = self.text(SERVICE / "BUILD.gn")
        source = self.text(SERVICE / "src/authority.rs")
        server = self.text(SERVICE / "src/main.rs")
        self.assertIn('"//src/fuchsia-desktop/theme_model"', build)
        self.assertIn('"//sdk/rust/zx"', build)
        self.assertNotIn('"//zircon/system/ulib/zx:zx_rust"', build)
        self.assertNotIn('"//third_party/rust_crates:serde_json"', build)
        self.assertIn("inputs = [", build)
        for package in ["base16", "base24", "dtcg", "omarchy"]:
            self.assertIn(f'//src/fuchsia-desktop/theme_catalog/catalog/instrument-studio-{package}.package.json', build)
        self.assertIn("use fidl::endpoints::RequestStream;", server)
        self.assertIn("use zx::Status;", server)
        self.assertIn("Status::NOT_FOUND", server)
        self.assertIn("metadata.as_ref().ok_or_else", server)
        self.assertIn("Status::BAD_STATE", server)
        self.assertIn("#[cfg(test)]\n    pub fn drain_if_changed", source)
        self.assertNotIn("fuchsia_zircon::", server)
        self.assertIn("NativeThemeV1::decode_canonical", source)
        self.assertIn("FALLBACK_THEME_ID", source)
        self.assertIn("MAX_DIAGNOSTIC_ERROR_BYTES", source)
        self.assertIn("mixed_valid_invalid_catalog_fails_closed", source)
        self.assertIn("diagnostic_error_is_bounded", source)
        self.assertNotRegex(source, r"canonical_bytes\(\).*record|package_path.*record")

    def test_p3s1_fidl_is_repository_local_not_sdk_distributed(self):
        build = self.text(SERVICE / "BUILD.gn")
        self.assertNotIn("sdk_category =", build)
        self.assertNotIn("stable =", build)


    def test_p3s1_authority_is_a_host_testable_library(self):
        build = self.text(SERVICE / "BUILD.gn")
        server = self.text(SERVICE / "src/main.rs")
        self.assertIn('import("//build/rust/rustc_library.gni")', build)
        self.assertIn('rustc_library("theme_service_core")', build)
        core = build.split('rustc_library("theme_service_core")', 1)[1].split('rustc_binary("bin")', 1)[0]
        binary = build.split('rustc_binary("bin")', 1)[1].split('fuchsia_component("component")', 1)[0]
        self.assertIn("with_unit_tests = true", core)
        self.assertIn('source_root = "src/authority.rs"', core)
        self.assertNotIn("with_unit_tests = true", binary)
        self.assertIn('"../theme_model/testdata/native-theme-v1-package.json"', core)
        self.assertIn('":theme_service_core"', binary)
        self.assertIn('"//src/lib/diagnostics/inspect/rust:fuchsia-inspect"', binary)
        self.assertIn("use theme_service_core::{", server)
        self.assertNotIn("mod authority;", server)

    def test_p3s1_component_and_routes_are_optional_read_only(self):
        cml = self.text(SERVICE / "meta/native_theme_service.cml")
        session = self.text(SESSION / "meta/workbench_session.cml")
        self.assertIn('protocol: "fuchsia.instrumentstudio.theme.NativeTheme"', cml)
        self.assertIn('name: "native_theme_service"', session)
        self.assertRegex(session, r'protocol:\s*"fuchsia\.instrumentstudio\.theme\.NativeTheme"[\s\S]*?availability:\s*"optional"')
        self.assertNotRegex(session, r"fuchsia\.instrumentstudio\.theme\.(Writer|Manager|Control|Store)")
        self.assertNotIn('startup: "eager"', session.split('name: "native_theme_service"', 1)[1].split("}", 1)[0])

    def test_p3s1_gherkin_mapping_and_scope(self):
        feature = self.text(FEATURE)
        tests = self.text(Path(__file__))
        self.assertEqual(feature.count("@implemented @p3-s1"), 4)
        for scenario in ["READ-ONLY", "WATCH", "FALLBACK", "OPTIONAL"]:
            self.assertIn(f"@scenario:P3S1-{scenario}", feature)
        self.assertIn("@planned @p3-s2", feature)
        self.assertIn("@planned @p4", feature)
        self.assertEqual(feature.count("@planned @p6"), 2)
        self.assertNotIn("@p3-s3", feature)
        self.assertNotIn("@p3-s4", feature)
        self.assertIn("sole writer", feature)
        self.assertIn("Apply and Restart", feature)
        self.assertIn("full product restarts", feature)
        self.assertIn("last-known-good or built-in", feature)
        self.assertEqual(len(re.findall(r"^    def test_p3s1_", tests, re.MULTILINE)), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)

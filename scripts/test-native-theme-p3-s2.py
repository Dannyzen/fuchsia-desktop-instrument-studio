#!/usr/bin/env python3
"""Source acceptance contract for P3-S2 restart-only theme selection."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "overlays/fuchsia/src/fuchsia-desktop/theme_service"
SESSION = ROOT / "overlays/fuchsia/products/workbench/workbench_session"


class P3S2Contract(unittest.TestCase):
    def text(self, path):
        return path.read_text(encoding="utf-8")

    def test_01_separate_bounded_control_identity(self):
        fidl = self.text(SERVICE / "fidl/theme.fidl")
        self.assertIn("type ThemeVariant = strict enum", fidl)
        self.assertIn("type ThemeIdentity = struct", fidl)
        self.assertIn("theme_id string:MAX_THEME_ID_BYTES", fidl)
        self.assertIn("variant ThemeVariant", fidl)
        self.assertIn("semantic_sha256 array<uint8, 32>", fidl)
        self.assertIn('@discoverable(server="platform")\nclosed protocol NativeThemeSettings', fidl)
        block = fidl.split("closed protocol NativeThemeSettings", 1)[1]
        self.assertEqual(re.findall(r"strict ([A-Z][A-Za-z0-9]+)\(", block),
                         ["GetState", "Select", "RestoreBuiltIn", "MigrateLegacy"])

    def test_01_control_route_is_settings_only(self):
        cml = self.text(SESSION / "meta/workbench_session.cml")
        offers = re.findall(
            r"\{\s*protocol:\s*\"fuchsia\.instrumentstudio\.theme\.NativeThemeSettings\"[\s\S]*?\}",
            cml,
        )
        self.assertEqual(len(offers), 1)
        self.assertIn('to: "#settings_elements"', offers[0])
        for collection in ["#elements", "#browser_elements", "#files_elements", "#terminal_elements"]:
            self.assertNotIn(collection, offers[0])
        build = self.text(SERVICE / "BUILD.gn")
        binary_deps = build.split('rustc_binary("bin")', 1)[1]
        self.assertNotIn('"//src/lib/fuchsia-async"', binary_deps)

    def test_01_public_protocol_remains_read_only(self):
        fidl = self.text(SERVICE / "fidl/theme.fidl")
        public = fidl.split("closed protocol NativeTheme {", 1)[1].split("};", 1)[0]
        self.assertEqual(re.findall(r"strict ([A-Z][A-Za-z0-9]+)\(", public),
                         ["ListThemes", "GetTheme", "GetCurrent", "WatchCurrent"])

    def test_02_strict_versioned_codec_negatives(self):
        source = self.text(SERVICE / "src/persistence.rs")
        for marker in [
            "codec_rejects_corrupt_state", "codec_rejects_duplicate_fields",
            "codec_rejects_unknown_fields", "codec_rejects_older_version",
            "codec_rejects_newer_version", "codec_rejects_malformed_hash",
            "codec_rejects_unknown_variant", "codec_rejects_oversize_identity",
            "codec_rejects_missing_history",
        ]:
            self.assertIn(f"fn {marker}", source)
        self.assertIn("STATE_VERSION: u32 = 1", source)
        self.assertIn("MAX_STATE_BYTES", source)
        self.assertNotIn("serde_json", source)

    def test_03_atomic_store_and_failure_contract(self):
        source = self.text(SERVICE / "src/persistence.rs")
        for marker in [
            "store_preserves_prior_state_on_write_failure",
            "store_preserves_prior_state_on_file_sync_failure",
            "store_preserves_prior_state_on_rename_failure",
            "store_reports_directory_sync_failure_after_replace",
            "corrupt_store_can_be_repaired_by_select",
            "corrupt_store_can_be_repaired_by_restore",
            "store_ignores_temporary_residue",
            "same_select_is_idempotent", "same_restore_is_idempotent",
        ]:
            self.assertIn(f"fn {marker}", source)
        order = [source.index(x) for x in ["write_temporary(", "sync_temporary(", "replace(", "sync_parent("]]
        self.assertEqual(order, sorted(order))

    def test_04_restart_only_recovery_and_immutable_watch(self):
        source = self.text(SERVICE / "src/authority.rs")
        for marker in [
            "startup_uses_valid_selected_identity", "startup_falls_back_to_valid_lkg",
            "startup_falls_back_to_builtin", "restart_after_restore_uses_builtin",
            "selection_does_not_change_current_snapshot",
            "selection_does_not_change_generation_or_watch",
        ]:
            self.assertIn(f"fn {marker}", source)
        self.assertIn("selected -> last-known-good -> built-in", source)
        self.assertIn("from_packaged_and_state", source)
        self.assertIn('"selection_source"', source)
        self.assertIn('"selection_error_code"', source)
        for marker in [
            "corrupt_state_reports_recovery_diagnostics",
            "invalid_selected_reports_lkg_recovery",
        ]:
            self.assertIn(f"fn {marker}", source)
        selection_block = source.split("fn selection_does_not_change_current_snapshot()", 1)[1].split("#[test]", 1)[0]
        watch_block = source.split("fn selection_does_not_change_generation_or_watch()", 1)[1].split("#[fuchsia::test]", 1)[0]
        self.assertIn(".select(", selection_block)
        self.assertIn(".select(", watch_block)

    def test_05_generated_control_transport_and_concurrency(self):
        source = self.text(SERVICE / "src/authority.rs")
        for marker in [
            "control_proxy_queries_and_selects_pending", "control_rejects_unknown_id",
            "control_rejects_semantic_hash_mismatch", "concurrent_settings_callers_are_serialized",
            "control_restore_is_idempotent", "legacy_migration_is_guarded",
        ]:
            self.assertIn(f"fn {marker}", source)
        self.assertIn("create_proxy_and_stream::<ftheme::NativeThemeSettingsMarker>", source)
        self.assertIn("serve_native_theme_settings", source)
        self.assertIn("zx_status::Status::INVALID_ARGS", source)

    def test_06_settings_client_and_legacy_migration(self):
        core = self.text(ROOT / "overlays/fuchsia/src/fuchsia-desktop/settings/src/settings_core.rs")
        main = self.text(ROOT / "overlays/fuchsia/src/fuchsia-desktop/settings/src/main.rs")
        self.assertIn("legacy_dark_maps_to_instrument_studio_dark", core)
        self.assertIn("legacy_contrast_maps_to_instrument_studio_high_contrast", core)
        self.assertIn("pending_service_state_shows_restart_required", core)
        production = core.split("#[cfg(test)]\nmod tests", 1)[0]
        self.assertNotIn("fs::write", production)
        self.assertNotIn("fs::rename", production)
        self.assertIn("NativeThemeSettingsMarker", main)
        self.assertIn("migrate_legacy", main)
        self.assertIn("select(&identity)", main)
        self.assertIn("app_preferences: theme_settings.is_some() && catalog_theme.is_some()", main)
        self.assertIn("Ok(Err(status))", main)
        for marker in [
            "theme_control_is_hidden_without_owner",
            "active_theme_status_tracks_service_state",
            "pending_service_state_shows_restart_required",
        ]:
            self.assertIn(f"fn {marker}", core)
        settings_build = self.text(ROOT / "overlays/fuchsia/src/fuchsia-desktop/settings/BUILD.gn")
        self.assertIn('rustc_library("settings_core")', settings_build)
        core_target = settings_build.split('rustc_library("settings_core")', 1)[1].split('rustc_binary("bin")', 1)[0]
        self.assertIn("with_unit_tests = true", core_target)
        cml = self.text(ROOT / "overlays/fuchsia/src/fuchsia-desktop/settings/meta/fuchsia_settings.cml")
        for protocol in ["NativeTheme", "NativeThemeSettings"]:
            pattern = rf'protocol:\s*"fuchsia\.instrumentstudio\.theme\.{protocol}"[\s\S]*?availability:\s*"optional"'
            self.assertRegex(cml, pattern)

    def test_07_feature_marks_only_p3s2_selection_implemented(self):
        feature = self.text(ROOT / "features/native-theme-live-journey.feature")
        self.assertIn("@implemented @p3-s2", feature)
        self.assertNotIn("@planned @p3-s2", feature)
        self.assertIn("@planned @p4", feature)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Source contract for the shared NativeTheme shell adapter."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "overlays/fuchsia/products/workbench/workbench_session/meta/workbench_session.cml"
TILING_CML = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/meta/tiling_wm.cml"
TILING_MAIN = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/src/main.rs"
TILING_BUILD = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/BUILD.gn"
TILING_OBSERVABILITY = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/src/observability.rs"
TOKENS = ROOT / "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs"
QUALIFICATION = ROOT / "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/qualification.rs"
HOST_MANIFEST = ROOT / "tools/native_theme/desktop-ui-host-qualifier/Cargo.toml"
HOST_LOCK = ROOT / "tools/native_theme/desktop-ui-host-qualifier/Cargo.lock"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"


class NativeThemeP4U1Contract(unittest.TestCase):
    def test_tiling_wm_has_optional_read_only_route_only(self) -> None:
        session = SESSION.read_text()
        tiling = TILING_CML.read_text()
        read_protocol = "fuchsia.instrumentstudio.theme.NativeTheme"
        writer_protocol = "fuchsia.instrumentstudio.theme.NativeThemeSettings"
        self.assertIn(read_protocol, tiling)
        self.assertIn("availability: \"optional\"", tiling)
        self.assertNotIn(writer_protocol, tiling)
        offer_start = session.index(f'protocol: "{read_protocol}"')
        offer_end = session.index("},", offer_start)
        offer = session[offer_start:offer_end]
        self.assertIn('"#tiling_wm"', offer)
        self.assertNotIn(writer_protocol, offer)

    def test_shell_resolves_one_snapshot_and_falls_back_before_construction(self) -> None:
        source = TILING_MAIN.read_text()
        build = TILING_BUILD.read_text()
        self.assertIn("fidl_fuchsia_instrumentstudio_theme as ftheme", source)
        self.assertIn("async fn resolve_startup_theme", source)
        self.assertIn("proxy.get_current().await", source)
        self.assertIn("ResolvedThemeSnapshot::from_canonical_snapshot", source)
        resolve = source.index("resolve_startup_theme().await")
        construct = source.index("TilingWm::new(", resolve)
        self.assertLess(resolve, construct)
        self.assertIn("theme_tokens: ThemeTokens", source)
        self.assertIn("InstrumentStudioLayout::with_theme", source)
        self.assertNotIn("red: 0.0, green: 0.82, blue: 1.0", source)
        self.assertIn("fuchsia.instrumentstudio.theme_rust", build)

    def test_applied_theme_receipt_is_published_to_inspect(self) -> None:
        source = TILING_OBSERVABILITY.read_text()
        main = TILING_MAIN.read_text()
        self.assertIn('create_child("theme")', source)
        creators = {
            "source": "string",
            "theme_id": "string",
            "variant": "string",
            "semantic_sha256": "string",
            "generation": "uint",
        }
        for field, kind in creators.items():
            self.assertIn(f'create_{kind}("{field}"', source)
        self.assertIn("semantic_sha256: String", main)
        self.assertIn("generation: u64", main)
        self.assertIn("WmObservability::attach", main)
        self.assertIn("startup_theme.semantic_sha256", main)
        self.assertIn("_theme: Node", source)
        retained = {
            "_theme_source": "theme_source", "_theme_id": "theme_id",
            "_theme_variant": "theme_variant",
            "_theme_semantic_sha256": "theme_semantic_sha256",
            "_theme_generation": "theme_generation",
        }
        for member, local in retained.items():
            self.assertIn(f"{member}:", source)
            self.assertIn(f"{member}: {local}", source)

    def test_stale_theme_service_cannot_block_shell_startup(self) -> None:
        source = TILING_MAIN.read_text()
        self.assertIn("TimeoutExt", source)
        self.assertIn("const THEME_SNAPSHOT_TIMEOUT_SECONDS: i64 = 2;", source)
        self.assertIn(".on_timeout(deadline, || None)", source)
        self.assertIn("reason=get-current-timeout", source)

    def test_snapshot_identity_is_checked_in_controlling_code(self) -> None:
        source = TOKENS.read_text()
        self.assertIn("theme.theme_id() != expected_theme_id", source)
        self.assertIn("theme.semantic_sha256() != expected_semantic_sha256", source)
        self.assertIn("return Err(ThemeAdapterError::IdentityMismatch)", source)

    def test_rust_qualification_covers_every_variant_and_oracle_role(self) -> None:
        source = QUALIFICATION.read_text()
        self.assertIn("all_variants_map_all_oracle_semantic_roles", source)
        for variant in ("light", "dark", "high-contrast"):
            self.assertIn(f'"{variant}",', source)
        for role in (
            "panel_bg", "panel_elevated", "border_muted", "text_primary", "text_secondary",
            "confirmed_focus", "selected_focus", "accent_secondary", "danger", "ok",
        ):
            self.assertIn(role, source)

    def test_repository_ci_executes_production_rust_qualification(self) -> None:
        workflow = CI_WORKFLOW.read_text()
        self.assertTrue(HOST_MANIFEST.is_file())
        self.assertTrue(HOST_LOCK.is_file())
        manifest = HOST_MANIFEST.read_text()
        self.assertIn('path = "../../../overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/lib.rs"', manifest)
        self.assertIn('path = "../../../overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/qualification.rs"', manifest)
        self.assertIn('CARGO_TARGET_DIR="$RUNNER_TEMP/desktop-ui-host-target"', workflow)
        self.assertIn('"$SQ02_CARGO" test --locked --manifest-path tools/native_theme/desktop-ui-host-qualifier/Cargo.toml', workflow)
        self.assertIn("python3 scripts/test-native-theme-p4-u1.py", workflow)
        self.assertIn("tools/native_theme/desktop-ui-host-qualifier/target/", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)

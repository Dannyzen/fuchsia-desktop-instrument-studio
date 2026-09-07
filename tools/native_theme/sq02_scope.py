"""Shared event-local path scope for the NativeThemeV1 SQ-02 gate."""

from __future__ import annotations

from collections.abc import Iterable

SQ02_TRACKED_PATHS = frozenset({
    ".gitignore",
    "tools/native_theme/desktop-ui-host-qualifier/rust-toolchain.toml",
    "tools/native_theme/desktop-ui-host-qualifier/Cargo.toml",
    "tools/native_theme/desktop-ui-host-qualifier/Cargo.lock",
    "scripts/test-native-theme-p4-u1.py",
    "overlays/fuchsia/src/ui/bin/tiling_wm/src/observability.rs",
    "overlays/fuchsia/src/ui/bin/tiling_wm/src/main.rs",
    "overlays/fuchsia/src/ui/bin/tiling_wm/meta/tiling_wm.cml",
    "overlays/fuchsia/src/ui/bin/tiling_wm/BUILD.gn",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/qualification.rs",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/lib.rs",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/chrome.rs",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/BUILD.gn",
    "overlays/fuchsia/products/workbench/workbench_session/meta/workbench_session.cml",
    ".github/workflows/ci.yml",
    "overlays/fuchsia/src/fuchsia-desktop/theme_model/BUILD.gn",
    "overlays/fuchsia/src/fuchsia-desktop/theme_model/src/qualification.rs",
    "scripts/native-theme-sq02-scope.py",
    "scripts/run-native-theme-sq02.py",
    "scripts/test-native-theme-sq02-harness.py",
    "scripts/test-native-theme-sq02-receipts.py",
    "scripts/test-native-theme-sq02-scope.py",
    "scripts/test-native-theme-sq02.py",
    "tools/native_theme/sq02-requirements.txt",
    "tools/native_theme/sq02_harness.py",
    "tools/native_theme/sq02_receipt_verifier.py",
    "tools/native_theme/sq02_scope.py",
    "tools/native_theme/sq02-rust-qualifier/Cargo.lock",
    "tools/native_theme/sq02-rust-qualifier/Cargo.toml",
    "tools/native_theme/sq02-rust-qualifier/rust-toolchain.toml",
    "tools/native_theme/sq02-rust-qualifier/src/main.rs",
})
DOC_SCOPE_PATHS = frozenset({"README.md"})
DOC_SCOPE_PREFIXES = ("docs/", "design/")


def is_doc_path(path: str) -> bool:
    return path in DOC_SCOPE_PATHS or path.startswith(DOC_SCOPE_PREFIXES)


def sq02_changed(paths: Iterable[str]) -> bool:
    return bool(set(paths) & SQ02_TRACKED_PATHS)


def unexpected_scope_paths(paths: Iterable[str]) -> list[str]:
    return sorted(path for path in set(paths) - SQ02_TRACKED_PATHS if not is_doc_path(path))

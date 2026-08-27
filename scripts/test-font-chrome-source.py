#!/usr/bin/env python3
# Source contract for native font-rendered Workbench chrome.
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TILING = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm"
build = (TILING / "BUILD.gn").read_text()
chrome = (TILING / "src/chrome.rs").read_text()
text = (TILING / "src/chrome_text.rs").read_text()
main = (TILING / "src/main.rs").read_text()
manifest = (TILING / "meta/tiling_wm.cml").read_text()
session_manifest = (ROOT / "overlays/fuchsia/products/workbench/workbench_session/meta/workbench_session.cml").read_text()
tiling_route = session_manifest.split("// Dependencies for tiling_wm", 1)[1].split("],\n    expose:", 1)[0]
for protocol in ("fuchsia.sysmem2.Allocator", "fuchsia.ui.composition.Allocator"):
    assert protocol in manifest, f"missing runtime allocator capability: {protocol}"
    assert protocol in tiling_route, f"session realm does not offer allocator to tiling_wm: {protocol}"
for asset in ("Roboto-Regular.ttf", "MaterialIcons-Regular.ttf"):
    assert asset in build, f"missing packaged font input: {asset}"
    assert asset in text, f"missing embedded font: {asset}"
for word in (
    "Workbench Studio",
    "Build",
    "Research",
    "Ops",
    "Inspect",
    "Windows",
    "Active view",
    "Spacing",
    "WM health",
):
    assert f'"{word}"' in chrome, f"missing readable chrome word: {word}"
for app in ("Settings", "Files", "Browser", "Terminal"):
    assert f'"{app}"' in main, f"missing full tile title: {app}"
for codepoint in ("e145", "e871", "e2c7", "e80b", "e86f", "e8b8"):
    assert f"\\u{{{codepoint}}}" in chrome, f"missing semantic icon U+{codepoint.upper()}"
assert "draw_rail_glyph(" not in chrome, "rectangle rail glyph path still active"
assert "LABEL_PARTS" not in chrome, "bitmap chrome label pool still active"
assert "pub struct TileName" in chrome
assert "_surface: ChromeTextSurface" in chrome
assert "TextRun::text(label, 16, 3, 22.0, TEXT_PRIMARY)" in chrome
assert "TILE_NAME_PARTS" not in chrome, "bitmap title pool remains"
assert "fn glyph5" not in chrome, "bitmap title font remains"
assert "fn draw_text" not in chrome, "bitmap title renderer remains"
for duplicate in ("Shell ready", "Focused", "12px gap"):
    assert f'"{duplicate}"' not in chrome, f"duplicate top status remains: {duplicate}"
assert "status_chips" not in chrome
assert "status_dots" not in chrome
assert "tile_short_label(&new_tile_id.0)" in main
assert ".await?" in main
assert "view.name.layout" not in main
assert "ChromeTextSurface::new" in chrome
assert "ShellChrome::create" in main and ".await?" in main
print("font chrome source contract: PASS")

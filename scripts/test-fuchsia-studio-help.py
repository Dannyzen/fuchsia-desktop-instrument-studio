#!/usr/bin/env python3
"""Host contract for the Linux-side Fuchsia Studio help surface."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = ROOT / "overlays/fuchsia/src/fuchsia-desktop/terminal"
TOOL = TERMINAL / "src/fuchsia-studio"
MANPAGE = TERMINAL / "src/fuchsia-studio.1"
BRIDGE = TERMINAL / "src/linux_console_bridge.rs"
BUILD = TERMINAL / "BUILD.gn"
CHROME = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/src/chrome.rs"
BROWSER = ROOT / "overlays/fuchsia/src/fuchsia-desktop/browser/src/main.rs"
SETTINGS = ROOT / "overlays/fuchsia/src/fuchsia-desktop/settings/src/settings_core.rs"
INPUT_DRIVER = TERMINAL / "src/input_driver.rs"
WM_DRIVER = ROOT / "overlays/fuchsia/src/ui/bin/tiling_wm/src/driver.rs"
LIVE_VERIFIER = ROOT / "scripts/verify-fuchsia-studio-help-live.sh"
README = ROOT / "README.md"


def invoke(executable: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(executable), *args],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def require(needle: str, haystack: str) -> None:
    assert needle in haystack, f"missing {needle!r}"


assert TOOL.is_file(), "Linux tool source is missing"
assert MANPAGE.is_file(), "manual page source is missing"
assert os.access(TOOL, os.X_OK), "Linux tool source must be executable"

help_result = invoke(TOOL, "help")
assert help_result.returncode == 0, help_result.stderr
assert max(map(len, help_result.stdout.splitlines())) <= 34, help_result.stdout
assert len(help_result.stdout.splitlines()) <= 16, help_result.stdout
require("             Browser, Terminal\n             Settings", help_result.stdout)
for phrase in (
    "FUCHSIA STUDIO",
    "Build, Research, Ops",
    "Left rail",
    "Windows",
    "Active view",
    "Spacing",
    "WM health",
    "fuchsia-studio health",
    "fuchsia-studio man",
):
    require(phrase, help_result.stdout)

brief_result = invoke(TOOL, "health", "--brief")
assert brief_result.returncode == 0, brief_result.stderr
require("[OK] Studio CLI + Linux shell", brief_result.stdout)
require("[INFO] Desktop health: Inspect", brief_result.stdout)

health_result = invoke(TOOL, "health")
assert health_result.returncode == 0, health_result.stderr
for phrase in (
    "[OK] Fuchsia Studio CLI installed",
    "[OK] Linux shell available",
    "[INFO] Desktop state is reported by Inspect",
):
    require(phrase, health_result.stdout)

man_result = invoke(TOOL, "man")
assert man_result.returncode == 0, man_result.stderr
for phrase in ("FUCHSIA-STUDIO(1)", "SYNOPSIS", "COMMANDS", "SCREEN LANGUAGE"):
    require(phrase, man_result.stdout)

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    health_alias = td_path / "health.sh"
    man_alias = td_path / "man"
    health_alias.symlink_to(TOOL)
    man_alias.symlink_to(TOOL)
    result = invoke(health_alias)
    assert result.returncode == 0, result.stderr
    require("[OK] Fuchsia Studio CLI installed", result.stdout)
    result = invoke(man_alias, "fuchsia-studio")
    assert result.returncode == 0, result.stderr
    require("FUCHSIA-STUDIO(1)", result.stdout)

unknown = invoke(TOOL, "unknown")
assert unknown.returncode == 2
require("Usage:", unknown.stderr)

manual = MANPAGE.read_text()
for phrase in (".TH FUCHSIA-STUDIO 1", ".SH SYNOPSIS", ".SH COMMANDS", ".SH SCREEN LANGUAGE"):
    require(phrase, manual)

bridge = BRIDGE.read_text()
for phrase in (
    'include_str!("fuchsia-studio")',
    'include_str!("fuchsia-studio.1")',
    "FUCHSIA_STUDIO_TOOL",
    "FUCHSIA_STUDIO_MANPAGE",
    "/usr/local/bin/fuchsia-studio",
    "/usr/local/bin/health.sh",
    "/usr/local/share/man/man1/fuchsia-studio.1",
    "fuchsia-studio health",
    "Try: man fuchsia-studio",
    "printf '%s' \"$FUCHSIA_STUDIO_TOOL\"",
    "printf '%s' \"$FUCHSIA_STUDIO_MANPAGE\"",
):
    require(phrase, bridge)
assert r'\"$FUCHSIA_STUDIO_TOOL\"' not in bridge, "bootstrap contains literal escaped quotes"
assert r'\"$FUCHSIA_STUDIO_MANPAGE\"' not in bridge, "bootstrap contains literal escaped quotes"

build = BUILD.read_text()
require('"src/fuchsia-studio"', build)
require('"src/fuchsia-studio.1"', build)

chrome = CHROME.read_text()
for phrase in (
    '"Windows"',
    '"Active view"',
    '"Spacing"',
    '"WM health"',
):
    require(phrase, chrome)
for duplicate in (
    '"Shell ready"',
    '"Focused"',
    '"12px gap"',
    '"Focus"',
    '"Gaps"',
    '"Tiles"',
    '"Gap"',
    '"Live"',
):
    assert duplicate not in chrome, f"ambiguous duplicate label remains: {duplicate}"
assert "status_chips" not in chrome
assert "status_dots" not in chrome

browser = BROWSER.read_text()
require('if narrow { "Address" } else { "Tab 1" }', browser)
assert 'if narrow { "Browser" } else { "Tab 1" }' not in browser

settings = SETTINGS.read_text()
require('(AppTheme::Dark, "Dark theme active".to_string())', settings)
assert '(AppTheme::Dark, "Ready".to_string())' not in settings

input_driver = INPUT_DRIVER.read_text()
require('text: Some("fuchsia-studio help\\n".to_string())', input_driver)
assert "echo terminalok" not in input_driver

wm_driver = WM_DRIVER.read_text()
require('.position(|view| view.id.to_ascii_lowercase().contains("terminal"))', wm_driver)
require('ensure!(!before.is_empty(), "expected at least one window")', wm_driver)
assert "expected exactly four windows" not in wm_driver

live_verifier = LIVE_VERIFIER.read_text()
require("component start core/session-manager/session:session/tiling_wm_driver", live_verifier)
require("confirmed", live_verifier)
require("terminal", live_verifier)

readme = README.read_text()
require("Latest Live 22:", readme)
require("three visible tiles. Files is absent.", readme)
require("Historical Live 4:", readme)
require("proves four tiles", readme)
assert "- Live Inspect: 4 tiles" not in readme
assert "Remaining gap: Instrument Studio chrome" not in readme

print("fuchsia_studio_help_contract_ok")

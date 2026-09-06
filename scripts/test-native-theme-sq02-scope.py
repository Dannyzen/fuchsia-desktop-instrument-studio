#!/usr/bin/env python3
"""Contract tests for event-local SQ-02 change scoping."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))

from sq02_scope import sq02_changed, unexpected_scope_paths


class ScopeTests(unittest.TestCase):
    def test_unrelated_files_and_docs_skip_sq02(self):
        self.assertFalse(sq02_changed([
            "overlays/fuchsia/src/fuchsia-desktop/files/src/main.rs",
            "scripts/test-files-grid-layout.py",
        ]))
        self.assertFalse(sq02_changed(["README.md", "docs/production-status.md", "design/sketch.md"]))

    def test_sq02_inputs_and_workflow_run_sq02(self):
        self.assertTrue(sq02_changed(["tools/native_theme/sq02_harness.py"]))
        self.assertTrue(sq02_changed([".github/workflows/ci.yml"]))
        self.assertTrue(sq02_changed(["scripts/native-theme-sq02-scope.py"]))

    def test_mixed_change_preserves_fail_closed_scope(self):
        changed = [
            "tools/native_theme/sq02_harness.py",
            "README.md",
            "overlays/fuchsia/src/fuchsia-desktop/files/src/main.rs",
        ]
        self.assertTrue(sq02_changed(changed))
        self.assertEqual(
            unexpected_scope_paths(changed),
            ["overlays/fuchsia/src/fuchsia-desktop/files/src/main.rs"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

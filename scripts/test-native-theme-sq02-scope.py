#!/usr/bin/env python3
"""Contract tests for event-local SQ-02 change scoping."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))

from sq02_scope import sq02_changed, unexpected_scope_paths


def cli_module():
    path = ROOT / "scripts/native-theme-sq02-scope.py"
    spec = importlib.util.spec_from_file_location("sq02_scope_cli", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_initial_multicommit_push_uses_default_branch_merge_base(self):
        cli = cli_module()
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                ).stdout.strip()
            git("init", "-q", "-b", "main")
            git("config", "user.name", "SQ02 test")
            git("config", "user.email", "sq02@example.invalid")
            (repo / "README.md").write_text("base\n")
            git("add", "README.md"); git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("switch", "-q", "-c", "feature")
            controlled = repo / "tools/native_theme/sq02_harness.py"
            controlled.parent.mkdir(parents=True); controlled.write_text("controlled\n")
            git("add", controlled.relative_to(repo).as_posix()); git("commit", "-q", "-m", "sq02")
            unrelated = repo / "overlays/fuchsia/src/fuchsia-desktop/files/src/main.rs"
            unrelated.parent.mkdir(parents=True); unrelated.write_text("files\n")
            git("add", unrelated.relative_to(repo).as_posix()); git("commit", "-q", "-m", "files")
            head = git("rev-parse", "HEAD")
            git("update-ref", "refs/remotes/origin/main", base)
            resolved = cli.resolve_comparison_base(repo, "0" * 40, head, "origin/main")
            self.assertEqual(resolved, base)
            paths = cli.changed_paths(repo, resolved, head)
            self.assertTrue(sq02_changed(paths))
            self.assertIn(controlled.relative_to(repo).as_posix(), paths)
            self.assertIn(unrelated.relative_to(repo).as_posix(), paths)
            with self.assertRaises(ValueError):
                cli.resolve_comparison_base(repo, "0" * 40, head, "origin/../main")

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

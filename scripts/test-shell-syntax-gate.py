#!/usr/bin/env python3
"""Regression contract for the per-file shell syntax gate."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-shell-syntax.py"


def run(*scripts: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *(str(script) for script in scripts)],
        text=True,
        capture_output=True,
        check=False,
    )


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    first = root / "00-valid.sh"
    second = root / "99-invalid.sh"
    first.write_text("#!/bin/sh\nexit 0\n")
    second.write_text("#!/bin/sh\nif then\n")

    negative = run(first, second)
    assert negative.returncode != 0, negative.stdout
    assert f"shell_syntax_error path={second}" in negative.stderr, negative.stderr
    assert "shell_syntax_failed files=1" in negative.stderr, negative.stderr

    second.write_text("#!/bin/sh\nexit 0\n")
    positive = run(first, second)
    assert positive.returncode == 0, positive.stderr
    assert "shell_syntax_ok files=2" in positive.stdout, positive.stdout

default = subprocess.run(
    [sys.executable, str(CHECKER)],
    text=True,
    capture_output=True,
    check=False,
)
assert default.returncode == 0, default.stderr
assert "shell_syntax_ok files=" in default.stdout, default.stdout

print("shell_syntax_gate_contract_ok")

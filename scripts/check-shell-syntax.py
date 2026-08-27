#!/usr/bin/env python3
"""Run bash syntax validation once per shell script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def shell_scripts(arguments: list[str]) -> list[Path]:
    if arguments:
        return [Path(argument) for argument in arguments]
    return sorted((ROOT / "scripts").glob("*.sh"))


def main(arguments: list[str]) -> int:
    scripts = shell_scripts(arguments)
    if not scripts:
        print("shell_syntax_failed reason=no_scripts", file=sys.stderr)
        return 1

    failures: list[tuple[Path, subprocess.CompletedProcess[str]]] = []
    for script in scripts:
        result = subprocess.run(
            ["bash", "-n", str(script)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append((script, result))

    if failures:
        for script, result in failures:
            print(f"shell_syntax_error path={script}", file=sys.stderr)
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)
        print(f"shell_syntax_failed files={len(failures)}", file=sys.stderr)
        return 1

    print(f"shell_syntax_ok files={len(scripts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

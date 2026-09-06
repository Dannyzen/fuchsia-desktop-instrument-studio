#!/usr/bin/env python3
"""Detect whether the current Git change set requires the SQ-02 gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))

from sq02_scope import sq02_changed

SHA = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REF = re.compile(r"^origin/[A-Za-z0-9][A-Za-z0-9._/-]*$")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def resolve_comparison_base(root: Path, base_sha: str, head_sha: str, default_ref: str | None) -> str:
    if not SHA.fullmatch(base_sha) or not SHA.fullmatch(head_sha):
        raise ValueError("base and head must be full lowercase Git SHAs")
    if base_sha != "0" * 40:
        return base_sha
    if not default_ref or not DEFAULT_REF.fullmatch(default_ref) or ".." in default_ref or "//" in default_ref:
        raise ValueError("all-zero push base requires a valid origin default ref")
    resolved = git(root, "merge-base", head_sha, default_ref)
    if not SHA.fullmatch(resolved):
        raise ValueError("default-branch merge base is not a full Git SHA")
    return resolved


def changed_paths(root: Path, base_sha: str, head_sha: str) -> list[str]:
    return sorted(set(git(root, "diff", "--name-only", f"{base_sha}..{head_sha}").splitlines()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--default-ref")
    parser.add_argument("--github-output")
    args = parser.parse_args()
    try:
        comparison_base_sha = resolve_comparison_base(
            ROOT, args.base_sha, args.head_sha, args.default_ref,
        )
    except ValueError as exc:
        parser.error(str(exc))
    paths = changed_paths(ROOT, comparison_base_sha, args.head_sha)
    run = sq02_changed(paths)
    payload = {
        "base_sha": comparison_base_sha,
        "head_sha": args.head_sha,
        "paths": paths,
        "run": run,
    }
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"run={str(run).lower()}\n")
            handle.write(f"comparison_base_sha={comparison_base_sha}\n")
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

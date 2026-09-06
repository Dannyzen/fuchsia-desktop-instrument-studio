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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()
    if not SHA.fullmatch(args.base_sha) or not SHA.fullmatch(args.head_sha):
        parser.error("base and head must be full lowercase Git SHAs")
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{args.base_sha}..{args.head_sha}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = sorted(set(result.stdout.splitlines()))
    run = sq02_changed(paths)
    payload = {
        "base_sha": args.base_sha,
        "head_sha": args.head_sha,
        "paths": paths,
        "run": run,
    }
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"run={str(run).lower()}\n")
            handle.write(f"comparison_base_sha={args.base_sha}\n")
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

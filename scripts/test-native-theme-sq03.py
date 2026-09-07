#!/usr/bin/env python3
"""Run the host-safe NativeTheme Phase 3 qualification contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = (
    "scripts/test-native-theme-service.py",
    "scripts/test-native-theme-p3-s2.py",
    "scripts/test-native-theme-p3-s3.py",
)
VERDICT_NAME = "sq-03-verdict.json"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", default=None)
    parser.add_argument("--output-dir", default="artifacts/quality/sq-03")
    args = parser.parse_args()

    actual_sha = git("rev-parse", "HEAD")
    source_sha = args.source_sha or actual_sha
    if source_sha != actual_sha:
        raise SystemExit(f"SQ03_SOURCE_SHA_MISMATCH expected={source_sha} actual={actual_sha}")
    if git("status", "--porcelain=v1", "--untracked-files=no"):
        raise SystemExit("SQ03_SOURCE_DIRTY tracked changes present")

    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "TZ": "UTC", "LC_ALL": "C", "LANG": "C", "PYTHONHASHSEED": "0"})
    commands = []
    passed = 0
    failed = 0
    for relative in CONTRACTS:
        result = subprocess.run(
            [sys.executable, relative], cwd=ROOT, env=env, capture_output=True, text=True
        )
        combined = result.stdout + result.stderr
        match = re.search(r"Ran (\d+) tests?", combined)
        count = int(match.group(1)) if match else 0
        if result.returncode == 0:
            passed += count
        else:
            failed += max(count, 1)
        commands.append({
            "command": f"{Path(sys.executable).name} {relative}",
            "exit_code": result.returncode,
            "test_count": count,
            "output_sha256": hashlib.sha256(combined.encode()).hexdigest(),
        })
        sys.stdout.write(combined)

    verdict = {
        "schema_version": 1,
        "gate": "sq-03-host-safe",
        "source_sha": source_sha,
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "result": "PASS" if all(row["exit_code"] == 0 for row in commands) else "FAIL",
        "tests": {"passed": passed, "failed": failed, "skipped": 0},
        "commands": commands,
        "scope": {
            "proves": "repository contracts for service, persistence, Settings authority, and diagnostics",
            "does_not_prove": "live Fuchsia routing, restart persistence, package identity, or rendered pixels",
        },
    }
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(verdict)
    (output_dir / VERDICT_NAME).write_bytes(payload)
    print(f"SQ03_VERDICT={verdict['result']} tests={passed} receipt={output_dir / VERDICT_NAME}")
    return 0 if verdict["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

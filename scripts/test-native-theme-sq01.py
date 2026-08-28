#!/usr/bin/env python3
"""Repository-owned NativeThemeV1 sq-01 source-quality command."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))
from sq01_harness import install_network_denial, run_gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    required = {"TZ": "UTC", "LC_ALL": "C", "LANG": "C", "PYTHONHASHSEED": "0", "NATIVE_THEME_SQ01_NETWORK": "deny"}
    wrong = {key: (os.environ.get(key), value) for key, value in required.items() if os.environ.get(key) != value}
    if wrong:
        parser.error("environment pins required: " + ", ".join(f"{k}={v[1]}" for k, v in wrong.items()))
    random.seed(0)
    install_network_denial()
    try:
        return run_gate(ROOT, args.source_sha, Path(args.output_dir))
    except Exception as exc:
        print(f"sq-01 FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

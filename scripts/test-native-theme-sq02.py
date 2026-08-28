#!/usr/bin/env python3
"""Inner deterministic SQ-02 gate; invoke through run-native-theme-sq02.py."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/native_theme"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cargo", required=True)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--cargo-home", required=True)
    parser.add_argument("--target-root", required=True)
    args = parser.parse_args()
    try:
        isolation = json.loads(os.environ["NATIVE_THEME_SQ02_ISOLATION_JSON"])
        from sq02_harness import QualificationError, run
        receipts = run(ROOT, args.source_sha, ROOT / args.output_dir, Path(args.cargo), Path(args.rustc),
                       Path(args.cargo_home), Path(args.target_root), isolation)
    except (KeyError, json.JSONDecodeError) as exc:
        print(f"CI_TOOLCHAIN_INFRASTRUCTURE: isolation proof unavailable ({type(exc).__name__})", file=sys.stderr)
        return 2
    except QualificationError as exc:
        print(f"{exc.classification}: {exc.message}", file=sys.stderr)
        return 2
    print(f"SQ02 PASS receipts={len(receipts)} authority=non-authoritative-harness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations
import runpy
import sys
from collections import Counter
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: assert-files-screenshot.py <screenshot.png>")
helper = runpy.run_path(str(Path(__file__).with_name("assert-example-domain-screenshot.py")))
width, height, rows, channels = helper["read_rgb"](Path(sys.argv[1]))
counts: Counter[tuple[int, int, int]] = Counter()
for row in rows:
    for offset in range(0, len(row), channels):
        counts[tuple(row[offset : offset + 3])] += 1
checks = {
    "background": counts[(53, 56, 61)] >= 400_000,
    "rows": counts[(116, 120, 128)] >= 300_000,
    "panel": counts[(90, 93, 101)] >= 80_000,
    "white_text": counts[(255, 255, 255)] >= 1_400,
    "cyan_accent": counts[(161, 229, 236)] >= 500,
    "pixel_diversity": len(counts) >= 350,
    "exact_size": (width, height) == (720, 1200),
}
failed = [name for name, passed in checks.items() if not passed]
print(
    f"files_pixels size={width}x{height} unique={len(counts)} "
    f"background={counts[(53, 56, 61)]} rows={counts[(116, 120, 128)]} "
    f"panel={counts[(90, 93, 101)]} white={counts[(255, 255, 255)]} "
    f"cyan={counts[(161, 229, 236)]}"
)
if failed:
    raise SystemExit(f"Files screenshot contract failed: {', '.join(failed)}")

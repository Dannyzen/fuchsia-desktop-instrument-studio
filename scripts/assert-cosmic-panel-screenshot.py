#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from collections import Counter
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("usage: assert-cosmic-panel-screenshot.py <screenshot.png>")

helper = runpy.run_path(str(Path(__file__).with_name("assert-example-domain-screenshot.py")))
width, height, rows, channels = helper["read_rgb"](Path(sys.argv[1]))
counts: Counter[tuple[int, int, int]] = Counter()
for row in rows:
    for offset in range(0, len(row), channels):
        counts[tuple(row[offset : offset + 3])] += 1
checks = {
    "background": counts[(53, 56, 61)] >= 500_000,
    "panel_surfaces": counts[(90, 93, 101)] >= 150_000,
    "cyan_accent": counts[(161, 229, 236)] >= 3_000,
    "green_accent": counts[(161, 224, 182)] >= 2_000,
    "orange_accent": counts[(246, 195, 141)] >= 1_500,
    "text": counts[(255, 255, 255)] >= 1_000,
    "pixel_diversity": len(counts) >= 300,
    "minimum_size": width >= 700 and height >= 1_000,
}
failed = [name for name, passed in checks.items() if not passed]
print(
    f"cosmic_panel_pixels size={width}x{height} unique={len(counts)} "
    f"background={counts[(53, 56, 61)]} panel={counts[(90, 93, 101)]} "
    f"cyan={counts[(161, 229, 236)]} green={counts[(161, 224, 182)]} "
    f"orange={counts[(246, 195, 141)]} white={counts[(255, 255, 255)]}"
)
if failed:
    raise SystemExit(f"COSMIC panel screenshot contract failed: {', '.join(failed)}")

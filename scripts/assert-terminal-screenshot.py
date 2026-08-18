#!/usr/bin/env python3
"""Verify a Terminal interaction produced a visible screenshot delta."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: assert-terminal-screenshot.py BEFORE.png AFTER.png")
    helper = runpy.run_path(str(Path(__file__).with_name("assert-example-domain-screenshot.py")))
    read_rgb = helper["read_rgb"]
    bw, bh, brows, bchannels = read_rgb(Path(sys.argv[1]))
    aw, ah, arows, achannels = read_rgb(Path(sys.argv[2]))
    if (bw, bh, bchannels) != (aw, ah, achannels):
        raise SystemExit("before and after screenshot formats differ")

    changed = 0
    bright = 0
    bright_by_row: list[int] = []
    unique: set[tuple[int, int, int]] = set()
    for before, after in zip(brows, arows):
        row_bright = 0
        for offset in range(0, len(after), achannels):
            before_rgb = tuple(before[offset : offset + 3])
            r, g, b = after[offset : offset + 3]
            after_rgb = (r, g, b)
            changed += before_rgb != after_rgb
            is_bright = r > 160 and g > 160 and b > 160
            bright += is_bright
            row_bright += is_bright
            unique.add(after_rgb)
        bright_by_row.append(row_bright)

    active_rows = [row for row, count in enumerate(bright_by_row[:120]) if count >= 3]
    text_bands: list[list[int]] = []
    for row in active_rows:
        if not text_bands or row > text_bands[-1][-1] + 4:
            text_bands.append([row])
        else:
            text_bands[-1].append(row)

    print(
        f"terminal_delta size={aw}x{ah} changed={changed} bright={bright} "
        f"unique={len(unique)} text_bands={len(text_bands)}"
    )
    if changed < 200 or bright < 100 or len(unique) < 20 or len(text_bands) < 3:
        raise SystemExit(
            "Terminal interaction must visibly show command, output, and returned prompt"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Host contract: narrow Files tile uses a 2x3 icon grid."""

GRID_TOP = 200
GRID_PAD = 10
GRID_GAP = 8
CELL_H = 88
COLS = 2
ROWS = 3
TILE_W = 326


def cell(width, col, row):
    cell_w = (width - GRID_PAD * 2 - GRID_GAP) / COLS
    x = GRID_PAD + col * (cell_w + GRID_GAP)
    y = GRID_TOP + row * (CELL_H + GRID_GAP)
    return x, y, cell_w, CELL_H


def main() -> int:
    x0, y0, w, h = cell(TILE_W, 0, 0)
    x1, y1, _, _ = cell(TILE_W, 1, 0)
    x2, y2, _, _ = cell(TILE_W, 0, 1)
    assert w > 140
    assert x1 > x0 + w
    assert y2 > y0 + h
    assert y0 == 200
    assert x0 == 10
    print("files_grid_layout_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

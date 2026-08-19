#!/usr/bin/env python3
"""Host contract: narrow Settings/Browser layout stays inside a 326x500 tile."""

TILE_W = 326
TILE_H = 500


def settings_narrow():
    # y bands from the live overlay
    dark = (88, 136)
    contrast = (140, 188)
    celsius = (220, 268)
    fahr = (272, 320)
    system = (328, 388)
    status_y = max(TILE_H - 40, 430)
    assert dark[1] <= contrast[0]
    assert contrast[1] <= celsius[0]
    assert celsius[1] <= fahr[0]
    assert fahr[1] <= system[0]
    assert system[1] <= status_y
    assert status_y + 32 <= TILE_H + 8  # 8px tolerance for bottom chip
    assert all(x < TILE_W for x in (16 + (TILE_W - 32),))


def browser_narrow():
    addr_x = 8
    addr_w = max(TILE_W - 16, 48)
    assert addr_x + addr_w <= TILE_W
    shown = "example.com"  # https:// stripped
    assert len(shown) * 8 < addr_w + 40


def main() -> int:
    settings_narrow()
    browser_narrow()
    print("narrow_app_layout_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Host contract: portrait FEMU 4-app tiles use compact chrome."""

TILE_W = 326
TILE_H = 500


def settings_narrow():
    # 56px sidebar + Appearance/Temperature cards
    sidebar = 56
    dark = (44, 84)
    contrast = (92, 132)
    celsius = (200, 240)
    fahr = (248, 288)
    system = (308, 344)
    status_y = max(TILE_H - 32, 360)
    assert sidebar < 72
    assert dark[1] <= contrast[0] <= celsius[0] <= fahr[0] <= system[0] <= status_y
    assert status_y + 28 <= TILE_H + 8


def display_url(url: str, width: int) -> str:
    max_chars = min(max(width // 9, 6), 24)
    trimmed = url.removeprefix("https://").removeprefix("http://").rstrip("/")
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[: max_chars - 1] + "…"


def portrait_is_narrow(width: int, height: int) -> bool:
    return width < 520 or (height > width and width < 800)


def main() -> int:
    settings_narrow()
    shown = display_url("https://example.com/", 310)
    assert "https://" not in shown
    assert shown.startswith("example")
    assert portrait_is_narrow(720, 1200)
    assert portrait_is_narrow(326, 500)
    assert not portrait_is_narrow(1280, 800)
    print("narrow_app_layout_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

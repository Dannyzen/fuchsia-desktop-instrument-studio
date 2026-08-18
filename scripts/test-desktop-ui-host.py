#!/usr/bin/env python3
"""Host-side contract tests for Instrument Studio layout tokens."""
from __future__ import annotations

PANEL_H = 48
RAIL_W = 72
INSPECTOR_H = 160


def regions(width: int, height: int, panel_h=PANEL_H, rail_w=RAIL_W, inspector_h=INSPECTOR_H):
    assert width >= 640 and height >= 480
    strip = (0, 0, width, panel_h)
    rail = (0, panel_h, rail_w, height - panel_h - inspector_h)
    stage = (rail_w, panel_h, width - rail_w, height - panel_h - inspector_h)
    inspector = (0, height - inspector_h, width, inspector_h)
    return strip, rail, stage, inspector


def main() -> int:
    strip, rail, stage, inspector = regions(1440, 900)
    assert strip == (0, 0, 1440, 48)
    assert rail == (0, 48, 72, 692)
    assert stage == (72, 48, 1368, 692)
    assert inspector == (0, 740, 1440, 160)
    assert stage[2] + rail[2] == 1440
    assert strip[3] + stage[3] + inspector[3] == 900
    strip, rail, stage, inspector = regions(720, 1200, panel_h=40, rail_w=56, inspector_h=120)
    assert stage[2] > 0 and stage[3] > 0
    try:
        regions(320, 240)
        raise SystemExit("expected tiny display rejection")
    except AssertionError:
        pass
    print("desktop_ui_host_contract_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

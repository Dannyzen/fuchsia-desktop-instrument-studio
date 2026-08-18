#!/usr/bin/env python3
"""Host-side contract tests for Instrument Studio layout tokens."""
from __future__ import annotations

# Mirror of desktop_ui layout math for CI without the Fuchsia toolchain.
PANEL_H = 48
RAIL_W = 72
INSPECTOR_H = 160


def regions(width: int, height: int):
    assert width >= 800 and height >= 600
    strip = (0, 0, width, PANEL_H)
    rail = (0, PANEL_H, RAIL_W, height - PANEL_H - INSPECTOR_H)
    stage = (RAIL_W, PANEL_H, width - RAIL_W, height - PANEL_H - INSPECTOR_H)
    inspector = (0, height - INSPECTOR_H, width, INSPECTOR_H)
    return strip, rail, stage, inspector


def main() -> int:
    strip, rail, stage, inspector = regions(1440, 900)
    assert strip == (0, 0, 1440, 48)
    assert rail == (0, 48, 72, 692)
    assert stage == (72, 48, 1368, 692)
    assert inspector == (0, 740, 1440, 160)
    assert stage[2] + rail[2] == 1440
    assert strip[3] + stage[3] + inspector[3] == 900
    try:
        regions(640, 480)
        raise SystemExit('expected tiny display rejection')
    except AssertionError:
        pass
    print('desktop_ui_host_contract_ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

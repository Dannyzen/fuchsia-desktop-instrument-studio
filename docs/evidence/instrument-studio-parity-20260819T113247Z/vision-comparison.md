# Vision comparison: design parity loop

Date: 2026-08-19T11:32Z
Design: `design/screenshots/01-instrument-studio.png`
Live: `emulator-parity-live.png`

## Observed gap (design vs prior live)

Design has Inter type, rounded 14px cards, title bars, cyan glow, Settings
sidebar+toggles, Files icon grid, Browser URL chrome, dense Terminal.
Live was a working 2x2 shell with gray slab apps.

## This loop

- Compact Settings stack: Ready no longer overlaps System
- Files title shortened to `Files`
- Host contract `scripts/test-narrow-app-layout.py`
- Browser URL wrap + title attempted; live shot still shows old chrome
  (`Tab 1`, cyan square, `https://example.co` clip)

## Diagnostics

- Inspect OK, tile_count=4, confirmed focus=terminal
- 4 apps Running

## Remaining (named beads)

- `8vg0.1` tile cards / radius / glow
- `8vg0.2` Settings sidebar + cards
- `8vg0.3` Files icon grid
- `8vg0.4` Terminal prompt density
- `8vg0.5` true rail icons
- `8vg0.6` Browser chrome + clip (still open)
- `ins3` residual Ready chip clip + Browser

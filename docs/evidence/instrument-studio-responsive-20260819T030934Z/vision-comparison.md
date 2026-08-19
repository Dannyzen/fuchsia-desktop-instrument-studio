# Vision comparison: narrow-tile responsive Settings/Files

Date: 2026-08-19T03:09Z
Live merkle: `35d48552678039295b3a1f46cbc5dd3d68e2c1625a10b0523be10af242ddba44`
Shot: `emulator-responsive-live.png`

## Change

- Settings <520px: stacked Dark / Contrast / Celsius / Fahrenheit
- Files <520px: two-row toolbar + width-bound rows
- Hit tests match stacked geometry
- 4-app stage restored

## Diagnostics

- Inspect OK, tile_count=4
- confirmed focus = terminal
- all four apps Running

## Vision

Improved:
- Settings controls stacked and mostly inside the tile
- Files toolbar wraps (Up/Open/New/Ren + Copy/Move/Del)
- Files list rows stay in-tile
- chrome labels still readable
- 2x2 stage intact, cyan Terminal focus

Residual (bead stays open):
- Settings status `Ready` overlaps System info
- Browser URL/page still clips (`https://example.co`, `Example Domain`)
- not yet a landscape RED screenshot set

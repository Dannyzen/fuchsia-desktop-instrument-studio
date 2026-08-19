# Vision comparison: OCR-clean chrome labels

Date: 2026-08-19T02:58Z
Live merkle: `35d48552678039295b3a1f46cbc5dd3d68e2c1625a10b0523be10af242ddba44`
Shot: `emulator-ocr-labels-live.png`

## Change

- 4px 5x7 glyphs
- taller portrait strip/inspector (52/136)
- shorter words: STUDIO / BLD RSH OPS / OK FOC GAP / INSPECT TILE FOC GAP LIVE
- labels created last so they paint above chrome surfaces

## Diagnostics

- Inspect OK
- live merkle == built package
- tile_count=3 this run (Settings Running but dropped from WM order after RemoveTile)
- confirmed focus = browser

## Vision (readable)

- brand: `STUDIO`
- pills: `BLD` (active) `RSH` `OPS`
- chips: `OK` `FOC` `GAP`
- inspector title: `INSPECT`
- inspector cards: `TILE` `FOC` `GAP` `LIVE`
- rail glyphs + cyan browser focus
- Terminal `localhost:/#`

## Residual

- bitmap font, not production type
- 4-app stage not intact this shot (3 tiles)
- true vector icons and app chrome restyle still open

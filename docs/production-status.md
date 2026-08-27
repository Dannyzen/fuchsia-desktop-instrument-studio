# Workbench Studio production status

Updated: 2026-08-27

## Short answer

Live 16 (`875b46ad…`) is a 2x2 of colored app cards (amber Browser, violet Files, cyan Settings, green Terminal). Still not production Instrument Studio.

Live 17: tile headers read BRW / FIL / TRM. Settings dropped this shot.

Live 18: Inspect tile_count=4. SET / FIL / TRM readable. BRW clipped.

Live 19: Settings sidebar + Appearance/Temperature cards. Dark/Celsius selected.

Live 20: chrome menu words no longer collide. WORKBENCH BLD RSH OPS / OK FOC GAP.

Live 21: packaged Roboto renders full shell words and packaged Material Icons renders semantic rail/inspector glyphs. Full SETTINGS / TERMINAL / BROWSER tile titles are readable. Inspect is healthy and built merkle equals live merkle, but Files is absent under the existing `8vg0.3` PresentView failure, so this is an honest three-tile proof.

**No. The live emulator screen is not production yet.**

It is a real native Fuchsia Workbench session with:

- Inspect-backed tiling WM
- Instrument Studio chrome regions
- Design-derived multi-rect iconography
- an Inspect-backed stage; Live 21 shows three apps because Files exited during PresentView

It is **not** yet the polished production Workbench Studio UI from the design screenshot.

## Done

- Native Roboto shell labels live-proven: Workbench Studio / Build / Research / Ops / Ready / Focus / Gaps / Inspect
- Native Material Icons live-proven for rail and inspector constructs
- Full Settings / Files / Browser / Terminal title source, with Settings / Terminal / Browser visible in Live 21
- Built `tiling_wm` merkle matches live (`90f336fb…`), Inspect health `OK`
- Chrome bitmap label path (brand/pills/chips/inspector) live-proven
- 3px/RLE label scale attempt live-proven (still not OCR-clean)
- Narrow-tile stacked Settings/Files (Browser clip residual)
- OCR-readable chrome labels (4px, labels-on-top): STUDIO / BLD RSH OPS / OK FOC GAP / INSPECT TILE FOC GAP LIVE

- Terminal tile wired to Alpine/Linux via Starnix Controller bridge

- Native tiling foundation + confirmed focus
- Live DF/Inspect feedback loop
- Shell chrome geometry (strip/rail/inspector)
- Density language (pills/chips/cards)
- Production-closer rail icon set (launcher/overview/files/browser/terminal/settings)
- Screenshot + vision evidence trail

## Not done (blocks “production”)

Screenshot-ranked (2026-08-19 vs `01-instrument-studio.png`):
1. App tiles are gray slabs, not Instrument Studio cards (`8vg0.1`)
2. Settings is stacked buttons, not sidebar+cards (`8vg0.2`)
3. Files is a list, not an icon grid (`8vg0.3`)
4. Browser URL/page still clips (`8vg0.6`)
5. Terminal is an empty `localhost:/#` box (`8vg0.4`)
6. Files PresentView still removes the Files tile (`8vg0.3`)
7. Tile-title font path, radius, glow, and release packaging remain


1. Move tile-title text from the large bitmap renderer to the native font surface
2. Fix the clipped/ghost title fragment below the top strip
3. Restore Files PresentView for a true four-app frame (`8vg0.3`)
4. Add optional rail labels/tooltips for ambiguous symbols
5. App chrome, terminal density, glow/radius fidelity, and release packaging

4-app Inspect gate: session-add Running is not enough. Live 15 fail-closed at tile_count=1.

Planning matrix: `docs/design-vision-bead-matrix.md` (two-round visual/IA + function validation).

## Latest live proof

- `design/screenshots/21-emulator-font-icons-live.png`
- `docs/evidence/instrument-studio-font-icons-20260827T051537Z/`

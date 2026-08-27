# Workbench Studio production status

Updated: 2026-08-27

## Short answer

**No. The live emulator screen is not production yet.**

Live 22 is a real native Fuchsia Workbench session with readable Roboto shell/tile headers, Material icons, a working Alpine/Starnix Terminal help command, Inspect health `OK`, and exact built/live package identity. It is an honest three-window proof because Files remains absent.

## Live trail

- Live 16: colored app cards.
- Live 17: first bitmap tile abbreviations.
- Live 18: four-tile Inspect proof with clipped titles.
- Live 19: Settings sidebar and cards.
- Live 20: chrome menu collision cleanup.
- Live 21: packaged Roboto shell words and Material icons; three visible apps.
- Live 22: packaged Roboto tile headers; duplicate top status chips removed; built-in `fuchsia-studio` help/health/manual; unwrapped narrative screenshot.

## Done

- Packaged Roboto renders Workbench Studio, workspace labels, Inspect labels, and full Terminal / Browser / Settings tile headers.
- The legacy 5x7 bitmap tile-title renderer and its 128-bar pool are removed.
- Packaged Material Icons render launcher rail and Inspect symbols.
- `fuchsia-studio help`, `health`, and `man` run inside Alpine through the existing Starnix console bridge.
- `health.sh` and `man fuchsia-studio` aliases are installed.
- The fixed keyboard driver demonstrates the help command in actual FEMU pixels.
- Live 22 Inspect reports health `OK`, `tile_count=3`, and confirmed Terminal focus before input.
- Controller route reports `Success`.
- Built/live merkles match for Terminal (`ff68d52c…`) and tiling WM (`080c7307…`).
- The final screenshot has no mid-word Terminal help wrap and retains visible health lines.

## Not done

1. Restore Files PresentView and prove Inspect `tile_count=4`.
2. Add in-place rail labels or tooltips so symbols do not require the help page.
3. Show numeric/current values in the Inspect cards rather than category labels and bars only.
4. Repair Browser toolbar/page clipping and replace prototype content.
5. Finish app-card polish, radius/glow fidelity, accessibility, recovery, rollback, and release packaging.

A component reporting `Running` is not a four-window proof. The acceptance gate remains Inspect `tile_count=4`.

## Latest live proof

- `design/screenshots/22-emulator-studio-help-live.png`
- `docs/evidence/instrument-studio-help-20260827T062745Z/`

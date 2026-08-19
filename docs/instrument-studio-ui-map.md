# Instrument Studio UI map

Design source: `design/sketches/01-instrument-studio/`

## Goal

Turn the Instrument Studio sketch into a native Fuchsia shell using shared
`desktop_ui` contracts and the diagnostics feedback loop.

## Region map

| Sketch region | desktop_ui symbol | Owner component (target) | Notes |
|---|---|---|---|
| Top workspace pills | `ChromeRegion::WorkspaceStrip` | panel / shell chrome | workspace switcher |
| Left launcher rail | `ChromeRegion::LauncherRail` | panel / shell chrome | app launch + status |
| 2x2 tiled apps | `ChromeRegion::TiledStage` | `tiling_wm` | confirmed-focus cyan ring already lands here |
| Bottom inspector | `ChromeRegion::Inspector` | shell chrome + diagnostics | binds to design-feedback / inspect |

## Tokens

`desktop_ui::INSTRUMENT_STUDIO_THEME` encodes:

- near-black panels
- cyan confirmed focus
- violet secondary accent
- gap 12px / active border 3px (aligned with tiling_wm config)

## Build sequence

1. Keep diagnostics green (`wm.available`, confirmed focus markers).
2. Land shared `desktop_ui` tokens/layout (this change).
3. Promote panel-spike into Instrument Studio chrome using tokens.
4. Wire inspector pane to `design-feedback.json` / live Inspect selectors.
5. Only then restyle in-app surfaces (Settings/Files/Browser chrome).

## Feedback loop command

```bash
./scripts/collect-desktop-diagnostics.sh ./artifacts/diagnostics-run
jq .evaluation ./artifacts/diagnostics-run/design-feedback.json
```


## Live implementation note (2026-08-18)

Shell chrome is drawn by `tiling_wm` using `desktop_ui::InstrumentStudioLayout`:

- workspace strip + cyan underline
- launcher rail + violet edge
- inspector bar + cyan top edge
- tiled stage is inset into the remaining rectangle

Evidence: `docs/evidence/instrument-studio-chrome-20260818T225220Z/`.


## Density pass (2026-08-18)

Chrome now includes geometric product density:

- brand block + workspace pills + status chip
- 4 launcher marks with active highlight
- 4 inspector cards with state-bound meter bars

Evidence: `docs/evidence/instrument-studio-density-20260818T230716Z/`.


## Iconography pass (2026-08-19)

Rail glyphs follow design sketch order:

1. Launcher
2. Overview
3. Files
4. Browser
5. Terminal
6. Settings

Brand mark uses cyan/violet split. Active rail slot tracks confirmed focus.

Evidence: `docs/evidence/instrument-studio-icons-20260819T001859Z/`.


## Typography/labels pass (2026-08-19)

Chrome now draws 5x7 bitmap labels for brand, workspace pills, status chips, and inspector cards.
Evidence: `docs/evidence/instrument-studio-labels-20260819T020608Z/`.
Residual: increase glyph scale / add true font path for OCR-clean production text.

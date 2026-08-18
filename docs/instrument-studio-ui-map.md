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

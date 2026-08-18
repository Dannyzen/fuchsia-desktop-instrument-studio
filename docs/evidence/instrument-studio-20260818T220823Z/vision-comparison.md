# Vision comparison: live emulator vs Instrument Studio design

Date: 2026-08-18T22:08Z
Source shot: `emulator-four-app.png`
Design target: `design/screenshots/01-instrument-studio.png`

## Live diagnostics (DF)

From Inspect on `core/session-manager/session:session/tiling_wm`:

- `tile_count = 4`
- `order = terminal, settings, files, browser`
- `focus.confirmed = terminal` and matches selected
- `config.gap_px = 12`, `active_border_px = 3`
- health status OK
- live merkle matches rebuilt package (`7aa36e02...`)
- `design-feedback.json` evaluation: **ready_for_ui_iteration = true**

## Vision findings

### Present (foundation contract)

1. True 2x2 tiled stage with four system apps running.
2. Cyan confirmed-focus ring on the Terminal tile (top-left).
3. Settings / Files / Browser content readable enough to identify apps.
4. Dark shell background; gaps between tiles visible.

### Missing vs Instrument Studio design

1. **No top workspace strip** (Build/Research/Ops pills, brand, status chips).
2. **No left launcher rail**.
3. **No bottom inspector** diagnostics pane.
4. App chrome is product-MVP utilitarian, not Instrument Studio density/polish.
5. Terminal tile is mostly empty black (prompt only), weak visual weight vs design.
6. No shared card radii, badges (`confirmed`, path chips), or secondary violet accents in chrome.

## Gap ranking (next implementation)

1. Session-integrated Instrument Studio chrome from `desktop_ui` regions:
   workspace strip + launcher rail + inspector.
2. Bind inspector to live Inspect/design-feedback fields.
3. Restyle Settings/Files/Browser chrome to shared tokens.
4. Ensure Terminal has stronger default content/affordance in tile.

## Conclusion

Observability + tiling foundation now **prove** the runtime feedback loop and 2x2 stage.
The **shell chrome layer** is the remaining product gap between live emulator and the design screenshot.

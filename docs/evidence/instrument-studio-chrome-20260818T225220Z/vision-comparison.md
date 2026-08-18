# Vision comparison: Instrument Studio chrome live

Date: 2026-08-18T22:52Z
Live merkle: `375af6ce3bb59b918b4156b6e5560015aea09f8ddb6f968098d5f6cc92428827`
Shot: `emulator-chrome-live.png`
Design target: `design/screenshots/01-instrument-studio.png`

## Diagnostics

- Inspect available, health OK
- tile_count=4 (terminal/settings/files/browser)
- confirmed focus = terminal
- gap_px=12, active_border_px=3
- design-feedback ready_for_ui_iteration=true

## Vision: chrome present

1. **Top workspace strip**: dark elevated bar across full width with cyan underline accent.
2. **Left launcher rail**: dark vertical rail with violet trailing edge.
3. **Bottom inspector**: dark bar across width with cyan top edge.
4. **Stage inset**: 2x2 app grid no longer full-bleed; reserved margins match chrome regions.
5. **Confirmed focus**: cyan ring still on Terminal (top-left).

## Still missing vs polished design

- No workspace pill labels / brand text
- No launcher icons
- No inspector telemetry text/cards
- App surfaces still MVP chrome (not Instrument Studio dense cards)
- Terminal tile still mostly empty prompt

## Conclusion

Shell chrome regions are now **live and visible** in the emulator via `tiling_wm` + `desktop_ui` layout.
Next iteration is content density inside those regions (labels/icons/inspector data), not region existence.

# Vision comparison: Instrument Studio density pass

Date: 2026-08-18T23:07Z
Live merkle: `8e5dafcf765fbf546c234b370ddbd9e9f1e5c23f5e3adbaced79bb512d8e6e05`
Shot: `emulator-density-live.png`
Design target: `design/screenshots/01-instrument-studio.png`

## Diagnostics

- Inspect OK, tile_count=4
- confirmed focus = terminal
- gap 12 / border 3
- ready_for_ui_iteration=true

## Vision: density now present

1. **Top strip**
   - brand block + cyan core
   - 3 workspace pills (first active with cyan underline)
   - status chip + green health dot
   - full-width cyan strip accent
2. **Left rail**
   - 4 launcher marks
   - active terminal mark highlighted cyan/violet
   - violet trailing edge
3. **Bottom inspector**
   - 4 cards
   - meter bars (cyan/cyan/violet/green) bound to live state
   - cyan top edge
4. **Stage**
   - inset 2x2 grid preserved
   - cyan confirmed focus on Terminal

## Closer to design

Structure + density language now match Instrument Studio chrome geometry and accent system.
This is a clear step beyond empty bars.

## Remaining for polished complete

- Glyph labels (Build/Research/Ops, brand wordmark, inspector captions)
- Richer iconography (not only geometric marks)
- App chrome restyle to Instrument Studio cards
- Terminal tile content density

## Conclusion

Density pass is live and screenshot-proven. Remaining work is typography/content finish, not shell geometry.

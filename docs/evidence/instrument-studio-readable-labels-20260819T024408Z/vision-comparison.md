# Vision comparison: readable-labels scale bump

Date: 2026-08-19T02:44Z
Live merkle: `3f003ec758ca36054a1af8df249285ed5fd46a607d0c21499bb4cc81fa41ab53`
Shot: `emulator-readable-labels-live.png`

## Change

- 5x7 glyphs scaled 2px -> 3px
- draw_text uses horizontal run-length bars
- LABEL_PARTS 220 -> 360
- wider pills/chips to fit 3px text

## Diagnostics

- Inspect OK, tile_count=4
- confirmed focus = terminal
- live merkle == built package
- ready_for_ui_iteration=true

## Vision

Readable now:
- chrome regions, pills, chips, inspector cards, rail glyphs
- 2x2 inset stage, cyan Terminal focus
- Terminal `localhost:/#`

Still not OCR-clean:
- brand wordmark not readable
- BUILD/RSRCH/OPS not readable
- OK/FOC/GAP not readable
- INSPECT / TILES/FOCUS/GAP/LIVE not readable

## Conclusion

Scale path is live. Typography remains a residual. Next: 4px + shorter labels, or true font TextSurface.

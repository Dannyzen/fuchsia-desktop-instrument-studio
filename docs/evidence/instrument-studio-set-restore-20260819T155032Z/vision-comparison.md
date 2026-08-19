# Vision: Settings restored on 4-app stage

Date: 2026-08-19T15:50Z
Live merkle: `376c744e02ff8b8b12f7b85b54186cd5e494a11aac9d481b9849dbf152afbecc`

## Cause

`watch_tile` treated `get_view_ref` failure as `ClientDied`. Settings
CreateView2 / TextSurface is slow, so the ViewRef miss dropped the tile
after session-add reported Running.

## Fix

Keep the tile on a transient ViewRef miss. Add Settings last.

## Live 18

- Inspect `tile_count=4`
- Order: Settings, Browser, Files, Terminal
- Vision reads `SET`, `FIL`, `TRM` on headers
- `BRW` is clipped/garbled
- Chrome labels still STUDIO / BLD RSH OPS / OK FOC GAP / INSPECT

## Residual

- Settings is stacked, not sidebar+cards
- Files is a list, not an icon grid
- Browser still Example Domain
- Terminal still `localhost:/#`
- No 14px radius / glow

# Vision: Instrument Studio card chrome

Date: 2026-08-19T14:30Z
Live merkle: `875b46ad1be566487b25a898d4bc2698bcd6bf3ba65b5275ea85e92e686f2e4e`

## Looks (this was the ask)

Live 16 is a 2x2 of **colored app cards**, not gray slabs:

- Browser: amber header + Example Domain
- Files: violet header + list
- Settings: cyan header + Dark / Celsius
- Terminal: green header + cyan confirmed-focus ring

Chrome labels still read STUDIO / BLD RSH OPS / OK FOC GAP / INSPECT.

## Inspect mismatch

Inspect still reports `tile_count=1` because PresentView called raw
`flatland.present` and never published observability. Vision is the look gate.
Fix: PresentView must go through `self.present()` so Inspect matches the shot.

## Residual vs design 01

- No readable SET/FIL/BRW/TRM title words
- No 14px radius / glow
- Settings still stacked, not sidebar+cards
- Files still a list, not an icon grid
- Browser still Example Domain, not fuchsia.dev chrome
- Terminal still `localhost:/#`

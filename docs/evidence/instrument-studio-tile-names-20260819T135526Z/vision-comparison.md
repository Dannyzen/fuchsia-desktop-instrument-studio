# Fail-closed: 4-app restore

Date: 2026-08-19T13:55Z
Live merkle: `35697fd9bd317ef84ddae9aeebe0379fd790a6d9d2cd5249eee113682f79c0d6`

## What landed in source

- WM title strip + color accent (`8vg0.1`)
- SET/FIL/BRW/TRM bitmap names via chrome labels
- Host contract `scripts/test-tile-identity.py`
- Demo loop now skips the 4-window driver unless Inspect `tile_count==4`

## What live did not prove

- Inspect `tile_count=1` (Terminal only)
- Settings/Files/Browser components Running + ViewProvider Success
- They never become WM tiles (no PresentView / GetLayout never completes)
- This is why Settings dropped after earlier `RemoveTile` shots

Do not close `8vg0.1`. Next: diagnose element PresentView for Settings/Files/Browser.

# Instrument Studio observability feedback loop

Goal: use Fuchsia diagnostics (Inspect + structured logs + screenshot) as a
tight development feedback loop while building toward the Instrument Studio
design sketches.

## Why

Screenshots alone are slow and ambiguous. The tiling WM now exposes an Inspect
hierarchy that tells us whether the live session matches the design contract:

- tile count and order
- selected vs confirmed focus
- gap / active border config
- present counters

## Inspect tree

```
root
  tiling_wm
    tile_count
    order
    present_count
    last_present_context
    config/
      gap_px
      active_border_px
      wrap_focus
    focus/
      selected
      confirmed
```

## Collect

With the Workbench emulator running:

```bash
./scripts/collect-desktop-diagnostics.sh ./artifacts/diagnostics-run
cat ./artifacts/diagnostics-run/design-feedback.json
```

The collector gathers:

- `ffx inspect` for `tiling_wm`
- `ffx log` markers (`TILING_WM_*`)
- optional session screenshot
- `design-feedback.json` evaluation against the Instrument Studio contract

`artifacts/` remains gitignored. Do not commit diagnostics bundles.

## Design contract checks

`design-feedback-report.py` evaluates:

1. Inspect node availability
2. At least one tile
3. Four-tile grid readiness for the 2x2 sketch
4. Confirmed-focus presence on an active desktop
5. Gap/border config sanity

Use `evaluation.next_actions` as the next implementation queue.

## Rebuild path

```bash
./scripts/apply-overlays.sh "$FUCHSIA_ROOT"
# then rebuild/publish tiling_wm into the running Workbench product lane
./scripts/collect-desktop-diagnostics.sh
```


## Live guest reload note

`tiling_wm` is a static session child in Workbench. Building and publishing the
package is necessary but not sufficient while an old session instance remains
pinned to a previous merkle.

After `fx build //src/ui/bin/tiling_wm:tiling_wm` and repository publish:

1. Restart the Workbench session or reboot the emulator target.
2. Re-run `./scripts/collect-desktop-diagnostics.sh`.
3. Confirm `design-feedback.json` reports `wm.available=true`.

Unit tests validate the Inspect publisher without requiring a live relaunch.

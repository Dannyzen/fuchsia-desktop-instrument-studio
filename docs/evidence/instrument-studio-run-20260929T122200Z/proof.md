# Current FEMU run, 2026-09-29T12:22:00Z

Guest: `fuchsia-workbench-femu`
Product: `workbench_slim.x64`
Screenshot: `design/screenshots/current-femu-run.png`
SHA-256: `8a1d8935b354bd6cf4f057301d279bd75102e2c2e7cea1552da3153dfaed064e`
Size: 720x1200

The documented path was executed: start the lab container, start headless FEMU, wait for the target, confirm guest SSH, add Settings, Terminal, Browser, and Files, then capture `ffx target screenshot`.

Inspect in `inspect.json`:

- `fuchsia.inspect.Health.status` = `OK`
- `tiling_wm.tile_count` = `3`
- `tiling_wm.order` = `instrument-studio-browser,instrument-studio-terminal,instrument-studio-settings`
- `tiling_wm.last_present_context` = `RemoveTile`
- focus confirmed and selected: `instrument-studio-settings`

The Files component was Running. It was not in the tile order.

Visible pixels: three tiles. Headers read Files, Terminal, and Settings. The Files body is empty. Terminal shows the studio help lines. Settings shows Appearance and Temperature. There is no fourth tile and no Browser page. The painted Files header and the Inspect order do not name the same first tile.

The runbook wait does not stop at the first count of 3. It accepts 3 only after at least three consecutive polls with that exact order. Any other incomplete count exits before Inspect or screenshot.

# Instrument Studio font + icon live proof

Captured: 2026-08-27T05:15:37Z on `fuchsia-workbench-femu` (Bigs)

## Source and runtime identity

- Public source base: `022af69c7e42c82c138af1c6661178bd62ce1357`
- Built `tiling_wm` merkle: `90f336fb19658691778959939fb97f9bd3bdc652005cc60b823470d748849e7a`
- Live `tiling_wm` merkle: `90f336fb19658691778959939fb97f9bd3bdc652005cc60b823470d748849e7a`
- Inspect health: `OK`
- Inspect at screenshot: `tile_count=3`, `present_count=17`
- Visible order: Settings, Terminal, Browser
- Screenshot SHA-256: `ae71f7ea42b340fdac3b20ba156e069044548ec9b871658a314f0b093eb31d4d`

## Visual result

Pass:

- Roboto text is readable: `Workbench Studio`, `Build`, `Research`, `Ops`, `Ready`, `Focus`, `Gaps`.
- Material Icons render as six distinct launcher, overview, files, browser, terminal, and settings symbols.
- Full tile titles `SETTINGS`, `TERMINAL`, and `BROWSER` replace three-letter abbreviations.
- Inspector labels and symbols read `Inspect`, `Tiles`, `Focus`, `Gap`, `Live`.

Residuals:

- Files returned `PEER_CLOSED` during PresentView and is not visible. This remains the separate open Files gate (`8vg0.3`); this shot is not a four-app claim.
- Tile titles still use the large bitmap renderer, not the new Roboto surface.
- A thin clipped/ghost title fragment remains immediately below the top strip.
- Rail icons are recognizable but do not yet have hover labels or tooltips.

Verdict: the shell is materially easier to read and navigate, but the screenshot is a three-tile readability proof, not production completion.

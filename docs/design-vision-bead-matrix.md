# Instrument Studio design-vision bead matrix

Source of truth: `design/sketches/01-instrument-studio/` plus variants 02/03.
Live proof: `design/screenshots/13-emulator-parity-live.png` (HEAD `f7b167b`).
Last lab shot after Browser work: 1-tile only — 4-app restore is required before claiming tile chrome.

## Round 1 — visual identification + information architecture

Every design region must have a named owner and a bead. Closed beads stay closed.

| Design element | IA role | Live now | Bead | Gate |
|---|---|---|---|---|
| Brand wordmark Workbench Studio | Identity | `STUDIO` 4px bitmap | `8vg0.9` | True font; OCR already closed `twge` |
| Workspace pills Build/Research/Ops/+ | Context switcher | Painted `BLD RSH OPS` | `8vg0.8` after `gvjg` | Visual first; switch later |
| Status chips session/focus/gaps | Health | `OK FOC GAP` | done in density/`twge` | Keep |
| Launcher rail 6 icons | App IA | Multi-rect glyphs | `8vg0.5` | Recognizable icons |
| 2x2 tiled stage | Primary work | Intact on 13; 1-tile on last lab | foundation `9cow` | Restore 4-app before UI claims |
| Tile title bars + app dots + chips | App identity | Missing (gray slabs) | `8vg0.1` | Visual ID first |
| Tile 14px radius + cyan glow | Focus language | Cyan square ring only | `8vg0.1` residual | Honest Flatland limit |
| Settings sidebar + cards/toggles | Settings IA | Stacked buttons | `8vg0.2` | Visual then live WM controls |
| Files grid + crumbs + Grid/List | Files IA | Gray list | `8vg0.3` | Visual then ops |
| Browser toolbar + URL + page card | Browser IA | Clips `example.co` | `8vg0.6` | In-tile URL + title |
| Terminal prompt density + chip | Terminal IA | Empty `localhost:/#` | `8vg0.4` | Prompt + one output line |
| Inspector command hints + live copy | System status | TILE/FOC/GAP/LIVE meters | `8vg0.7` | One live Inspect value + hints |
| Click-to-focus tiles | Selection | Confirmed cyan focus | `9cow` | Keep |
| Live WM settings slider/toggles | Control | Not in Settings UI | `v00n` | After Settings cards |
| Command palette Ctrl-K | Expert path (v2) | Absent | `8vg0.10` after `904w` | After shortcuts |
| Spatial overview | Orientation (v3) | Absent | `zszv` after `gvjg` | After split-tree |
| Global shortcuts | Keyboard IA | Absent | `904w` | Native input policy |
| Narrow-tile stack | Responsive IA | Settings/Files stack | `ins3` | Browser clip shared with `8vg0.6` |
| Linux in Terminal | Function | Alpine/Starnix wired | `7el5` closed | Keep |
| Public package + CI | Release IA | `f7b167b` green | `g6rn` closed | Keep |

## Round 2 — function + go-forward order

Rules:
1. Do not reopen closed foundation/chrome/density/icon/Linux/label beads.
2. Overlay edit is not live. Merkle + vision required.
3. Visual identification before richer function on the same surface.
4. Variant 2/3 stay behind their platform beads (`904w`, `gvjg`).

Execution order:
1. Restore 4-app stage (lab hygiene, not a new bead).
2. `8vg0.1` tile title bars / identity chips (visual ID).
3. `8vg0.6` Browser URL in-tile (function + visual).
4. `8vg0.2` Settings sidebar/cards (IA then `v00n` controls).
5. `8vg0.3` Files grid.
6. `8vg0.4` Terminal density.
7. `8vg0.7` inspector hints + live Inspect.
8. `8vg0.5` / `8vg0.9` true icons and fonts.
9. `904w` → `8vg0.10` palette.
10. `gvjg` → `8vg0.8` pill switching → `zszv` overview.

R2 check: every row has a bead or a closed proof. Gaps filled this turn: inspector `8vg0.7`, pill function `8vg0.8`, true fonts `8vg0.9`, palette `8vg0.10`.

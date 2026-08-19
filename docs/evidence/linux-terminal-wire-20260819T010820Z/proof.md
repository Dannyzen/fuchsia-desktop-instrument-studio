# Linux terminal wiring proof

Date: 2026-08-19T01:08Z

## Wiring

1. Session child `linux_container` = Alpine Starnix container
2. Offer `fuchsia.starnix.container.Controller` to `#terminal_elements`
3. Terminal args: `/pkg/bin/linux_console_bridge /bin/bash -l`
4. Bridge uses `Controller.SpawnConsole`

## Live checks

- `linux_container` present under session, runner `starnix`, exposes Controller
- terminal tile Running
- `ffx component doctor` on terminal:
  - `svc/fuchsia.starnix.container.Controller` Success
  - PTY + process launcher Success
- Independent agent path:
  - `Linux localhost 6.6.30-starnix ...`
  - `NAME="Alpine Linux"`
  - `/bin/bash`
  - `LINUX_AGENT_OK`

## Residual

Prompt OCR / keystroke proof inside the tile is not yet gated. Capability path is green.

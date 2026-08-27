# Linux terminal wiring

Updated: 2026-08-27

The Workbench Terminal launches the in-tree Fuchsia terminal and bridges its console to Alpine/Linux through Starnix:

```text
/pkg/bin/terminal /pkg/bin/linux_console_bridge /bin/bash -l
```

`linux_console_bridge` connects to `fuchsia.starnix.container.Controller` from the session child `linux_container`, calls `SpawnConsole`, installs the bounded Fuchsia Studio help assets into writable Alpine `/usr/local`, and enters interactive Bash.

## Built-in help

Inside the Terminal:

```sh
fuchsia-studio help
fuchsia-studio health
fuchsia-studio man
health.sh
man fuchsia-studio
```

The help page explains the visible Workbench screen language. The health command checks the Linux CLI/runtime boundary and points desktop state to the Inspect surface rather than inventing WM state inside Linux.

## Authority boundary

- The exact Terminal URL runs in `terminal_elements`.
- Only that collection receives the Starnix Controller route.
- The keyboard acceptance driver remains a fixed one-shot child. It types only `fuchsia-studio help\n` and is not a general input service.
- Generic elements do not inherit Terminal process or Controller authority.

## Live proof

- Latest: `docs/evidence/instrument-studio-help-20260827T062745Z/`
- Original Linux wiring: `docs/evidence/linux-terminal-wire-20260819T010820Z/`

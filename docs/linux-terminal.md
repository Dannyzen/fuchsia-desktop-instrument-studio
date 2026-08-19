# Linux terminal wiring

Updated: 20260819T010224Z

The Instrument Studio / Workbench terminal tile now launches:

```
/pkg/bin/terminal /pkg/bin/linux_console_bridge /bin/bash -l
```

`linux_console_bridge` connects to `fuchsia.starnix.container.Controller`
exposed by the session child `linux_container`
(`fuchsia-pkg://fuchsia.com/alpine#meta/alpine_container.cm`) and calls
`SpawnConsole` for Alpine bash.

Fallback remains packaged zxsh at `/pkg/bin/sh` if bridge/controller fails
(terminal will error rather than silently using zxsh unless args are changed).

Prove:

```bash
# on device/session
ffx component show core/session-manager/session:session/linux_container
ffx session add --name linux-term fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm
```

## Live proof (20260819T010820Z)

See `docs/evidence/linux-terminal-wire-20260819T010820Z/`.

# Instrument Studio built-in help proof

This receipt binds the Live 22 screenshot to implementation commit `ac5f93b90230ca35c45328925614631e4e931b02`.

## Proven

- Real Workbench slim FEMU pixels, not a web mockup
- `fuchsia-studio help` visibly rendered inside the Alpine/Starnix Terminal
- `fuchsia-studio health`, `fuchsia-studio man`, `health.sh`, and `man fuchsia-studio` covered by the host command contract
- Roboto headers for Terminal, Browser, and Settings
- No duplicate top Focus/Gap status chips
- Inspect health `OK`, exactly three visible windows, and Terminal as confirmed input target
- `fuchsia.starnix.container.Controller` route `Success`
- Built and live Terminal and tiling WM merkles matched exactly

## Honest limit

This proves readable typography and a working narrative help surface. It does not prove production readiness. Files is absent, rail icons still lack in-place help, Inspect bars do not show values, and Browser remains prototype UI.

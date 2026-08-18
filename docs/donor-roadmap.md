# Native Fuchsia Tiling WM donor roadmap

## Thesis

Keep Workbench, Flatland, Scenic focus, and Fuchsia component policy as the runtime authority. Borrow interaction and state ideas from mature Rust WMs, but reimplement them against native Fuchsia capabilities. Do not import Linux compositor machinery.

## Phase delivered

- Pure `WindowPolicy` with validated geometry, smart gaps, safe empty cycle, stable identity, removal reconciliation, reorder identity, and four-direction navigation tests.
- Stable tile IDs from `element_manager/name` annotations, with deterministic suffixes for collisions.
- Real `fuchsia.session.window.Manager.Focus`, confirmed through Scenic focus-chain observation.
- 12 logical-pixel outer/inter-tile gaps and a 3 logical-pixel active ring rendered as Flatland filled rectangles.
- Single-tile smart gaps preserve exact 720x1200 fullscreen compatibility.
- Lifecycle proof for four attached views, remove to three, relaunch to four, and no runtime crash marker.
- Restart-stable structured config for gap, border, and wrap defaults.

## Donor decisions

| Donor | Adopt | Defer or reject | Why |
|---|---|---|---|
| COSMIC | Split-tree hierarchy, stack nodes, drop zones, output-bound workspaces, delayed focus-follows-pointer, visible insertion feedback | Smithay, Wayland/Xwayland, libinput, desktop process assumptions | The UX and state policy transfer. The Linux compositor substrate does not. |
| niri | Invariant-first state, predictable focus/move grammar, overview as a projection, immediate semantic commit before animation, reduced-motion behavior | Scrollable columns as the first layout engine | Its interaction discipline is excellent, but a split tree is more familiar for the first general Fuchsia desktop. |
| Penrose | Pure/testable state transitions, zipper-like layout operations, independent geometry tests | X11 client discovery and EWMH | The data-structure discipline transfers cleanly. X11 authority does not exist on Flatland. |
| LeftWM | Small serializable state surface and explicit config validation | Static tag-stack UX as the final desktop model | Its compact control surface is a good settings and query precedent. |
| komorebi | Typed command/query separation, subscriptions, ordered window rules, restart reconciliation concepts | HWND re-enumeration, named pipes, border helper processes, Win32 hooks | Typed policy and reconciliation transfer. Win32 mechanisms do not. |

## Ordered next phases

1. `beads-work-ledger-904w`: add a production-safe session input-policy surface for global WM chords. The removed `fuchsia.ui.shortcut` protocol and one-listener-per-ViewRef `input3` rule make per-window interception unsafe.
2. `beads-work-ledger-ins3`: make Settings and Browser responsive at narrow tile widths, then define minimum-size fallback or stack behavior.
3. `beads-work-ledger-v00n`: expose a versioned live WM settings query/set/watch service with atomic persistence and last-valid retention.
4. `beads-work-ledger-gvjg`: replace the flat grid with `Split | Stack | Leaf | Placeholder`, output-bound named workspaces, floating/transient rules, and drop targets.
5. `beads-work-ledger-zszv`: add a semantic overview, Fuchsia-native accessibility announcements, insertion hints, reduced-motion controls, and optional spring interpolation.

## Explicit non-goals

- No Wayland, X11, Xwayland, Smithay, wlroots, D-Bus, systemd, `/proc`, UNIX socket IPC, Win32 hooks, or external border helpers.
- No `fuchsia.ui.test.input.Registry` in production.
- No second overview state model.
- No animation that delays final semantic focus or input routing.
- No persistence of Flatland handles. Persist versioned policy and reconcile fresh presented views.

## Primary sources

- COSMIC config: https://github.com/pop-os/cosmic-comp/blob/8806436f81a82c38e7d18e1ec2ff1edc201faacc/cosmic-comp-config/src/lib.rs
- COSMIC tiling policy: https://github.com/pop-os/cosmic-comp/blob/8806436f81a82c38e7d18e1ec2ff1edc201faacc/src/shell/layout/tiling/mod.rs
- COSMIC actions: https://github.com/pop-os/cosmic-comp/blob/8806436f81a82c38e7d18e1ec2ff1edc201faacc/src/input/actions.rs
- niri design principles: https://github.com/niri-wm/niri/blob/606284464d4a99bb35710fee68192bc71085ee7c/docs/wiki/Development%3A-Design-Principles.md
- niri floating windows: https://github.com/niri-wm/niri/blob/606284464d4a99bb35710fee68192bc71085ee7c/docs/wiki/Floating-Windows.md
- niri overview: https://github.com/niri-wm/niri/blob/606284464d4a99bb35710fee68192bc71085ee7c/docs/wiki/Overview.md
- niri IPC: https://github.com/niri-wm/niri/blob/606284464d4a99bb35710fee68192bc71085ee7c/docs/wiki/IPC.md
- niri accessibility: https://github.com/niri-wm/niri/blob/606284464d4a99bb35710fee68192bc71085ee7c/docs/wiki/Accessibility.md
- LeftWM state surface: https://github.com/leftwm/leftwm/blob/ff1c08524a9ad2d62eaa5433842c9ac0f22eac0e/leftwm-core/src/utils/state_socket.rs
- Penrose data structures: https://github.com/sminez/penrose/blob/5ab890bc98a06c450bfec40c405829c3cf68982c/docs/src/overview/data-structures.md
- Penrose pure stack: https://github.com/sminez/penrose/blob/5ab890bc98a06c450bfec40c405829c3cf68982c/src/pure/stack.rs
- komorebi design: https://github.com/LGUG2Z/komorebi/blob/3f3fac8b65f83dcb0e9a78a0214a5497f2a6fa86/docs/design.md
- komorebi socket schema: https://github.com/LGUG2Z/komorebi/blob/3f3fac8b65f83dcb0e9a78a0214a5497f2a6fa86/docs/cli/socket-schema.md

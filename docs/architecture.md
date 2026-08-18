# Fuchsia desktop MVP architecture

## Verdict

Build a Fuchsia-native Rust desktop with COSMIC-level usability. The compositor, session, focus model, app lifecycle, and desktop chrome use Fuchsia protocols. Chromium WebEngine is an isolated page-rendering child, not the desktop or browser UI.

## Four-app product boundary

The first usable release contains Browser, Terminal, Files, and Settings. Each application must render real content, accept focus and input, survive close/relaunch, and carry a reproducible runtime acceptance test. Launcher cards and static mock surfaces do not count.

The sequence is risk ordered:

1. Browser proves cross-process Flatland composition, networking, dynamic code, and the heaviest package closure.
2. Terminal proves keyboard routing, PTY lifecycle, resize, and scrollback.
3. Files proves bounded storage access and destructive-operation UX.
4. Settings proves shared state, persistence, and capability ownership.

## Proven runtime baseline

- Core SDK: `33.20260816.0.1`
- Fuchsia source: `7f75b7f6ffdacf5a818dd8d207263edd45126ddd`
- Emulator: SDK-embedded QEMU `11.0.2`
- Products booted: `minimal.x64`, `workbench_eng.x64`
- Acceleration: KVM, observed as `-enable-kvm` and `-cpu host`
- Networking: emulator user networking, no published container or host ports
- Graphics stack: Scenic with Vulkan renderer and Flatland
- Product shell: `session_manager`, `workbench_session`, and tiling window manager
- Native Rust rendering: passed
- Native Rust browser plus Chromium child viewport: passed
- Browser pointer, focus, keyboard, visible startup/live typed URL text, two persistent tabs with independent frame histories, typed URL, back, forward, and reload contracts: 13/13 passed
- Product-session Browser route: passed with ten consecutive running checks under `browser_elements`
- External HTTPS rendering: Example Domain title, body copy, and link visibly rendered; screenshot pixel contract passed

## Browser decision

Full desktop Chrome was removed from Fuchsia. The maintained Chromium surface is WebEngine, which provides page rendering but no address bar, tabs, bookmarks, downloads, extensions, or browser window policy. Rust owns those product surfaces.

The browser is implemented at `source/fuchsia/src/fuchsia-desktop/browser/`. It creates a Flatland root view, draws a 72-pixel native toolbar, embeds a WebEngine Frame below it, exposes `fuchsia.ui.app.ViewProvider`, and owns pointer hit regions, focus, keyboard editing state, navigation actions, and native text. The address value is a transparent CPU-backed sysmem image rendered with Carnelian's Forma glyph path and composited by Flatland above the address rectangle. Two buffers alternate; the replaced image is reused only after its Flatland release fence signals. Each tab retains its Frame, NavigationController, Flatland viewport, ChildViewWatcher, and ViewRef. Switching removes the inactive viewport transform and adds the active transform in one presentation without `ReleaseViewport`; independent-history acceptance proves frame state survives. The parent hit region covers only the toolbar; the active WebEngine child receives page-region input.

### Vulkan boundary

Do not request `fuchsia.web.ContextFeatureFlags::VULKAN` under FEMU for the browser path.

Evidence:

- WebEngine Shell forced Vulkan and produced a uniform initial frame with Scenic buffer-collection failures.
- Fuchsia's upstream WebEngine pixel suite currently instantiates its cases with `use_vulkan=false`; source comments say Vulkan cases are disabled due to flakiness.
- The unchanged upstream software pixel case passed 1/1.
- The Rust browser test then rendered exactly `931,840` page pixels and `92,160` toolbar pixels at 1280 by 800.

This does not disable Vulkan globally. Scenic still uses Vulkan to compose the desktop. Only Chromium's WebEngine context falls back to its own SwiftShader path.

### Cold-start presentation

Workbench's presenter allows roughly 15 seconds for a child view to attach. The first uncached WebEngine launch took roughly 50 seconds and failed presentation before Chromium started. A cached relaunch attached in about 0.13 seconds.

Production guardrail: pre-resolve or prewarm WebEngine before presenting the browser window, and keep browser failure isolated from shell startup.

## Capability boundary

The Rust browser UI receives only the capabilities it must pass to or use with WebEngine:

- `fuchsia.web.ContextProvider`
- `fuchsia.ui.input3.Keyboard`
- Flatland, Allocator, TouchSource, and Focuser
- network interface, DNS, and socket protocols
- fonts, internationalization, accessibility semantics, process launcher, VMEX, sysmem, scheduler roles, and memory pressure required by WebEngine

The Context is created with `NETWORK`, not `VULKAN`. The shell itself should not gain browser network, VMEX, or storage privileges.

The deterministic Browser suite remains in `/core/testing/system-tests`. The assembled Workbench product separately caches `web_engine`, runs `web_engine#meta/context_provider.cm` as a lazy child of `workbench_session`, and offers its provider dependencies only to that child. Element Manager maps the exact `fuchsia_browser` URL to `browser_elements`; common UI protocols go to both collections, while ContextProvider, DNS/socket, process launcher, and VMEX go only to `browser_elements`. A Workbench product-policy fragment authorizes `fuchsia.kernel.VmexResource` only for `browser_elements:**`. The general `elements` collection does not receive the Browser-only additions. Workbench enables `small-open-fonts-collection` and places its asset provider in `base_packages`; cache classification is insufficient because the static font child must resolve before any development repository is registered.

## Rust UI choice

Direct Flatland/FIDL is the durable ownership boundary. The browser reuses Carnelian's supported `FontFace`, `Text`, Forma `Context`, and `Composition` primitives only for glyph rasterization into browser-owned sysmem buffers; it does not adopt Carnelian's app or view lifecycle. Slint, egui, iced, and winit do not currently advertise a maintained Fuchsia backend; porting one would add platform work before product value.

## App architecture

### Browser

Rust root view, toolbar, navigation state, tabs, downloads/bookmarks persistence, and a WebEngine child viewport. WebEngine crash or package-resolution failure must not stop the desktop.

### Terminal

Use Fuchsia's in-tree Rust terminal stack (`src/ui/bin/terminal` plus `src/lib/ui/terminal`) as the implementation base. Under the pinned product it builds with Clippy and passes 57/57 attempted component tests, with one test skipped. Those tests cover keyboard mapping, PTY lifecycle, resize, rendering state, and scroll behavior.

The stock `terminal.cml` is not an acceptable product manifest: it requests broad Bluetooth, update, virtualization, package, power, network, and root realm capabilities. A Workbench dynamic-element smoke test failed closed because Workbench does not offer `fuchsia.hardware.pty.Device`; the terminal then failed to create its server-PTY file descriptor and Carnelian panicked while unwrapping the render error. The failed element was removed.

Accepted product rule: Element Manager maps only `fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm` into the dedicated `terminal_elements` collection. That collection receives PTY, process launch, sysmem, Flatland, keyboard/IME, tracing, logging, and inspect capabilities. The bounded shell is `/pkg/bin/sh`, packaged with the Terminal rather than reached through a broad executable directory. Generic `elements` receive neither PTY nor process launch; a live Flatland-Rainbow control element verifies the negative boundary.

Bidirectional acceptance uses a fixed one-shot Workbench child with only `fuchsia.ui.test.input.Registry`. It types `echo terminalok\n`; the screenshot visibly shows the typed command, `terminalok` output, and the returned `$` prompt. The input driver is not a general text-injection service and grants no new authority to Terminal. Accepted screenshot SHA-256: `ff46b7fc4db18a6694210384d93709517579f266e5679485d14f1a577ad50e1d`.

### Files

Rust file browser rooted in component-owned `/data`. Package files remain read-only. Create, rename, move, copy, text open, and nonrecursive delete are covered by core/controller tests; delete requires a visible two-step confirmation. Canonicalization rejects parent traversal, absolute paths, and symlink escapes. This is accepted for the single-component MVP, not as a hostile multi-process broker because a same-component TOCTOU race still requires handle-relative directory APIs.

Element Manager maps only the exact Files URL to `files_elements`. Files receives storage, graphics/sysmem, logging, tracing, and Inspect, but no root/system filesystem, PTY, process launcher, WebEngine, network, package administration, or input injection. A generic `elements` control cannot read Files data. The input driver remains an isolated fixed child. Core/controller tests pass 10/10, touch geometry passes 3/3, and the accepted product screenshot SHA-256 is `4ad22d0f4518f39acc05365d3559aafae52efa21df050e17f12e95baad314ea1`.

### Settings

Rust Settings exposes only controls with explicit owners. Theme is app-owned and atomically persisted in `/data`; Celsius/Fahrenheit is system-owned through `fuchsia.settings.Intl`; build and product information is read-only through `fuchsia.buildinfo.Provider` and `fuchsia.hwinfo.Product`. Brightness, Accessibility, Keyboard, and Network are hidden because this product does not prove their writable owner contracts.

Element Manager maps the exact production and test-only failure URLs to `settings_elements`. Production receives `/data`, Intl, build/product info, graphics/sysmem, logging, tracing, and Inspect, but no PTY, process launcher, WebEngine, network, or input injection. A fixed driver proves Dark, High Contrast, Celsius, and Fahrenheit. Component removal and recreation restores High Contrast and Fahrenheit. A separate non-product failure package injects an Intl write failure and visibly retains Fahrenheit. Core tests pass 7/7, touch geometry 3/3, and deterministic product/failure screenshots have SHA-256 `916dddd51cec3c994a5cd5470ffd18c27a6860de5ab97eff73de95c8543a269a` and `f840648d038ec91e07587f0a19711463aa26712005c926ddcff5cc23e5441c6f`.

## COSMIC reuse boundary

COSMIC defines the experience benchmark, not the platform contract. Reuse or clean-room adapt its panel hierarchy, spacing scale, accent vocabulary, workspace model, app grouping, keyboard policy, and layout mathematics. Do not import Smithay, Wayland/Xwayland, DRM/GBM/EGL, libinput, udev, libseat, DBus, systemd/logind, X11, or Linux process/session semantics.

The accepted native panel spike uses Flatland directly and requests no PTY, process launcher, WebEngine, network, or input-injection authority. The current `libcosmic/cosmic-theme` crate is not vendored because its missing dependency closure costs more than the token model provides. Full evidence and exact pins live in `spikes/001-cosmic-portability/README.md`.

## Product assembly path

1. Keep the accepted `workbench_eng.x64` product unchanged as the rapid component/UI baseline.
2. Browser, Terminal, Files, and Settings each have exact URL routing and per-app capability manifests.
3. All four remain Running concurrently through five checks on FEMU/SwiftShader with a negative cross-capability matrix.
4. Baseline measurement reports 157 embedded repository packages, 675 blobs, 333,007,242 uncompressed bytes, 126,402,298 delivery bytes, and a 138,121,268-byte FVM; 111 bootfs packages and 64 on-demand development packages are reported separately.
5. `workbench_slim.x64` is a separate ENG-compatible product bundle. It embeds Browser, Terminal, Files, Settings, WebEngine, fonts, and Workbench session packages; removes Starnix, battery, WLAN/Thread/TUN and explicit ENG audio/display/network tools; and leaves the accepted Workbench bundle unchanged.
6. Final assembled-system comparison removes 20 packages and adds the three previously external application packages, for a net reduction of 17 packages, 48 unique FXFS blobs, and 7,405,568 bytes of actual `used_space_in_blobfs`. FVM shrinks by 7,307,264 bytes. The strict verifier stops the development repository before boot, then proves external Browser HTTPS, Terminal PTY input, the Files bounded-storage journey, Settings persistence, exact routes, and concurrent four-app liveness from embedded cache.
7. This pinned graph exposes only ENG platform artifacts while building the accepted Workbench graph, so the isolated slim bundle intentionally retains ENG bootfs and synthetic-input support. USERDEBUG platform rebuild, removal of acceptance drivers, audio-route completion, accessibility, recovery, rollback execution, and CI remain separate gates. Rollback is selecting the untouched `workbench_eng.x64` product bundle.

## Reproducibility and proof

- Browser verifier: `scripts/verify-browser.sh`
- Product-session and external-page verifier: `scripts/verify-browser-product-session.sh`
- External screenshot validator: `scripts/assert-example-domain-screenshot.py`
- Terminal product-session and capability verifier: `scripts/verify-terminal-product-session.sh`
- Terminal screenshot-delta validator: `scripts/assert-terminal-screenshot.py`
- Files core/UI/product verifiers: `scripts/verify-files-core.sh`, `scripts/verify-files-ui.sh`, `scripts/verify-files-product-session.sh`
- Settings core/UI/product verifiers: `scripts/verify-settings-core.sh`, `scripts/verify-settings-ui.sh`, `scripts/verify-settings-product-session.sh`
- Concurrent four-app lifecycle/capability verifier: `scripts/verify-four-app-session.sh`
- Baseline package/blob measurement: `scripts/measure-workbench-closure.sh`
- Slim package/blob measurement: `scripts/measure-slim-closure.sh`
- Final assembled-system/TUF comparison: `scripts/compare-assembled-products.py`
- Self-contained slim runtime verifier: `scripts/verify-slim-product.sh`
- Machine-readable baseline: `artifacts/workbench-closure-baseline.json`
- Machine-readable slim closure: `artifacts/workbench-closure-slim.json`
- Machine-readable assembled comparison: `artifacts/workbench-assembled-comparison.json`
- Accepted Terminal screenshot: `artifacts/fuchsia-terminal-product.png`
- Browser build logs: `artifacts/build-fuchsia-browser-*.log`
- Browser test logs: `artifacts/run-fuchsia-browser-*.log`
- Structured output: `artifacts/fuchsia-browser-test-*`
- Stable baseline screenshot: `artifacts/fuchsia-browser.png`
- Stable active-control screenshot: `artifacts/fuchsia-browser-toolbar-active.png`
- Stable typed-navigation screenshot: `artifacts/fuchsia-browser-address-loaded.png`
- Product external-page screenshot: `artifacts/fuchsia-browser-product-external.png`
- Product external-page SHA-256: `500f65593da19d1fe4743e4527357da184550882a266710962b730d321b6f74e`
- Browser acceptance count: 13/13 tests
- Baseline SHA-256: `1a4f6a0e9a8cf5883f5917ed5a7a2221b1981ca192e2a7b1433c83738ac45db1`
- Active-control SHA-256: `32e01b98ad32f39f61094ec99b4393fb57614ff3824a4a79f2ddf5a60b6aded1`

## Primary sources

- https://fuchsia.googlesource.com/fuchsia/+/refs/heads/main/docs/development/tools/ffx/workflows/start-the-fuchsia-emulator.md
- https://fuchsia.googlesource.com/fuchsia/+/refs/heads/main/docs/contribute/governance/rfcs/0166_ui_stack.md
- https://fuchsia.googlesource.com/fuchsia/+/refs/heads/main/docs/contribute/governance/rfcs/0189_window_management.md
- https://fuchsia.googlesource.com/fuchsia/+/refs/heads/main/src/ui/tests/integration_graphics_tests/web-pixel-tests/
- https://fuchsia.googlesource.com/fuchsia/+/refs/heads/main/src/chromium/config/web_context_provider.core_shard.cml
- https://chromium.googlesource.com/chromium/src/+/HEAD/fuchsia_web/README.md
- https://chromium.googlesource.com/chromium/src/+/HEAD/fuchsia_web/shell/web_engine_shell.cc
- https://chromium.googlesource.com/chromium/src/+/HEAD/fuchsia_web/shell/present_frame.cc

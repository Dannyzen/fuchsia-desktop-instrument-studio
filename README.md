# Fuchsia Desktop Instrument Studio

Public package for a **native Fuchsia** desktop direction: Workbench + Flatland + interactive tiling window manager + four system apps, with Instrument Studio UI design sketches.

This repository does **not** vendor the multi-gigabyte Fuchsia tree, SDK, emulator images, or runtime state. It publishes the overlays, scripts, design artifacts, and instructions needed to rebuild on top of public Fuchsia sources.

## Security boundary

- No private keys, tokens, `.env` secrets, or `authorized_keys` material are included.
- `state/`, `sdk/`, `source/`, `artifacts/`, and caches are gitignored and must stay local.
- CI runs a fail-closed secret scan on every push.

If you find credential-like material, open an issue and rotate immediately.

## What you get

- `overlays/fuchsia/**`: native desktop overlays
  - interactive `tiling_wm` with confirmed-focus policy
  - Browser / Files / Settings / Terminal / panel spike components
  - Workbench session product wiring
- `scripts/**`: bootstrap, overlay apply, verification helpers
- `design/sketches/**`: interactive HTML directions for richer UI
- `design/screenshots/current-femu-run.png`: the screenshot from the documented FEMU run
- `design/screenshots/**`: older captures kept on disk, not embedded below
- `docs/donor-roadmap.md`: native-only roadmap adapted from mature Rust WMs
- GitHub Actions CI for public-readiness gates

## Pinned baseline

See `versions.env`:

- Fuchsia source: `85d1818a43cb152bf09a0a58ac571012f6ead5e7`
- Product target: `//products/workbench:workbench_slim.x64`

## Design direction

We are building **Instrument Studio** first:

1. shared native desktop chrome
2. confirmed-focus active window treatment
3. live WM settings surface
4. command palette and spatial overview as progressive layers

### Screenshots

The image below is the direct headless FEMU capture from the verified three-app run on 2026-09-30. It is the only current run screenshot embedded here.

![Current FEMU run](design/screenshots/current-femu-run.png)

The pixels show Browser with its local documentation example, Terminal with a Linux prompt and `fuchsia-studio` help text, and Settings with Appearance and Temperature controls. The Browser example is local content; this screenshot does not prove external network access. The UI displays `2026-09-29`; this on-screen value differs from the capture date and is not used as the screenshot timestamp. Files was not launched or shown.

Inspect for the same run: `Health.status=OK`, `tile_count=3`, order `instrument-studio-browser,instrument-studio-terminal,instrument-studio-settings`. The embedded PNG is pixel-identical to the guest capture.

The previous capture is preserved as `design/screenshots/previous-femu-run-2026-09-29.png`; it is not embedded because its Files header disagreed with its Inspect order. Older evidence remains historical and does not describe this run.

Interactive sketches live under `design/sketches/`.

## Run the desktop

This repository is an overlay package. Cloning it does not boot a desktop. There is no emulator image, SDK, or product bundle in git.

The system this package produces is **Workbench slim on FEMU**. The commands below are the ones the live verifiers actually use. `scripts/start-emulator.sh` is not that path: it only starts QEMU `workbench_eng.x64` or `minimal.x64`.

### What has to exist first

- Linux x86_64 host with KVM (`/dev/kvm`) and rootless Podman
- A lab workspace that already has the SDK, Fuchsia source at the pin in `versions.env`, overlays applied, and a built slim bundle
- Container name `fuchsia-desktop-mvp`, isolate dir `/workspace/state/ffx`

On the lab used to develop this package, that workspace is `/srv/bigs-runtime/workspaces/projects/fuchsia-desktop-mvp`. The public clone of this repo is not a substitute for that lab.

Built bundle the guest actually boots:

```text
/workspace/source/fuchsia/out/workbench_eng.x64-release/obj/products/workbench/workbench_slim.x64/product_bundle
```

If that directory is missing, do the Local rebuild steps below, then come back here.

### 1. Start the tool container if it is not running

From the lab workspace, not from a docs-only clone:

```bash
podman compose up -d
podman ps --filter name=fuchsia-desktop-mvp --format '{{.Names}} {{.Status}}'
```

Expected: `fuchsia-desktop-mvp` is `Up`.

Helper used in every later command:

```bash
ffx() {
  podman exec -e FUCHSIA_NODENAME=fuchsia-workbench-femu fuchsia-desktop-mvp     /workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx "$@"
}
```

### 2. Boot FEMU, or reuse it if it is already running

```bash
ffx emu list
```

If the list shows `[running] fuchsia-workbench-femu`, do not start another copy.

If it is not running:

```bash
ffx emu start   --engine femu --gpu swiftshader_indirect --accel hyper --headless   --net user --smp 8 --name fuchsia-workbench-femu --startup-timeout 180   --log /workspace/artifacts/fuchsia-workbench-femu.log   /workspace/source/fuchsia/out/workbench_eng.x64-release/obj/products/workbench/workbench_slim.x64/product_bundle
```

The guest is headless. There is no local window and no VNC in this path. You look at it with `ffx target screenshot`.

### 3. Prove the guest is reachable

```bash
ffx target wait -t 180
ffx emu list
ffx target list
ffx target ssh "echo FUCHSIA_GUEST_OK"
```

Expected:

- emulator line `[running] fuchsia-workbench-femu`
- target `fuchsia-workbench-femu` in Product state with RCS `Y`
- guest prints `FUCHSIA_GUEST_OK`

### 4. Put the desktop on the stage without duplicates

A fresh slim boot can be an empty tiling WM (`tile_count=0`). A reused guest can already have the verified three-app stage. Read Inspect first so rerunning this runbook does not add duplicate windows. This procedure covers exactly three visible apps; a count of 4 is outside this proof:

```bash
wm_tile_count() {
  ffx --machine json inspect show core/session-manager/session:session/tiling_wm |
    python3 -c 'import json, sys

def find(value):
    if isinstance(value, dict):
        if "tile_count" in value:
            return value["tile_count"]
        for child in value.values():
            result = find(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = find(child)
            if result is not None:
                return result
    return None

result = find(json.load(sys.stdin))
if not isinstance(result, int):
    raise SystemExit("tiling_wm tile_count is unavailable")
print(result)'
}

tile_count="$(wm_tile_count)"
case "$tile_count" in
  0)
    ffx session add --name instrument-studio-settings fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm
    ffx session add --name instrument-studio-terminal fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm
    ffx session add --name instrument-studio-browser fuchsia-pkg://fuchsia.com/fuchsia_browser#meta/fuchsia_browser.cm
    ;;
  3)
    echo "three-app stage already present; not adding duplicates"
    ;;
  *)
    echo "unexpected existing tile_count=$tile_count; stop instead of creating a mixed or duplicate stage" >&2
    exit 1
    ;;
esac

stable_three=0
for attempt in $(seq 1 30); do
  tile_count="$(wm_tile_count)"
  if [ "$tile_count" -eq 3 ]; then
    stable_three=$((stable_three + 1))
  else
    stable_three=0
  fi
  if [ "$stable_three" -ge 3 ]; then
    break
  fi
  sleep 2
done

wm_tile_order() {
  ffx --machine json inspect show core/session-manager/session:session/tiling_wm |
    python3 -c 'import json, sys

def find(value):
    if isinstance(value, dict):
        if "order" in value and isinstance(value["order"], str):
            return value["order"]
        for child in value.values():
            result = find(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = find(child)
            if result is not None:
                return result
    return None

result = find(json.load(sys.stdin))
if not isinstance(result, str):
    raise SystemExit("tiling_wm order is unavailable")
print(result)'
}

order="$(wm_tile_order)"
test "$tile_count" -eq 3
test "$stable_three" -ge 3
test "$order" = "instrument-studio-browser,instrument-studio-terminal,instrument-studio-settings"
echo "tile_count=3 order=$order"
```

Check the complete window-manager state:

```bash
ffx --machine json inspect show core/session-manager/session:session/tiling_wm
```

Expected from the 2026-09-30 run: `tiling_wm.tile_count` is 3, `fuchsia.inspect.Health.status` is `OK`, and order is `instrument-studio-browser,instrument-studio-terminal,instrument-studio-settings`. Files was not launched and is not represented in this screenshot. A component reporting `Running` is not a tile.
The wait requires three consecutive polls at count 3 and the exact order before it proceeds to Inspect or screenshot. Counts 0, 1, 2, or 4 fail this three-app procedure.

Capture pixels. `-d` requires an existing directory inside the tool container, so create its host-mounted counterpart first:

```bash
mkdir -p artifacts/instrument-studio-run
ffx target screenshot -d /workspace/artifacts/instrument-studio-run --format png
```

FFX writes `screenshot.png` in the lab `artifacts/instrument-studio-run/` directory on the host. The current `design/screenshots/current-femu-run.png` is a pixel-identical copy of the verified three-app capture.

### 5. Use it as an end user inside Terminal

The Terminal is Alpine/Linux through Starnix. After Terminal has focus:

```sh
fuchsia-studio help
fuchsia-studio health
fuchsia-studio man
```

That is the in-guest help surface. Desktop health still comes from Inspect, not from those Linux commands.

### Stop

```bash
ffx emu stop fuchsia-workbench-femu
```

Do not run that if another session is using the same guest.

## Local rebuild

### 1. Get public Fuchsia source at the pin

```bash
./scripts/fetch-fuchsia-source.sh ./source/fuchsia
```

Or follow upstream docs and check out the commit in `versions.env`.

### 2. Apply overlays

```bash
./scripts/apply-overlays.sh ./source/fuchsia
```

### 3. Configure and build Workbench slim

Inside your Fuchsia tree / container workflow:

```bash
fx set workbench_eng.x64 --release
fx build //products/workbench:workbench_slim.x64
```

Exact containerized flow used during development is documented in `docs/architecture.md` and the helper scripts under `scripts/`.

### 4. Optional runtime verification

With an emulator/session and local `sdk/` + `artifacts/` layout available:

```bash
./scripts/verify-tiling-wm-interaction.sh
./scripts/verify-tiling-wm-lifecycle.sh
./scripts/verify-slim-product.sh
```

These scripts will not fully run in a docs-only checkout without local fetches.

## Optional Starnix agent path

The agent-linux overlay is included without credentials.

1. Create your own keypair locally.
2. Install the public key using `authorized_keys.template` as a guide.
3. Export:

```bash
export AGENT_SSH_KEY=/absolute/path/to/private_key
export AGENT_KNOWN_HOSTS=/absolute/path/to/known_hosts
```

Never commit those files.

## Repository layout

```text
overlays/fuchsia/     # files to copy onto a Fuchsia checkout
scripts/              # fetch/apply/verify/secret-scan helpers
design/sketches/      # HTML UI directions
design/screenshots/   # current verified three-app PNG plus archived captures
docs/                 # architecture + donor roadmap
.github/workflows/    # CI
versions.env          # pins
```

## Instrument Studio UI path

Shared native UI contracts live in `overlays/fuchsia/src/fuchsia-desktop/desktop_ui`.
Region/token mapping: `docs/instrument-studio-ui-map.md`.

Host contract test:

```bash
python3 scripts/test-desktop-ui-host.py
```

## Observability feedback loop

Instrument Studio development uses Fuchsia diagnostics as the feedback channel:

```bash
./scripts/collect-desktop-diagnostics.sh ./artifacts/diagnostics-run
cat ./artifacts/diagnostics-run/design-feedback.json
```

See `docs/observability-feedback-loop.md` for the Inspect tree and design checks.

## Linux terminal

Workbench terminal bridges to Alpine/Linux via Starnix and installs a bounded `fuchsia-studio` help, health, and manual command inside the Linux console. Its optional PTY use matches the Fuchsia session-manager route availability. The Workbench session routes `FlatlandFactory` only to `terminal_elements`. `scripts/apply-overlays.sh` applies the source-pinned session-manager PTY offer and matching CML golden update. The 2026-09-30 live run above exercised these routes. See `docs/linux-terminal.md`.

## Production status

See `docs/production-status.md` for an honest done/not-done gate.

## Live demo evidence

Current run, 2026-09-30, guest `fuchsia-workbench-femu`, product `workbench_slim.x64`:

- Source: Fuchsia pin `85d1818a43cb152bf09a0a58ac571012f6ead5e7`; SDK `33.20260816.0.1`.
- Product bundle manifest SHA-256: `d4eef69025cec87e66e321c252269b3db77a6f7e581d17b3beaa6279ece0ea6a`.
- Reachable: Product state, RCS `Y`, guest printed `FUCHSIA_GUEST_OK`.
- Packages resolved from the embedded bundle; no development repository was registered on the final guest.
- Visible apps: Settings, Terminal, and Browser. Files was not launched or shown.
- Inspect: Health `OK`, `tile_count=3`, order `instrument-studio-browser,instrument-studio-terminal,instrument-studio-settings`.
- Screenshot: `design/screenshots/current-femu-run.png`, 720×1200, SHA-256 `e754988a7eeec4cd29015be03569faabe7afbcb48d10fe9ec91fffed392911b7`.
- Provenance limit: the Fuchsia checkout contained local overlay changes, and the earlier build receipt reported `input_unchanged=false`. This run makes no clean-tree provenance claim.

The prior 2026-09-29 screenshot is archived as `design/screenshots/previous-femu-run-2026-09-29.png`; it is historical, not proof for this run.

## Status

The current FEMU screenshot proves three visible app surfaces and the Linux help surface. It does not prove a fourth tile, Files presentation, or external Browser connectivity. The restart-only NativeTheme control plane remains a separate draft change and is not implied by this run.

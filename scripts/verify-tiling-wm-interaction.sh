#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
container=fuchsia-desktop-mvp
ffx=(podman exec "$container" /workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx)
bundle=/workspace/source/fuchsia/out/workbench_eng.x64-release/obj/products/workbench/workbench_slim.x64/product_bundle
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$project/artifacts/tiling-wm-interaction-$stamp"
mkdir -p "$out"
declare -A urls=(
  [browser]='fuchsia-pkg://fuchsia.com/fuchsia_browser#meta/fuchsia_browser.cm'
  [terminal]='fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm'
  [files]='fuchsia-pkg://fuchsia.com/fuchsia_files#meta/fuchsia_files.cm'
  [settings]='fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm'
)
declare -A collections=(
  [browser]='browser_elements'
  [terminal]='terminal_elements'
  [files]='files_elements'
  [settings]='settings_elements'
)
declare -A names
for app in browser terminal files settings; do names[$app]="wm-$app-$stamp"; done
cleanup() {
  for app in browser terminal files settings; do
    "${ffx[@]}" session remove "${names[$app]}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

"${ffx[@]}" emu stop fuchsia-workbench-qemu >/dev/null 2>&1 || true
"${ffx[@]}" emu stop fuchsia-workbench-femu >/dev/null 2>&1 || true
"${ffx[@]}" emu start --engine femu --gpu swiftshader_indirect --accel hyper --headless \
  --net user --smp 8 --name fuchsia-workbench-femu --startup-timeout 180 \
  --log "/workspace${out#$project}/emulator.log" "$bundle"
export FUCHSIA_NODENAME=fuchsia-workbench-femu
"${ffx[@]}" target wait -t 180

for app in browser terminal files settings; do
  "${ffx[@]}" session add --name "${names[$app]}" "${urls[$app]}" >"$out/$app-session-add.log" 2>&1
  moniker="core/session-manager/session:session/${collections[$app]}:${names[$app]}"
  for _ in $(seq 1 30); do
    "${ffx[@]}" component show "$moniker" >"$out/$app-show.txt" 2>&1 || true
    grep -q 'Execution State:  Running' "$out/$app-show.txt" && break
    sleep 1
  done
  grep -q 'Execution State:  Running' "$out/$app-show.txt"
done
sleep 2
"${ffx[@]}" component start core/session-manager/session:session/tiling_wm_driver >"$out/driver-start.log" 2>&1
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm_driver' --since '5m ago' --no-color dump >"$out/driver.log" 2>&1 || true
  grep -q 'TILING_WM_DRIVER_DONE' "$out/driver.log" && break
  sleep 1
done
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm' --since '5m ago' --no-color dump >"$out/tiling-wm.log" 2>&1 || true
  if grep -q 'TILING_WM_ACTIVE' "$out/tiling-wm.log" && grep -q 'TILING_WM_ORDER' "$out/tiling-wm.log"; then
    break
  fi
  sleep 1
done
"${ffx[@]}" target screenshot -d "/workspace${out#$project}"
grep -q 'TILING_WM_DRIVER_DONE' "$out/driver.log"
grep -q 'TILING_WM_ACTIVE' "$out/tiling-wm.log"
grep -q 'TILING_WM_ORDER' "$out/tiling-wm.log"
python3 - "$out/screenshot.png" <<'PIXELS'
from PIL import Image
import sys
im = Image.open(sys.argv[1]).convert("RGBA")
assert im.size == (720, 1200), im.size
outer_gap = im.getpixel((5, 5))
center_gap = im.getpixel((360, 300))
active = im.getpixel((12, 200))
inactive = im.getpixel((366, 200))
assert outer_gap[3] == 0, f"outer gap is not transparent: {outer_gap}"
assert center_gap[3] == 0, f"inter-tile gap is not transparent: {center_gap}"
assert active[0] < 20 and active[1] > 200 and active[2] > 240 and active[3] == 255, \
    f"active focus ring is not cyan: {active}"
assert inactive[3] == 255 and inactive != active, f"inactive ring is not distinct: {inactive}"
print(f"TILING_WM_PIXELS outer={outer_gap} center={center_gap} active={active} inactive={inactive}")
PIXELS
printf 'TILING_WM_INTERACTION_GREEN=%s\n' "$out"

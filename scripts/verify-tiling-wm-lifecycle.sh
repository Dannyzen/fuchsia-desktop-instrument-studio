#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
ffx=(podman exec fuchsia-desktop-mvp /workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx)
bundle=/workspace/source/fuchsia/out/workbench_eng.x64-release/obj/products/workbench/workbench_slim.x64/product_bundle
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$project/artifacts/tiling-wm-lifecycle-$stamp"
mkdir -p "$out"
declare -A urls=(
  [browser]='fuchsia-pkg://fuchsia.com/fuchsia_browser#meta/fuchsia_browser.cm'
  [terminal]='fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm'
  [files]='fuchsia-pkg://fuchsia.com/fuchsia_files#meta/fuchsia_files.cm'
  [settings]='fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm'
)
declare -A collections=(
  [browser]='browser_elements' [terminal]='terminal_elements'
  [files]='files_elements' [settings]='settings_elements'
)
declare -A names
for app in browser terminal files settings; do names[$app]="life-$app-$stamp"; done
cleanup() { for app in browser terminal files settings; do "${ffx[@]}" session remove "${names[$app]}" >/dev/null 2>&1 || true; done; }
trap cleanup EXIT
add_and_wait() {
  local app=$1
  "${ffx[@]}" session add --name "${names[$app]}" "${urls[$app]}" >"$out/$app-add.log" 2>&1
  local moniker="core/session-manager/session:session/${collections[$app]}:${names[$app]}"
  for _ in $(seq 1 30); do
    "${ffx[@]}" component show "$moniker" >"$out/$app-show.txt" 2>&1 || true
    grep -q 'Execution State:  Running' "$out/$app-show.txt" && return 0
    sleep 1
  done
  return 1
}
"${ffx[@]}" emu stop fuchsia-workbench-femu >/dev/null 2>&1 || true
"${ffx[@]}" emu start --engine femu --gpu swiftshader_indirect --accel hyper --headless \
  --net user --smp 8 --name fuchsia-workbench-femu --startup-timeout 180 \
  --log "/workspace${out#$project}/emulator.log" "$bundle"
export FUCHSIA_NODENAME=fuchsia-workbench-femu
"${ffx[@]}" target wait -t 180
for app in browser terminal files settings; do add_and_wait "$app"; done
"${ffx[@]}" component start core/session-manager/session:session/tiling_wm_driver >"$out/driver-before-start.log" 2>&1
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm_driver' --since '2m ago' --no-color dump >"$out/driver-before.log" 2>&1 || true
  grep -q 'TILING_WM_DRIVER_DONE' "$out/driver-before.log" && break
  sleep 1
done
grep -q 'TILING_WM_DRIVER_DONE' "$out/driver-before.log"
grep -q 'count=4' "$out/driver-before.log"
marker=''
while IFS= read -r line; do
  [[ "$line" == *TILING_WM_DRIVER_DONE* ]] && marker=$line
done <"$out/driver-before.log"
focused_id=${marker#*focused_id=}
focused_id=${focused_id%% *}
active_app=''
for app in browser terminal files settings; do
  [[ "${names[$app]}" == "$focused_id" ]] && active_app=$app
done
[[ -n "$active_app" ]]
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm' --since '5m ago' --no-color dump >"$out/tiling-wm.log" 2>&1 || true
  grep -q "TILING_WM_ACTIVE id=$focused_id" "$out/tiling-wm.log" && break
  sleep 1
done
grep -q "TILING_WM_ACTIVE id=$focused_id" "$out/tiling-wm.log"
"${ffx[@]}" session remove "$focused_id" >"$out/active-remove.log" 2>&1
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm' --since '5m ago' --no-color dump >"$out/tiling-wm.log" 2>&1 || true
  grep -q "TILING_WM_REMOVE id=$focused_id remaining=3" "$out/tiling-wm.log" &&     grep -q "TILING_WM_ACTIVE_CLEARED reason=removed id=$focused_id" "$out/tiling-wm.log" && break
  sleep 1
done
grep -q "TILING_WM_REMOVE id=$focused_id remaining=3" "$out/tiling-wm.log"
grep -q "TILING_WM_ACTIVE_CLEARED reason=removed id=$focused_id" "$out/tiling-wm.log"
"${ffx[@]}" component show core/session-manager/session:session/tiling_wm >"$out/tiling-wm-show.txt"
grep -q 'Execution State:  Running' "$out/tiling-wm-show.txt"
add_and_wait "$active_app"
"${ffx[@]}" component start core/session-manager/session:session/tiling_wm_driver_after_churn >"$out/driver-after-start.log" 2>&1
for _ in $(seq 1 20); do
  "${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm_driver_after_churn' --since '2m ago' --no-color dump >"$out/driver-after.log" 2>&1 || true
  grep -q 'TILING_WM_DRIVER_DONE' "$out/driver-after.log" && break
  sleep 1
done
grep -q 'TILING_WM_DRIVER_DONE' "$out/driver-after.log"
grep -q 'count=4' "$out/driver-after.log"
"${ffx[@]}" target screenshot -d "/workspace${out#$project}"
"${ffx[@]}" log --component 'core/session-manager/session:session/tiling_wm' --since '5m ago' --no-color dump >"$out/tiling-wm.log" 2>&1 || true
if grep -Ei 'panicked|crash|Error handling message' "$out/tiling-wm.log"; then
  echo 'tiling WM lifecycle failure detected' >&2
  exit 1
fi
printf 'TILING_WM_LIFECYCLE_GREEN=%s\n' "$out"

#!/usr/bin/env bash
set -euo pipefail
cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
source_root=/workspace/source/fuchsia
out_dir="$source_root/out/workbench_eng.x64-release"
repo=/workspace/repositories/mvp
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="/workspace/artifacts/four-app-session-$stamp"
mkdir -p "$out/screenshot"

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
declare -A monikers
for app in browser terminal files settings; do
  names[$app]="four-$app-$stamp"
  monikers[$app]="core/session-manager/session:session/${collections[$app]}:${names[$app]}"
done
cleanup() {
  for app in browser terminal files settings; do
    "$FFX" session remove "${names[$app]}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

cd "$source_root"
./scripts/fx build 2>&1 | tee "$out/build.log"
if grep -E 'warning:|error:' "$out/build.log"; then
  echo "Four-app Workbench build emitted diagnostics" >&2
  exit 1
fi
cd /workspace
"$FFX" emu stop fuchsia-workbench-qemu >/dev/null 2>&1 || true
"$FFX" emu stop fuchsia-workbench-femu >/dev/null 2>&1 || true
"$FFX" emu start \
  --engine femu --gpu swiftshader_indirect --accel hyper --headless --net user --smp 8 \
  --name fuchsia-workbench-femu --startup-timeout 180 \
  --log "$out/emulator.log" \
  "$out_dir/obj/products/workbench/workbench_eng.x64/product_bundle"
export FUCHSIA_NODENAME=fuchsia-workbench-femu
"$FFX" target wait -t 180
cd "$out_dir"
for manifest in \
  obj/src/fuchsia-desktop/browser/package/package_manifest.json \
  obj/src/fuchsia-desktop/terminal/package/package_manifest.json \
  obj/src/fuchsia-desktop/files/package/package_manifest.json \
  obj/src/fuchsia-desktop/settings/package/package_manifest.json; do
  test -f "$manifest"
done
"$FFX" repository publish \
  --package obj/src/fuchsia-desktop/browser/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/terminal/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/files/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/settings/package/package_manifest.json \
  "$repo"
cd /workspace
"$FFX" target repository register -r fuchsia-mvp --alias fuchsia.com

for app in browser terminal files settings; do
  "$FFX" session add --name "${names[$app]}" "${urls[$app]}" >"$out/$app-session-add.log" 2>&1
  for _ in $(seq 1 30); do
    "$FFX" component show "${monikers[$app]}" >"$out/$app-show.txt" 2>&1 || true
    grep -q 'Execution State:  Running' "$out/$app-show.txt" && break
    sleep 1
  done
  grep -q 'Execution State:  Running' "$out/$app-show.txt"
done

for _ in $(seq 1 5); do
  sleep 1
  for app in browser terminal files settings; do
    "$FFX" component show "${monikers[$app]}" >"$out/$app-show.txt" 2>&1
    grep -q 'Execution State:  Running' "$out/$app-show.txt"
  done
done

# Positive capability matrix.
for capability in \
  '/svc/fuchsia.web.ContextProvider' \
  '/svc/fuchsia.process.Launcher' \
  '/svc/fuchsia.net.interfaces.State' \
  '/svc/fuchsia.ui.composition.Flatland'; do
  grep -Fq "$capability" "$out/browser-show.txt"
done
for capability in \
  '/svc/fuchsia.hardware.pty.Device' \
  '/svc/fuchsia.process.Launcher' \
  '/svc/fuchsia.ui.composition.Flatland'; do
  grep -Fq "$capability" "$out/terminal-show.txt"
done
for capability in '/data' '/svc/fuchsia.ui.composition.Flatland'; do
  grep -Fq "$capability" "$out/files-show.txt"
done
for capability in \
  '/data' \
  '/svc/fuchsia.settings.Intl' \
  '/svc/fuchsia.buildinfo.Provider' \
  '/svc/fuchsia.hwinfo.Product' \
  '/svc/fuchsia.ui.composition.Flatland'; do
  grep -Fq "$capability" "$out/settings-show.txt"
done

# Negative cross-application capability matrix.
if grep -Eq '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.settings.Intl|/svc/fuchsia.ui.test.input.Registry|/data' "$out/browser-show.txt"; then
  echo 'Browser inherited another application authority' >&2; exit 1
fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.settings.Intl|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry|/data' "$out/terminal-show.txt"; then
  echo 'Terminal inherited another application authority' >&2; exit 1
fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.process.Launcher|/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.settings.Intl|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry' "$out/files-show.txt"; then
  echo 'Files inherited another application authority' >&2; exit 1
fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.process.Launcher|/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry' "$out/settings-show.txt"; then
  echo 'Settings inherited another application authority' >&2; exit 1
fi

for app in browser terminal files settings; do
  "$FFX" component route "${monikers[$app]}" svc/fuchsia.ui.composition.Flatland \
    >"$out/$app-flatland-route.txt"
  "$FFX" log --component "${names[$app]}" --since '5m ago' --no-color dump \
    >"$out/$app.log" 2>&1 || true
  if grep -Ei 'panic|fatal|Flatland error' "$out/$app.log"; then
    echo "$app runtime failure signature found" >&2; exit 1
  fi
done
"$FFX" target screenshot -d "$out/screenshot"
"$FFX" component list >"$out/component-list.txt"
for app in browser terminal files settings; do
  grep -Fq "${names[$app]}" "$out/component-list.txt"
done
sha256sum "$out/screenshot/screenshot.png" >"$out/screenshot.sha256"
printf 'FOUR_APP_RESULT_DIR=%s\n' "$out"
printf 'Browser, Terminal, Files, and Settings remained Running together for five rechecks.\n'

#!/usr/bin/env bash
set -euo pipefail
cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
source_root=/workspace/source/fuchsia
out_dir="$source_root/out/workbench_eng.x64-release"
bundle="$out_dir/obj/products/workbench/workbench_slim.x64/product_bundle"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="/workspace/artifacts/slim-product-session-$stamp"
mkdir -p "$out/browser" "$out/terminal" "$out/files" "$out/settings"

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
  names[$app]="slim-$app-$stamp"
  monikers[$app]="core/session-manager/session:session/${collections[$app]}:${names[$app]}"
done
cleanup() {
  for app in browser terminal files settings; do
    "$FFX" session remove "${names[$app]}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

# A long-lived fuchsia-mvp server can auto-register after target discovery.
# Stop it before boot so all four application URLs must resolve from cache.
"$FFX" repository server stop fuchsia-mvp >"$out/repository-server-stop.log" 2>&1 || true
"$FFX" emu stop fuchsia-workbench-qemu >/dev/null 2>&1 || true
"$FFX" emu stop fuchsia-workbench-femu >/dev/null 2>&1 || true
"$FFX" emu start \
  --engine femu --gpu swiftshader_indirect --accel hyper --headless --net user --smp 8 \
  --additional-port-forwards agent-linux-ssh:7000 --port-map agent-linux-ssh:17000 \
  --name fuchsia-workbench-femu --startup-timeout 180 \
  --log "$out/emulator.log" "$bundle"
export FUCHSIA_NODENAME=fuchsia-workbench-femu
"$FFX" target wait -t 180
"$FFX" target repository list >"$out/repositories-before.txt" 2>&1 || true
if grep -q 'fuchsia-mvp' "$out/repositories-before.txt"; then
  echo 'Slim acceptance target inherited the development repository' >&2
  exit 1
fi

add_and_wait() {
  local app=$1
  "$FFX" session add --name "${names[$app]}" "${urls[$app]}" >"$out/$app/session-add.log" 2>&1
  for _ in $(seq 1 30); do
    "$FFX" component show "${monikers[$app]}" >"$out/$app/show.txt" 2>&1 || true
    grep -q 'Execution State:  Running' "$out/$app/show.txt" && return 0
    sleep 1
  done
  return 1
}

# Browser resolves from embedded cache and renders external HTTPS.
add_and_wait browser
for _ in $(seq 1 45); do
  "$FFX" log --component "${names[browser]}" --since '5m ago' --no-color dump >"$out/browser/component.log" 2>&1 || true
  grep -q 'loaded=Some(true)' "$out/browser/component.log" && break
  sleep 1
done
grep -q 'loaded=Some(true)' "$out/browser/component.log"
"$FFX" target screenshot -d "$out/browser"
"$FFX" session remove "${names[browser]}"

# Terminal PTY journey using the Workbench-embedded bounded driver subpackage.
add_and_wait terminal
"$FFX" target screenshot -d "$out/terminal"
mv "$out/terminal/screenshot.png" "$out/terminal/baseline.png"
"$FFX" component start core/session-manager/session:session/terminal_input_driver >"$out/terminal/driver-start.log" 2>&1
for attempt in $(seq 1 20); do
  sleep 1
  mkdir -p "$out/terminal/capture-$attempt"
  "$FFX" target screenshot -d "$out/terminal/capture-$attempt"
done
"$FFX" log --component "${names[terminal]}" --since '5m ago' --no-color dump >"$out/terminal/component.log" 2>&1 || true
"$FFX" log --component terminal_input_driver --since '5m ago' --no-color dump >"$out/terminal/driver.log" 2>&1 || true
if grep -E 'unable to create pty|unable to spawn pty|panicked at' "$out/terminal/component.log"; then
  echo 'Slim Terminal PTY failed' >&2; exit 1
fi
"$FFX" session remove "${names[terminal]}"

# Files bounded-storage journey.
add_and_wait files
"$FFX" component start core/session-manager/session:session/files_input_driver >"$out/files/driver-start.log" 2>&1 || true
for _ in $(seq 1 40); do
  "$FFX" log --component "${names[files]}" --since '5m ago' --no-color dump >"$out/files/component.log" 2>&1 || true
  grep -q 'Files action Open: Opened /Documents' "$out/files/component.log" && break
  sleep 1
done
for expected in \
  'Files action Create: Created Untitled.txt' \
  'Files action Rename: Renamed Untitled.txt to Untitled Renamed.txt' \
  'Files action Copy: Copied Untitled Renamed.txt to Untitled Renamed Copy.txt' \
  'Files action Move: Moved Untitled Renamed.txt' \
  'Files action Delete: Confirm delete Untitled Renamed Copy.txt' \
  'Files action Delete: Deleted Untitled Renamed Copy.txt' \
  'Files action Open: Opened /Documents'; do
  grep -Fq "$expected" "$out/files/component.log"
done
"$FFX" target screenshot -d "$out/files"
"$FFX" session remove "${names[files]}"

# Settings backed-control journey and restart persistence.
add_and_wait settings
"$FFX" component start core/session-manager/session:session/settings_input_driver >"$out/settings/driver-start.log" 2>&1 || true
for _ in $(seq 1 40); do
  "$FFX" log --component "${names[settings]}" --since '5m ago' --no-color dump >"$out/settings/component-before.log" 2>&1 || true
  grep -q 'Applied Fahrenheit temperature unit' "$out/settings/component-before.log" && break
  sleep 1
done
for expected in \
  'Settings action ThemeDark: Applied Dark theme' \
  'Settings action ThemeContrast: Applied High Contrast theme' \
  'Settings action TemperatureCelsius: Applied Celsius temperature unit' \
  'Settings action TemperatureFahrenheit: Applied Fahrenheit temperature unit'; do
  grep -Fq "$expected" "$out/settings/component-before.log"
done
"$FFX" session remove "${names[settings]}"
sleep 1
add_and_wait settings
sleep 2
"$FFX" log --component "${names[settings]}" --since '5m ago' --no-color dump >"$out/settings/component.log" 2>&1 || true
grep -Fq 'theme=High Contrast temperature=Fahrenheit' "$out/settings/component.log"
"$FFX" target screenshot -d "$out/settings"

# Re-add the other apps and prove concurrent lifecycle plus isolated namespaces.
for app in browser terminal files; do add_and_wait "$app"; done
for _ in $(seq 1 5); do
  sleep 1
  for app in browser terminal files settings; do
    "$FFX" component show "${monikers[$app]}" >"$out/$app/show.txt" 2>&1
    grep -q 'Execution State:  Running' "$out/$app/show.txt"
  done
done
if grep -Eq '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.settings.Intl|/svc/fuchsia.ui.test.input.Registry|/data' "$out/browser/show.txt"; then exit 1; fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.settings.Intl|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry|/data' "$out/terminal/show.txt"; then exit 1; fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.process.Launcher|/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.settings.Intl|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry' "$out/files/show.txt"; then exit 1; fi
if grep -Eq '/svc/fuchsia.web.ContextProvider|/svc/fuchsia.process.Launcher|/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry' "$out/settings/show.txt"; then exit 1; fi
"$FFX" target repository list >"$out/repositories-after.txt" 2>&1 || true
if grep -q 'fuchsia-mvp' "$out/repositories-after.txt"; then
  echo 'Slim app proof used the development repository' >&2; exit 1
fi
printf 'SLIM_RESULT_DIR=%s\n' "$out"
printf 'Slim Browser, Terminal, Files, and Settings resolved from the image and passed bounded journeys.\n'

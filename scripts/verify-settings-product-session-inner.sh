#!/usr/bin/env bash
set -euo pipefail
cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
source_root=/workspace/source/fuchsia
out_dir="$source_root/out/workbench_eng.x64-release"
repo=/workspace/repositories/mvp
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="fuchsia-settings-proof-$stamp"
failure="fuchsia-settings-failure-$stamp"
control="settings-generic-control-$stamp"
moniker="core/session-manager/session:session/settings_elements:$name"
failure_moniker="core/session-manager/session:session/settings_elements:$failure"
control_moniker="core/session-manager/session:session/elements:$control"
out="/workspace/artifacts/settings-product-session-$stamp"
mkdir -p "$out/product" "$out/failure"

cleanup() {
  "$FFX" session remove "$name" >/dev/null 2>&1 || true
  "$FFX" session remove "$failure" >/dev/null 2>&1 || true
  "$FFX" component destroy "$control_moniker" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$source_root"
./scripts/fx build 2>&1 | tee "$out/build.log"
if grep -E 'warning:|error:' "$out/build.log"; then
  echo "Workbench Settings build emitted diagnostics" >&2
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
"$FFX" repository publish \
  --package obj/src/fuchsia-desktop/settings/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/settings/failure_package/package_manifest.json \
  --package obj/src/fuchsia-desktop/settings/input_driver_package/package_manifest.json \
  --package obj/src/fuchsia-desktop/files/generic_control_package/package_manifest.json \
  "$repo"
cd /workspace
"$FFX" target repository register -r fuchsia-mvp --alias fuchsia.com

"$FFX" session add --name "$name" \
  fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm \
  >"$out/session-add.log" 2>&1
for _ in $(seq 1 30); do
  "$FFX" component show "$moniker" >"$out/component-show-before.txt" 2>&1 || true
  grep -q 'Execution State:  Running' "$out/component-show-before.txt" && break
  sleep 1
done
grep -q 'Execution State:  Running' "$out/component-show-before.txt"
for _ in $(seq 1 5); do
  sleep 1
  "$FFX" component show "$moniker" >"$out/component-show-before.txt" 2>&1
  grep -q 'Execution State:  Running' "$out/component-show-before.txt"
done

"$FFX" component start core/session-manager/session:session/settings_input_driver \
  >"$out/input-start.log" 2>&1 || true
for _ in $(seq 1 40); do
  "$FFX" log --component "$name" --since "5m ago" --no-color dump \
    >"$out/component-before.log" 2>&1 || true
  grep -q 'Applied Fahrenheit temperature unit' "$out/component-before.log" && break
  sleep 1
done
"$FFX" log --component settings_input_driver --since "5m ago" --no-color dump \
  >"$out/input.log" 2>&1 || true
for expected in \
  'Settings action ThemeDark: Applied Dark theme' \
  'Settings action ThemeContrast: Applied High Contrast theme' \
  'Settings action TemperatureCelsius: Applied Celsius temperature unit' \
  'Settings action TemperatureFahrenheit: Applied Fahrenheit temperature unit'; do
  grep -Fq "$expected" "$out/component-before.log"
done
grep -Fq 'Completed backed Settings touch journey' "$out/input.log"

"$FFX" session remove "$name"
sleep 1
"$FFX" session add --name "$name" \
  fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm \
  >"$out/session-readd.log" 2>&1
for _ in $(seq 1 30); do
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
  grep -q 'Execution State:  Running' "$out/component-show.txt" && break
  sleep 1
done
grep -q 'Execution State:  Running' "$out/component-show.txt"
sleep 2
"$FFX" log --component "$name" --since "5m ago" --no-color dump \
  >"$out/component.log" 2>&1 || true
grep -Fq 'theme=High Contrast temperature=Fahrenheit' "$out/component.log"
grep -Fq 'hidden=[Brightness, Accessibility, Keyboard, Network]' "$out/component.log"
"$FFX" target screenshot -d "$out/product"

"$FFX" component route "$moniker" svc/fuchsia.settings.Intl >"$out/intl-route.txt"
"$FFX" component route "$moniker" svc/fuchsia.buildinfo.Provider >"$out/buildinfo-route.txt"
"$FFX" component route "$moniker" svc/fuchsia.hwinfo.Product >"$out/product-route.txt"
for capability in \
  '/svc/fuchsia.settings.Intl' \
  '/svc/fuchsia.buildinfo.Provider' \
  '/svc/fuchsia.hwinfo.Product' \
  '/svc/fuchsia.ui.composition.Flatland' \
  '/svc/fuchsia.sysmem.Allocator' \
  '/data'; do
  grep -Fq "$capability" "$out/component-show.txt"
done
if grep -Eq \
  '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.process.Launcher|/svc/fuchsia.web.ContextProvider|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry|/bin|/boot' \
  "$out/component-show.txt"; then
  echo "Settings inherited a prohibited capability" >&2
  exit 1
fi

"$FFX" session remove "$name"
"$FFX" session add --name "$failure" \
  fuchsia-pkg://fuchsia.com/fuchsia_settings_failure#meta/fuchsia_settings_failure.cm \
  >"$out/failure-add.log" 2>&1
for _ in $(seq 1 30); do
  "$FFX" component show "$failure_moniker" >"$out/failure-show.txt" 2>&1 || true
  grep -q 'Execution State:  Running' "$out/failure-show.txt" && break
  sleep 1
done
grep -q 'Execution State:  Running' "$out/failure-show.txt"
sleep 2
"$FFX" log --component "$failure" --since "5m ago" --no-color dump \
  >"$out/failure.log" 2>&1 || true
grep -Fq 'Apply failed: injected Intl apply failure; retained Fahrenheit' "$out/failure.log"
"$FFX" target screenshot -d "$out/failure"

"$FFX" component create "$control_moniker" \
  fuchsia-pkg://fuchsia.com/files_generic_control#meta/files_generic_control.cm \
  >"$out/control-create.log" 2>&1
"$FFX" component start "$control_moniker" >"$out/control-start.log" 2>&1 || true
"$FFX" component show "$control_moniker" >"$out/control-show.txt" 2>&1
if grep -Eq '/svc/fuchsia.settings.Intl|/svc/fuchsia.buildinfo.Provider|/svc/fuchsia.hwinfo.Product' \
  "$out/control-show.txt"; then
  echo "Generic elements inherited Settings-specific protocols" >&2
  exit 1
fi

if grep -Ei 'panic|fatal|Flatland error' "$out/component.log" "$out/failure.log"; then
  echo "Settings runtime failure signature found" >&2
  exit 1
fi
printf 'SETTINGS_RESULT_DIR=%s\n' "$out"

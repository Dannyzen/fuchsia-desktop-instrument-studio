#!/usr/bin/env bash
set -euo pipefail
cd /workspace
export FUCHSIA_NODENAME=fuchsia-workbench-qemu
FFX=/workspace/sdk/packages/tools/x64/ffx
source_root=/workspace/source/fuchsia
out_dir="$source_root/out/workbench_eng.x64-release"
repo=/workspace/repositories/mvp
name="fuchsia-files-proof-$(date -u +%Y%m%dT%H%M%SZ)"
control="fuchsia-files-generic-$(date -u +%Y%m%dT%H%M%SZ)"
moniker="core/session-manager/session:session/files_elements:$name"
control_moniker="core/session-manager/session:session/elements:$control"
out="/workspace/artifacts/files-product-session-$name"
mkdir -p "$out"

cleanup() {
  "$FFX" session remove "$name" >/dev/null 2>&1 || true
  "$FFX" component destroy "$control_moniker" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$source_root"
./scripts/fx build 2>&1 | tee "$out/build.log"
if grep -E 'warning:|error:' "$out/build.log"; then
  echo "Workbench Files build emitted diagnostics" >&2
  exit 1
fi
cd /workspace
"$FFX" emu stop fuchsia-workbench-qemu >/dev/null 2>&1 || true
"$FFX" emu start \
  --engine qemu --accel hyper --headless --net user --smp 8 \
  --name fuchsia-workbench-qemu --startup-timeout 180 \
  --log "$out/emulator.log" \
  "$out_dir/obj/products/workbench/workbench_eng.x64/product_bundle"
"$FFX" target wait -t 180

cd "$out_dir"
"$FFX" repository publish \
  --package obj/src/fuchsia-desktop/files/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/files/input_driver_package/package_manifest.json \
  --package obj/src/fuchsia-desktop/files/generic_control_package/package_manifest.json \
  "$repo"
cd /workspace
"$FFX" target repository register -r fuchsia-mvp --alias fuchsia.com
"$FFX" session add --name "$name" \
  fuchsia-pkg://fuchsia.com/fuchsia_files#meta/fuchsia_files.cm \
  >"$out/session-add.log" 2>&1

state=""
for _ in $(seq 1 30); do
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
  state=$(sed -n 's/^ *Execution State:  //p' "$out/component-show.txt" | head -n 1)
  [[ "$state" == "Running" ]] && break
  sleep 1
done
[[ "$state" == "Running" ]]
for _ in $(seq 1 5); do
  sleep 1
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1
  grep -q 'Execution State:  Running' "$out/component-show.txt"
done

"$FFX" component start core/session-manager/session:session/files_input_driver \
  >"$out/input-start.log" 2>&1 || true
for _ in $(seq 1 40); do
  "$FFX" log --component "$name" --since "5m ago" --no-color dump \
    >"$out/component.log" 2>&1 || true
  grep -q 'Files action Open: Opened /Documents' "$out/component.log" && break
  sleep 1
done
"$FFX" log --component files_input_driver --since "5m ago" --no-color dump \
  >"$out/input.log" 2>&1 || true

for expected in \
  'Files action Create: Created Untitled.txt' \
  'Files action Rename: Renamed Untitled.txt to Untitled Renamed.txt' \
  'Files action Copy: Copied Untitled Renamed.txt to Untitled Renamed Copy.txt' \
  'Files action Move: Moved Untitled Renamed.txt' \
  'Files action Delete: Confirm delete Untitled Renamed Copy.txt' \
  'Files action Delete: Deleted Untitled Renamed Copy.txt' \
  'Files action Open: Opened /Documents'; do
  grep -Fq "$expected" "$out/component.log"
done
grep -Fq 'Completed bounded Files touch journey' "$out/input.log"
grep -Fq 'Rejected outside-root probe: path is outside bounded root: ../outside' \
  "$out/component.log"

"$FFX" component create "$control_moniker" \
  fuchsia-pkg://fuchsia.com/files_generic_control#meta/files_generic_control.cm \
  >"$out/control-create.log" 2>&1
"$FFX" component start "$control_moniker" >"$out/control-start.log" 2>&1 || true
for _ in $(seq 1 20); do
  "$FFX" log --component "$control" --since "5m ago" --no-color dump \
    >"$out/control.log" 2>&1 || true
  grep -q 'Generic element storage is isolated from Fuchsia Files' "$out/control.log" && break
  sleep 1
done
grep -q 'Generic element storage is isolated from Fuchsia Files' "$out/control.log"

"$FFX" target screenshot -d "$out"
python3 /workspace/scripts/assert-files-screenshot.py "$out/screenshot.png"
if grep -Eq \
  '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.process.Launcher|/svc/fuchsia.web.ContextProvider|/svc/fuchsia.net|/svc/fuchsia.ui.test.input.Registry' \
  "$out/component-show.txt"; then
  echo "Files inherited a prohibited capability" >&2
  exit 1
fi
grep -q '/svc/fuchsia.ui.composition.Flatland' "$out/component-show.txt"
grep -q '/svc/fuchsia.sysmem.Allocator' "$out/component-show.txt"
grep -q 'data' "$out/component-show.txt"
if grep -Ei 'panic|fatal|Flatland error' "$out/component.log"; then
  echo "Files runtime failure signature found" >&2
  exit 1
fi
cp "$out/screenshot.png" /workspace/artifacts/fuchsia-files-product.png
sha256sum /workspace/artifacts/fuchsia-files-product.png
printf 'Fuchsia Files product session passed: %s; generic storage control %s\n' \
  "$moniker" "$control_moniker"

#!/usr/bin/env bash
set -euo pipefail

cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
source_root=/workspace/source/fuchsia
out_dir="$source_root/out/workbench_eng.x64-release"
repo=/workspace/repositories/mvp
name="cosmic-panel-spike-$(date -u +%Y%m%dT%H%M%SZ)"
moniker="core/session-manager/session:session/elements:$name"
out="/workspace/artifacts/cosmic-panel-spike-$name"
mkdir -p "$out"

cleanup() {
  "$FFX" session remove "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$source_root"
./scripts/fx build   //src/fuchsia-desktop/panel-spike:package   //src/fuchsia-desktop/panel-spike:bin.clippy   2>&1 | tee "$out/build.log"
if grep -E 'warning:|error:' "$out/build.log"; then
  echo "COSMIC panel build or Clippy emitted diagnostics" >&2
  exit 1
fi

cd "$out_dir"
"$FFX" repository publish   --package obj/src/fuchsia-desktop/panel-spike/package/package_manifest.json   "$repo"
cd /workspace
"$FFX" target repository register -r fuchsia-mvp --alias fuchsia.com
"$FFX" session add --name "$name"   fuchsia-pkg://fuchsia.com/fuchsia_cosmic_panel_spike#meta/fuchsia_cosmic_panel_spike.cm   >"$out/session-add.log" 2>&1

state=""
for _ in $(seq 1 30); do
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
  state=$(sed -n 's/^ *Execution State:  //p' "$out/component-show.txt" | head -n 1)
  [[ "$state" == "Running" || "$state" == "Stopped" ]] && break
  sleep 1
done
if [[ "$state" != "Running" ]]; then
  "$FFX" log --component "$name" --since "5m ago" --no-color dump     >"$out/component.log" 2>&1 || true
  cat "$out/component-show.txt" >&2
  cat "$out/component.log" >&2
  exit 1
fi

for _ in $(seq 1 5); do
  sleep 1
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1
  state=$(sed -n 's/^ *Execution State:  //p' "$out/component-show.txt" | head -n 1)
  [[ "$state" == "Running" ]] || exit 1
done

"$FFX" target screenshot -d "$out"
python3 /workspace/scripts/assert-cosmic-panel-screenshot.py "$out/screenshot.png"
"$FFX" log --component "$name" --since "5m ago" --no-color dump   >"$out/component.log" 2>&1 || true
grep -q 'Presented COSMIC-derived native panel' "$out/component.log"
if grep -Eq   '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.process.Launcher|/svc/fuchsia.web.ContextProvider|/svc/fuchsia.net'   "$out/component-show.txt"; then
  echo "COSMIC panel inherited a prohibited capability" >&2
  exit 1
fi
if grep -Ei 'panic|fatal|Flatland error' "$out/component.log"; then
  echo "COSMIC panel runtime failure signature found" >&2
  exit 1
fi
cp "$out/screenshot.png" /workspace/artifacts/fuchsia-cosmic-panel-spike.png
sha256sum /workspace/artifacts/fuchsia-cosmic-panel-spike.png
printf 'COSMIC panel spike passed: %s is Running under generic elements
' "$moniker"

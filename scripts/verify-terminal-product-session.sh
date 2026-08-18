#!/usr/bin/env bash
set -euo pipefail

cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
repo=/workspace/repositories/mvp
out_dir=/workspace/source/fuchsia/out/workbench_eng.x64-release
name="fuchsia-terminal-proof-$(date -u +%Y%m%dT%H%M%SZ)"
generic_name="fuchsia-terminal-generic-control-$(date -u +%Y%m%dT%H%M%SZ)"
moniker="core/session-manager/session:session/terminal_elements:$name"
generic_moniker="core/session-manager/session:session/elements:$generic_name"
out="/workspace/artifacts/terminal-product-session-$name"
mkdir -p "$out"

cd "$out_dir"
"$FFX" repository publish \
  --package obj/src/fuchsia-desktop/terminal/package/package_manifest.json \
  --package obj/src/fuchsia-desktop/terminal/generic_control_package/package_manifest.json \
  "$repo"
cd /workspace

cleanup() {
  "$FFX" session remove "$name" >/dev/null 2>&1 || true
  "$FFX" session remove "$generic_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$FFX" session add --name "$name" \
  fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm \
  >"$out/session-add.log" 2>&1

state=""
for _ in $(seq 1 30); do
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
  state=$(sed -n 's/^ *Execution State:  //p' "$out/component-show.txt" | head -n 1)
  if [[ "$state" == "Running" ]]; then
    break
  fi
  if [[ "$state" == "Stopped" ]]; then
    break
  fi
  sleep 1
done
if [[ "$state" != "Running" ]]; then
  "$FFX" log --component "$name" --since "5m ago" --no-color dump \
    >"$out/component.log" 2>&1 || true
  cat "$out/component-show.txt" >&2
  cat "$out/component.log" >&2
  exit 1
fi

for _ in $(seq 1 10); do
  "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
  state=$(sed -n 's/^ *Execution State:  //p' "$out/component-show.txt" | head -n 1)
  if [[ "$state" != "Running" ]]; then
    break
  fi
  sleep 1
done
if [[ "$state" != "Running" ]]; then
  echo "Terminal did not remain Running" >&2
  exit 1
fi

"$FFX" target screenshot -d "$out"
mv "$out/screenshot.png" "$out/baseline.png"

# The fixed Workbench child types only `echo terminalok\n` through the standard
# UI test-input registry. The Terminal receives no injection capability.
"$FFX" component start   core/session-manager/session:session/terminal_input_driver   >"$out/input-driver-start.log" 2>&1

visible=0
for attempt in $(seq 1 20); do
  "$FFX" target screenshot -d "$out"
  mv "$out/screenshot.png" "$out/result-$attempt.png"
  if python3 /workspace/scripts/assert-terminal-screenshot.py       "$out/baseline.png" "$out/result-$attempt.png"; then
    cp "$out/result-$attempt.png" /workspace/artifacts/fuchsia-terminal-product.png
    visible=1
    break
  fi
  sleep 1
done

"$FFX" log --component "$name" --since "5m ago" --no-color dump \
  >"$out/component.log" 2>&1 || true
if grep -E 'fuchsia.hardware.pty.Device.*not available|unable to create pty|unable to spawn pty|panicked at' "$out/component.log"; then
  echo "Terminal PTY/process check failed" >&2
  exit 1
fi
if [[ "$visible" != 1 ]]; then
  echo "Typed Terminal output did not become visible" >&2
  exit 1
fi

# Live capability audit: a benign default-collection element must not receive
# the PTY or process launcher that the exact Terminal URL receives.
"$FFX" session add --name "$generic_name"   fuchsia-pkg://fuchsia.com/terminal_generic_control#meta/flatland-rainbow.cm   >"$out/generic-session-add.log" 2>&1
for _ in $(seq 1 30); do
  "$FFX" component show "$generic_moniker" >"$out/generic-component-show.txt" 2>&1 || true
  generic_state=$(sed -n 's/^ *Execution State:  //p' "$out/generic-component-show.txt" | head -n 1)
  [[ "$generic_state" == "Running" ]] && break
  sleep 1
done
[[ "$generic_state" == "Running" ]]

"$FFX" component show "$moniker" >"$out/terminal-capabilities.txt"
"$FFX" component route "$moniker" svc/fuchsia.hardware.pty.Device   >"$out/terminal-pty-route.txt"
"$FFX" component route "$moniker" svc/fuchsia.process.Launcher   >"$out/terminal-process-route.txt"
grep -q '/svc/fuchsia.hardware.pty.Device' "$out/terminal-capabilities.txt"
grep -q '/svc/fuchsia.process.Launcher' "$out/terminal-capabilities.txt"
if grep -Eq '/svc/fuchsia.hardware.pty.Device|/svc/fuchsia.process.Launcher'     "$out/generic-component-show.txt"; then
  echo "Generic Workbench element inherited Terminal authority" >&2
  exit 1
fi

sha256sum /workspace/artifacts/fuchsia-terminal-product.png
echo "Terminal product-session check passed: $moniker is Running with visible typed PTY output"

#!/usr/bin/env bash
set -euo pipefail
cd /workspace
product="${1:-workbench_eng.x64}"
case "$product" in
  minimal.x64) name=fuchsia-minimal-qemu ;;
  workbench_eng.x64) name=fuchsia-workbench-qemu ;;
  *) printf 'unsupported product: %s
' "$product" >&2; exit 2 ;;
esac
mkdir -p artifacts state/home/.ssh state/ffx
if [[ ! -f state/home/.ssh/fuchsia_ed25519 ]]; then
  ssh-keygen -q -P "" -t ed25519 -f state/home/.ssh/fuchsia_ed25519 -C "fuchsia-desktop-mvp@bigs"
  ssh-keygen -y -f state/home/.ssh/fuchsia_ed25519 > state/home/.ssh/fuchsia_authorized_keys
fi
sdk/packages/tools/x64/ffx emu start \
  --engine qemu --accel hyper --headless --net user --smp 8 \
  --name "$name" --startup-timeout 180 \
  --log "/workspace/artifacts/${name}.log" \
  "/workspace/product-bundles/${product}"

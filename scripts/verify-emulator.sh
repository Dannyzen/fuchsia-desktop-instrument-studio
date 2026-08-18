#!/usr/bin/env bash
set -euo pipefail
cd /workspace
FFX=sdk/packages/tools/x64/ffx
"$FFX" emu list
"$FFX" target list
"$FFX" target show
"$FFX" target ssh "echo FUCHSIA_GUEST_OK"
if "$FFX" component show /core/ui/scenic >/dev/null 2>&1; then
  "$FFX" component show /core/ui/scenic
  "$FFX" component show /core/session-manager
fi

#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
podman exec fuchsia-desktop-mvp bash -lc '
set -euo pipefail
export FUCHSIA_NODENAME=fuchsia-workbench-femu
FFX=/workspace/sdk/packages/tools/x64/ffx
"$FFX" repository server start --background --address 0.0.0.0:8083 \
  -r fuchsia-mvp --repo-path /workspace/repositories/mvp --no-device
"$FFX" target repository register -r fuchsia-mvp --alias fuchsia.com --storage-type ephemeral
/workspace/scripts/verify-browser.sh
cd /workspace/source/fuchsia/out/workbench_eng.x64-release
"$FFX" repository publish \
  --package obj/src/ui/bin/terminal/terminal_tests/package_manifest.json \
  /workspace/repositories/mvp
rm -rf /workspace/artifacts/slim-terminal-tests
cd /workspace
"$FFX" test run --output-directory /workspace/artifacts/slim-terminal-tests \
  --capture-syslog fuchsia-pkg://fuchsia.com/terminal_tests#meta/terminal_tests.cm
'

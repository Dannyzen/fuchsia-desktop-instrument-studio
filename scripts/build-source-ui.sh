#!/usr/bin/env bash
set -euo pipefail
cd /workspace/source/fuchsia
export PATH="$PWD/.jiri_root/bin:$PATH"
mkdir -p /workspace/artifacts
{
  ./scripts/fx build \
    //src/ui/examples/flatland-rainbow \
    //src/lib/ui/carnelian:examples \
    //src/chromium:web_engine \
    //src/chromium:web_engine_shell \
    //src/ui/bin/terminal:terminal \
    //src/ui/bin/terminal:tests
  ./scripts/fx build --host \
    //src/developer/ffx/frontends/ffx:ffx_bin \
    //src/developer/ffx/plugins/repository:ffx_repository_tool_host_tool
} 2>&1 | tee /workspace/artifacts/build-source-ui.log

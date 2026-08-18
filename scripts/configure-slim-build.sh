#!/usr/bin/env bash
set -euo pipefail
# The pinned tree discovers new Bazel product configs only after regenerating
# the established Workbench GN graph. Build the separate slim bundle target in
# that graph; this does not overwrite the accepted workbench_eng.x64 bundle.
/workspace/scripts/configure-source-build.sh
cd /workspace/source/fuchsia
./scripts/fx build //products/workbench:workbench_slim.x64

#!/usr/bin/env bash
set -euo pipefail
cd /workspace
source versions.env
FFX=sdk/packages/tools/x64/ffx
mkdir -p product-bundles/minimal.x64 product-bundles/workbench_eng.x64
"$FFX" product download "$MINIMAL_X64_TRANSFER" product-bundles/minimal.x64 --force
"$FFX" product download "$WORKBENCH_ENG_X64_TRANSFER" product-bundles/workbench_eng.x64 --force

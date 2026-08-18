#!/usr/bin/env bash
set -euo pipefail
cd /workspace
mkdir -p artifacts
sdk/packages/tools/x64/ffx target screenshot -d /workspace/artifacts
mv artifacts/screenshot.png "artifacts/screenshot-$(date -u +%Y%m%dT%H%M%SZ).png"

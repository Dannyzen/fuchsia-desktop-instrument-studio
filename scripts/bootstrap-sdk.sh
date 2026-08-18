#!/usr/bin/env bash
set -euo pipefail
cd /workspace
mkdir -p sdk/packages cache/cipd state/ffx state/home
cipd ensure -ensure-file cipd.ensure -root sdk/packages -cache-dir cache/cipd
sdk/packages/tools/x64/ffx sdk version
sdk/packages/tools/x64/qemu_internal/bin/qemu-system-x86_64 --version

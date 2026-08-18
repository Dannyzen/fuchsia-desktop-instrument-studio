#!/usr/bin/env bash
set -euo pipefail
cd /workspace
name="${1:-fuchsia-workbench-qemu}"
sdk/packages/tools/x64/ffx emu stop "$name"

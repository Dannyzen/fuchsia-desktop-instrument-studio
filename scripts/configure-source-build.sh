#!/usr/bin/env bash
set -euo pipefail
cd /workspace/source/fuchsia
export PATH="$PWD/.jiri_root/bin:$PATH"
./scripts/fx metrics disable
./scripts/fx set workbench_eng.x64 \
  --with //products/workbench:workbench_slim.x64 \
  --with //src/ui/examples/flatland-rainbow \
  --with //src/lib/ui/carnelian:examples \
  --with //src/ui/tests/integration_graphics_tests/web-pixel-tests:tests \
  --with //src/fuchsia-desktop/browser:package \
  --with //src/fuchsia-desktop/terminal:package \
  --with //src/fuchsia-desktop/terminal:input_driver_package \
  --with //src/fuchsia-desktop/terminal:generic_control_package \
  --with //src/fuchsia-desktop/panel-spike:package \
  --with //src/fuchsia-desktop/files:package \
  --with //src/fuchsia-desktop/files:input_driver_package \
  --with //src/fuchsia-desktop/files:generic_control_package \
  --with //src/fuchsia-desktop/settings:package \
  --with //src/fuchsia-desktop/settings:failure_package \
  --with //src/fuchsia-desktop/settings:input_driver_package \
  --with //src/ui/bin/terminal:tests \
  --with-host //scripts/fxtest/python:install \
  --release \
  --args=rust_cap_lints='"warn"' \
  --args=discoverable_package_labels='["//src/chromium:web_engine","//src/chromium:web_engine_shell","//src/fuchsia-desktop/terminal:package","//src/ui/bin/terminal:terminal"]'

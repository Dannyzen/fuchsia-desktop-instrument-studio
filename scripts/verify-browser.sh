#!/usr/bin/env bash
set -euo pipefail

cd /workspace
FFX=/workspace/sdk/packages/tools/x64/ffx
SOURCE=/workspace/source/fuchsia
OUT="$SOURCE/out/workbench_eng.x64-release"
REPO=/workspace/repositories/mvp
TARGET=//src/ui/tests/integration_graphics_tests/web-pixel-tests:web_runner_pixel_test
TEST_URL='fuchsia-pkg://fuchsia.com/web_runner_pixel_test#meta/web_runner_pixel_test_component.cm'
GTEST_FILTER='ParameterizedStaticHtmlPixelTests/StaticHtmlPixelTests.ValidPixelTest/0:ParameterizedDynamicHtmlPixelTests/DynamicHtmlPixelTests.*'
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
result_dir="/workspace/artifacts/fuchsia-browser-test-$stamp"
build_log="/workspace/artifacts/build-fuchsia-browser-$stamp.log"
run_log="/workspace/artifacts/run-fuchsia-browser-$stamp.log"

mkdir -p /workspace/artifacts

if ! "$FFX" repository server list | python3 -c 'import sys; raise SystemExit(0 if "fuchsia-mvp" in sys.stdin.read() else 1)'; then
  printf '%s\n' 'fuchsia-mvp repository server is not running' >&2
  exit 2
fi
if ! "$FFX" target repository list | python3 -c 'import sys; data=sys.stdin.read(); raise SystemExit(0 if "fuchsia-mvp" in data and "fuchsia.com" in data else 1)'; then
  printf '%s\n' 'target is not registered to fuchsia-mvp with alias fuchsia.com' >&2
  exit 2
fi

(
  cd "$SOURCE"
  ./scripts/fx build "$TARGET"
) 2>&1 | tee "$build_log"

(
  cd "$OUT"
  "$FFX" repository publish \
    --package obj/src/ui/tests/integration_graphics_tests/web-pixel-tests/web_runner_pixel_test/package_manifest.json \
    "$REPO"
)

"$FFX" test run \
  --realm /core/testing/system-tests \
  -t 240 \
  --test-filter main \
  --capture-syslog \
  --output-directory "$result_dir" \
  "$TEST_URL" -- --gtest_filter="$GTEST_FILTER" \
  2>&1 | tee "$run_log"

python3 - "$result_dir" <<'PY'
from pathlib import Path
from shutil import copy2
import sys
root = Path(sys.argv[1])
for name in (
    "fuchsia-browser.png",
    "fuchsia-browser-toolbar-active.png",
    "fuchsia-browser-address-loaded.png",
):
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise SystemExit(f"expected one {name} screenshot, found {len(matches)}")
    destination = Path("/workspace/artifacts") / name
    copy2(matches[0], destination)
    print(destination)
PY

sha256sum \
  /workspace/artifacts/fuchsia-browser.png \
  /workspace/artifacts/fuchsia-browser-toolbar-active.png \
  /workspace/artifacts/fuchsia-browser-address-loaded.png

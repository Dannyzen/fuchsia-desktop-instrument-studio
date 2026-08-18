#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
log="$project/artifacts/verify-settings-product-session.log"
output=$(podman exec fuchsia-desktop-mvp /workspace/scripts/verify-settings-product-session-inner.sh | tee "$log")
result_dir=$(printf '%s\n' "$output" | sed -n 's/^SETTINGS_RESULT_DIR=//p' | tail -n 1)
[[ "$result_dir" == /workspace/artifacts/settings-product-session-* ]]
host_result="$project${result_dir#/workspace}"
python3 "$project/scripts/assert-settings-screenshot.py" \
  "$host_result/product/screenshot.png" "$host_result/failure/screenshot.png" \
  | tee "$host_result/pixels.txt"
cp "$host_result/product/screenshot.png" "$project/artifacts/fuchsia-settings-product.png"
cp "$host_result/failure/screenshot.png" "$project/artifacts/fuchsia-settings-failure.png"
sha256sum "$project/artifacts/fuchsia-settings-product.png" \
  "$project/artifacts/fuchsia-settings-failure.png"
printf 'Fuchsia Settings product session passed: %s\n' "$host_result"

#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
log="$project/artifacts/verify-slim-product.log"
output=$(podman exec fuchsia-desktop-mvp /workspace/scripts/verify-slim-product-inner.sh | tee "$log")
result_dir=$(printf '%s\n' "$output" | sed -n 's/^SLIM_RESULT_DIR=//p' | tail -n 1)
[[ "$result_dir" == /workspace/artifacts/slim-product-session-* ]]
host_result="$project${result_dir#/workspace}"
python3 "$project/scripts/assert-example-domain-screenshot.py" "$host_result/browser/screenshot.png"
terminal_pass=''
for candidate in "$host_result"/terminal/capture-*/screenshot.png; do
  if python3 "$project/scripts/assert-terminal-screenshot.py" "$host_result/terminal/baseline.png" "$candidate" >/dev/null 2>&1; then
    terminal_pass=$candidate
    break
  fi
done
[[ -n "$terminal_pass" ]]
python3 "$project/scripts/assert-files-screenshot.py" "$host_result/files/screenshot.png"
python3 "$project/scripts/assert-settings-screenshot.py" \
  "$host_result/settings/screenshot.png" "$project/artifacts/fuchsia-settings-failure.png"
cp "$host_result/browser/screenshot.png" "$project/artifacts/fuchsia-slim-browser-external.png"
cp "$terminal_pass" "$project/artifacts/fuchsia-slim-terminal.png"
cp "$host_result/files/screenshot.png" "$project/artifacts/fuchsia-slim-files.png"
cp "$host_result/settings/screenshot.png" "$project/artifacts/fuchsia-slim-settings.png"
sha256sum "$project/artifacts/fuchsia-slim-"*.png
printf 'Self-contained slim product passed: %s\n' "$host_result"

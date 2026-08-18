#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
log="$project/artifacts/verify-four-app-session.log"
output=$(podman exec fuchsia-desktop-mvp /workspace/scripts/verify-four-app-session-inner.sh | tee "$log")
result_dir=$(printf '%s\n' "$output" | sed -n 's/^FOUR_APP_RESULT_DIR=//p' | tail -n 1)
[[ "$result_dir" == /workspace/artifacts/four-app-session-* ]]
host_result="$project${result_dir#/workspace}"
cp "$host_result/screenshot/screenshot.png" "$project/artifacts/fuchsia-four-app-session.png"
sha256sum "$project/artifacts/fuchsia-four-app-session.png"
printf 'Concurrent four-app session passed: %s\n' "$host_result"

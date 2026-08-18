#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
root="$project/source/fuchsia/src/fuchsia-desktop/settings"
rustc="$project/source/fuchsia/prebuilt/third_party/rust/linux-x64/bin/rustc"
out="$project/artifacts/settings-ui-tests"
mkdir -p "$out"
"$rustc" --test "$root/src/settings_ui.rs" --edition=2024 -o "$out/settings_ui_tests"
"$out/settings_ui_tests" --nocapture

#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
root="$project/source/fuchsia/src/fuchsia-desktop/settings"
rustc="$project/source/fuchsia/prebuilt/third_party/rust/linux-x64/bin/rustc"
out="$project/artifacts/settings-core-tests"
mkdir -p "$out"
"$rustc" --test "$root/src/settings_core.rs" --edition=2024 -o "$out/settings_core_tests"
"$out/settings_core_tests" --nocapture

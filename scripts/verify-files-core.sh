#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
root="$project/source/fuchsia/src/fuchsia-desktop/files"
rustc="$project/source/fuchsia/prebuilt/third_party/rust/linux-x64/bin/rustc"
out="$project/artifacts/files-core-tests"
mkdir -p "$out"
"$rustc" --test "$root/src/files_core.rs" --edition=2024 -o "$out/files_core_tests"
"$out/files_core_tests" --nocapture

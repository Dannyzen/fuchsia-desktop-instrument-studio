#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck disable=SC1091
source "$ROOT/versions.env"
DEST=${1:-"$ROOT/source/fuchsia"}
PIN=${FUCHSIA_SOURCE_GIT_REVISION}
mkdir -p "$(dirname "$DEST")"
if [[ -d "$DEST/.git" ]]; then
  git -C "$DEST" fetch --depth 1 origin "$PIN"
  git -C "$DEST" checkout --detach "$PIN"
else
  git clone --filter=blob:none --no-checkout https://fuchsia.googlesource.com/fuchsia "$DEST"
  git -C "$DEST" fetch --depth 1 origin "$PIN"
  git -C "$DEST" checkout --detach "$PIN"
fi
echo "Fuchsia source ready at $DEST @ $PIN"
echo "Next: $ROOT/scripts/apply-overlays.sh $DEST"

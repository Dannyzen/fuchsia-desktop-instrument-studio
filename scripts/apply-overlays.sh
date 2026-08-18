#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
FUCHSIA_ROOT=${1:-${FUCHSIA_ROOT:-}}
if [[ -z "${FUCHSIA_ROOT}" ]]; then
  echo "usage: $0 /path/to/fuchsia" >&2
  exit 2
fi
FUCHSIA_ROOT=$(cd "$FUCHSIA_ROOT" && pwd)
OVERLAY="$ROOT/overlays/fuchsia"
if [[ ! -d "$OVERLAY" ]]; then
  echo "missing overlays at $OVERLAY" >&2
  exit 1
fi
while IFS= read -r -d '' file; do
  rel=${file#"$OVERLAY/"}
  dest="$FUCHSIA_ROOT/$rel"
  mkdir -p "$(dirname "$dest")"
  cp -a "$file" "$dest"
  echo "applied $rel"
done < <(find "$OVERLAY" -type f -print0)
echo "Overlays applied to $FUCHSIA_ROOT"

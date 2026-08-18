#!/usr/bin/env bash
# Collect Fuchsia diagnostics for the Instrument Studio design feedback loop.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)

PROJECT_ROOT=${PROJECT_ROOT:-$ROOT}
MVP_ROOT=${MVP_ROOT:-/srv/bigs-runtime/workspaces/projects/fuchsia-desktop-mvp}
CONTAINER=${FUCHSIA_CONTAINER:-fuchsia-desktop-mvp}
ISOLATE_DIR=${FFX_ISOLATE_DIR:-/workspace/state/ffx}
FFX_BIN=${FFX_BIN:-/workspace/sdk/packages/tools/x64/ffx}
OUT_DIR=${1:-$PROJECT_ROOT/artifacts/diagnostics-$(date -u +%Y%m%dT%H%M%SZ)}
TIMEOUT_SEC=${DIAG_TIMEOUT_SEC:-20}

mkdir -p "$OUT_DIR"

run_ffx() {
  if command -v podman >/dev/null 2>&1 && podman container exists "$CONTAINER" >/dev/null 2>&1; then
    timeout --foreground "${TIMEOUT_SEC}s" podman exec "$CONTAINER" "$FFX_BIN" --isolate-dir "$ISOLATE_DIR" "$@"
    return $?
  fi
  if command -v ffx >/dev/null 2>&1; then
    timeout --foreground "${TIMEOUT_SEC}s" ffx "$@"
    return $?
  fi
  echo "ffx unavailable" >&2
  return 127
}

echo "Collecting diagnostics into $OUT_DIR"

set +e
run_ffx target list >"$OUT_DIR/target-list.txt" 2>&1
target_rc=$?

run_ffx --machine json inspect list >"$OUT_DIR/inspect-list.json" 2>"$OUT_DIR/inspect-list.err"
list_rc=$?

# Prefer exact component query; fall back to full show only if small path fails quickly.
run_ffx --machine json inspect show core/session-manager/session:session/tiling_wm >"$OUT_DIR/inspect-tiling_wm.json" 2>"$OUT_DIR/inspect-tiling_wm.err"
show_rc=$?
if [[ $show_rc -ne 0 || ! -s "$OUT_DIR/inspect-tiling_wm.json" ]]; then
  run_ffx --machine json inspect show tiling_wm >"$OUT_DIR/inspect-tiling_wm.json" 2>>"$OUT_DIR/inspect-tiling_wm.err"
  show_rc=$?
fi
if [[ $show_rc -ne 0 || ! -s "$OUT_DIR/inspect-tiling_wm.json" ]]; then
  # Bounded dump: selectors only if available; else skip full-system show (too large/slow).
  echo '{"note":"tiling_wm inspect node not found in live session; package rebuild/relaunch required"}' >"$OUT_DIR/inspect-tiling_wm.json"
fi

# Dump recent markers only; avoid hanging boot-wide dumps.
run_ffx log --filter TILING_WM --severity info --dump >"$OUT_DIR/tiling-wm-markers.log" 2>"$OUT_DIR/tiling-wm-markers.log.err"
run_ffx log --component tiling --severity info --dump >"$OUT_DIR/tiling-wm.log" 2>"$OUT_DIR/tiling-wm.log.err"

if [[ -d "$MVP_ROOT/artifacts" ]]; then
  newest=$(ls -1t "$MVP_ROOT/artifacts"/*.png 2>/dev/null | head -n 1 || true)
  if [[ -n "${newest:-}" ]]; then
    cp -a "$newest" "$OUT_DIR/session.png" || true
    echo "$newest" >"$OUT_DIR/session.png.source"
  fi
fi
set -e

python3 "$ROOT/scripts/design-feedback-report.py" \
  --out-dir "$OUT_DIR" \
  --design-target instrument-studio \
  >"$OUT_DIR/design-feedback.json"

echo "WROTE $OUT_DIR/design-feedback.json"
if [[ ! -s "$OUT_DIR/design-feedback.json" ]]; then
  echo "empty feedback report" >&2
  exit 1
fi

cat >"$OUT_DIR/collector-status.json" <<EOF
{"target_rc": $target_rc, "inspect_list_rc": $list_rc, "inspect_show_rc": $show_rc}
EOF

if [[ $target_rc -ne 0 ]]; then
  echo "target list failed; feedback bundle written for offline inspection" >&2
  exit 2
fi
echo "DONE $OUT_DIR"

#!/usr/bin/env bash
set -euo pipefail
project=${PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
container=fuchsia-desktop-mvp
ffx=(podman exec "$container" /workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out=${1:-$project/artifacts/starnix-gui-keyboard-$stamp}
mkdir -p "$out"

"$project/scripts/verify-slim-product.sh" >"$out/workbench-verifier.log" 2>&1
moniker='core/session-manager/session:session/elements:linux-gui'
child="$moniker/daemons:framebuffer-demo"
"${ffx[@]}" session add --name linux-gui \
  fuchsia-pkg://fuchsia.com/fuchsia_agent_linux_gui#meta/agent_linux_gui_container.cm \
  >"$out/session-add.log" 2>&1
"${ffx[@]}" component run "$child" \
  fuchsia-pkg://fuchsia.com/fuchsia_agent_linux_gui#meta/framebuffer_demo.cm \
  >"$out/component-run.log" 2>&1
sleep 4
"${ffx[@]}" component show "$moniker" >"$out/container-show.txt"
"${ffx[@]}" component show "$child" >"$out/demo-show.txt"
"${ffx[@]}" target screenshot -d "/workspace/artifacts/$(basename "$out")" --format png \
  >"$out/baseline-capture.log" 2>&1
mv "$out/screenshot.png" "$out/baseline.png"

"${ffx[@]}" component start core/session-manager/session:session/gui_input_driver \
  >"$out/keyboard-driver-start.log" 2>&1

changed=0
for attempt in $(seq 1 20); do
  sleep 1
  capture="$out/after-$attempt"
  mkdir -p "$capture"
  "${ffx[@]}" target screenshot -d "/workspace/artifacts/$(basename "$out")/after-$attempt" --format png \
    >"$capture/capture.log" 2>&1
  if python3 - "$out/baseline.png" "$capture/screenshot.png" "$capture/pixels.json" <<'PY2'
from PIL import Image
from collections import Counter
from pathlib import Path
import hashlib,json,sys
before=Path(sys.argv[1]); after=Path(sys.argv[2]); evidence=Path(sys.argv[3])
b=Image.open(before).convert('RGBA'); a=Image.open(after).convert('RGBA')
bc=Counter(b.get_flattened_data()); ac=Counter(a.get_flattened_data())
result={
  'baseline_sha256':hashlib.sha256(before.read_bytes()).hexdigest(),
  'after_sha256':hashlib.sha256(after.read_bytes()).hexdigest(),
  'dimensions':list(a.size),
  'baseline_cyan':bc[(74,213,255,255)],
  'baseline_violet':bc[(255,92,196,255)],
  'after_green':ac[(65,227,135,255)],
  'after_violet':ac[(255,92,196,255)],
  'after_cyan':ac[(74,213,255,255)],
  'after_transparent':ac[(0,0,0,0)],
  'changed':before.read_bytes()!=after.read_bytes(),
}
result['passed']=(result['dimensions']==[720,1200] and result['baseline_cyan']==432000 and result['baseline_violet']==432000 and result['after_green']==432000 and result['after_violet']==432000 and result['after_cyan']==0 and result['after_transparent']==0 and result['changed'])
evidence.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
raise SystemExit(0 if result['passed'] else 1)
PY2
  then
    cp "$capture/screenshot.png" "$out/keyboard-accepted.png"
    changed=1
    break
  fi
done
"${ffx[@]}" log --component starnix_kernel --filter FRAMEBUFFER_DEMO --no-color dump \
  >"$out/demo-log.txt" 2>&1 || true
if [ "$changed" -ne 1 ]; then
  printf 'RED: injected keyboard input did not produce the required Linux framebuffer acknowledgement\n' >&2
  exit 1
fi
printf 'GREEN: injected keyboard input changed the Linux framebuffer deterministically\n'

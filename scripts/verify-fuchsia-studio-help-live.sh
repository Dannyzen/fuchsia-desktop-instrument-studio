#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
project=${PROJECT_ROOT:-$root}
container_project=${CONTAINER_PROJECT_ROOT:-/workspace}
container=${FUCHSIA_CONTAINER:-fuchsia-desktop-mvp}
ffx=(podman exec "$container" /workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx)
out_dir=/workspace/source/fuchsia/out/workbench_eng.x64-release
bundle=$out_dir/obj/products/workbench/workbench_slim.x64/product_bundle
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$project/artifacts/fuchsia-studio-help-$stamp"
container_out="$container_project/artifacts/fuchsia-studio-help-$stamp"
mkdir -p "$out"

declare -A urls=(
  [settings]='fuchsia-pkg://fuchsia.com/fuchsia_settings#meta/fuchsia_settings.cm'
  [terminal]='fuchsia-pkg://fuchsia.com/fuchsia_terminal#meta/fuchsia_terminal.cm'
  [browser]='fuchsia-pkg://fuchsia.com/fuchsia_browser#meta/fuchsia_browser.cm'
)
declare -A collections=(
  [settings]='settings_elements'
  [terminal]='terminal_elements'
  [browser]='browser_elements'
)
declare -A names monikers
for app in settings terminal browser; do
  names[$app]="studio-help-$app-$stamp"
  monikers[$app]="core/session-manager/session:session/${collections[$app]}:${names[$app]}"
done

cleanup() {
  for app in settings terminal browser; do
    "${ffx[@]}" session remove "${names[$app]}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

"${ffx[@]}" emu stop fuchsia-workbench-qemu >/dev/null 2>&1 || true
"${ffx[@]}" emu stop fuchsia-workbench-femu >/dev/null 2>&1 || true
"${ffx[@]}" emu start \
  --engine femu --gpu swiftshader_indirect --accel hyper --headless \
  --net user --smp 8 --name fuchsia-workbench-femu --startup-timeout 180 \
  --log "$container_out/emulator.log" "$bundle"
export FUCHSIA_NODENAME=fuchsia-workbench-femu
"${ffx[@]}" target wait -t 180

for app in settings terminal browser; do
  "${ffx[@]}" session add --name "${names[$app]}" "${urls[$app]}" \
    >"$out/$app-session-add.log" 2>&1
  for _ in $(seq 1 45); do
    "${ffx[@]}" component show "${monikers[$app]}" >"$out/$app-show.txt" 2>&1 || true
    grep -q 'Execution State:  Running' "$out/$app-show.txt" && break
    sleep 1
  done
  grep -q 'Execution State:  Running' "$out/$app-show.txt"
done

for _ in $(seq 1 30); do
  "${ffx[@]}" --machine json inspect show \
    core/session-manager/session:session/tiling_wm >"$out/inspect.json" 2>"$out/inspect.err" || true
  if python3 - "$out/inspect.json" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(1)
values={}
def walk(x):
    if isinstance(x,dict):
        for k,v in x.items():
            if k in {'tile_count','status','confirmed'} and not isinstance(v,(dict,list)):
                values.setdefault(k,[]).append(v)
            walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(data)
assert 3 in values.get('tile_count',[]), values
assert 'OK' in values.get('status',[]), values
PY
  then
    break
  fi
  sleep 1
done

python3 - "$out/inspect.json" <<'PY'
import json, sys
values={}
def walk(x):
    if isinstance(x,dict):
        for k,v in x.items():
            if k in {'tile_count','status','confirmed'} and not isinstance(v,(dict,list)):
                values.setdefault(k,[]).append(v)
            walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
data=json.load(open(sys.argv[1])); walk(data)
assert 3 in values.get('tile_count',[]), values
assert 'OK' in values.get('status',[]), values
print('inspect',values)
PY

"${ffx[@]}" component start core/session-manager/session:session/tiling_wm_driver \
  >"$out/focus-driver-start.log" 2>&1
for _ in $(seq 1 30); do
  "${ffx[@]}" --machine json inspect show \
    core/session-manager/session:session/tiling_wm >"$out/inspect-focused.json" 2>/dev/null || true
  if python3 - "$out/inspect-focused.json" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(1)
confirmed=[]
def walk(x):
    if isinstance(x,dict):
        for k,v in x.items():
            if k=='confirmed' and isinstance(v,str): confirmed.append(v)
            walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(data)
assert any('terminal' in value.lower() for value in confirmed), confirmed
PY
  then
    break
  fi
  sleep 1
done
python3 - "$out/inspect-focused.json" <<'PY'
import json, sys
confirmed=[]
def walk(x):
    if isinstance(x,dict):
        for k,v in x.items():
            if k=='confirmed' and isinstance(v,str): confirmed.append(v)
            walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(json.load(open(sys.argv[1])))
assert any('terminal' in value.lower() for value in confirmed), confirmed
print('focused', confirmed)
PY

"${ffx[@]}" target screenshot -d "$container_out"
mv "$out/screenshot.png" "$out/before-help.png"
"${ffx[@]}" component start core/session-manager/session:session/terminal_input_driver \
  >"$out/input-driver-start.log" 2>&1

visible=0
for attempt in $(seq 1 25); do
  sleep 1
  attempt_dir="$container_out/capture-$attempt"
  mkdir -p "$out/capture-$attempt"
  "${ffx[@]}" target screenshot -d "$attempt_dir"
  if python3 "$root/scripts/assert-terminal-screenshot.py" \
    "$out/before-help.png" "$out/capture-$attempt/screenshot.png" \
    >"$out/capture-$attempt/assert.txt" 2>&1; then
    cp "$out/capture-$attempt/screenshot.png" "$out/screenshot.png"
    visible=1
    break
  fi
done
[[ "$visible" == 1 ]]

"${ffx[@]}" component show "${monikers[terminal]}" >"$out/terminal-show.txt"
"${ffx[@]}" component route "${monikers[terminal]}" \
  svc/fuchsia.starnix.container.Controller >"$out/controller-route.txt"
grep -q 'fuchsia.starnix.container.Controller' "$out/controller-route.txt"
grep -q 'Success' "$out/controller-route.txt"
"${ffx[@]}" component show core/session-manager/session:session/tiling_wm \
  >"$out/tiling-wm-show.txt"

podman exec -i "$container" python3 - "$out_dir" <<'PY' >"$out/built-merkles.json"
import json,sys
from pathlib import Path
out=Path(sys.argv[1])
paths={
 'terminal':out/'obj/src/fuchsia-desktop/terminal/package/package_manifest.json',
 'tiling_wm':out/'obj/src/ui/bin/tiling_wm/tiling_wm/package_manifest.json',
}
result={}
for name,path in paths.items():
    data=json.load(open(path))
    result[name]=next(b['merkle'] for b in data['blobs'] if b.get('path')=='meta/')
print(json.dumps(result,sort_keys=True))
PY

python3 - "$out" <<'PY'
import json,re,sys
from pathlib import Path
out=Path(sys.argv[1])
built=json.load(open(out/'built-merkles.json'))
def live(name):
    text=(out/f'{name}-show.txt').read_text()
    match=re.search(r'Merkle root:\s+([0-9a-f]{64})',text)
    assert match, f'missing live merkle in {name}'
    return match.group(1)
actual={'terminal':live('terminal'),'tiling_wm':live('tiling-wm')}
assert actual==built,(actual,built)
receipt={'built':built,'live':actual,'equal':True}
(out/'merkle-receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps(receipt,sort_keys=True))
PY

sha256sum "$out/screenshot.png" "$out/inspect.json" "$out/merkle-receipt.json" \
  >"$out/SHA256SUMS"
printf 'FUCHSIA_STUDIO_HELP_LIVE=PASS\nRESULT_DIR=%s\n' "$out"

#!/usr/bin/env bash
set -euo pipefail
project=${PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
container=fuchsia-desktop-mvp
lock="$project/config/starnix-agent-package-lock.json"
cache="$project/cache/alpine-v3.19"
[[ $(hostname) == bigs ]]
: # public package: set PROJECT_ROOT explicitly when needed
[[ -f "$lock" ]]

mapfile -t files < <(python3 - "$lock" "$cache" <<'PYLOCK'
from pathlib import Path
import hashlib,json,re,sys
lock=Path(sys.argv[1]); cache=Path(sys.argv[2])
data=json.loads(lock.read_text())
assert data['schema_version']==1
assert data['alpine_branch']=='v3.19'
assert data['architecture']=='x86_64'
for item in data['packages']:
    name=item['file']
    if not re.fullmatch(r'[A-Za-z0-9._+\-]+\.apk',name):
        raise SystemExit(f'invalid locked filename: {name}')
    p=cache/name
    raw=p.read_bytes()
    if len(raw)!=item['bytes']:
        raise SystemExit(f'length mismatch: {name}')
    got=hashlib.sha256(raw).hexdigest()
    if got!=item['sha256']:
        raise SystemExit(f'hash mismatch: {name}: {got}')
    print(name)
PYLOCK
)
((${#files[@]} > 0))
"$project/scripts/starnix-agent-exec.sh" "install -d -m 700 /tmp/agent-apks"
container_paths=()
for name in "${files[@]}"; do container_paths+=("/workspace/cache/alpine-v3.19/$name"); done
podman exec "$container" scp -F none -P 17000   -i ${AGENT_SSH_KEY:?set AGENT_SSH_KEY}   -o BatchMode=yes -o IdentitiesOnly=yes   -o StrictHostKeyChecking=yes   -o UserKnownHostsFile=${AGENT_KNOWN_HOSTS:-${PROJECT_ROOT:-.}/state/agent-linux/known_hosts}   "${container_paths[@]}" root@127.0.0.1:/tmp/agent-apks/
python3 - "$lock" <<'PYHASH' | "$project/scripts/starnix-agent-exec.sh" "sha256sum -c -"
from pathlib import Path
import json,sys
data=json.loads(Path(sys.argv[1]).read_text())
for item in data['packages']:
    print(f"{item['sha256']}  /tmp/agent-apks/{item['file']}")
PYHASH
remote_command=$(python3 - "$lock" <<'PYCMD'
from pathlib import Path
import json,shlex,sys
data=json.loads(Path(sys.argv[1]).read_text())
files=[f"/tmp/agent-apks/{x['file']}" for x in data['packages']]
packages=[x['package'] for x in data['packages']]
cmd=['apk','add','--no-network','--force-non-repository',*files]
checks=[]
for package in packages:
    checks.extend(['&&','apk','info','-e',package])
print(' '.join(shlex.quote(x) if x != '&&' else x for x in [*cmd,*checks]))
PYCMD
)
"$project/scripts/starnix-agent-exec.sh" "$remote_command"
"$project/scripts/starnix-agent-exec.sh" "jq --version"
printf 'FUCHSIA_AGENT_PACKAGES_READY lock=%s packages=%s\n' "$lock" "${files[*]}"

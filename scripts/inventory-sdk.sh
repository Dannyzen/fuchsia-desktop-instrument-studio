#!/usr/bin/env bash
set -euo pipefail
cd /workspace
printf '== CIPD ==
'
cipd version
printf '
== package tree ==
'
python3 - <<'PY2'
from pathlib import Path
for p in sorted(Path('sdk/packages').rglob('*')):
    if p.is_file() and (p.stat().st_mode & 0o111 or p.name.endswith(('.json','.manifest'))):
        print(p, p.stat().st_size)
PY2
printf '
== candidate binaries ==
'
python3 - <<'PY2'
from pathlib import Path
for name in ('ffx','qemu-system-x86_64','emulator'):
    for p in Path('sdk/packages').rglob(name):
        print(name, p)
PY2

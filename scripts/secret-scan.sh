#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
python3 "$ROOT/scripts/public_readiness_scan.py" "$ROOT"   --terms "BEGIN OPENSSH PRIVATE KEY,BEGIN RSA PRIVATE KEY,id_ed25519,ghp_,gho_,github_pat_"   --max-samples 50 > /tmp/instrument-studio-secret-scan.json
python3 - <<'PY'
import json
import sys
from pathlib import Path
rep = json.loads(Path('/tmp/instrument-studio-secret-scan.json').read_text())
print(Path('/tmp/instrument-studio-secret-scan.json').read_text())
bad = 0
tracked = rep['tracked_scan']
for key in ['secrets']:
    total = int(tracked[key]['total'])
    print(f'tracked.{key}={total}')
    bad += total
hist = int(rep['history_scan']['secrets']['total'])
print(f'history.secrets={hist}')
bad += hist
forbidden_names = {'authorized_keys', 'id_ed25519', 'id_rsa', '.env'}
for p in Path('.').rglob('*'):
    if not p.is_file() or '.git' in p.parts:
        continue
    if p.name.endswith('.template') or p.name.endswith('.example'):
        continue
    if p.name in forbidden_names or p.suffix == '.pem':
        print('forbidden file', p)
        bad += 1
if bad:
    print('SECRET_SCAN_FAIL')
    sys.exit(1)
print('SECRET_SCAN_PASS')
PY

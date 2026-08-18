#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
python3 "$ROOT/scripts/public_readiness_scan.py" "$ROOT" \
  --terms "BEGIN OPENSSH PRIVATE KEY,BEGIN RSA PRIVATE KEY" \
  --max-samples 50 > /tmp/instrument-studio-secret-scan.json
python3 - <<'PY'
import json
import re
import sys
from pathlib import Path

rep = json.loads(Path("/tmp/instrument-studio-secret-scan.json").read_text())
ignore_names = {"public_readiness_scan.py", "secret-scan.sh"}
real_secret = re.compile(
    r"BEGIN [A-Z ]*PRIVATE KEY|"
    r"ghp_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"gho_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}"
)
bad = 0
for section in (
    rep["tracked_scan"]["secrets"]["samples"],
    rep["history_scan"]["secrets"]["samples"],
):
    for sample in section:
        path = Path(sample["path"]).name
        if path in ignore_names:
            continue
        text = sample.get("text", "")
        if not real_secret.search(text):
            continue
        print("secret_hit", sample)
        bad += 1

forbidden_names = {"authorized_keys", "id_ed25519", "id_rsa", ".env"}
for p in Path(".").rglob("*"):
    if not p.is_file() or ".git" in p.parts or ".jj" in p.parts:
        continue
    if p.name.endswith(".template") or p.name.endswith(".example"):
        continue
    if p.name in forbidden_names or p.suffix == ".pem":
        print("forbidden file", p)
        bad += 1

if bad:
    print("SECRET_SCAN_FAIL", bad)
    sys.exit(1)
print("SECRET_SCAN_PASS")
print("tracked_files", rep["tracked_files"])
print("raw_secret_total", rep["tracked_scan"]["secrets"]["total"])
PY

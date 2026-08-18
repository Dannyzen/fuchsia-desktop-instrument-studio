#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
out="$project/source/fuchsia/out/workbench_eng.x64-release"
execroot="$out/gen/build/bazel/output_base/execroot/_main"
image="$execroot/bazel-out/fuchsia_sdk_x64-opt/bin/products/workbench/assembly_slim.x64_product_assembly_out/image_assembly.json"
delivery="$out/obj/products/workbench/workbench_slim.x64/product_bundle/blobs/1"
readarray -t embedded < <(python3 - "$image" "$execroot" <<'PYINNER'
import json, sys
from pathlib import Path
data = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
for wanted in ("fuchsia_browser", "web_engine", "fuchsia_terminal", "fuchsia_files", "fuchsia_settings", "workbench_session"):
    matches = []
    for tier in ("system", "base", "cache", "on_demand", "bootfs_packages"):
        for rel in data.get(tier, []):
            path = root / rel
            try:
                name = json.load(open(path))["package"]["name"]
            except Exception:
                continue
            if name == wanted:
                matches.append(str(path))
    if len(matches) != 1:
        raise SystemExit(f"{wanted}: expected one manifest, got {matches}")
    print(matches[0])
PYINNER
)
python3 "$project/scripts/measure-product-closure.py" \
  --image-assembly "$image" --execroot "$execroot" --delivery-dir "$delivery" \
  --app "browser=${embedded[0]},${embedded[1]}" \
  --app "terminal=${embedded[2]}" \
  --app "files=${embedded[3]}" \
  --app "settings=${embedded[4]}" \
  --app "session=${embedded[5]}" \
  --output-json "$project/artifacts/workbench-closure-slim.json" \
  --output-md "$project/artifacts/workbench-closure-slim.md"
sha256sum "$project/artifacts/workbench-closure-slim.json" \
  "$project/artifacts/workbench-closure-slim.md"

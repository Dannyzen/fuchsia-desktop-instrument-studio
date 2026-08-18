#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
[[ -n "${ALLOW_NON_BIGS:-}" || "$(hostname)" == "bigs" ]]
: # public package: set PROJECT_ROOT explicitly when needed
out="$project/source/fuchsia/out/workbench_eng.x64-release"
execroot="$out/gen/build/bazel/output_base/execroot/_main"
image="$execroot/bazel-out/fuchsia_sdk_x64-opt/bin/products/workbench/assembly_eng.x64_product_assembly_out/image_assembly.json"
delivery="$out/obj/products/workbench/workbench_eng.x64/product_bundle/blobs/1"
readarray -t embedded < <(python3 - "$image" "$execroot" <<'PYINNER'
import json, sys
from pathlib import Path
data = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
for wanted in ("web_engine", "fuchsia_terminal", "workbench_session"):
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
  --app "browser=$out/obj/src/fuchsia-desktop/browser/package/package_manifest.json,${embedded[0]}" \
  --app "terminal=${embedded[1]}" \
  --app "files=$out/obj/src/fuchsia-desktop/files/package/package_manifest.json" \
  --app "settings=$out/obj/src/fuchsia-desktop/settings/package/package_manifest.json" \
  --app "session=${embedded[2]}" \
  --output-json "$project/artifacts/workbench-closure-baseline.json" \
  --output-md "$project/artifacts/workbench-closure-baseline.md"
sha256sum "$project/artifacts/workbench-closure-baseline.json" \
  "$project/artifacts/workbench-closure-baseline.md"

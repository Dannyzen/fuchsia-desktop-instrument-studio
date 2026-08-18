#!/usr/bin/env bash
set -euo pipefail

FFX=${FFX:-/workspace/sdk/packages/tools/x64/ffx}
BROWSER_URL=fuchsia-pkg://fuchsia.com/fuchsia_browser#meta/fuchsia_browser.cm
name="fuchsia-browser-route-proof-$(date -u +%Y%m%dT%H%M%SZ)"
moniker="core/session-manager/session:session/browser_elements:$name"
out="/workspace/artifacts/browser-product-session-$name"
mkdir -p "$out"

cleanup() {
  "$FFX" session remove "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$FFX" session add --name "$name" "$BROWSER_URL" | tee "$out/session-add.log"

state=""
for _ in $(seq 1 30); do
  if "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1; then
    state=$(sed -n 's/^[[:space:]]*Execution State:[[:space:]]*//p' "$out/component-show.txt" | head -n 1)
    if [[ "$state" == "Running" || "$state" == "Stopped" ]]; then
      break
    fi
  fi
  sleep 1
done

if [[ "$state" == "Running" ]]; then
  for _ in $(seq 1 10); do
    sleep 1
    "$FFX" component show "$moniker" >"$out/component-show.txt" 2>&1 || true
    state=$(sed -n 's/^[[:space:]]*Execution State:[[:space:]]*//p' "$out/component-show.txt" | head -n 1)
    [[ "$state" == "Running" ]] || break
  done
fi

"$FFX" log --component "$name" --since "5m ago" --no-color dump >"$out/component.log" 2>&1 || true
"$FFX" target screenshot -d "$out"
mv "$out/screenshot.png" "$out/external-page.png"
cp "$out/external-page.png" /workspace/artifacts/fuchsia-browser-product-external.png

if [[ "$state" != "Running" ]]; then
  echo "Browser element did not remain running, state=${state:-unresolved}" >&2
  sed -n '1,220p' "$out/component-show.txt" >&2 || true
  sed -n '1,220p' "$out/component.log" >&2 || true
  exit 1
fi

if grep -E 'fuchsia.web.ContextProvider.*not available|NavigationController.*PEER_CLOSED|No capability available.*ContextProvider|VmexResource.Get|RenderProcess gone|page_type=Some\(Error\)|LoadFailed|error=Some\(Crash\)' "$out/component.log"; then
  echo "Browser product-session capability check failed" >&2
  exit 1
fi

if ! grep -F 'title=Some("Example Domain")' "$out/component.log" >/dev/null; then
  echo "External page title was not observed" >&2
  exit 1
fi
if ! grep -F 'loaded=Some(true)' "$out/component.log" >/dev/null; then
  echo "External page did not report loaded=true" >&2
  exit 1
fi

python3 /workspace/scripts/assert-example-domain-screenshot.py "$out/external-page.png"

sha256sum "$out/external-page.png"
echo "Browser product-session external-page check passed: $moniker is Running"

#!/usr/bin/env bash
set -euo pipefail
project=${PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
container=fuchsia-desktop-mvp
out=/workspace/source/fuchsia/out/starnix_agent.x64-release
ffx=(/workspace/sdk/packages/tools/x64/ffx --isolate-dir /workspace/state/ffx)

[[ $(hostname) == bigs ]]
: # public package: set PROJECT_ROOT explicitly when needed
[[ -n "${AGENT_SSH_KEY:-}" && -f "${AGENT_SSH_KEY}" ]]
: > "$project/state/agent-linux/known_hosts"
chmod 600 "$project/state/agent-linux/known_hosts"

podman exec "$container" "${ffx[@]}" component run -r   core/starnix_runner/playground:agent-linux   fuchsia-pkg://fuchsia.com/alpine#meta/alpine_container.cm

podman exec "$container" "${ffx[@]}" component run -r   core/starnix_runner/playground:agent-linux/daemons:sshd   fuchsia-pkg://fuchsia.com/fuchsia_agent_linux#meta/agent_linux_sshd.cm

podman exec "$container" python3 /workspace/scripts/starnix-agent-forward.py

for _ in $(seq 1 60); do
  if podman exec "$container" ssh       -F none -p 17000 -i ${AGENT_SSH_KEY:?set AGENT_SSH_KEY}       -o BatchMode=yes -o IdentitiesOnly=yes       -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${AGENT_KNOWN_HOSTS:-${PROJECT_ROOT:-.}/state/agent-linux/known_hosts}       -o ConnectTimeout=1 root@127.0.0.1 true >/dev/null 2>&1; then
    printf '%s
' 'FUCHSIA_AGENT_LINUX_READY'
    exit 0
  fi
  sleep 1
done
printf '%s
' 'agent Linux SSH did not become ready' >&2
exit 1

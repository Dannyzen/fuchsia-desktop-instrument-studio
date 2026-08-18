#!/usr/bin/env bash
set -euo pipefail
container=fuchsia-desktop-mvp
timeout_seconds=${FUCHSIA_AGENT_TIMEOUT_SECONDS:-120}
if [[ $# -eq 0 ]]; then
  printf 'usage: %s <remote command> [arguments...]
' "$0" >&2
  exit 64
fi
podman exec "$container" python3 /workspace/scripts/starnix-agent-forward.py >/dev/null
exec podman exec -i "$container" timeout --foreground "${timeout_seconds}s"   ssh -F none -p 17000 -i ${AGENT_SSH_KEY:?set AGENT_SSH_KEY to your local private key path}   -o BatchMode=yes -o IdentitiesOnly=yes   -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${AGENT_KNOWN_HOSTS:-${PROJECT_ROOT:-.}/state/agent-linux/known_hosts}   -o ConnectTimeout=5 -o ServerAliveInterval=15 -o ServerAliveCountMax=2   root@127.0.0.1 "$@"

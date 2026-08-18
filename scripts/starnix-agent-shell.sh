#!/usr/bin/env bash
set -euo pipefail
container=fuchsia-desktop-mvp
podman exec "$container" python3 /workspace/scripts/starnix-agent-forward.py >/dev/null
exec podman exec -it "$container" ssh -tt   -F none -p 17000 -i ${AGENT_SSH_KEY:?set AGENT_SSH_KEY to your local private key path}   -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes   -o UserKnownHostsFile=${AGENT_KNOWN_HOSTS:-${PROJECT_ROOT:-.}/state/agent-linux/known_hosts} root@127.0.0.1

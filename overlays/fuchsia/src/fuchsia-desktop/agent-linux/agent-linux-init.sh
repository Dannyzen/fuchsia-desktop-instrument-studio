#!/bin/sh
set -eu
umask 077
state=/tmp/fuchsia-agent-linux
auth_dir=/root/.ssh
rm -rf "$state"
mkdir -p "$state" "$auth_dir"
chmod 700 "$auth_dir"
cp data/authorized_keys "$auth_dir/authorized_keys"
chmod 600 "$auth_dir/authorized_keys"
printf '%s\n' 'nameserver 10.0.2.3' 'options timeout:2 attempts:3' > /etc/resolv.conf
chmod 644 /etc/resolv.conf
ssh-keygen -q -t ed25519 -N '' -f "$state/ssh_host_ed25519_key"
printf '%s
' 'FUCHSIA_AGENT_LINUX_SSHD_READY port=7000 auth=publickey' >&2
exec /usr/sbin/sshd -D -e   -f data/agent-sshd_config   -o "AuthorizedKeysFile=$auth_dir/authorized_keys"   -o "HostKey=$state/ssh_host_ed25519_key"

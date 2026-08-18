#!/usr/bin/env python3
"""Idempotently map container-local TCP 17000 to Fuchsia guest TCP 7000."""
from __future__ import annotations
import json
import re
import socket
import time

MONITOR = "/workspace/state/ffx/data/emu/instances/fuchsia-workbench-femu/monitor"
HOST_PORT = 17000
GUEST_PORT = 7000


def command(sock: socket.socket, text: str) -> str:
    sock.sendall((text + "\n").encode())
    deadline = time.monotonic() + 2.0
    chunks: list[bytes] = []
    while time.monotonic() < deadline:
        try:
            part = sock.recv(65536)
        except TimeoutError:
            break
        if not part:
            break
        chunks.append(part)
        if b"(qemu)" in b"".join(chunks):
            break
    return b"".join(chunks).decode("utf-8", "replace")


def mappings(text: str) -> list[tuple[int, int]]:
    found=[]
    for line in text.splitlines():
        if "TCP[HOST_FORWARD]" not in line:
            continue
        cols=line.split()
        if len(cols) >= 6:
            try:
                found.append((int(cols[3]), int(cols[5])))
            except ValueError:
                pass
    return found


with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(0.4)
    sock.connect(MONITOR)
    try:
        sock.recv(65536)
    except TimeoutError:
        pass
    before=command(sock,"info usernet")
    pairs=mappings(before)
    if (HOST_PORT,GUEST_PORT) not in pairs:
        conflict=[p for p in pairs if p[0] == HOST_PORT and p[1] != GUEST_PORT]
        if conflict:
            raise SystemExit(f"host port {HOST_PORT} already maps to {conflict[0][1]}")
        response=command(sock,f"hostfwd_add net0 tcp:127.0.0.1:{HOST_PORT}-:{GUEST_PORT}")
        if "could not set up host forwarding rule" in response.lower():
            raise SystemExit(response.strip())
        after=command(sock,"info usernet")
        pairs=mappings(after)
    if (HOST_PORT,GUEST_PORT) not in pairs:
        raise SystemExit(f"forward not observed: {pairs}")
print(json.dumps({"status":"ready","listen_namespace":"lab-container","host":"127.0.0.1","host_port":HOST_PORT,"guest_port":GUEST_PORT},sort_keys=True))

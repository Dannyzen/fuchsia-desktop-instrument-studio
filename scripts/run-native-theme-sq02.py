#!/usr/bin/env python3
"""Stdlib-only SQ-02 outer launcher and OS network-namespace proof."""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


FIXED = {
    "CARGO_NET_OFFLINE": "true", "LANG": "C", "LC_ALL": "C",
    "NATIVE_THEME_SQ02_NETWORK": "deny", "PYTHONHASHSEED": "0",
    "RUSTUP_NO_UPDATE_CHECK": "1", "TZ": "UTC",
}
STATIC_FILES = (
    "scripts/run-native-theme-sq02.py", "scripts/test-native-theme-sq02.py",
    "tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py",
    "tools/native_theme/sq02-rust-qualifier/Cargo.toml",
    "tools/native_theme/sq02-rust-qualifier/Cargo.lock",
    "tools/native_theme/sq02-rust-qualifier/rust-toolchain.toml",
    "tools/native_theme/sq02-rust-qualifier/src/main.rs",
)
PROBE = """import errno,json,socket
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
try:
 s.connect(('192.0.2.1',9)); print(json.dumps({'blocked':False,'error_class':'NONE'},sort_keys=True,separators=(',',':')))
except OSError as e:
 print(json.dumps({'blocked':e.errno in (errno.ENETUNREACH,errno.ENETDOWN,errno.EHOSTUNREACH),'error_class':errno.errorcode.get(e.errno,'OTHER')},sort_keys=True,separators=(',',':')))
finally:
 s.close()
"""


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source-sha", required=True)
    result.add_argument("--output-dir", default="artifacts/quality/sq-02")
    result.add_argument("--cargo")
    result.add_argument("--rustc")
    result.add_argument("--cargo-home")
    result.add_argument("--target-root")
    result.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    return result


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def static_scan(repo: Path) -> None:
    for relative in STATIC_FILES:
        path = repo / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("static source inventory missing or symlinked")
        raw = path.read_bytes()
        if relative.endswith(".py"):
            tree = ast.parse(raw, filename=relative)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                    raise RuntimeError("dynamic execution hook rejected")
                if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                       and keyword.value.value is True for keyword in node.keywords):
                    raise RuntimeError("shell execution hook rejected")
    qualifier = repo / "tools/native_theme/sq02-rust-qualifier"
    if (qualifier / "build.rs").exists() or b"proc-macro" in (qualifier / "Cargo.toml").read_bytes():
        raise RuntimeError("build script or proc macro rejected")


def resolved_tools(repo: Path, args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    cargo = args.cargo or os.environ.get("SQ02_CARGO")
    rustc = args.rustc or os.environ.get("SQ02_RUSTC")
    if not cargo:
        cargo = str(repo / "source/fuchsia-full/prebuilt/third_party/rust/linux-x64/bin/cargo")
    if not rustc:
        rustc = str(repo / "source/fuchsia-full/prebuilt/third_party/rust/linux-x64/bin/rustc")
    cargo_path, rustc_path = Path(cargo), Path(rustc)
    for path, name in ((cargo_path, "cargo"), (rustc_path, "rustc")):
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK) or path.name != name:
            raise RuntimeError(f"resolved {name} unavailable")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        expected = repo / "source/fuchsia-full/prebuilt/third_party/rust/linux-x64/bin"
        if cargo_path.resolve() != (expected / "cargo").resolve() or rustc_path.resolve() != (expected / "rustc").resolve():
            raise RuntimeError("Bigs qualification requires the project Fuchsia prebuilt toolchain")
    workspace_parent = next((parent for parent in repo.parents if parent.name == "workspaces"), None)
    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        task_root = Path(runner_temp)
    elif workspace_parent is not None:
        task_root = workspace_parent / "tmp"
    else:
        raise RuntimeError("project temporary root unavailable")
    lane = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:12]
    task = f"sq02-{args.source_sha[:12]}-{lane}"
    cargo_home = Path(args.cargo_home or os.environ.get("SQ02_CARGO_HOME", str(task_root / f"{task}-cargo-home")))
    target_root = Path(args.target_root or os.environ.get("SQ02_TARGET_ROOT", str(task_root / f"{task}-target")))
    if not cargo_home.is_absolute() or not target_root.is_absolute() or cargo_home == target_root:
        raise RuntimeError("task-unique Cargo roots must be distinct absolute paths")
    if not os.environ.get("GITHUB_ACTIONS"):
        try:
            cargo_home.relative_to(task_root)
            target_root.relative_to(task_root)
        except ValueError as exc:
            raise RuntimeError("Bigs Cargo and target state must be project temporary state") from exc
    return cargo_path.resolve(), rustc_path.resolve(), cargo_home, target_root


def namespace_identity() -> str:
    value = os.readlink("/proc/self/ns/net")
    if not value.startswith("net:[") or not value.endswith("]"):
        raise RuntimeError("network namespace identity unavailable")
    return value


def allowed_launcher_command(argv: object, *, phase: str) -> bool:
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(item, str) for item in argv):
        return False
    names = [Path(item).name for item in argv]
    if phase == "selection":
        if names[0] == "unshare":
            return tuple(argv[1:-1]) == ("-Urn", "--") and names[-1] == "true"
        return (len(names) == 6 and names[0] == "sudo" and argv[1] == "-n" and
                names[2] == "unshare" and tuple(argv[3:5]) == ("-n", "--") and names[5] == "true")
    if phase == "socket-probe":
        return len(argv) == 5 and Path(argv[0]).resolve() == Path(sys.executable).resolve() and tuple(argv[1:4]) == ("-I", "-S", "-c") and argv[4] == PROBE
    return False


def run_allowed(argv: object, *, phase: str, **kwargs: object) -> subprocess.CompletedProcess:
    if kwargs.get("shell") or not allowed_launcher_command(argv, phase=phase):
        raise RuntimeError("launcher command rejected by allowlist")
    return subprocess.run(argv, shell=False, **kwargs)


def choose_namespace() -> tuple[str, list[str]]:
    unshare = shutil.which("unshare", path="/usr/bin:/bin")
    env = shutil.which("env", path="/usr/bin:/bin")
    true = shutil.which("true", path="/usr/bin:/bin")
    if not unshare or not env or not true:
        raise RuntimeError("namespace tools unavailable")
    candidate = [unshare, "-Urn", "--", true]
    if run_allowed(candidate, phase="selection", check=False, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL).returncode == 0:
        return "unprivileged-user-network", [unshare, "-Urn", "--"]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        sudo = shutil.which("sudo", path="/usr/bin:/bin")
        if sudo:
            candidate = [sudo, "-n", unshare, "-n", "--", true]
            if run_allowed(candidate, phase="selection", check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL).returncode == 0:
                return "ci-sudo-network", [sudo, "-n", unshare, "-n", "--"]
    raise RuntimeError("OS network namespace unavailable")


def enter(args: argparse.Namespace) -> NoReturn:
    repo = root()
    static_scan(repo)
    cargo, rustc, cargo_home, target_root = resolved_tools(repo, args)
    mode, prefix = choose_namespace()
    parent = namespace_identity()
    env_tool = shutil.which("env", path="/usr/bin:/bin")
    if env_tool is None:
        raise RuntimeError("env tool unavailable")
    forwarded = [
        "--source-sha", args.source_sha, "--output-dir", args.output_dir,
        "--cargo", str(cargo), "--rustc", str(rustc), "--cargo-home", str(cargo_home),
        "--target-root", str(target_root), "--inside",
    ]
    assignments = [f"{key}={value}" for key, value in sorted(FIXED.items())] + [
        f"NATIVE_THEME_SQ02_PARENT_NETNS={parent}", f"NATIVE_THEME_SQ02_NAMESPACE_MODE={mode}",
        "NATIVE_THEME_SQ02_TOOLCHAIN_ORIGIN=" + ("hosted-official-nightly" if os.environ.get("GITHUB_ACTIONS") == "true" else "project-fuchsia-prebuilt"),
        "PATH=/usr/bin:/bin",
    ]
    command = [*prefix, env_tool, "-i", *assignments, str(Path(sys.executable).absolute()), "-I",
               str(Path(__file__).resolve()), *forwarded]
    os.execve(command[0], command, {"PATH": "/usr/bin:/bin"})


def inside(args: argparse.Namespace) -> NoReturn:
    repo = root()
    static_scan(repo)
    parent = os.environ.get("NATIVE_THEME_SQ02_PARENT_NETNS")
    mode = os.environ.get("NATIVE_THEME_SQ02_NAMESPACE_MODE")
    current = namespace_identity()
    if not parent or current == parent or mode not in ("unprivileged-user-network", "ci-sudo-network"):
        raise RuntimeError("network namespace did not change")
    result = run_allowed([str(Path(sys.executable).absolute()), "-I", "-S", "-c", PROBE],
                         phase="socket-probe", check=False, capture_output=True, text=True,
                         env={**FIXED, "PATH": "/usr/bin:/bin"})
    try:
        proof = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("raw socket probe malformed") from exc
    if result.returncode != 0 or proof.get("blocked") is not True or proof.get("error_class") not in ("ENETUNREACH", "ENETDOWN", "EHOSTUNREACH"):
        raise RuntimeError("raw child socket was not OS-blocked")
    normalized = {
        "child_raw_socket_blocked": True, "error_class": proof["error_class"],
        "namespace_changed": True, "namespace_mode": mode, "parent_identity_compared": True,
    }
    environment = {**os.environ, "NATIVE_THEME_SQ02_NAMESPACE_PROVED": "true",
                   "NATIVE_THEME_SQ02_ISOLATION_JSON": json.dumps(normalized, sort_keys=True, separators=(",", ":"))}
    inner = repo / "scripts/test-native-theme-sq02.py"
    forwarded = [item for item in sys.argv[1:] if item != "--inside"]
    command = [str(Path(sys.executable).absolute()), "-I", str(inner), *forwarded]
    os.execve(command[0], command, environment)


def main() -> int:
    args = parser().parse_args()
    try:
        if args.inside:
            inside(args)
        enter(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"CI_TOOLCHAIN_INFRASTRUCTURE: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

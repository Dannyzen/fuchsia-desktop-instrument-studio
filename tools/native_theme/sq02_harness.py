#!/usr/bin/env python3
"""Repository-owned NativeTheme SQ-02 qualification and receipt producer.

This module is the inner gate.  It assumes the stdlib-only outer launcher has
already established and proved an OS network namespace.  It has no approval,
merge, release, runtime, Product Assembly, or independent-verdict authority.
"""

from __future__ import annotations

import ast
from collections import Counter
import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, NoReturn
import urllib.request


BASE_SHA = "036944123fa15d5b5fac5718899b08a44691727c"
FUCHSIA_REVISION = "7f75b7f6ffdacf5a818dd8d207263edd45126ddd"
PINNED = {"coverage": "7.6.12", "jsonschema": "4.25.1"}
RUST_PIN = "nightly-2026-08-13"
RECEIPTS = (
    "source-toolchain-manifest.json",
    "cross-language-parity.json",
    "fuzz-corpus-manifest.json",
    "resource-bounds.json",
    "coverage.json",
    "reproducible-builds.json",
    "package-and-catalog-scan.json",
    "verdict.json",
)
VERDICT_INPUTS = RECEIPTS[:-1]
REQUIREMENT_IDS = (
    "SQ02-BOUNDARY-262143",
    "SQ02-BOUNDARY-262144",
    "SQ02-BOUNDARY-262145",
    "SQ02-CORPUS-ALL",
    "SQ02-DIAGNOSTICS",
    "SQ02-FULL-FILE-HASH",
    "SQ02-PACKAGES-5",
    "SQ02-RETAINED-BYTES",
    "SQ02-SEMANTIC-HASH",
)
ALLOWED_TRACKED_PATHS = {
    ".github/workflows/ci.yml",
    "overlays/fuchsia/src/fuchsia-desktop/theme_model/BUILD.gn",
    "overlays/fuchsia/src/fuchsia-desktop/theme_model/src/qualification.rs",
    "scripts/run-native-theme-sq02.py",
    "scripts/test-native-theme-sq02-harness.py",
    "scripts/test-native-theme-sq02-receipts.py",
    "scripts/test-native-theme-sq02.py",
    "tools/native_theme/sq02-requirements.txt",
    "tools/native_theme/sq02_harness.py",
    "tools/native_theme/sq02_receipt_verifier.py",
    "tools/native_theme/sq02-rust-qualifier/Cargo.lock",
    "tools/native_theme/sq02-rust-qualifier/Cargo.toml",
    "tools/native_theme/sq02-rust-qualifier/rust-toolchain.toml",
    "tools/native_theme/sq02-rust-qualifier/src/main.rs",
}
ENVIRONMENT = {
    "CARGO_NET_OFFLINE": "true",
    "LANG": "C",
    "LC_ALL": "C",
    "NATIVE_THEME_SQ02_NETWORK": "deny",
    "PYTHONHASHSEED": "0",
    "RUSTUP_NO_UPDATE_CHECK": "1",
    "TZ": "UTC",
}
CORPUS_SEED = 0
CORPUS_VERSION = "sq02-corpus-v1"
CORPUS_OPERATORS = (
    "asset-boundary",
    "byte-flip",
    "duplicate-key",
    "hash-tamper",
    "insertion",
    "invalid-utf8",
    "nesting-boundary",
    "nonfinite",
    "provenance-tamper",
    "schema-version",
    "semantic-failure",
    "string-boundary",
    "token-boundary",
    "truncation",
    "valid-inert-metadata",
    "whitespace-noncanonical",
)
PRIVATE_PATTERNS = (
    re.compile(rb"/(?:home|Users|srv)/[^\s\"']+"),
    re.compile(rb"(?i)(?:api[_-]?key|authorization|bearer|client[_-]?secret)\s*[:=]"),
    re.compile(b"(?i)(?:\\." + b"beads|kan" + b"ban|her" + b"mes[_-]?(?:task|session|run)|orchestration[_-]?id)"),
)
_PRODUCTION_CACHE: dict[str, tuple[Any, Any]] = {}


class QualificationError(RuntimeError):
    """Stable classified gate failure."""

    def __init__(self, classification: str, message: str):
        self.classification = classification
        self.message = message
        super().__init__(f"{classification}: {message}")


def fail(classification: str, message: str) -> NoReturn:
    raise QualificationError(classification, message)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError) as exc:
        fail("CI_RECEIPT_INVALID", f"non-canonical value: {type(exc).__name__}")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw: bytes, *, final_lf: bool = True) -> Any:
    if final_lf and (not raw.endswith(b"\n") or raw.endswith(b"\n\n")):
        fail("CI_INPUT_INVALID", "JSON requires exactly one final LF")
    body = raw[:-1] if final_lf else raw
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                fail("CI_INPUT_INVALID", "duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(body.decode("utf-8", "strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _value: fail("CI_INPUT_INVALID", "nonfinite JSON"))
    except QualificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        fail("CI_INPUT_INVALID", f"JSON parse failed: {type(exc).__name__}")
    if final_lf and canonical_json_bytes(value) != raw:
        fail("CI_INPUT_INVALID", "JSON is not canonical")
    return value


def install_python_network_denial():
    """Defense in depth only; OS namespace evidence is produced by the launcher."""
    originals = (socket.socket.connect, socket.create_connection, urllib.request.urlopen)
    def denied(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise PermissionError("sq-02 defense-in-depth network denial")
    socket.socket.connect = denied
    socket.create_connection = denied
    urllib.request.urlopen = denied
    def restore() -> None:
        socket.socket.connect, socket.create_connection, urllib.request.urlopen = originals
    return restore


def allowed_subprocess(argv: object, root: Path, *, cargo: Path | None = None,
                       rustc: Path | None = None) -> bool:
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(item, str) for item in argv):
        return False
    executable = Path(argv[0]).name
    tail = tuple(argv[1:])
    if executable == "git":
        return tail in {
            ("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
            ("status", "--porcelain=v1", "--untracked-files=all"), ("ls-files",),
        } or (len(tail) == 3 and tail[:2] == ("diff", "--name-only")) or (
            len(tail) == 3 and tail[:2] == ("archive", "--format=tar")
        )
    if cargo is not None and Path(argv[0]).resolve() == cargo.resolve():
        if tail == ("--version", "--verbose"):
            return True
        required = ("run", "--locked", "--offline", "--manifest-path")
        return tail[:4] == required and "--target-dir" in tail and "--" in tail and tail[-4] == "--packages" and tail[-2] == "--corpus"
    if rustc is not None and Path(argv[0]).resolve() == rustc.resolve():
        return tail == ("--version", "--verbose")
    if Path(argv[0]).resolve() == Path(sys.executable).resolve() and len(tail) >= 3 and tail[:2] == ("-m", "coverage"):
        if tail[2] == "run":
            return "--branch" in tail and any(item.endswith(("test-native-theme-sq02-harness.py", "test-native-theme-sq02-receipts.py")) for item in tail)
        if tail[2] == "json":
            return "-o" in tail
    return False


def run_allowed(argv: object, root: Path, *, cargo: Path | None = None,
                rustc: Path | None = None, **kwargs: Any) -> subprocess.CompletedProcess:
    if kwargs.get("shell") or not allowed_subprocess(argv, root, cargo=cargo, rustc=rustc):
        fail("CI_COMMAND_DENIED", "subprocess command is outside the SQ-02 allowlist")
    return subprocess.run(argv, cwd=root, shell=False, **kwargs)


def _git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    command = ["git", *args]
    allowed = {
        ("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"),
        ("status", "--porcelain=v1", "--untracked-files=all"), ("ls-files",),
    }
    if tuple(args) not in allowed and not (len(args) == 3 and args[:2] == ("diff", "--name-only")):
        fail("CI_COMMAND_DENIED", "undeclared git command")
    result = run_allowed(command, root, check=True, capture_output=True, text=not binary)
    return result.stdout


def source_identity(root: Path, output: Path, expected_sha: str) -> tuple[str, str]:
    sha = str(_git(root, "rev-parse", "HEAD")).strip()
    tree = str(_git(root, "rev-parse", "HEAD^{tree}")).strip()
    if sha != expected_sha or not re.fullmatch(r"[0-9a-f]{40}", sha):
        fail("CI_SOURCE_IDENTITY", "source SHA mismatch")
    dirty = str(_git(root, "status", "--porcelain=v1", "--untracked-files=all")).splitlines()
    try:
        excluded = output.resolve().relative_to(root.resolve()).as_posix() + "/"
    except ValueError:
        excluded = ""
    remaining = [row for row in dirty if not (excluded and row[3:].startswith(excluded))]
    if remaining:
        fail("CI_SOURCE_DIRTY", "tracked or non-output source changes present")
    changed = set(str(_git(root, "diff", "--name-only", f"{BASE_SHA}..{sha}")).splitlines())
    unexpected = sorted(changed - ALLOWED_TRACKED_PATHS)
    if unexpected:
        fail("CI_SOURCE_SCOPE", "changed tracked path outside SQ-02 allowlist")
    return sha, tree


def validate_output(root: Path, output: Path) -> Path:
    expected = (root / "artifacts/quality/sq-02").resolve()
    candidate = output.resolve(strict=False)
    if candidate != expected:
        fail("CI_OUTPUT_PATH", "authoritative output must be artifacts/quality/sq-02")
    if any(path.is_symlink() for path in [output, *output.parents] if path != Path("/")):
        fail("CI_OUTPUT_PATH", "output path contains a symlink")
    return candidate


def static_scan(root: Path) -> dict[str, Any]:
    scan_paths = [
        "scripts/run-native-theme-sq02.py", "scripts/test-native-theme-sq02.py",
        "tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py",
        "tools/native_theme/sq02-rust-qualifier/Cargo.toml",
        "tools/native_theme/sq02-rust-qualifier/Cargo.lock",
        "tools/native_theme/sq02-rust-qualifier/rust-toolchain.toml",
        "tools/native_theme/sq02-rust-qualifier/src/main.rs",
    ]
    hashes: dict[str, str] = {}
    for relative in scan_paths:
        raw = (root / relative).read_bytes()
        hashes[relative] = sha256(raw)
        if relative.endswith("main.rs") and any(token in raw for token in (
            b"std::net", b"std::process::Command", b"include_str!(\"/", b"include_bytes!(\"/",
        )):
            fail("CI_STATIC_SCAN", "Rust qualifier has forbidden authority")
        if relative.endswith(".py"):
            try:
                tree = ast.parse(raw, filename=relative)
            except SyntaxError:
                fail("CI_STATIC_SCAN", f"Python syntax failed in {relative}")
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                    fail("CI_STATIC_SCAN", f"dynamic execution hook in {relative}")
                if any(keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                       and keyword.value.value is True for keyword in node.keywords):
                    fail("CI_STATIC_SCAN", f"shell execution hook in {relative}")
    qualifier = root / "tools/native_theme/sq02-rust-qualifier"
    if (qualifier / "build.rs").exists() or list(qualifier.rglob("*.so")):
        fail("CI_STATIC_SCAN", "build script or plugin artifact present")
    manifest = (qualifier / "Cargo.toml").read_text(encoding="utf-8")
    dependencies = re.findall(r"^(\w[\w-]*)\s*=\s*\"=([^\"]+)\"$", manifest, re.MULTILINE)
    if dependencies != [("hex", "0.4.3"), ("serde_json", "1.0.149"), ("sha2", "0.11.0")]:
        fail("CI_STATIC_SCAN", "Cargo direct dependency inventory drift")
    if "default = []" not in manifest or "proc-macro" in manifest:
        fail("CI_STATIC_SCAN", "Cargo feature or proc-macro policy drift")
    return {"files": hashes, "passed": True, "reviewed_direct_dependencies": dict(dependencies)}


def _load_production(root: Path):
    identity = str(root.resolve())
    if identity in _PRODUCTION_CACHE:
        return _PRODUCTION_CACHE[identity]
    native = root / "tools/native_theme"
    old_path = list(sys.path)
    for name in list(sys.modules):
        if name in {"catalog", "compiler_core", "native_theme_v1"} or name == "adapters" or name.startswith("adapters."):
            sys.modules.pop(name, None)
    sys.path.insert(0, str(native))
    try:
        import catalog  # type: ignore
        import native_theme_v1  # type: ignore
        _PRODUCTION_CACHE[identity] = (catalog, native_theme_v1)
        return _PRODUCTION_CACHE[identity]
    finally:
        sys.path[:] = old_path


def build_packages(root: Path, destination: Path) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    catalog, contract = _load_production(root)
    descriptor_raw = (root / "tools/native_theme/catalog/catalog-source.json").read_bytes()
    descriptor = strict_json(descriptor_raw)
    source_paths = {descriptor["template_path"], *(row["source_path"] for row in descriptor["entries"])}
    supplied = {path: (root / path).read_bytes() for path in sorted(source_paths)}
    artifacts = catalog.generate_catalog(descriptor, supplied)
    destination.mkdir(parents=True, exist_ok=False)
    packages: list[dict[str, Any]] = []
    for row in descriptor["entries"]:
        filename = f"{row['id']}.package.json"
        raw = artifacts[filename]
        value = strict_json(raw)
        contract.validate_package(value)
        semantic = contract.package_semantic_identity(value).removeprefix("sha256:")
        (destination / filename).write_bytes(raw)
        packages.append({"bytes": len(raw), "file": filename, "id": row["id"],
                         "semantic_sha256": semantic, "sha256": sha256(raw)})
    legacy_raw = (root / "tools/native_theme/fixtures/native-theme-v1-package.json").read_bytes()
    legacy_value = strict_json(legacy_raw)
    contract.validate_package(legacy_value)
    legacy_name = "instrument-studio-legacy.package.json"
    (destination / legacy_name).write_bytes(legacy_raw)
    packages.append({"bytes": len(legacy_raw), "file": legacy_name,
                     "id": "instrument-studio-legacy",
                     "semantic_sha256": contract.package_semantic_identity(legacy_value).removeprefix("sha256:"),
                     "sha256": sha256(legacy_raw)})
    if len(packages) != 5:
        fail("CI_PACKAGE_PARITY", "exact five-package inventory missing")
    manifest = {"packages": packages, "schema_version": "sq02-package-input-v1"}
    (destination / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return packages, artifacts


def package_with_exact_length(root: Path, target: int) -> bytes:
    _, contract = _load_production(root)
    value = strict_json((root / "tools/native_theme/fixtures/native-theme-v1-package.json").read_bytes())
    baseline = contract.canonical_json_bytes(value) + b"\n"
    empty = 0
    selected: tuple[int, int] | None = None
    for index in range(128):
        key = f"org.constructresearch.instrumentstudio.boundary_padding_{index:03}"
        empty += len(key) + 6
        if target >= len(baseline) + empty:
            payload = target - len(baseline) - empty
            if payload <= (index + 1) * contract.LIMITS["string_bytes"]:
                selected = index + 1, payload
                break
    if selected is None:
        fail("CI_BOUNDARY", "exact boundary is unreachable")
    chunks, payload = selected
    extensions = value["metadata"]["extensions"]
    for index in range(chunks):
        amount = min(payload, contract.LIMITS["string_bytes"])
        payload -= amount
        extensions[f"org.constructresearch.instrumentstudio.boundary_padding_{index:03}"] = "x" * amount
    raw = contract.canonical_json_bytes(value) + b"\n"
    if len(raw) != target:
        fail("CI_BOUNDARY", "constructed boundary length drift")
    return raw


def python_decode(root: Path, raw: bytes, *, compiler_layer: bool = False) -> dict[str, Any]:
    _, contract = _load_production(root)
    if len(raw) > contract.LIMITS["compiled_pack_bytes"]:
        code = "E_CANONICAL_SIZE" if compiler_layer else "E_LIMIT_PACK"
        return {"accepted": False, "code": code, "layer": "compiler" if compiler_layer else "bounds"}
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError:
        return {"accepted": False, "code": "E_UTF8", "layer": "json"}
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                raise contract.ContractError("E_JSON_DUPLICATE: duplicate key")
            result[key] = value
        return result
    try:
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise contract.ContractError("E_JSON_NONCANONICAL: final LF")
        value = json.loads(text[:-1], object_pairs_hook=pairs,
                           parse_constant=lambda _value: (_ for _ in ()).throw(
                               contract.ContractError("E_NUMBER_NONFINITE: nonfinite")))
        if contract.canonical_json_bytes(value) + b"\n" != raw:
            raise contract.ContractError("E_JSON_NONCANONICAL: bytes")
        contract.validate_package(value)
        semantic = contract.package_semantic_identity(value)
        if value["metadata"]["provenance"]["semantic_hash"] != semantic:
            raise contract.ContractError("E_HASH: semantic identity hash mismatch")
        return {"accepted": True, "code": None, "layer": "accepted", "package_sha256": sha256(raw),
                "semantic_sha256": semantic.removeprefix("sha256:")}
    except contract.ContractError as exc:
        match = re.match(r"^(E_[A-Z0-9_]+)", str(exc))
        code = match.group(1) if match else "E_CONTRACT"
    except (json.JSONDecodeError, RecursionError, ValueError):
        code = "E_JSON_MALFORMED"
    layer = "json" if code.startswith(("E_JSON", "E_UTF8", "E_NUMBER")) else (
        "bounds" if code.startswith("E_LIMIT") else "contract")
    return {"accepted": False, "code": code, "layer": layer}


def _mutated_value(root: Path, case_id: str) -> dict[str, Any]:
    value = strict_json((root / "tools/native_theme/fixtures/native-theme-v1-package.json").read_bytes())
    value["metadata"]["extensions"][f"org.constructresearch.instrumentstudio.case_{case_id}"] = True
    return value


def generate_corpus(root: Path, destination: Path) -> tuple[dict[str, Any], bytes]:
    _, contract = _load_production(root)
    rng = random.Random(CORPUS_SEED)
    destination.mkdir(parents=True, exist_ok=False)
    cases: list[dict[str, Any]] = []
    hashes: set[str] = set()
    operators = list(CORPUS_OPERATORS)
    rng.shuffle(operators)
    for round_index in range(16):
        for operator in operators:
            case_id = f"case-{round_index:02}-{operator}"
            value = _mutated_value(root, case_id)
            raw: bytes
            if operator == "valid-inert-metadata":
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "byte-flip":
                value["metadata"]["extensions"][f"org.constructresearch.instrumentstudio.flip_{round_index:02}"] = "a"
                raw = (contract.canonical_json_bytes(value) + b"\n").replace(b'\":\"a\"', b'\":\"b\"', 1)
            elif operator == "truncation":
                raw = (contract.canonical_json_bytes(value) + b"\n")[:-(round_index + 1)]
            elif operator == "insertion":
                raw = contract.canonical_json_bytes(value) + (b" " * (round_index + 1)) + b"\n"
            elif operator == "duplicate-key":
                raw = (b'{"case":"' + case_id.encode() + b'","case":"duplicate"}\n')
            elif operator == "invalid-utf8":
                raw = b'{"case":"' + case_id.encode() + b'\xff"}\n'
            elif operator == "nonfinite":
                raw = b'{"case":"' + case_id.encode() + b'","value":NaN}\n'
            elif operator == "whitespace-noncanonical":
                raw = (b"{" + b" " * (round_index + 1) + contract.canonical_json_bytes(value)[1:] + b"\n")
            elif operator == "nesting-boundary":
                raw = (b'{"case":"' + case_id.encode() + b'","value":' + b"[" * 34 + b"0" + b"]" * 34 + b"}\n")
            elif operator == "string-boundary":
                value["metadata"]["extensions"][f"org.constructresearch.instrumentstudio.string_{round_index:02}"] = "x" * (4097 + round_index)
                raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            elif operator == "token-boundary":
                current = sum(len(variant[layer]) for variant in value["variants"].values()
                              for layer in ("primitives", "semantic", "components"))
                for index in range(1025 - current):
                    value["variants"]["dark"]["primitives"][f"extra{round_index:02}_{index:04}"] = "#000000ff"
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "asset-boundary":
                items = value["variants"]["dark"]["assets"]["items"]
                template = next(iter(items.values()))
                for index in range(len(items), 65):
                    items[f"extra.asset.{round_index:02}.{index:02}"] = json.loads(json.dumps(template))
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "provenance-tamper":
                value["metadata"]["provenance"]["source_identity"] = f"../case-{round_index:02}"
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "hash-tamper":
                value["metadata"]["provenance"]["semantic_hash"] = "sha256:" + sha256(case_id.encode())
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "semantic-failure":
                value["variants"]["dark"]["semantic"]["border.focusConfirmed"] = value["variants"]["dark"]["semantic"]["interaction.selection"]
                raw = contract.canonical_json_bytes(value) + b"\n"
            elif operator == "schema-version":
                value["schema_version"] = f"2.0.{round_index}"
                raw = contract.canonical_json_bytes(value) + b"\n"
            else:  # pragma: no cover - inventory is asserted before execution
                fail("CI_CORPUS", "unknown mutation operator")
            result = python_decode(root, raw)
            digest = sha256(raw)
            if digest in hashes:
                fail("CI_CORPUS", "duplicate corpus byte hash")
            hashes.add(digest)
            filename = f"{case_id}.bin"
            (destination / filename).write_bytes(raw)
            rust_code = {"hash-tamper": "E_HASH", "provenance-tamper": "E_IDENTITY"}.get(
                operator, result["code"])
            cases.append({
                "accepted_package_sha256": result.get("package_sha256"),
                "accepted_semantic_sha256": result.get("semantic_sha256"),
                "file": filename, "id": case_id, "mutation_operator": operator,
                "python_accepted": result["accepted"], "python_code": result["code"],
                "python_layer": result["layer"], "rust_accepted": result["accepted"],
                "rust_code": rust_code, "sha256": digest,
            })
    if len(cases) != 256 or set(Counter(row["mutation_operator"] for row in cases)) != set(CORPUS_OPERATORS):
        fail("CI_CORPUS", "corpus inventory drift")
    manifest = {"cases": cases, "generator_version": CORPUS_VERSION, "schema_version": "sq02-corpus-input-v1",
                "seed": CORPUS_SEED}
    raw_manifest = canonical_json_bytes(manifest)
    (destination / "manifest.json").write_bytes(raw_manifest)
    all_bytes = b"".join((destination / row["file"]).read_bytes() for row in cases)
    return manifest, all_bytes


def _binary_record(path: Path, expected_name: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if resolved.name != expected_name:
        fail("CI_TOOLCHAIN_INFRASTRUCTURE", f"resolved {expected_name} name mismatch")
    admitted = {expected_name: resolved}
    result = run_allowed([str(resolved), "--version", "--verbose"], resolved.parent,
                         cargo=admitted.get("cargo"), rustc=admitted.get("rustc"), check=True,
                         capture_output=True, text=True, env={**os.environ, **ENVIRONMENT})
    version = "\n".join(line.strip() for line in result.stdout.splitlines() if line.strip())
    if expected_name == "rustc" and "nightly" not in version:
        fail("CI_TOOLCHAIN_INFRASTRUCTURE", "rustc is not nightly")
    return {"binary_sha256": sha256(resolved.read_bytes()), "name": expected_name, "version": version}


def run_cargo(root: Path, cargo: Path, rustc: Path, cargo_home: Path, target: Path,
              package_dir: Path, corpus_dir: Path) -> tuple[dict[str, Any], bytes]:
    if not cargo_home.is_absolute() or not target.is_absolute() or cargo_home == target:
        fail("CI_TOOLCHAIN_INFRASTRUCTURE", "Cargo state roots must be distinct absolute paths")
    cargo_home.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)
    manifest = root / "tools/native_theme/sq02-rust-qualifier/Cargo.toml"
    command = [str(cargo.resolve()), "run", "--locked", "--offline", "--manifest-path", str(manifest),
               "--target-dir", str(target), "--", "--packages", str(package_dir), "--corpus", str(corpus_dir)]
    env = {**os.environ, **ENVIRONMENT, "CARGO_HOME": str(cargo_home), "RUSTC": str(rustc.resolve())}
    result = run_allowed(command, root, cargo=cargo, rustc=rustc, check=False,
                         capture_output=True, text=True, env=env)
    if result.returncode != 0:
        classification = "CI_TOOLCHAIN_INFRASTRUCTURE" if any(
            marker in result.stderr.lower() for marker in ("no matching package", "download", "not found", "toolchain")) else "CI_QUALIFICATION_FAILURE"
        fail(classification, "locked offline Cargo qualifier failed")
    lines = [line for line in result.stdout.splitlines() if line.startswith("SQ02_RUST:")]
    if len(lines) != 1:
        fail("CI_QUALIFICATION_FAILURE", "Rust qualifier did not emit exactly one record")
    raw = lines[0].removeprefix("SQ02_RUST:").encode("ascii") + b"\n"
    parsed = strict_json(raw)
    if parsed.get("requirement_ids") != list(REQUIREMENT_IDS):
        fail("CI_QUALIFICATION_FAILURE", "Rust requirement inventory mismatch")
    return parsed, raw


def payload(root: Path, workspace: Path, cargo: Path, rustc: Path, cargo_home: Path,
            target: Path) -> dict[str, Any]:
    scan = static_scan(root)
    package_dir = workspace / "packages"
    corpus_dir = workspace / "corpus"
    packages, catalog_artifacts = build_packages(root, package_dir)
    descriptor = strict_json((root / "tools/native_theme/catalog/catalog-source.json").read_bytes())
    source_sizes = [(root / descriptor["template_path"]).stat().st_size]
    source_sizes.extend((root / row["source_path"]).stat().st_size for row in descriptor["entries"])
    for size in (262143, 262144, 262145):
        (package_dir / f"boundary-{size}.json").write_bytes(package_with_exact_length(root, size))
    corpus_manifest, corpus_bytes = generate_corpus(root, corpus_dir)
    rust, rust_raw = run_cargo(root, cargo, rustc, cargo_home, target, package_dir, corpus_dir)
    python_boundary = []
    for size in (262143, 262144, 262145):
        raw = (package_dir / f"boundary-{size}.json").read_bytes()
        contract_result = python_decode(root, raw)
        compiler_result = python_decode(root, raw, compiler_layer=True)
        python_boundary.append({"bytes": size, "compiler": compiler_result, "contract": contract_result})
    diagnostic_mapping = []
    for operator in CORPUS_OPERATORS:
        rows = [row for row in corpus_manifest["cases"] if row["mutation_operator"] == operator]
        diagnostic_mapping.append({
            "mutation_operator": operator,
            "python_accepted": sorted({row["python_accepted"] for row in rows}),
            "python_codes": sorted({row["python_code"] for row in rows}, key=lambda item: "" if item is None else item),
            "rust_accepted": sorted({row["rust_accepted"] for row in rows}),
            "rust_codes": sorted({row["rust_code"] for row in rows}, key=lambda item: "" if item is None else item),
        })
    return {
        "catalog": {name: {"bytes": len(raw), "sha256": sha256(raw)} for name, raw in sorted(catalog_artifacts.items())},
        "corpus_bytes_sha256": sha256(corpus_bytes),
        "corpus_manifest_sha256": sha256(canonical_json_bytes(corpus_manifest)),
        "diagnostic_mapping": diagnostic_mapping,
        "packages": packages,
        "python_boundaries": python_boundary,
        "rust": rust,
        "rust_raw_sha256": sha256(rust_raw),
        "size_observations": {
            "catalog_bytes": sum(len(raw) for raw in catalog_artifacts.values()),
            "largest_catalog_receipt_bytes": max(len(raw) for name, raw in catalog_artifacts.items() if name.endswith(".receipt.json")),
            "largest_package_bytes": max(row["bytes"] for row in packages),
            "largest_source_bytes": max(source_sizes),
        },
        "static_scan": scan,
    }


def authority_scan(root: Path, receipts: dict[str, bytes]) -> dict[str, Any]:
    tracked = str(_git(root, "ls-files")).splitlines()
    changed = set(str(_git(root, "diff", "--name-only", f"{BASE_SHA}..HEAD")).splitlines())
    findings: list[dict[str, str]] = []
    for relative in sorted(changed):
        path = root / relative
        if path.is_symlink() or ".." in PurePosixPath(relative).parts:
            findings.append({"code": "E_PATH_AUTHORITY", "file": relative})
            continue
        raw = path.read_bytes()
        for pattern in PRIVATE_PATTERNS:
            if pattern.search(raw):
                findings.append({"code": "E_PRIVATE_OR_SECRET", "file": relative})
                break
    for name, raw in receipts.items():
        if any(pattern.search(raw) for pattern in PRIVATE_PATTERNS):
            findings.append({"code": "E_PRIVATE_OR_SECRET", "file": name})
    build = (root / "overlays/fuchsia/src/fuchsia-desktop/theme_model/BUILD.gn").read_text()
    qualification_block = build[build.index('rustc_test("theme_model_qualification")'):]
    forbidden_edges = [token for token in ("fuchsia_package", "fuchsia_component", "resource", "product_assembly", "runtime_deps")
                       if token in qualification_block]
    catalog_descriptor = strict_json((root / "tools/native_theme/catalog/catalog-source.json").read_bytes())
    catalog_build = (root / "overlays/fuchsia/src/fuchsia-desktop/theme_catalog/BUILD.gn").read_text()
    catalog_copy_only = catalog_build.lstrip().startswith('copy("catalog_artifacts")') and all(
        token not in catalog_build for token in ("fuchsia_package", "fuchsia_component", "resource", "product_assembly"))
    return {
        "audited_authority_files": sorted(relative for relative in changed if relative.endswith((".py", ".rs"))),
        "bounded_lexical_scan": True, "catalog_copy_only": catalog_copy_only,
        "catalog_entry_count": len(catalog_descriptor["entries"]), "changed_files_scanned": len(changed),
        "findings": findings, "fuchsia_forbidden_edges": forbidden_edges,
        "qualification_testonly": "testonly = true" in qualification_block,
        "receipts_scanned": 8, "tracked_files_considered": len(tracked),
    }


def coverage_machine_sha256(machine: dict[str, Any]) -> str:
    normalized = json.loads(json.dumps(machine))
    normalized.get("meta", {}).pop("timestamp", None)
    return sha256(canonical_json_bytes(normalized))


def measure_coverage(root: Path, workspace: Path) -> tuple[dict[str, dict[str, int]], str]:
    workspace.mkdir(parents=True, exist_ok=False)
    data_file = workspace / ".coverage-sq02"
    report_file = workspace / "coverage-machine.json"
    include = ",".join(str(root / name) for name in (
        "tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py"))
    environment = {**os.environ, **ENVIRONMENT, "COVERAGE_FILE": str(data_file), "PYTHONDONTWRITEBYTECODE": "1"}
    tests = ("scripts/test-native-theme-sq02-harness.py", "scripts/test-native-theme-sq02-receipts.py")
    for index, test in enumerate(tests):
        command = [str(Path(sys.executable).absolute()), "-m", "coverage", "run"]
        if index:
            command.append("--append")
        command.extend(["--branch", f"--include={include}", test])
        result = run_allowed(command, root, check=False, capture_output=True, text=True, env=environment)
        if result.returncode != 0:
            fail("CI_COVERAGE", "coverage test execution failed")
    command = [str(Path(sys.executable).absolute()), "-m", "coverage", "json", "-o", str(report_file)]
    result = run_allowed(command, root, check=False, capture_output=True, text=True, env=environment)
    if result.returncode != 0:
        fail("CI_COVERAGE", "coverage machine report failed")
    machine_raw = report_file.read_bytes()
    machine = json.loads(machine_raw)
    metrics: dict[str, dict[str, int]] = {}
    for relative in ("tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py"):
        candidates = [row for name, row in machine["files"].items() if name.replace("\\", "/").endswith(relative)]
        if len(candidates) != 1:
            fail("CI_COVERAGE", f"coverage module missing: {relative}")
        row = candidates[0]
        summary = row["summary"]
        executed = set(row["executed_lines"])
        tree = ast.parse((root / relative).read_bytes(), filename=relative)
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        body_executed = 0
        for function in functions:
            body_lines = {getattr(node, "lineno", -1) for statement in function.body for node in ast.walk(statement)
                          if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if executed & body_lines:
                body_executed += 1
        metric = {
            "branches_covered": summary["covered_branches"], "branches_total": summary["num_branches"],
            "functions_with_body_execution": body_executed, "functions_total": len(functions),
            "statements_covered": summary["covered_lines"], "statements_total": summary["num_statements"],
        }
        if metric["statements_covered"] != metric["statements_total"] or metric["branches_covered"] != metric["branches_total"] or metric["functions_with_body_execution"] != metric["functions_total"]:
            fail("CI_COVERAGE", f"safety-bearing coverage gap in {relative}")
        metrics[relative] = metric
    return metrics, coverage_machine_sha256(machine)


def _tracked_hashes(root: Path) -> dict[str, str]:
    return {relative: sha256((root / relative).read_bytes()) for relative in str(_git(root, "ls-files")).splitlines()}


def write_receipts(root: Path, output: Path, source_sha: str, source_tree: str,
                   isolation: dict[str, Any], cargo: Path, rustc: Path, first: dict[str, Any],
                   second: dict[str, Any], coverage_metrics: dict[str, dict[str, int]],
                   coverage_artifact_sha256: str) -> dict[str, bytes]:
    runtime = {name: importlib.metadata.version(name) for name in sorted(PINNED)}
    if runtime != PINNED:
        fail("CI_TOOLCHAIN_INFRASTRUCTURE", "Python dependency version drift")
    python_version = ".".join(map(str, sys.version_info[:3]))
    cargo_record = _binary_record(cargo, "cargo")
    rustc_record = _binary_record(rustc, "rustc")
    receipts: dict[str, bytes] = {}
    manifest = {
        "authority": "non-authoritative-harness", "base_sha": BASE_SHA,
        "command_schema": "scripts/run-native-theme-sq02.py --source-sha SHA --output-dir artifacts/quality/sq-02 --cargo PATH --rustc PATH --cargo-home PATH --target-root PATH",
        "environment": ENVIRONMENT, "fuchsia_pinned_revision": FUCHSIA_REVISION,
        "os_isolation": isolation, "python_dependencies": runtime, "python_version": python_version,
        "qualification_inputs": {"catalog": first["catalog"], "corpus_bytes_sha256": first["corpus_bytes_sha256"],
        "corpus_manifest_sha256": first["corpus_manifest_sha256"], "packages": first["packages"],
        "rust_record_sha256": first["rust_raw_sha256"]},
        "source_sha": source_sha, "source_tree": source_tree, "toolchain": {"cargo": cargo_record, "rustc": rustc_record,
        "origin": os.environ.get("NATIVE_THEME_SQ02_TOOLCHAIN_ORIGIN"), "rust_channel": RUST_PIN},
        "tracked_source_hashes": _tracked_hashes(root),
    }
    receipts[RECEIPTS[0]] = canonical_json_bytes(manifest)
    parity = {
        "diagnostic_mapping": first["diagnostic_mapping"], "package_count": 5, "packages": first["packages"], "python_rust_corpus_accepted": first["rust"]["corpus"]["accepted"],
        "python_rust_corpus_executed": first["rust"]["corpus"]["executed"],
        "python_rust_corpus_rejected": first["rust"]["corpus"]["rejected"],
        "requirement_ids": first["rust"]["requirement_ids"], "rust_record_sha256": first["rust_raw_sha256"],
        "schema_version": "sq02-cross-language-parity-v1", "status": "PASS",
    }
    receipts[RECEIPTS[1]] = canonical_json_bytes(parity)
    counts = {operator: 16 for operator in CORPUS_OPERATORS}
    fuzz = {
        "duplicate_hashes": 0, "duplicate_ids": 0, "executed": 256,
        "generator_source_sha256": sha256((root / "tools/native_theme/sq02_harness.py").read_bytes()),
        "generator_version": CORPUS_VERSION, "manifest_sha256": first["corpus_manifest_sha256"],
        "operator_counts": counts, "python_rust_parity": 256, "seed": CORPUS_SEED,
        "skipped": 0, "total_generated": 256,
    }
    receipts[RECEIPTS[2]] = canonical_json_bytes(fuzz)
    bounds = {
        "dominated_relations": [{"dominated": "runtime_snapshot_bytes", "proof": "compiled_pack_bytes <= runtime_snapshot_bytes",
                                 "stricter": "compiled_pack_bytes"}],
        "limits": {"assets": 64, "catalog_bytes": 8388608, "compiled_pack_bytes": 262144,
                   "receipt_bytes": 16384, "runtime_snapshot_bytes": 524288, "source_bytes": 1048576,
                   "string_bytes": 4096, "tokens": 1024},
        "observations": {**first["size_observations"],
                         "executed_asset_plus_one_cases": 16,
                         "executed_string_plus_one_or_more_cases": 16,
                         "executed_token_plus_one_cases": 16},
        "rows": first["python_boundaries"], "rust_rows": first["rust"]["boundaries"],
        "runtime_accounting": "same-retained-canonical-bytes-no-second-snapshot",
        "schema_version": "sq02-resource-bounds-v1", "status": "PASS",
    }
    receipts[RECEIPTS[3]] = canonical_json_bytes(bounds)
    coverage_receipt = {
        "claim_scope": "Python safety-bearing statement/branch/function execution; Rust requirement completeness only",
        "production_modules": {"gate": "established-source-bound", "reported_separately": True},
        "machine_artifact_sha256": coverage_artifact_sha256,
        "python_safety_modules": coverage_metrics,
        "rust_claim": "executed-requirement-ID-completeness-not-source-or-function-coverage",
        "rust_requirement_ids": list(REQUIREMENT_IDS), "schema_version": "sq02-coverage-v1",
        "status": "PASS",
    }
    receipts[RECEIPTS[4]] = canonical_json_bytes(coverage_receipt)
    comparisons = {
        "catalog_equal": first["catalog"] == second["catalog"], "corpus_bytes_equal": first["corpus_bytes_sha256"] == second["corpus_bytes_sha256"],
        "corpus_manifest_equal": first["corpus_manifest_sha256"] == second["corpus_manifest_sha256"],
        "package_bytes_equal": first["packages"] == second["packages"], "rust_payload_equal": first["rust"] == second["rust"],
    }
    if not all(comparisons.values()):
        fail("CI_REPRODUCIBILITY", "clean archive payloads differ")
    reproducible = {"archive_materializations": 2, "cargo_binary_equality_required": False,
                    "comparisons": comparisons, "schema_version": "sq02-reproducible-builds-v1", "status": "PASS"}
    receipts[RECEIPTS[5]] = canonical_json_bytes(reproducible)
    scan = authority_scan(root, receipts)
    if scan["findings"] or scan["fuchsia_forbidden_edges"] or not scan["qualification_testonly"]:
        fail("CI_AUTHORITY_SCAN", "authority scan failed")
    scan.update({"schema_version": "sq02-package-catalog-scan-v1", "status": "PASS"})
    receipts[RECEIPTS[6]] = canonical_json_bytes(scan)
    hashes = {name: sha256(receipts[name]) for name in VERDICT_INPUTS}
    verdict = {
        "authority": "non-authoritative-harness",
        "cheapest_next_proof": "parent runs pinned Fuchsia target and generated host qualifier; Mr. Tester independently verifies",
        "claims_excluded": ["deploy", "independent approval", "merge", "Product Assembly/runtime inclusion", "release"],
        "failure_classification": None, "receipt_hashes": hashes, "required_skips": 0,
        "residual_risks": ["hosted CI toolchain differs from Fuchsia custom prebuilt", "Fuchsia target execution is parent-owned"],
        "root_cause_status": "none", "source_sha": source_sha, "source_tree": source_tree,
        "status": "PASS",
    }
    receipts[RECEIPTS[7]] = canonical_json_bytes(verdict)
    if any(pattern.search(raw) for raw in receipts.values() for pattern in PRIVATE_PATTERNS):
        fail("CI_AUTHORITY_SCAN", "receipt contains a private, credential, or orchestration marker")
    output.mkdir(parents=True, exist_ok=False)
    for name in RECEIPTS:
        (output / name).write_bytes(receipts[name])
    return receipts


def materialize(root: Path, sha: str, destination: Path) -> None:
    command = ["git", "archive", "--format=tar", sha]
    result = run_allowed(command, root, check=True, capture_output=True)
    destination.mkdir(parents=True, exist_ok=False)
    archive_path = destination.parent / f"{destination.name}.tar"
    archive_path.write_bytes(result.stdout)
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    fail("CI_MATERIALIZATION", "unsafe git archive member")
            archive.extractall(destination, filter="data")
    finally:
        archive_path.unlink(missing_ok=True)


def run(root: Path, source_sha: str, output: Path, cargo: Path, rustc: Path,
        cargo_home: Path, target_root: Path, isolation: dict[str, Any]) -> dict[str, bytes]:
    if os.environ.get("NATIVE_THEME_SQ02_NAMESPACE_PROVED") != "true":
        fail("CI_TOOLCHAIN_INFRASTRUCTURE", "OS network namespace proof is absent")
    for key, value in ENVIRONMENT.items():
        if os.environ.get(key) != value:
            fail("CI_TOOLCHAIN_INFRASTRUCTURE", f"fixed environment drift: {key}")
    output = validate_output(root, output)
    sha, tree = source_identity(root, output, source_sha)
    static_scan(root)
    undo = install_python_network_denial()
    temp_parent = Path(tempfile.mkdtemp(prefix="sq02-authoritative-", dir=str(target_root.parent)))
    try:
        archive_a, archive_b = temp_parent / "archive-a", temp_parent / "archive-b"
        materialize(root, sha, archive_a)
        materialize(root, sha, archive_b)
        first = payload(archive_a, temp_parent / "payload-a", cargo, rustc,
                        cargo_home, target_root / "archive-a")
        second = payload(archive_b, temp_parent / "payload-b", cargo, rustc,
                         cargo_home, target_root / "archive-b")
        coverage_metrics, coverage_artifact = measure_coverage(root, temp_parent / "coverage")
        receipts = write_receipts(root, output, sha, tree, isolation, cargo, rustc, first, second,
                                  coverage_metrics, coverage_artifact)
        from sq02_receipt_verifier import verify_directory
        verify_directory(root, output, expected_sha=sha, expected_tree=tree)
        after_sha, after_tree = source_identity(root, output, source_sha)
        if (after_sha, after_tree) != (sha, tree):
            fail("CI_SOURCE_DRIFT", "source moved during qualification")
        return receipts
    finally:
        undo()
        shutil.rmtree(temp_parent, ignore_errors=True)

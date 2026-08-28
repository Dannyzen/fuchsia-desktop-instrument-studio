#!/usr/bin/env python3
"""Pure, parser-neutral deterministic compiler core for NativeThemeV1.

External format adapters are responsible for parsing and normalization.  This
module accepts only the small explicit normalized language documented by its
public constants and data classes; it never loads source files or executes
external content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import NoReturn

from native_theme_v1 import (
    ContractError,
    HASH_RE,
    LIMITS,
    RGBA_RE,
    assert_dominated_runtime_snapshot,
    canonical_json_bytes,
    package_semantic_identity,
    validate_package,
)


__all__ = (
    "CompilationResult", "CompilerDiagnostic", "CompilerError",
    "MAX_COMPILE_CPU_SECONDS", "MAX_COMPILE_RSS_BYTES",
    "compile_normalized", "compile_normalized_to_path",
)


NORMALIZED_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSION = "1.0.0"
SUPPORTED_PROFILE_VERSION = "2025.10"
SUPPORTED_COMPILER_VERSION = "1.0.0"
MAX_COMPILE_CPU_SECONDS = 2.0
MAX_COMPILE_RSS_BYTES = 128 * 1024 * 1024

_ROOT_FIELDS = {
    "normalized_version", "required_versions", "source_content_hash", "package",
    "tokens", "aliases", "derivations",
}
_VERSION_FIELDS = {"schema", "profile", "compiler"}
_TOKEN_TYPES = {"boolean", "color", "number", "string"}
_TOKEN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_NETWORK_RE = re.compile(r"^(?:https?|wss?|ftp)://", re.IGNORECASE)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_DERIVATION_RESULT_TYPES = {
    "legacy-quantize-half-up": "color",
    "srgb-alpha-preservation": "color",
}
_FORBIDDEN_IDENTIFIER_SEGMENTS = {
    "code": "E_EXECUTABLE",
    "command": "E_SHELL",
    "exec": "E_EXECUTABLE",
    "executable": "E_EXECUTABLE",
    "file": "E_RUNTIME_PATH",
    "loader": "E_PLUGIN",
    "path": "E_RUNTIME_PATH",
    "plugin": "E_PLUGIN",
    "script": "E_SCRIPT",
    "shell": "E_SHELL",
    "template": "E_TEMPLATE",
    "uri": "E_NETWORK_URI",
    "url": "E_NETWORK_URI",
}


@dataclass(frozen=True)
class CompilerDiagnostic:
    """One stable compiler diagnostic."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class CompilerError(ContractError):
    """A deterministic normalized-compiler rejection."""

    def __init__(self, code: str, message: str):
        self.diagnostic = CompilerDiagnostic(code, message)
        self.code = code
        self.message = message
        super().__init__(str(self.diagnostic))


@dataclass(frozen=True)
class CompilationResult:
    """Fresh deterministic products returned by a successful compilation."""

    canonical_bytes: bytes
    semantic_hash: str
    package: dict[str, object]
    diagnostics: tuple[CompilerDiagnostic, ...]
    receipt: dict[str, object]
    receipt_bytes: bytes


@dataclass(frozen=True)
class _ResolvedToken:
    token_type: str
    value: object
    alias_depth: int = 0
    resolution_depth: int = 0


def _reject(code: str, message: str) -> NoReturn:
    raise CompilerError(code, message)


def _contract_code(exc: ContractError) -> tuple[str, str]:
    text = str(exc)
    match = re.match(r"^(E_[A-Z0-9_]+):\s*(.*)$", text)
    return (match.group(1), match.group(2)) if match else ("E_CONTRACT", text)


def _canonical(value: object) -> bytes:
    try:
        return canonical_json_bytes(value)
    except ContractError as exc:
        code, message = _contract_code(exc)
        _reject(code, message)
    except (TypeError, ValueError) as exc:
        _reject("E_NORMALIZED_TYPE", f"value is not canonical JSON data: {exc}")


def _fresh_json_value(value: object, *, depth: int = 0,
                      active: set[int] | None = None) -> object:
    """Copy JSON-compatible input while enforcing limits before recursion can bomb."""
    if depth > LIMITS["nesting"]:
        _reject("E_LIMIT_NESTING", "nesting exceeds 32")
    if active is None:
        active = set()
    if isinstance(value, str):
        if len(value.encode("utf-8")) > LIMITS["string_bytes"]:
            _reject("E_LIMIT_STRING", "string exceeds 4 KiB")
        return value
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _reject("E_NUMBER_NONFINITE", "numbers must be finite")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            _reject("E_LIMIT_NESTING", "cyclic normalized data is forbidden")
        active.add(identity)
        result: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                _reject("E_NORMALIZED_TYPE", "object keys must be strings")
            copied_key = _fresh_json_value(key, depth=depth + 1, active=active)
            result[copied_key] = _fresh_json_value(child, depth=depth + 1, active=active)
        active.remove(identity)
        return result
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            _reject("E_LIMIT_NESTING", "cyclic normalized data is forbidden")
        active.add(identity)
        result = [_fresh_json_value(child, depth=depth + 1, active=active) for child in value]
        active.remove(identity)
        return result
    _reject("E_NORMALIZED_TYPE", f"unsupported normalized value type {type(value).__name__}")


def _unsafe_extra_code(key: str, value: object) -> str | None:
    lowered = key.lower().replace("-", "_")
    if lowered in {"url", "uri", "network_uri", "network_url"}:
        return "E_NETWORK_URI"
    if lowered in {"script", "script_content"}:
        return "E_SCRIPT"
    if lowered in {"shell", "shell_command", "command"}:
        return "E_SHELL"
    if lowered in {"executable", "exec", "binary"}:
        return "E_EXECUTABLE"
    if lowered in {"plugin", "loader", "runtime_loader"}:
        return "E_PLUGIN"
    if lowered in {"template", "template_content"}:
        return "E_TEMPLATE"
    if lowered in {"runtime_path", "file", "file_path"}:
        return "E_RUNTIME_PATH"
    if lowered in {"runtime_content", "content", "payload"}:
        return "E_RUNTIME_CONTENT"
    if lowered in {"path", "absolute_path"} and isinstance(value, str):
        if _NETWORK_RE.match(value):
            return "E_NETWORK_URI"
        if _is_absolute_path(value):
            return "E_ABSOLUTE_PATH"
        if _has_traversal(value):
            return "E_PATH_TRAVERSAL"
        return "E_RUNTIME_PATH"
    return None


def _reject_dangerous_extras(value: Mapping[str, object], allowed: set[str]) -> None:
    for key in value.keys() - allowed:
        code = _unsafe_extra_code(key, value[key])
        if code is not None:
            _reject(code, f"normalized field {key!r} requests forbidden capability")


def _is_absolute_path(value: str) -> bool:
    return value.startswith(("/", "\\")) or _WINDOWS_ABSOLUTE_RE.match(value) is not None


def _has_traversal(value: str) -> bool:
    return ".." in PurePosixPath(value.replace("\\", "/")).parts


def _check_identifier_safety(value: str, label: str) -> None:
    if _NETWORK_RE.match(value):
        _reject("E_NETWORK_URI", f"{label} cannot be a network URI")
    if _is_absolute_path(value):
        _reject("E_ABSOLUTE_PATH", f"{label} cannot be an absolute path")
    if _has_traversal(value):
        _reject("E_PATH_TRAVERSAL", f"{label} cannot traverse paths")
    lowered = value.lower()
    if value.startswith("#!"):
        _reject("E_SCRIPT", f"{label} cannot contain a script")
    if lowered.startswith(("script:", "javascript:")):
        _reject("E_SCRIPT", f"{label} cannot name a script")
    if lowered.startswith(("shell:", "command:", "sh -c", "bash -c", "powershell")):
        _reject("E_SHELL", f"{label} cannot name a shell command")
    if lowered.startswith(("exec:", "executable:")):
        _reject("E_EXECUTABLE", f"{label} cannot name executable content")
    if lowered.startswith(("plugin:", "loader:")):
        _reject("E_PLUGIN", f"{label} cannot name a plugin or loader")
    if lowered.startswith("template:") or "{{" in value or "{%" in value:
        _reject("E_TEMPLATE", f"{label} cannot contain a template")
    if lowered.startswith(("file:", "runtime:")):
        _reject("E_RUNTIME_PATH", f"{label} cannot name a runtime path")
    if "/" in value or "\\" in value:
        _reject("E_RUNTIME_PATH", f"{label} cannot name a path")
    segments = {segment for segment in re.split(r"[._-]+", lowered) if segment}
    for segment in sorted(segments):
        code = _FORBIDDEN_IDENTIFIER_SEGMENTS.get(segment)
        if code is not None:
            _reject(code, f"{label} cannot name {segment} capability")


def _token_name(value: object, label: str) -> str:
    if not isinstance(value, str):
        _reject("E_NORMALIZED_TYPE", f"{label} must be a string")
    _check_identifier_safety(value, label)
    if _TOKEN_NAME_RE.fullmatch(value) is None:
        _reject("E_TOKEN_NAME", f"{label} is not a bounded token identifier")
    return value


def _token_type(value: object, label: str) -> str:
    if not isinstance(value, str) or value not in _TOKEN_TYPES:
        _reject("E_TOKEN_TYPE", f"{label} must be one of {','.join(sorted(_TOKEN_TYPES))}")
    return value


def _literal(token_type: str, value: object, label: str) -> object:
    if token_type == "color":
        if not isinstance(value, str) or RGBA_RE.fullmatch(value) is None:
            _reject("E_COLOR_CANONICAL", f"{label} must be lowercase #rrggbbaa")
    elif token_type == "string":
        if not isinstance(value, str):
            _reject("E_TOKEN_TYPE", f"{label} must be a string")
        _check_identifier_safety(value, label)
    elif token_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _reject("E_TOKEN_TYPE", f"{label} must be a finite number")
    elif token_type == "boolean" and not isinstance(value, bool):
        _reject("E_TOKEN_TYPE", f"{label} must be a boolean")
    return value


def _validate_versions(root: dict[str, object]) -> None:
    version = root.get("normalized_version")
    if not isinstance(version, str) or version != NORMALIZED_VERSION:
        _reject("E_NORMALIZED_VERSION", "unsupported normalized language version")
    versions = root.get("required_versions")
    if not isinstance(versions, dict) or set(versions) != _VERSION_FIELDS:
        _reject("E_NORMALIZED_VERSION", "required_versions must have exact schema/profile/compiler fields")
    expected = {
        "schema": (SUPPORTED_SCHEMA_VERSION, "E_VERSION_SCHEMA"),
        "profile": (SUPPORTED_PROFILE_VERSION, "E_VERSION_PROFILE"),
        "compiler": (SUPPORTED_COMPILER_VERSION, "E_VERSION_COMPILER"),
    }
    for name, (supported, code) in expected.items():
        if not isinstance(versions[name], str) or versions[name] != supported:
            _reject(code, f"unsupported required {name} version")


def _build_symbols(root: dict[str, object]) -> tuple[dict[str, dict[str, object]], int, int, int]:
    tokens, aliases, derivations = root["tokens"], root["aliases"], root["derivations"]
    if not all(isinstance(items, list) for items in (tokens, aliases, derivations)):
        _reject("E_NORMALIZED_TYPE", "tokens, aliases, and derivations must be lists")
    if len(tokens) + len(derivations) > LIMITS["tokens"]:
        _reject("E_LIMIT_TOKENS", "normalized token count exceeds 1024")
    if len(aliases) > LIMITS["aliases"]:
        _reject("E_LIMIT_ALIASES", "alias count exceeds 2048")

    symbols: dict[str, dict[str, object]] = {}

    def add(name: str, symbol: dict[str, object]) -> None:
        if name in symbols:
            _reject("E_TOKEN_DUPLICATE", f"duplicate normalized token {name}")
        symbols[name] = symbol

    for index, entry in enumerate(tokens):
        if not isinstance(entry, dict):
            _reject("E_NORMALIZED_TYPE", f"tokens[{index}] must be an object")
        allowed = {"name", "type", "value"}
        _reject_dangerous_extras(entry, allowed)
        if set(entry) != allowed:
            _reject("E_TOKEN_SHAPE", f"tokens[{index}] has invalid fields")
        name = _token_name(entry["name"], f"tokens[{index}].name")
        token_type = _token_type(entry["type"], f"tokens[{index}].type")
        add(name, {"kind": "literal", "type": token_type,
                   "value": _literal(token_type, entry["value"], f"token {name}")})

    for index, entry in enumerate(aliases):
        if not isinstance(entry, dict):
            _reject("E_NORMALIZED_TYPE", f"aliases[{index}] must be an object")
        allowed = {"name", "type", "target"}
        _reject_dangerous_extras(entry, allowed)
        if set(entry) != allowed:
            _reject("E_ALIAS_SHAPE", f"aliases[{index}] has invalid fields")
        name = _token_name(entry["name"], f"aliases[{index}].name")
        token_type = _token_type(entry["type"], f"aliases[{index}].type")
        target = _token_name(entry["target"], f"aliases[{index}].target")
        add(name, {"kind": "alias", "type": token_type, "target": target})

    for index, entry in enumerate(derivations):
        if not isinstance(entry, dict):
            _reject("E_NORMALIZED_TYPE", f"derivations[{index}] must be an object")
        allowed = {"name", "type", "operation", "operands"}
        _reject_dangerous_extras(entry, allowed)
        if set(entry) != allowed or not isinstance(entry["operands"], list):
            _reject("E_DERIVATION_OPERANDS", f"derivations[{index}] has invalid shape")
        name = _token_name(entry["name"], f"derivations[{index}].name")
        token_type = _token_type(entry["type"], f"derivations[{index}].type")
        operation = entry["operation"]
        if not isinstance(operation, str):
            _reject("E_DERIVATION_UNKNOWN", "derivation operation must be a named string")
        _check_identifier_safety(operation, "derivation operation")
        if operation not in _DERIVATION_RESULT_TYPES:
            _reject("E_DERIVATION_UNKNOWN", f"unknown derivation operation {operation}")
        operands = [_token_name(item, f"derivation {name} operand") for item in entry["operands"]]
        add(name, {"kind": "derivation", "type": token_type,
                   "operation": operation, "operands": operands})
    return symbols, len(tokens), len(aliases), len(derivations)


def _derive(operation: str, declared_type: str,
            operands: list[_ResolvedToken]) -> _ResolvedToken:
    result_type = _DERIVATION_RESULT_TYPES[operation]
    if declared_type != result_type:
        _reject("E_TOKEN_TYPE_CONFLICT", f"{operation} produces {result_type}, not {declared_type}")
    if operation == "srgb-alpha-preservation":
        if len(operands) != 1 or operands[0].token_type != "color":
            _reject("E_DERIVATION_OPERANDS", "srgb-alpha-preservation requires one color operand")
        return _ResolvedToken("color", operands[0].value)
    if len(operands) != 4 or any(item.token_type != "number" for item in operands):
        _reject("E_DERIVATION_OPERANDS", "legacy-quantize-half-up requires four number operands")
    channels: list[int] = []
    for item in operands:
        try:
            component = Decimal(str(item.value))
        except (InvalidOperation, ValueError):
            _reject("E_DERIVATION_OPERANDS", "legacy component is not decimal")
        if not component.is_finite() or not Decimal(0) <= component <= Decimal(1):
            _reject("E_DERIVATION_OPERANDS", "legacy component must be in 0..1")
        channels.append(int((component * Decimal(255)).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    return _ResolvedToken("color", "#" + "".join(f"{channel:02x}" for channel in channels))


def _resolve_symbols(symbols: dict[str, dict[str, object]]) -> dict[str, _ResolvedToken]:
    resolved: dict[str, _ResolvedToken] = {}
    visiting: list[str] = []

    def resolve(name: str) -> _ResolvedToken:
        if name in resolved:
            return resolved[name]
        if len(visiting) > LIMITS["nesting"]:
            _reject("E_LIMIT_NESTING", "token dependency nesting exceeds 32")
        if name in visiting:
            cycle = visiting[visiting.index(name):] + [name]
            code = "E_ALIAS_CYCLE" if any(symbols[item]["kind"] == "alias" for item in cycle[:-1]) else "E_DERIVATION_OPERANDS"
            _reject(code, "token resolution cycle: " + " -> ".join(cycle))
        symbol = symbols[name]
        visiting.append(name)
        kind = symbol["kind"]
        if kind == "literal":
            result = _ResolvedToken(symbol["type"], symbol["value"])
        elif kind == "alias":
            target = symbol["target"]
            if target not in symbols:
                _reject("E_ALIAS_UNRESOLVED", f"alias {name} targets unknown token {target}")
            aliases_in_path = sum(symbols[item]["kind"] == "alias" for item in visiting)
            if symbols[target]["kind"] == "alias" and aliases_in_path >= LIMITS["alias_depth"]:
                _reject("E_LIMIT_ALIAS_DEPTH", f"alias {name} exceeds depth 32")
            target_result = resolve(target)
            if symbol["type"] != target_result.token_type:
                _reject("E_TOKEN_TYPE_CONFLICT", f"alias {name} changes {target_result.token_type} to {symbol['type']}")
            depth = target_result.alias_depth + 1
            if depth > LIMITS["alias_depth"]:
                _reject("E_LIMIT_ALIAS_DEPTH", f"alias {name} exceeds depth 32")
            result = _ResolvedToken(
                symbol["type"], target_result.value, depth,
                target_result.resolution_depth + 1,
            )
        else:
            operand_names = symbol["operands"]
            missing = [item for item in operand_names if item not in symbols]
            if missing:
                _reject("E_DERIVATION_OPERANDS", f"derivation {name} has unknown operands")
            operand_results = [resolve(item) for item in operand_names]
            result = _derive(symbol["operation"], symbol["type"], operand_results)
            resolution_depth = 1 + max(
                (item.resolution_depth for item in operand_results), default=0,
            )
            if resolution_depth > LIMITS["nesting"]:
                _reject("E_LIMIT_NESTING", "token dependency nesting exceeds 32")
            result = _ResolvedToken(
                result.token_type, result.value,
                max((item.alias_depth for item in operand_results), default=0),
                resolution_depth,
            )
        visiting.pop()
        resolved[name] = result
        return result

    for token_name in sorted(symbols):
        resolve(token_name)
    return resolved


def _substitute_tokens(value: object, resolved: dict[str, _ResolvedToken]) -> object:
    if isinstance(value, dict):
        if "$token" in value:
            if set(value) != {"$token"} or not isinstance(value["$token"], str):
                _reject("E_TOKEN_REFERENCE", "package token references require exact {$token: name} shape")
            name = value["$token"]
            _check_identifier_safety(name, "package token reference")
            if name not in resolved:
                _reject("E_TOKEN_UNKNOWN", f"package references unknown token {name}")
            return _fresh_json_value(resolved[name].value)
        return {key: _substitute_tokens(child, resolved) for key, child in value.items()}
    if isinstance(value, list):
        return [_substitute_tokens(child, resolved) for child in value]
    return value


def _check_path(value: object, label: str) -> None:
    if not isinstance(value, str):
        return
    if _NETWORK_RE.match(value):
        _reject("E_NETWORK_URI", f"{label} cannot use a network URI")
    if _is_absolute_path(value):
        _reject("E_ABSOLUTE_PATH", f"{label} must be package-relative")
    if _has_traversal(value):
        _reject("E_PATH_TRAVERSAL", f"{label} cannot traverse directories")
    if value.lower().startswith(("file:", "runtime:")) or "\\" in value:
        _reject("E_RUNTIME_PATH", f"{label} cannot use an arbitrary runtime path")


def _check_package_safety(package: dict[str, object]) -> None:
    def capabilities(value: object, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = key.lower().replace("-", "_")
                child_location = f"{location}.{key}"
                if location == "package.metadata" and lowered == "extensions":
                    # Namespaced extensions are inert metadata. Their namespace,
                    # JSON shape, nesting, and total size are validated elsewhere;
                    # interpreting ordinary nested keys as capabilities would break
                    # the contract's additive-metadata guarantee.
                    continue
                if lowered == "executable_content":
                    if location != "package.policy" or child != "forbidden":
                        _reject("E_EXECUTABLE", f"{child_location} must remain forbidden")
                else:
                    code = _unsafe_extra_code(key, child)
                    if code is not None and lowered not in {"path", "content_hash"}:
                        _reject(code, f"{child_location} requests forbidden capability")
                capabilities(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                capabilities(child, f"{location}[{index}]")

    capabilities(package, "package")
    metadata = package.get("metadata")
    if isinstance(metadata, dict):
        provenance = metadata.get("provenance")
        if isinstance(provenance, dict):
            _check_path(provenance.get("source_identity"), "source_identity")
    variants = package.get("variants")
    total_decoded = 0.0
    if not isinstance(variants, dict):
        return
    for variant_name, variant in variants.items():
        if not isinstance(variant, dict):
            continue
        assets = variant.get("assets")
        if not isinstance(assets, dict):
            continue
        items = assets.get("items")
        if not isinstance(items, dict):
            continue
        if len(items) > LIMITS["semantic_assets"]:
            _reject("E_LIMIT_ASSETS", f"{variant_name} semantic asset count exceeds 64")
        for asset_name, asset in items.items():
            if not isinstance(asset, dict):
                continue
            _check_path(asset.get("path"), f"asset {asset_name}")
            decoded = asset.get("decoded_bytes")
            if isinstance(decoded, (int, float)) and not isinstance(decoded, bool) and math.isfinite(decoded):
                if decoded > LIMITS["decoded_asset_bytes"]:
                    _reject("E_LIMIT_ASSET_BYTES", f"asset {asset_name} exceeds 512 KiB decoded")
                total_decoded += decoded
    if total_decoded > LIMITS["decoded_assets_total_bytes"]:
        _reject("E_LIMIT_ASSETS_TOTAL", "decoded assets exceed 4 MiB total")


def _check_package_versions(package: dict[str, object]) -> None:
    if "schema_version" in package and package["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        _reject("E_VERSION_SCHEMA", "package schema_version differs from required version")
    profile = package.get("profile")
    if isinstance(profile, dict) and "version" in profile and profile["version"] != SUPPORTED_PROFILE_VERSION:
        _reject("E_VERSION_PROFILE", "package profile version differs from required version")
    metadata = package.get("metadata")
    provenance = metadata.get("provenance") if isinstance(metadata, dict) else None
    if isinstance(provenance, dict) and "compiler_version" in provenance and provenance["compiler_version"] != SUPPORTED_COMPILER_VERSION:
        _reject("E_VERSION_COMPILER", "package compiler version differs from required version")


def _validate_complete_package(package: dict[str, object]) -> tuple[bytes, str]:
    _check_package_versions(package)
    _check_package_safety(package)
    canonical_body = _canonical(package)
    package_file_bytes = canonical_body + b"\n"
    if len(package_file_bytes) > LIMITS["compiled_pack_bytes"]:
        _reject("E_CANONICAL_SIZE", "canonical package exceeds 256 KiB")
    assert_dominated_runtime_snapshot(len(package_file_bytes))

    metadata = package.get("metadata")
    provenance = metadata.get("provenance") if isinstance(metadata, dict) else None
    if isinstance(provenance, dict):
        for field in ("content_hash", "semantic_hash"):
            if field in provenance and (not isinstance(provenance[field], str) or HASH_RE.fullmatch(provenance[field]) is None):
                _reject("E_PROVENANCE_HASH", f"provenance {field} is not canonical sha256")
        if isinstance(provenance.get("semantic_hash"), str) and HASH_RE.fullmatch(provenance["semantic_hash"]):
            expected = package_semantic_identity(package)
            if provenance["semantic_hash"] != expected:
                _reject("E_SEMANTIC_HASH_MISMATCH", "package provenance semantic hash mismatch")
    try:
        validate_package(package)
    except ContractError as exc:
        code, message = _contract_code(exc)
        _reject("E_PACKAGE_VALIDATION", f"{code}: {message}")
    return package_file_bytes, package_semantic_identity(package)


def compile_normalized(normalized: Mapping[str, object]) -> CompilationResult:
    """Compile one already-parsed normalized package candidate without side effects."""
    if not isinstance(normalized, Mapping):
        _reject("E_NORMALIZED_ROOT", "normalized root must be a mapping")
    copied = _fresh_json_value(normalized)
    if not isinstance(copied, dict):
        _reject("E_NORMALIZED_ROOT", "normalized root must be an object")
    _reject_dangerous_extras(copied, _ROOT_FIELDS)
    if set(copied) != _ROOT_FIELDS:
        _reject("E_NORMALIZED_FIELDS", "normalized root requires exact declared fields")
    source_bytes = _canonical(copied)
    if len(source_bytes) > LIMITS["source_bytes"]:
        _reject("E_LIMIT_SOURCE", "normalized source exceeds 1 MiB")
    _validate_versions(copied)
    source_content_hash = copied["source_content_hash"]
    if not isinstance(source_content_hash, str) or HASH_RE.fullmatch(source_content_hash) is None:
        _reject("E_PROVENANCE_HASH", "source_content_hash must be canonical sha256")
    if not isinstance(copied["package"], dict):
        _reject("E_NORMALIZED_TYPE", "package candidate must be an object")
    symbols, token_count, alias_count, derivation_count = _build_symbols(copied)
    resolved = _resolve_symbols(symbols)
    package = _substitute_tokens(copied["package"], resolved)
    if not isinstance(package, dict):
        _reject("E_NORMALIZED_TYPE", "resolved package candidate must be an object")
    canonical_bytes, semantic_hash = _validate_complete_package(package)
    provenance = package["metadata"]["provenance"]
    if provenance["content_hash"] != source_content_hash:
        _reject(
            "E_PROVENANCE_HASH_MISMATCH",
            "normalized source_content_hash differs from package provenance",
        )
    receipt: dict[str, object] = {
        "alias_count": alias_count,
        "compiler_version": SUPPORTED_COMPILER_VERSION,
        "derivation_count": derivation_count,
        "normalized_version": NORMALIZED_VERSION,
        "package_bytes": len(canonical_bytes),
        "package_sha256": "sha256:" + hashlib.sha256(canonical_bytes).hexdigest(),
        "resource_budget": {
            "cpu_milliseconds": int(MAX_COMPILE_CPU_SECONDS * 1000),
            "rss_bytes": MAX_COMPILE_RSS_BYTES,
        },
        "semantic_hash": semantic_hash,
        "source_content_hash": source_content_hash,
        "token_count": token_count,
    }
    return CompilationResult(
        canonical_bytes=bytes(canonical_bytes),
        semantic_hash=semantic_hash,
        package=_fresh_json_value(package),
        diagnostics=(),
        receipt=_fresh_json_value(receipt),
        receipt_bytes=_canonical(receipt),
    )


def compile_normalized_to_path(normalized: Mapping[str, object], output: Path) -> CompilationResult:
    """Compile and atomically promote canonical bytes to *output* on success only."""
    result = compile_normalized(normalized)
    destination = Path(output)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(result.canonical_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    except (OSError, ValueError) as exc:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        _reject("E_OUTPUT_PROMOTION", f"atomic output promotion failed: {exc}")
    return result

"""Shared, side-effect-free authority for NativeTheme source adapters."""

from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import NoReturn

from native_theme_v1 import (
    ContractError,
    LIMITS,
    package_semantic_identity,
    validate_package,
)


MAX_SOURCE_BYTES = LIMITS["source_bytes"]
MAX_INERT_TEXT_BYTES = LIMITS["string_bytes"]
ADAPTER_EXTENSION = "org.constructresearch.instrumentstudio.adapter_source"
TEMPLATE_SEMANTIC_HASH = "sha256:5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a"
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")
_NETWORK_RE = re.compile(r"^(?:https?|wss?|ftp)://", re.IGNORECASE)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_HASH_PREFIX = "sha256:"
_EXECUTABLE_SUFFIXES = (".bat", ".cmd", ".exe", ".ps1", ".py", ".sh")
_TEMPLATE_SUFFIXES = (".j2", ".jinja", ".jinja2", ".tmpl")


@dataclass(frozen=True)
class AdapterDiagnostic:
    """One stable source-adapter diagnostic."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class AdapterError(ContractError):
    """A deterministic source-adapter rejection."""

    def __init__(self, code: str, message: str):
        self.diagnostic = AdapterDiagnostic(code, message)
        self.code = code
        self.message = message
        super().__init__(str(self.diagnostic))


def reject(code: str, message: str) -> NoReturn:
    raise AdapterError(code, message)


def _bounded_inert_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        reject("E_PROVENANCE", f"{field} must be non-empty inert text")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeError:
        reject("E_UTF8", f"{field} must be valid UTF-8")
    if len(encoded) > MAX_INERT_TEXT_BYTES:
        reject("E_LIMIT_STRING", f"{field} exceeds 4 KiB")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        reject("E_PROVENANCE", f"{field} contains control content")
    lowered = value.lower().lstrip()
    if value.startswith("#!") or lowered.startswith(("script:", "javascript:")):
        reject("E_SCRIPT", f"{field} cannot contain a script")
    if lowered.startswith(("command:", "shell:", "sh -c", "bash -c", "powershell")):
        reject("E_SHELL", f"{field} cannot contain a command")
    if lowered.startswith(("plugin:", "loader:")):
        reject("E_PLUGIN", f"{field} cannot contain a plugin")
    if lowered.startswith("template:") or "{{" in value or "{%" in value:
        reject("E_TEMPLATE", f"{field} cannot contain a template")
    return value


def _validate_source_identity(value: object) -> str:
    identity = _bounded_inert_text(value, "source_identity")
    lowered = identity.lower()
    if _NETWORK_RE.match(identity):
        reject("E_NETWORK_URI", "source_identity cannot be a network URI")
    if identity.startswith(("/", "\\")) or _WINDOWS_ABSOLUTE_RE.match(identity):
        reject("E_ABSOLUTE_PATH", "source_identity must be repository/policy-relative")
    segments = identity.replace("\\", "/").split("/")
    if ".." in segments:
        reject("E_PATH_TRAVERSAL", "source_identity cannot traverse directories")
    if lowered.startswith(("file:", "runtime:")) or "\\" in identity:
        reject("E_RUNTIME_PATH", "source_identity cannot name a runtime path")
    if lowered.startswith(("script:", "javascript:")) or lowered.endswith(_EXECUTABLE_SUFFIXES):
        reject("E_SCRIPT", "source_identity cannot name a script or executable")
    if lowered.startswith(("command:", "shell:")) or any(character.isspace() for character in identity):
        reject("E_SHELL", "source_identity cannot name a command")
    if lowered.startswith(("plugin:", "loader:")) or any(segment in {"plugin", "plugins"} for segment in segments):
        reject("E_PLUGIN", "source_identity cannot name a plugin")
    if lowered.startswith("template:") or lowered.endswith(_TEMPLATE_SUFFIXES) or "{{" in identity or "{%" in identity:
        reject("E_TEMPLATE", "source_identity cannot name a template")
    if any(segment in {"runtime", "proc", "dev", "sys"} for segment in segments):
        reject("E_RUNTIME_PATH", "source_identity cannot name a runtime path")
    if _IDENTITY_RE.fullmatch(identity) is None or any(segment in {"", "."} for segment in segments):
        reject("E_PROVENANCE", "source_identity is not a bounded repository/policy-relative identity")
    return identity


@dataclass(frozen=True)
class AdapterProvenance:
    """Caller-owned immutable provenance applied to one imported source."""

    source_identity: str
    license_spdx: str
    attribution: str
    notice: str

    def __post_init__(self) -> None:
        validate_provenance(self)


def validate_provenance(value: object) -> AdapterProvenance:
    if not isinstance(value, AdapterProvenance):
        reject("E_PROVENANCE", "provenance must be AdapterProvenance")
    _validate_source_identity(value.source_identity)
    _bounded_inert_text(value.license_spdx, "license_spdx")
    _bounded_inert_text(value.attribution, "attribution")
    _bounded_inert_text(value.notice, "notice")
    return value


def source_bytes(raw: object) -> bytes:
    if not isinstance(raw, bytes):
        reject("E_SOURCE_TYPE", "adapter source must be raw bytes")
    if len(raw) > MAX_SOURCE_BYTES:
        reject("E_LIMIT_SOURCE", "source exceeds 1 MiB")
    return raw


def strict_utf8(raw: object) -> str:
    bounded = source_bytes(raw)
    try:
        return bounded.decode("utf-8", "strict")
    except UnicodeDecodeError:
        reject("E_UTF8", "source is not strict UTF-8")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            reject("E_JSON_DUPLICATE", f"duplicate JSON key {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> NoReturn:
    reject("E_NUMBER_NONFINITE", f"JSON number {value} is not finite")


def _inspect_json(value: object, depth: int = 0) -> None:
    if depth > LIMITS["nesting"]:
        reject("E_LIMIT_NESTING", "source nesting exceeds 32")
    if isinstance(value, float) and not math.isfinite(value):
        reject("E_NUMBER_NONFINITE", "JSON numbers must be finite")
    if isinstance(value, str) and len(value.encode("utf-8")) > MAX_INERT_TEXT_BYTES:
        reject("E_LIMIT_STRING", "source string exceeds 4 KiB")
    if isinstance(value, dict):
        for key, child in value.items():
            _inspect_json(key, depth + 1)
            _inspect_json(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _inspect_json(child, depth + 1)


def parse_json(raw: object) -> dict[str, object]:
    text = strict_utf8(raw)
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except AdapterError:
        raise
    except json.JSONDecodeError as exc:
        reject("E_JSON_PARSE", f"invalid JSON at line {exc.lineno} column {exc.colno}")
    _inspect_json(value)
    if not isinstance(value, dict):
        reject("E_JSON_ROOT", "JSON root must be an object")
    return value


def capability_code(key: str, value: object) -> str | None:
    lowered = key.lower().replace("-", "_")
    if lowered in {"command", "exec", "executable", "shell"}:
        return "E_EXECUTABLE"
    if lowered in {"script", "script_content"}:
        return "E_SCRIPT"
    if lowered in {"template", "template_content"}:
        return "E_TEMPLATE"
    if lowered in {"plugin", "loader", "plugins", "runtime_loader"}:
        return "E_PLUGIN"
    if lowered in {"runtime_path", "file", "file_path"}:
        return "E_RUNTIME_PATH"
    if lowered in {"include", "import", "inherit", "inherits", "path"}:
        if isinstance(value, str):
            if _NETWORK_RE.match(value):
                return "E_NETWORK_URI"
            if value.startswith(("/", "\\")) or _WINDOWS_ABSOLUTE_RE.match(value):
                return "E_ABSOLUTE_PATH"
            if ".." in value.replace("\\", "/").split("/"):
                return "E_PATH_TRAVERSAL"
        return "E_RUNTIME_PATH"
    return None


def reject_capabilities(value: object, location: str = "source") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            code = capability_code(key, child)
            if code is not None:
                reject(code, f"{location}.{key} requests forbidden executable/runtime capability")
            reject_capabilities(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_capabilities(child, f"{location}[{index}]")


def _fresh_template(template: object) -> dict[str, object]:
    if isinstance(template, bytes):
        candidate = parse_json(template)
    elif isinstance(template, Mapping):
        candidate = copy.deepcopy(dict(template))
        _inspect_json(candidate)
    else:
        reject("E_TEMPLATE_PACKAGE", "template package must be bytes or a mapping")
    try:
        validate_package(candidate)
    except ContractError as exc:
        reject("E_TEMPLATE_PACKAGE", f"invalid complete-package template: {exc}")
    if package_semantic_identity(candidate) != TEMPLATE_SEMANTIC_HASH:
        reject("E_TEMPLATE_PACKAGE", "complete-package template semantic identity is not the committed authority")
    return candidate


def content_hash(raw: bytes) -> str:
    return _HASH_PREFIX + hashlib.sha256(raw).hexdigest()


def normalized_root(
    raw: bytes,
    template: object,
    provenance: AdapterProvenance,
    *,
    source_format: str,
    profile_version: str,
    preserved_tokens: object,
    token_provenance: dict[str, dict[str, str]],
) -> tuple[dict[str, object], dict[str, object]]:
    """Create a fresh exact normalized root and return it with its package."""
    source_bytes(raw)
    validate_provenance(provenance)
    package = _fresh_template(template)
    source_digest = content_hash(raw)
    metadata = package["metadata"]
    metadata["license"] = {"spdx": provenance.license_spdx, "notice": provenance.notice}
    extensions = metadata["extensions"]
    extensions[ADAPTER_EXTENSION] = {
        "profile_version": profile_version,
        "source_format": source_format,
        "tokens": copy.deepcopy(preserved_tokens),
    }
    package_provenance = {
        "attribution": provenance.attribution,
        "compiler_version": "1.0.0",
        "content_hash": source_digest,
        "license": provenance.license_spdx,
        "profile_version": profile_version,
        "semantic_hash": "",
        "source_format": source_format,
        "source_identity": provenance.source_identity,
        "tokens": copy.deepcopy(token_provenance),
    }
    metadata["provenance"] = package_provenance
    package_provenance["semantic_hash"] = package_semantic_identity(package)
    root = {
        "aliases": [],
        "derivations": [],
        "normalized_version": "1.0.0",
        "package": package,
        "required_versions": {"compiler": "1.0.0", "profile": "2025.10", "schema": "1.0.0"},
        "source_content_hash": source_digest,
        "tokens": [],
    }
    return root, package


def explicit(source_token: str) -> dict[str, str]:
    return {"kind": "explicit", "source_token": source_token}


def inherited(source_token: str) -> dict[str, str]:
    return {"kind": "inherited", "source_token": source_token}


def derived(source_token: str, derivation: str) -> dict[str, str]:
    return {"derivation": derivation, "kind": "derived", "source_token": source_token}

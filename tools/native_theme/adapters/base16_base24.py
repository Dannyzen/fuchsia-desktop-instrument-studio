"""Strict raw-JSON adapters for the Base16 and Base24 palette profiles."""

from __future__ import annotations

import re

from native_theme_v1 import package_semantic_identity

from .common import (
    AdapterProvenance,
    capability_code,
    derived,
    explicit,
    normalized_root,
    parse_json,
    reject,
)


_BASE16_PROFILE = "base16-v1"
_BASE24_PROFILE = "base24-v1"
_ROOT_FIELDS = {"declared_layer", "profile_version", "tokens"}
_HEX_RE = re.compile(r"^[0-9a-f]{6}$")
# The committed Base role map. Roles absent here intentionally retain the
# complete-package fallback policy/template value.
_BASE_ROLE_MAP = {
    "base00": (("primitives", "canvas"), ("semantic", "surface.canvas"),
               ("semantic", "terminal.background"), ("semantic", "text.inverse"),
               ("terminal", "ansi0")),
    "base01": (("semantic", "surface.raised"),),
    "base02": (("semantic", "terminal.selection"),),
    "base03": (("semantic", "text.muted"),),
    "base04": (("semantic", "border.normal"),),
    "base05": (("terminal", "ansi7"),),
    "base06": (("primitives", "ink"), ("semantic", "text.normal"),
               ("semantic", "terminal.foreground")),
    "base07": (("semantic", "text.bright"),),
    "base08": (("primitives", "danger"), ("semantic", "status.danger"),
               ("semantic", "window.urgent"), ("terminal", "ansi1")),
    "base09": (),
    "base0A": (("semantic", "status.warning"), ("terminal", "ansi3")),
    "base0B": (("semantic", "status.success"), ("terminal", "ansi2")),
    "base0C": (("semantic", "border.focusConfirmed"), ("semantic", "terminal.cursor"),
               ("components", "terminal.cursor.color"), ("terminal", "ansi6")),
    "base0D": (("primitives", "accent"), ("semantic", "interaction.accent"),
               ("semantic", "window.active"), ("components", "button.primary.color")),
    "base0E": (("terminal", "ansi5"),),
    "base0F": (),
}
_NORMAL_ANSI_SOURCE = (
    "base00", "base08", "base0B", "base0A", "base14", "base0E", "base0C", "base05",
)
_BRIGHT_DEPENDENT_ROLES = {
    "base14": (("semantic", "border.active"),),
    "base16": (("semantic", "status.info"),),
    "base17": (("semantic", "text.strong"),),
}


def _validate_root(value: dict[str, object], profile: str, count: int) -> dict[str, str]:
    missing = _ROOT_FIELDS - set(value)
    if missing:
        reject("E_FIELD_REQUIRED", "profile requires declared_layer, profile_version, and tokens")
    extras = set(value) - _ROOT_FIELDS
    if extras:
        key = sorted(extras)[0]
        code = capability_code(key, value[key])
        if profile == _BASE16_PROFILE and code is not None:
            code = "E_FIELD_FORBIDDEN"
        reject(code or "E_FIELD_EXTRA", f"unsupported profile field {key}")
    if value["profile_version"] != profile:
        reject("E_VERSION_PROFILE", f"expected profile_version {profile}")
    if value["declared_layer"] != "primitives":
        reject("E_PROFILE_LAYER", f"{profile} accepts only the primitives layer")
    tokens = value["tokens"]
    if not isinstance(tokens, dict):
        reject("E_FIELD_REQUIRED", "tokens must be an object")
    required = {f"base{i:02X}" for i in range(count)}
    missing_tokens = required - set(tokens)
    if missing_tokens:
        reject("E_FIELD_REQUIRED", f"missing required token {sorted(missing_tokens)[0]}")
    extra_tokens = set(tokens) - required
    if extra_tokens:
        key = sorted(extra_tokens)[0]
        code = capability_code(key, tokens[key])
        reject(code or "E_FIELD_EXTRA", f"unsupported token {key}")
    for key in sorted(required):
        if not isinstance(tokens[key], str) or _HEX_RE.fullmatch(tokens[key]) is None:
            reject("E_COLOR_CANONICAL", f"{key} must be exactly six lowercase hexadecimal digits")
    return tokens


def _write(package: dict[str, object], domain: str, role: str, color: str) -> None:
    package["variants"]["dark"][domain][role] = color


def _adapt(raw: bytes, template_package: object, provenance: AdapterProvenance, *, count: int) -> dict[str, object]:
    profile = _BASE16_PROFILE if count == 16 else _BASE24_PROFILE
    value = parse_json(raw)
    tokens = _validate_root(value, profile, count)
    token_provenance: dict[str, dict[str, str]] = {}
    root, package = normalized_root(
        raw, template_package, provenance,
        source_format="base16-json" if count == 16 else "base24-json",
        profile_version=profile,
        preserved_tokens=tokens,
        token_provenance=token_provenance,
    )
    for source_token in sorted(tokens):
        token_provenance[f"source.{source_token}"] = explicit(source_token)
    for source_token, destinations in _BASE_ROLE_MAP.items():
        color = "#" + tokens[source_token] + "ff"
        for domain, role in destinations:
            _write(package, domain, role, color)
            token_provenance[f"{domain}.{role}"] = explicit(source_token)

    for ansi, source_token in enumerate(_NORMAL_ANSI_SOURCE):
        if source_token in tokens:
            _write(package, "terminal", f"ansi{ansi}", "#" + tokens[source_token] + "ff")
            token_provenance[f"terminal.ansi{ansi}"] = explicit(source_token)
        else:
            token_provenance[f"terminal.ansi{ansi}"] = derived(
                f"builtin.terminal.ansi{ansi}", "base16-bright-ansi-fallback-v1",
            )

    if count == 24:
        for offset in range(8):
            source_token = f"base1{offset}"
            _write(package, "terminal", f"ansi{offset + 8}", "#" + tokens[source_token] + "ff")
            token_provenance[f"terminal.ansi{offset + 8}"] = explicit(source_token)
        for source_token, destinations in _BRIGHT_DEPENDENT_ROLES.items():
            for domain, role in destinations:
                _write(package, domain, role, "#" + tokens[source_token] + "ff")
                token_provenance[f"{domain}.{role}"] = explicit(source_token)
    else:
        fallback = package["variants"]["dark"]
        for ansi in range(8, 16):
            token_provenance[f"terminal.ansi{ansi}"] = derived(
                f"builtin.terminal.ansi{ansi}", "base16-bright-ansi-fallback-v1",
            )
        for destinations in _BRIGHT_DEPENDENT_ROLES.values():
            for domain, role in destinations:
                token_provenance[f"{domain}.{role}"] = derived(
                    f"builtin.{domain}.{role}", "base16-bright-ansi-fallback-v1",
                )
                # Make the fallback dependency explicit while retaining the
                # already-cloned template value.
                fallback[domain][role] = fallback[domain][role]

    token_provenance["semantic.interaction.selection"] = derived(
        "base02", "palette-owned-selection-policy-v1",
    )

    package["metadata"]["provenance"]["tokens"] = token_provenance
    # Metadata is inert, but recompute after the adapter has completed all
    # package writes so the invariant stays local and obvious.
    package["metadata"]["provenance"]["semantic_hash"] = package_semantic_identity(package)
    return root


def adapt_base16(raw: bytes, template_package: object, provenance: AdapterProvenance) -> dict[str, object]:
    return _adapt(raw, template_package, provenance, count=16)


def adapt_base24(raw: bytes, template_package: object, provenance: AdapterProvenance) -> dict[str, object]:
    return _adapt(raw, template_package, provenance, count=24)

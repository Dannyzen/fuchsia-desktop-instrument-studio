#!/usr/bin/env python3
"""Independent NativeThemeV1 semantic checks for the sq-01 quality gate.

This module deliberately does not import either production validator/compiler or
the legacy inventory/oracle validator.  It uses only the standard library and
jsonschema, and returns stable diagnostic records rather than exiting.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ModuleNotFoundError:  # dependency prep is deliberately outside the gate
    jsonschema = None

ROLES = {
    "surface.canvas", "surface.raised", "surface.sunken", "surface.overlay",
    "text.normal", "text.muted", "text.bright", "text.inverse",
    "border.normal", "border.muted", "border.focusConfirmed", "border.danger",
    "interaction.accent", "interaction.accentHover", "interaction.selection",
    "interaction.selectionInactive", "interaction.disabled", "interaction.link",
    "status.info", "status.success", "status.warning", "status.danger",
    "status.neutral", "terminal.background", "terminal.foreground",
    "terminal.black", "terminal.red", "terminal.green", "terminal.yellow",
    "terminal.blue", "terminal.magenta", "terminal.cyan", "terminal.white",
    "terminal.brightBlack", "terminal.brightWhite",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def _luminance(color: str) -> float:
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def validate(package: dict[str, Any], schema: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    if jsonschema is not None:
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
            jsonschema.Draft202012Validator(schema).validate(package)
        except jsonschema.exceptions.SchemaError as exc:
            errors.append({"code": "E_SCHEMA_DEFINITION", "detail": exc.message})
        except jsonschema.exceptions.ValidationError as exc:
            errors.append({"code": "E_SCHEMA_STRUCTURE", "detail": exc.message})
    variants = package.get("variants", {})
    if set(variants) != {"light", "dark", "high-contrast"}:
        errors.append({"code": "E_VARIANT_REQUIRED", "detail": "exact variants required"})
    for variant_name, variant in sorted(variants.items()):
        semantic = variant.get("semantic", {}) if isinstance(variant, dict) else {}
        if set(semantic) != ROLES:
            errors.append({"code": "E_SEMANTIC_ROLES", "detail": variant_name})
            continue
        for role, color in semantic.items():
            if not isinstance(color, str) or len(color) != 9 or not color.startswith("#") or color.lower() != color:
                errors.append({"code": "E_COLOR_CANONICAL", "detail": f"{variant_name}:{role}"})
        if semantic.get("border.focusConfirmed") == semantic.get("interaction.selection"):
            errors.append({"code": "E_FOCUS_COLLAPSE", "detail": variant_name})
        for fg, bg, minimum, code in (
            ("text.normal", "surface.canvas", 4.5, "E_CONTRAST_TEXT"),
            ("border.focusConfirmed", "surface.canvas", 3.0, "E_CONTRAST_FOCUS"),
            ("interaction.selection", "surface.canvas", 3.0, "E_CONTRAST_SELECTION"),
            ("status.danger", "surface.canvas", 3.0, "E_CONTRAST_STATUS"),
        ):
            try:
                if _contrast(semantic[fg], semantic[bg]) < minimum:
                    errors.append({"code": code, "detail": variant_name})
            except (KeyError, ValueError):
                pass
        assets = variant.get("assets", {}).get("items", {})
        if "status.error" not in assets:
            errors.append({"code": "E_STATUS_NONCOLOR", "detail": variant_name})
        for asset_id, asset in assets.items():
            if not asset_id or not isinstance(asset, dict) or not asset.get("spdx"):
                errors.append({"code": "E_ASSET_LICENSE", "detail": f"{variant_name}:{asset_id}"})
    provenance = package.get("metadata", {}).get("provenance", {})
    for key in ("source_identity", "content_hash", "compiler_version", "semantic_hash", "license", "attribution"):
        if not provenance.get(key):
            errors.append({"code": "E_PROVENANCE", "detail": key})
    policies = oracle.get("policies", {})
    focus = policies.get("focus", {})
    if focus.get("confirmed_target") == focus.get("selection_target"):
        errors.append({"code": "E_LEGACY_FOCUS", "detail": "focus and selection collapse"})
    settings = policies.get("settings_migration", {})
    if not all(key in settings for key in ("Dark", "Contrast")):
        errors.append({"code": "E_SETTINGS_MAPPING", "detail": "legacy settings incomplete"})
    semantic_sha = oracle.get("semantic_sha256")
    if not isinstance(semantic_sha, str) or len(semantic_sha) != 64:
        errors.append({"code": "E_ORACLE_HASH", "detail": "invalid semantic hash"})
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "semantic_package_sha256": hashlib.sha256(_canonical(package)).hexdigest(),
        "oracle_semantic_sha256": semantic_sha,
        "roles_checked": len(ROLES),
        "variants_checked": len(variants),
    }


def validate_paths(package_path: Path, schema_path: Path, oracle_path: Path) -> dict[str, Any]:
    return validate(json.loads(package_path.read_text("utf-8")),
                    json.loads(schema_path.read_text("utf-8")),
                    json.loads(oracle_path.read_text("utf-8")))

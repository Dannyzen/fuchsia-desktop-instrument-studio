#!/usr/bin/env python3
"""Bounded Phase 1 compiler proof for NativeThemeV1 color snapshots.

This intentionally accepts only a flat Base24 YAML subset or the current Rust
ThemeTokens constants. It is not the general DTCG/Base16/Omarchy compiler.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import NoReturn

LIMITS = {
    "source_bytes": 1024 * 1024, "compiled_pack_bytes": 256 * 1024,
    "catalog_bytes": 8 * 1024 * 1024, "tokens": 1024, "aliases": 2048,
    "alias_depth": 32, "nesting": 32, "string_bytes": 4096,
    "semantic_assets": 64, "decoded_asset_bytes": 512 * 1024,
    "decoded_assets_total_bytes": 4 * 1024 * 1024,
    "runtime_snapshot_bytes": 512 * 1024,
}
CONTRACT_FIELDS = {"schema_version", "profile", "theme", "metadata", "variants", "fallback", "policy"}
VARIANT_FIELDS = {"primitives", "semantic", "components", "typography", "geometry", "elevation", "opacity", "motion", "assets", "terminal"}
REQUIRED_VARIANTS = {"light", "dark", "high-contrast"}
PROFILE_LAYERS = {
    "dtcg-2025.10-instrument-studio-v1": {"primitives", "semantic", "components"},
    "base16-v1": {"primitives"}, "base24-v1": {"primitives"},
    "omarchy-colors-toml-v1": {"primitives"}, "native-legacy-v1": {"semantic"},
}
RGBA_RE = re.compile(r"^#[0-9a-f]{8}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMANTIC_COLOR_ROLES = {
    *(f"surface.{x}" for x in ("canvas", "deep", "sunken", "base", "raised", "overlay")),
    *(f"text.{x}" for x in ("muted", "subtle", "normal", "strong", "bright", "inverse", "disabled")),
    *(f"border.{x}" for x in ("subtle", "normal", "strong", "active", "focusConfirmed")),
    *(f"interaction.{x}" for x in ("accent", "hover", "pressed", "selection", "selected", "disabled")),
    *(f"status.{x}" for x in ("info", "success", "warning", "danger")),
    *(f"window.{x}" for x in ("active", "inactive", "urgent")),
    *(f"terminal.{x}" for x in ("background", "foreground", "cursor", "selection")),
}
TYPOGRAPHY_ROLES = {"caption", "label", "body", "title", "data-display"}

SCHEMA_VERSION = "1.0.0"
COMPILER_VERSION = "0.1.0-proof"
PROFILE_VERSION = "base24-instrument-studio-proof-v1"
MAX_SOURCE_BYTES = 64 * 1024
MAX_TOKENS = 256
MAX_IDENTIFIER_CHARS = 128
ROOT = Path(__file__).resolve().parents[2]
BASE_KEYS = tuple(
    [f"base0{i}" for i in range(10)]
    + [f"base0{c}" for c in "ABCDEF"]
    + [f"base1{i}" for i in range(8)]
)
META_KEYS = ("scheme", "author", "variant")
ALLOWED_KEYS = set(META_KEYS + BASE_KEYS)
ROLE_TO_BASE = {
    "surface.canvas": "base00",
    "surface.raised": "base01",
    "interaction.selection": "base02",
    "text.muted": "base03",
    "border.normal": "base04",
    "text.bright": "base07",
    "status.danger": "base08",
    "status.success": "base0B",
    "border.focusConfirmed": "base0C",
    "interaction.accent": "base0D",
}
LEGACY_TO_ROLE = {
    "panel_bg": "surface.canvas",
    "panel_elevated": "surface.raised",
    "selected_focus": "interaction.selection",
    "text_secondary": "text.muted",
    "border_muted": "border.normal",
    "text_primary": "text.bright",
    "danger": "status.danger",
    "ok": "status.success",
    "confirmed_focus": "border.focusConfirmed",
    "accent_secondary": "interaction.accent",
}
BOUNDS = {
    "aliases": 0,
    "assets": 0,
    "identifier_chars": MAX_IDENTIFIER_CHARS,
    "source_bytes": MAX_SOURCE_BYTES,
    "tokens": MAX_TOKENS,
}
HEX_RE = re.compile(r"^[0-9a-fA-F]{6}$")
LEGACY_RE = re.compile(
    r"^\s*([a-z_]+):\s*ColorRgba::new\(\s*([0-9.]+),\s*([0-9.]+),\s*([0-9.]+),\s*([0-9.]+)\s*\),"
)


class ContractError(ValueError):
    """A deterministic contract rejection."""


def fail(message: str) -> NoReturn:
    raise ContractError(message)


def reject(code: str, message: str) -> NoReturn:
    fail(f"{code}: {message}")


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject("E_JSON_DUPLICATE", f"duplicate key {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) > LIMITS["source_bytes"]:
        reject("E_LIMIT_SOURCE", "source exceeds 1 MiB")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_pairs, parse_constant=lambda value: reject("E_NUMBER_NONFINITE", value))
    except UnicodeDecodeError:
        reject("E_UTF8", "source is not UTF-8")
    if not isinstance(value, dict):
        reject("E_JSON_ROOT", "root must be an object")
    return value


def canonical_json_bytes(value: object) -> bytes:
    def inspect(item: object, depth: int = 0) -> None:
        if depth > LIMITS["nesting"]:
            reject("E_LIMIT_NESTING", "nesting exceeds 32")
        if isinstance(item, float) and not __import__("math").isfinite(item):
            reject("E_NUMBER_NONFINITE", "numbers must be finite")
        if isinstance(item, str) and len(item.encode("utf-8")) > LIMITS["string_bytes"]:
            reject("E_LIMIT_STRING", "string exceeds 4 KiB")
        if isinstance(item, dict):
            for key, child in item.items():
                inspect(key, depth + 1); inspect(child, depth + 1)
        elif isinstance(item, list):
            for child in item: inspect(child, depth + 1)
    inspect(value)
    def normalize(item: object) -> object:
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def semantic_identity(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def package_semantic_identity(package: dict[str, object]) -> str:
    """Hash renderable package meaning, excluding mandatory inert metadata."""
    semantic = json.loads(json.dumps(package))
    semantic.pop("metadata", None)
    return semantic_identity(semantic)


def validate_profile_fixture(data: dict[str, object]) -> None:
    if set(data) != {"profile_version", "declared_layer", "tokens"}:
        reject("E_PROFILE_FIELDS", "profile fixture fields differ")
    profile = data.get("profile_version")
    if profile not in PROFILE_LAYERS:
        reject("E_VERSION_PROFILE", "unknown required profile version")
    if data.get("declared_layer") not in PROFILE_LAYERS[profile]:
        reject("E_PROFILE_LAYER", "tokens are declared in a forbidden layer")
    if not isinstance(data.get("tokens"), dict) or not data["tokens"]:
        reject("E_PROFILE_TOKENS", "tokens must be a non-empty object")


def validate_root_schema_structural(schema: dict[str, object], instance: dict[str, object]) -> None:
    """Honest stdlib fallback: checks root dispatch only, not full Draft semantics."""
    refs = schema.get("oneOf")
    if refs != [{"$ref": "#/$defs/legacySnapshot"}, {"$ref": "#/$defs/nativePackage"}]:
        reject("E_SCHEMA_ROOT", "root must dispatch both declared contracts")
    if "variants" in instance:
        validate_package(instance)
    elif "colors" not in instance:
        reject("E_SCHEMA_ROOT", "instance matches neither declared contract")


def validate_profile_manifest(manifest: dict[str, object], fixtures: Path) -> dict[str, int]:
    if set(manifest) != {"schema_version", "profiles"} or manifest["schema_version"] != "1.1.0":
        reject("E_MANIFEST", "manifest shape/version")
    profiles = manifest["profiles"]
    if not isinstance(profiles, list) or len(profiles) != len(PROFILE_LAYERS):
        reject("E_MANIFEST", "all profiles required")
    positives = negatives = uncovered = 0
    seen = set()
    for entry in profiles:
        required = {"profile", "type", "layers", "variants", "derivations", "role_map", "diagnostics", "positive_cases", "negative_cases", "complete_package"}
        if not isinstance(entry, dict) or set(entry) != required or entry["profile"] not in PROFILE_LAYERS:
            reject("E_MANIFEST", "profile entry incomplete")
        seen.add(entry["profile"]); positives += len(entry["positive_cases"]); negatives += len(entry["negative_cases"])
        output = entry["complete_package"]
        output_path = fixtures.parent / output.get("file", "") if isinstance(output, dict) else fixtures
        if not isinstance(output, dict) or set(output) != {"file", "sha256", "semantic_hash", "selection"} or not output_path.is_file():
            uncovered += 1
        else:
            package = load_json_strict(output_path)
            expected_selection = {name: package["variants"][name]["semantic"]["interaction.selection"] for name in sorted(REQUIRED_VARIANTS)}
            if output["sha256"] != "sha256:" + hashlib.sha256(output_path.read_bytes()).hexdigest() or output["semantic_hash"] != package_semantic_identity(package) or output["selection"] != expected_selection:
                uncovered += 1
        for case in entry["positive_cases"] + entry["negative_cases"]:
            if not isinstance(case, dict) or not (fixtures / case["file"]).is_file(): uncovered += 1
        negative_codes = {case.get("code") for case in entry["negative_cases"]}
        if not set(entry["diagnostics"]) <= negative_codes: uncovered += len(set(entry["diagnostics"]) - negative_codes)
    if seen != set(PROFILE_LAYERS) or positives < 5 or negatives < 25 or uncovered:
        reject("E_MANIFEST_COVERAGE", f"positive={positives} negative={negatives} uncovered={uncovered}")
    return {"profiles": len(profiles), "positive_cases": positives, "negative_cases": negatives, "uncovered": uncovered}


def _exact_object(value, keys, code):
    if not isinstance(value, dict) or set(value) != set(keys): reject(code, "required exact shape")


def _number(value, low, high, code):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high: reject(code, f"bound {low}..{high}")


def validate_package(data: dict[str, object]) -> None:
    if set(data) - CONTRACT_FIELDS:
        reject("E_FIELD_FORBIDDEN", "unknown required or executable field")
    missing = CONTRACT_FIELDS - set(data)
    if missing:
        reject("E_FIELD_REQUIRED", ",".join(sorted(missing)))
    if data["schema_version"] != "1.0.0":
        reject("E_VERSION_REQUIRED", "unsupported schema version")
    profile = data["profile"]
    if profile != {"name": "instrument-studio-dtcg-subset", "version": "2025.10"}:
        reject("E_VERSION_PROFILE", "unsupported normative profile")
    variants = data["variants"]
    if not isinstance(variants, dict) or set(variants) != REQUIRED_VARIANTS:
        reject("E_VARIANT_REQUIRED", "light, dark, and high-contrast are required")
    fallback = data["fallback"]
    if not isinstance(fallback, dict) or set(fallback) != {"built_in_theme_id", "missing_asset", "missing_token", "last_known_good", "storage_independent"} or fallback.get("missing_token") != "fail" or fallback.get("storage_independent") is not True:
        reject("E_FALLBACK_REQUIRED", "fallback policy is incomplete")
    metadata = data["metadata"]
    if not isinstance(metadata, dict) or set(metadata) != {"license", "provenance", "extensions"}:
        reject("E_METADATA_REQUIRED", "license, provenance, and extensions are required")
    extensions = metadata["extensions"]
    if not isinstance(extensions, dict) or any(not key.startswith("org.constructresearch.instrumentstudio.") for key in extensions):
        reject("E_EXTENSION_NAMESPACE", "extension key is outside the reserved namespace")
    license_data = metadata["license"]
    if not isinstance(license_data, dict) or set(license_data) != {"spdx", "notice"} or not all(isinstance(value, str) and value for value in license_data.values()):
        reject("E_LICENSE", "SPDX identifier and notice are required")
    provenance = metadata["provenance"]
    provenance_keys = {"source_format", "profile_version", "source_identity", "content_hash", "compiler_version", "semantic_hash", "license", "attribution", "tokens"}
    if not isinstance(provenance, dict) or set(provenance) != provenance_keys or not HASH_RE.fullmatch(str(provenance.get("content_hash", ""))) or not HASH_RE.fullmatch(str(provenance.get("semantic_hash", ""))):
        reject("E_PROVENANCE", "complete hashes, identity, compiler, license, attribution, and tokens required")
    identity = provenance["source_identity"]
    if not isinstance(identity, str) or identity.startswith(("/", "http://", "https://")) or ".." in Path(identity).parts:
        reject("E_PROVENANCE", "source identity must be repository-relative or URI policy identity")
    if not isinstance(provenance["tokens"], dict) or any(not isinstance(v, dict) or v.get("kind") not in {"explicit", "inherited", "derived"} or not set(v) <= {"kind", "source_token", "derivation"} for v in provenance["tokens"].values()):
        reject("E_PROVENANCE", "per-token provenance is invalid")
    policy = data["policy"]
    if not isinstance(policy, dict) or policy.get("unknown_required_version") != "fail-closed" or policy.get("no_animation_required_for_correctness") is not True:
        reject("E_COMPATIBILITY", "fail-closed and animation-independent policy required")
    compatibility = policy.get("compatibility")
    if compatibility != {"current": "1.0.0", "previous": "0.x", "window": "N/N-1"}:
        reject("E_COMPATIBILITY", "N/N-1 window required")
    token_count = 0
    for variant_name, variant in variants.items():
        if not isinstance(variant, dict) or set(variant) != VARIANT_FIELDS:
            reject("E_DOMAIN_REQUIRED", f"{variant_name} domains are incomplete")
        for layer in ("primitives", "semantic", "components"):
            if not isinstance(variant[layer], dict) or not variant[layer]:
                reject("E_LAYER_REQUIRED", f"{variant_name}.{layer}")
            token_count += len(variant[layer])
        for layer in ("primitives", "semantic", "components"):
            for name, color in variant[layer].items():
                if (name.endswith("color") or layer != "components") and isinstance(color, str) and color.startswith("#") and not RGBA_RE.fullmatch(color):
                    reject("E_COLOR_CANONICAL", f"{variant_name}.{layer}.{name}")
        terminal = variant["terminal"]
        if not isinstance(terminal, dict) or set(terminal) != {f"ansi{i}" for i in range(16)} or any(not isinstance(v, str) or not RGBA_RE.fullmatch(v) for v in terminal.values()):
            reject("E_TERMINAL_ANSI", "exact ANSI 0..15 palette required")
        semantic = variant["semantic"]
        if not isinstance(semantic, dict) or set(semantic) != SEMANTIC_COLOR_ROLES:
            reject("E_SEMANTIC_ROLES", "exact complete semantic taxonomy required")
        if any(not isinstance(v, str) or not RGBA_RE.fullmatch(v) for v in semantic.values()):
            reject("E_COLOR_CANONICAL", "all semantic roles require lowercase #rrggbbaa")
        if semantic["border.focusConfirmed"] == semantic["interaction.selection"]:
            reject("E_FOCUS_DISTINCT", "confirmed focus and selection must differ")
        assets = variant["assets"]
        if not isinstance(assets, dict) or set(assets) != {"items", "fallback"} or "status.error" not in assets.get("items", {}):
            reject("E_STATUS_NONCOLOR", "status.error semantic asset is required")
        if len(assets["items"]) > LIMITS["semantic_assets"]:
            reject("E_LIMIT_ASSETS", "semantic asset count exceeds 64")
        for asset_id, asset in assets["items"].items():
            required_asset = {"path", "kind", "variants", "width", "height", "decoded_bytes", "spdx", "attribution"}
            if not isinstance(asset, dict) or set(asset) != required_asset or asset["kind"] not in {"svg", "png"} or not isinstance(asset["variants"], list) or not asset["variants"]:
                reject("E_ASSET_METADATA", f"{asset_id} metadata")
            asset_path = asset["path"]
            if not isinstance(asset_path, str) or asset_path.startswith("/") or ".." in Path(asset_path).parts or "\\" in asset_path:
                reject("E_ASSET_PATH", f"{asset_id} must be package-relative")
            _number(asset["width"], 1, 4096, "E_ASSET_METADATA"); _number(asset["height"], 1, 4096, "E_ASSET_METADATA"); _number(asset["decoded_bytes"], 1, LIMITS["decoded_asset_bytes"], "E_LIMIT_ASSET_BYTES")
        typography = variant["typography"]
        if not isinstance(typography, dict) or set(typography) != {"families", "roles", "minimum_legible_px", "terminal_cell", "fallback"}:
            reject("E_TYPOGRAPHY", "body and mono selections are required")
        families = typography["families"]
        if not isinstance(families, dict) or not {"ui", "monospace"} <= set(families) or any(not isinstance(v, list) or not v or not all(isinstance(x, str) for x in v) for v in families.values()): reject("E_TYPOGRAPHY", "family stacks")
        if set(typography["roles"]) != TYPOGRAPHY_ROLES: reject("E_TYPOGRAPHY", "all typography roles")
        for style in typography["roles"].values():
            if not isinstance(style, dict) or set(style) != {"family", "size_px", "line_height", "weight", "letter_spacing_em"}: reject("E_TYPOGRAPHY", "typed role")
            _number(style["size_px"], 10, 96, "E_TYPOGRAPHY"); _number(style["line_height"], 1, 2, "E_TYPOGRAPHY"); _number(style["weight"], 100, 900, "E_TYPOGRAPHY"); _number(style["letter_spacing_em"], -.1, .2, "E_TYPOGRAPHY")
        geometry = variant["geometry"]
        geometry_keys = {"spacing", "gaps", "heights", "accent_rail_px", "panel", "radii", "border_widths", "icon_sizes", "minimum_hit_target_px", "density", "responsive"}
        if not isinstance(geometry, dict) or set(geometry) != geometry_keys or geometry.get("density") not in {"compact", "comfortable", "touch"}:
            reject("E_GEOMETRY", "density and responsive geometry are required")
        if geometry["responsive"] != {"narrow_max_px": 719, "regular_max_px": 1199, "wide_min_px": 1200}: reject("E_GEOMETRY", "fixed product thresholds")
        elevation = variant["elevation"]
        if not isinstance(elevation, dict) or set(elevation) != {"levels"} or set(elevation["levels"]) != {"flat", "raised", "overlay"}: reject("E_ELEVATION", "levels")
        for shadow in elevation["levels"].values():
            if not isinstance(shadow, dict) or set(shadow) != {"x_px", "y_px", "blur_px", "spread_px", "color"}: reject("E_ELEVATION", "shadow shape")
            _number(shadow["blur_px"], 0, 64, "E_ELEVATION")
        opacity = variant["opacity"]
        if not isinstance(opacity, dict) or set(opacity) != {"disabled", "overlay"}: reject("E_OPACITY", "shape")
        for value in opacity.values(): _number(value, 0, 1, "E_OPACITY")
        motion = variant["motion"]
        if not isinstance(motion, dict) or set(motion) != {"durations_ms", "easing", "reduced"} or set(motion["durations_ms"]) != {"short", "medium", "long"} or set(motion["easing"]) != {"standard", "emphasized"}: reject("E_MOTION", "shape")
        for value in motion["durations_ms"].values(): _number(value, 0, 1000, "E_MOTION")
        if motion["reduced"] != {"duration_ms": 0, "substitution": "instant", "essential_only": True}: reject("E_REDUCED_MOTION", "deterministic reduced motion required")
        fg, bg = semantic.get("text.normal"), semantic.get("surface.canvas")
        if not isinstance(fg, str) or not isinstance(bg, str) or not RGBA_RE.fullmatch(fg) or not RGBA_RE.fullmatch(bg):
            reject("E_COLOR_CANONICAL", "semantic text/surface colors")
        target = 7.0 if variant_name == "high-contrast" else 4.5
        if contrast(fg[1:7], bg[1:7]) < target:
            reject("E_CONTRAST_NORMAL", f"{variant_name} text contrast below {target}")
        focus = semantic.get("border.focusConfirmed")
        selection = semantic.get("interaction.selection")
        ui_target = 4.5 if variant_name == "high-contrast" else 3.0
        if not isinstance(focus, str) or not RGBA_RE.fullmatch(focus) or contrast(focus[1:7], bg[1:7]) < ui_target:
            reject("E_CONTRAST_UI", f"{variant_name} focus contrast below {ui_target}")
        if not isinstance(selection, str) or not RGBA_RE.fullmatch(selection) or contrast(selection[1:7], bg[1:7]) < ui_target:
            reject("E_CONTRAST_SELECTION", f"{variant_name} selection contrast below {ui_target}")
    if token_count > LIMITS["tokens"]:
        reject("E_LIMIT_TOKENS", "token count exceeds 1024")
    encoded = canonical_json_bytes(data)
    if len(encoded) > LIMITS["compiled_pack_bytes"]:
        reject("E_LIMIT_PACK", "compiled pack exceeds 256 KiB")
    if provenance["semantic_hash"] != package_semantic_identity(data):
        reject("E_PROVENANCE", "complete package semantic hash mismatch")


def read_bounded(path: Path) -> bytes:
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        fail(f"source exceeds {MAX_SOURCE_BYTES} bytes")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        fail("source must be valid UTF-8")
    return raw


def parse_flat_base24(path: Path) -> tuple[dict[str, str], bytes]:
    raw = read_bounded(path)
    values: dict[str, str] = {}
    for line_no, original in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not original or original.startswith("#"):
            continue
        if original[:1].isspace() or "\t" in original:
            fail(f"line {line_no}: nested YAML and indentation are forbidden")
        if ":" not in original:
            fail(f"line {line_no}: expected key: value")
        key, value = (part.strip() for part in original.split(":", 1))
        if len(key) > MAX_IDENTIFIER_CHARS:
            fail(f"line {line_no}: identifier exceeds {MAX_IDENTIFIER_CHARS} characters")
        if key not in ALLOWED_KEYS:
            fail(f"unsupported key: {key}")
        if key in values:
            fail(f"duplicate key: {key}")
        if any(mark in value for mark in ("*", "&")):
            fail("aliases are forbidden")
        if any(mark in value for mark in ("{", "}", "[", "]", "|", ">")):
            fail(f"line {line_no}: structured YAML is forbidden")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if len(value) > MAX_IDENTIFIER_CHARS:
            fail(f"line {line_no}: value exceeds {MAX_IDENTIFIER_CHARS} characters")
        values[key] = value
    if len(values) > MAX_TOKENS:
        fail(f"token count exceeds {MAX_TOKENS}")
    for key in META_KEYS + BASE_KEYS:
        if key not in values:
            fail(f"missing required key: {key}")
    if values["variant"] != "dark":
        fail("proof profile variant must be dark")
    for key in BASE_KEYS:
        if not HEX_RE.fullmatch(values[key]):
            fail(f"{key} must be exactly six hexadecimal digits")
        values[key] = values[key].lower()
    return values, raw


def srgb_luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((srgb_luminance(a), srgb_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def require_text_contrast(colors: dict[str, str]) -> None:
    background = colors["surface.canvas"].removeprefix("#")
    for role in ("text.bright", "text.muted"):
        ratio = contrast(colors[role].removeprefix("#"), background)
        if ratio < 4.5:
            fail(f"{role} contrast {ratio:.2f} is below WCAG 2.2 AA 4.5")


def semantic_hash(colors: dict[str, str], variant: str) -> str:
    payload = {"schema_version": SCHEMA_VERSION, "variant": variant, "colors": colors}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def source_identity(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        fail("source must be inside repository for bounded proof")


def make_snapshot(*, colors: dict[str, str], source_format: str, source_profile: str,
                  source_path: Path, source_raw: bytes, provenance: dict[str, dict[str, str]]) -> dict[str, object]:
    require_text_contrast(colors)
    variant = "dark"
    return {
        "bounds": BOUNDS,
        "colors": dict(sorted(colors.items())),
        "compiler_version": COMPILER_VERSION,
        "display_name": "Instrument Studio",
        "provenance": dict(sorted(provenance.items())),
        "schema_version": SCHEMA_VERSION,
        "semantic_hash": semantic_hash(dict(sorted(colors.items())), variant),
        "source": {
            "content_sha256": "sha256:" + hashlib.sha256(source_raw).hexdigest(),
            "format": source_format,
            "identity": source_identity(source_path),
            "profile_version": source_profile,
        },
        "theme_id": "instrument-studio",
        "variant": variant,
    }


def compile_base24(path: Path) -> dict[str, object]:
    values, raw = parse_flat_base24(path)
    colors = {role: "#" + values[key] for role, key in ROLE_TO_BASE.items()}
    provenance = {
        role: {"kind": "derived" if role in {"border.normal", "border.focusConfirmed"} else "explicit", "source_token": key}
        for role, key in ROLE_TO_BASE.items()
    }
    return make_snapshot(
        colors=colors,
        source_format="base24-yaml-flat-v1",
        source_profile=PROFILE_VERSION,
        source_path=path,
        source_raw=raw,
        provenance=provenance,
    )


def quantize_channel(value: str) -> int:
    number = Decimal(value)
    if number < 0 or number > 1:
        fail("legacy color channel is outside 0..1")
    return int((number * 255).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compile_legacy(path: Path) -> dict[str, object]:
    raw = read_bounded(path)
    found: dict[str, tuple[str, str, str, str]] = {}
    for line in raw.decode("utf-8").splitlines():
        match = LEGACY_RE.match(line)
        if match:
            found[match.group(1)] = tuple(match.groups()[1:])  # type: ignore[assignment]
    missing = sorted(set(LEGACY_TO_ROLE) - set(found))
    if missing:
        fail("missing legacy colors: " + ", ".join(missing))
    colors: dict[str, str] = {}
    provenance: dict[str, dict[str, str]] = {}
    for legacy, role in LEGACY_TO_ROLE.items():
        red, green, blue, alpha = found[legacy]
        if Decimal(alpha) != Decimal("1.0"):
            fail(f"legacy {legacy} alpha must be 1.0")
        rgb = tuple(quantize_channel(value) for value in (red, green, blue))
        colors[role] = "#" + "".join(f"{channel:02x}" for channel in rgb)
        provenance[role] = {"kind": "legacy-quantized", "source_token": legacy}
    return make_snapshot(
        colors=colors,
        source_format="rust-theme-tokens-v1",
        source_profile="instrument-studio-legacy-v1",
        source_path=path,
        source_raw=raw,
        provenance=provenance,
    )


def write_canonical(snapshot: dict[str, object], output: Path) -> None:
    encoded = (json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=output.name + ".", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    base24 = subparsers.add_parser("compile-base24")
    base24.add_argument("--input", type=Path, required=True)
    base24.add_argument("--output", type=Path, required=True)
    legacy = subparsers.add_parser("compile-legacy")
    legacy.add_argument("--tokens-rs", type=Path, required=True)
    legacy.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compile-base24":
            snapshot = compile_base24(args.input)
        else:
            snapshot = compile_legacy(args.tokens_rs)
        write_canonical(snapshot, args.output)
    except (ContractError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"WROTE {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

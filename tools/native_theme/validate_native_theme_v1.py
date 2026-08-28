#!/usr/bin/env python3
"""Independent stdlib validator for the source-bound NativeThemeV1 proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = Path(__file__).with_name("native-theme-v1.schema.json")
COMPILER_VERSION = "0.1.0-proof"
MAX_TEXT_CHARS = 128
HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BASE24_PROVENANCE = {
    "border.focusConfirmed": ("derived", "base0C"),
    "border.normal": ("derived", "base04"),
    "interaction.accent": ("explicit", "base0D"),
    "interaction.selection": ("explicit", "base02"),
    "status.danger": ("explicit", "base08"),
    "status.success": ("explicit", "base0B"),
    "surface.canvas": ("explicit", "base00"),
    "surface.raised": ("explicit", "base01"),
    "text.bright": ("explicit", "base07"),
    "text.muted": ("explicit", "base03"),
}
LEGACY_PROVENANCE = {
    "border.focusConfirmed": ("legacy-quantized", "confirmed_focus"),
    "border.normal": ("legacy-quantized", "border_muted"),
    "interaction.accent": ("legacy-quantized", "accent_secondary"),
    "interaction.selection": ("legacy-quantized", "selected_focus"),
    "status.danger": ("legacy-quantized", "danger"),
    "status.success": ("legacy-quantized", "ok"),
    "surface.canvas": ("legacy-quantized", "panel_bg"),
    "surface.raised": ("legacy-quantized", "panel_elevated"),
    "text.bright": ("legacy-quantized", "text_primary"),
    "text.muted": ("legacy-quantized", "text_secondary"),
}
PROFILES = {
    "base24-yaml-flat-v1": {
        "identity": "tools/native_theme/fixtures/base24-instrument-studio.yaml",
        "profile_version": "base24-instrument-studio-proof-v1",
        "provenance": BASE24_PROVENANCE,
    },
    "rust-theme-tokens-v1": {
        "identity": "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs",
        "profile_version": "instrument-studio-legacy-v1",
        "provenance": LEGACY_PROVENANCE,
    },
}


class ValidationError(ValueError):
    pass


def fail(message: str) -> NoReturn:
    raise ValidationError(message)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def bounded_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        fail(f"{label} must be a string")
    if not 1 <= len(value) <= MAX_TEXT_CHARS:
        fail(f"{label} length must be 1..{MAX_TEXT_CHARS}")
    return value


def validate_source_and_provenance(data: dict[str, object], expected_roles: set[str]) -> None:
    source = data["source"]
    if not isinstance(source, dict):
        fail("source must be an object")
    if set(source) != {"content_sha256", "format", "identity", "profile_version"}:
        fail("invalid source fields")
    source_format = bounded_text(source["format"], "source.format")
    identity = bounded_text(source["identity"], "source.identity")
    profile_version = bounded_text(source["profile_version"], "source.profile_version")
    content_hash = source["content_sha256"]
    if not isinstance(content_hash, str) or not HASH_RE.fullmatch(content_hash):
        fail("invalid source content hash")
    profile = PROFILES.get(source_format)
    if profile is None:
        fail(f"unsupported source format: {source_format}")
    if identity != profile["identity"]:
        fail(f"source.identity does not match {source_format}")
    if profile_version != profile["profile_version"]:
        fail(f"source.profile_version does not match {source_format}")
    source_path = (ROOT / identity).resolve()
    try:
        source_path.relative_to(ROOT)
    except ValueError:
        fail("source identity escapes repository")
    if not source_path.is_file():
        fail(f"source file unavailable: {identity}")
    expected_hash = "sha256:" + hashlib.sha256(source_path.read_bytes()).hexdigest()
    if content_hash != expected_hash:
        fail("source content hash mismatch")

    provenance = data["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != expected_roles:
        fail("provenance roles do not match colors")
    expected_provenance = profile["provenance"]
    for role in sorted(expected_roles):
        entry = provenance[role]
        if not isinstance(entry, dict) or set(entry) != {"kind", "source_token"}:
            fail(f"invalid provenance for {role}")
        kind = bounded_text(entry["kind"], f"provenance.{role}.kind")
        source_token = bounded_text(entry["source_token"], f"provenance.{role}.source_token")
        expected_kind, expected_token = expected_provenance[role]
        if (kind, source_token) != (expected_kind, expected_token):
            fail(f"provenance mismatch for {role}")


def validate(path: Path) -> None:
    raw = path.read_bytes()
    if len(raw) > 128 * 1024:
        fail("snapshot exceeds 131072 bytes")
    data = json.loads(raw, object_pairs_hook=no_duplicates)
    if not isinstance(data, dict):
        fail("snapshot must be an object")
    schema = json.loads(SCHEMA_PATH.read_text(), object_pairs_hook=no_duplicates)
    expected_top = set(schema["required"])
    actual_top = set(data)
    if actual_top - expected_top:
        fail("unexpected top-level fields: " + ", ".join(sorted(actual_top - expected_top)))
    if expected_top - actual_top:
        fail("missing top-level fields: " + ", ".join(sorted(expected_top - actual_top)))
    if data["schema_version"] != "1.0.0":
        fail("unsupported schema_version")
    if data["compiler_version"] != COMPILER_VERSION:
        fail("unsupported compiler_version")
    if data["variant"] != "dark":
        fail("variant must be dark in proof profile")
    if data["theme_id"] != "instrument-studio" or data["display_name"] != "Instrument Studio":
        fail("unexpected theme identity")
    colors = data["colors"]
    if not isinstance(colors, dict):
        fail("colors must be an object")
    expected_roles = set(schema["properties"]["colors"]["required"])
    if set(colors) != expected_roles:
        fail("colors must contain exactly the proof semantic roles")
    for role, value in colors.items():
        if not isinstance(value, str) or not HEX_RE.fullmatch(value):
            fail(f"invalid color for {role}")
    validate_source_and_provenance(data, expected_roles)
    if data["bounds"] != {"aliases": 0, "assets": 0, "identifier_chars": 128, "source_bytes": 65536, "tokens": 256}:
        fail("proof bounds changed")
    semantic = {"schema_version": data["schema_version"], "variant": data["variant"], "colors": colors}
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    if data["semantic_hash"] != expected:
        fail("semantic_hash mismatch")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} SNAPSHOT.json", file=sys.stderr)
        return 2
    try:
        validate(Path(argv[1]))
    except (ValidationError, OSError, json.JSONDecodeError, TypeError, KeyError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 2
    print("VALID NativeThemeV1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

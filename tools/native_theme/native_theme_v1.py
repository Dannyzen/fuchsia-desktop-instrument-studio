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

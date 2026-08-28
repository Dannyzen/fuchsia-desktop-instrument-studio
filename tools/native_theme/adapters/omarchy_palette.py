"""Palette-only stdlib TOML adapter for Omarchy colors.toml."""

from __future__ import annotations

import re
import tomllib

from native_theme_v1 import package_semantic_identity

from .common import (
    AdapterProvenance,
    derived,
    explicit,
    normalized_root,
    reject,
    reject_capabilities,
    strict_utf8,
)


_PROFILE = "omarchy-colors-toml-v1"
_HEX_RE = re.compile(r"^#[0-9a-f]{6}$")
_PALETTE_FIELDS = {
    "accent", "ansi", "background", "foreground", "mode", "muted",
    "selection", "status", "variant",
}
_DECLARATION_FIELDS = {"declared_layer", "profile_version"}


def _color(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX_RE.fullmatch(value) is None:
        reject("E_COLOR_CANONICAL", f"{label} must be lowercase #rrggbb")
    return value + "ff"


def _table(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        reject("E_FIELD_REQUIRED", f"{label} must be a table")
    missing = fields - set(value)
    if missing:
        reject("E_FIELD_REQUIRED", f"{label} is missing {sorted(missing)[0]}")
    extras = set(value) - fields
    if extras:
        reject("E_FIELD_EXTRA", f"{label} has unsupported field {sorted(extras)[0]}")
    return value


def _ramp(value: object, label: str, size: int) -> list[str]:
    if not isinstance(value, list) or len(value) != size:
        reject("E_FIELD_REQUIRED", f"{label} must contain exactly {size} colors")
    return [_color(item, f"{label}[{index}]") for index, item in enumerate(value)]


def adapt_omarchy_palette(raw: bytes, template_package: object, provenance: AdapterProvenance) -> dict[str, object]:
    text = strict_utf8(raw)
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        reject("E_TOML_PARSE", f"invalid colors.toml: {exc}")
    reject_capabilities(value)
    missing = _PALETTE_FIELDS - set(value)
    if missing:
        reject("E_FIELD_REQUIRED", f"colors.toml is missing {sorted(missing)[0]}")
    extras = set(value) - _PALETTE_FIELDS - _DECLARATION_FIELDS
    if extras:
        reject("E_FIELD_EXTRA", f"colors.toml has unsupported field {sorted(extras)[0]}")
    if "profile_version" in value and value["profile_version"] != _PROFILE:
        reject("E_VERSION_PROFILE", f"expected profile_version {_PROFILE}")
    if "declared_layer" in value and value["declared_layer"] != "primitives":
        reject("E_PROFILE_LAYER", "colors.toml accepts only the primitives layer")
    if value["mode"] != "dark" or value["variant"] != "instrument-studio":
        reject("E_VERSION_PROFILE", "colors.toml must declare dark instrument-studio palette identity")
    background = _ramp(_table(value["background"], {"ramp"}, "background")["ramp"], "background.ramp", 3)
    foreground = _ramp(_table(value["foreground"], {"ramp"}, "foreground")["ramp"], "foreground.ramp", 3)
    ansi_table = _table(value["ansi"], {"normal", "bright"}, "ansi")
    normal = _ramp(ansi_table["normal"], "ansi.normal", 8)
    bright = _ramp(ansi_table["bright"], "ansi.bright", 8)
    status_table = _table(value["status"], {"danger", "info", "success", "warning"}, "status")
    accent = _color(value["accent"], "accent")
    muted = _color(value["muted"], "muted")
    selection = _color(value["selection"], "selection")
    status = {key: _color(status_table[key], f"status.{key}") for key in sorted(status_table)}

    # Preserve the palette in the committed profile fixture's canonical token
    # vocabulary, rather than leaking TOML parser table representation.
    preserved_tokens = {
        "accent": value["accent"],
        "ansi.bright": value["ansi"]["bright"],
        "ansi.normal": value["ansi"]["normal"],
        "background.ramp": value["background"]["ramp"],
        "foreground.ramp": value["foreground"]["ramp"],
        "mode": value["mode"],
        "muted": value["muted"],
        "selection": value["selection"],
        "status": value["status"],
        "variant": value["variant"],
    }

    token_provenance: dict[str, dict[str, str]] = {}
    root, package = normalized_root(
        raw, template_package, provenance,
        source_format="omarchy-colors-toml",
        profile_version=_PROFILE,
        preserved_tokens=preserved_tokens,
        token_provenance=token_provenance,
    )
    for source_token in sorted(preserved_tokens):
        token_provenance[f"source.{source_token}"] = explicit(source_token)
    dark = package["variants"]["dark"]

    mappings = {
        ("primitives", "canvas"): (background[1], "background.ramp[1]"),
        ("primitives", "ink"): (foreground[2], "foreground.ramp[2]"),
        ("primitives", "accent"): (accent, "accent"),
        ("primitives", "danger"): (status["danger"], "status.danger"),
        ("semantic", "surface.deep"): (background[0], "background.ramp[0]"),
        ("semantic", "surface.canvas"): (background[1], "background.ramp[1]"),
        ("semantic", "surface.raised"): (background[2], "background.ramp[2]"),
        ("semantic", "text.muted"): (muted, "muted"),
        ("semantic", "text.normal"): (foreground[2], "foreground.ramp[2]"),
        ("semantic", "interaction.accent"): (accent, "accent"),
        ("semantic", "terminal.background"): (background[1], "background.ramp[1]"),
        ("semantic", "terminal.foreground"): (foreground[2], "foreground.ramp[2]"),
        ("semantic", "terminal.selection"): (selection, "selection"),
        ("semantic", "window.active"): (accent, "accent"),
        ("components", "button.primary.color"): (accent, "accent"),
    }
    for name in ("danger", "info", "success", "warning"):
        mappings[("semantic", f"status.{name}")] = (status[name], f"status.{name}")
    for (domain, role), (color, source_token) in mappings.items():
        dark[domain][role] = color
        token_provenance[f"{domain}.{role}"] = explicit(source_token)
    for index, color in enumerate(normal + bright):
        dark["terminal"][f"ansi{index}"] = color
        source_token = f"ansi.{('normal' if index < 8 else 'bright')}[{index if index < 8 else index - 8}]"
        token_provenance[f"terminal.ansi{index}"] = explicit(source_token)
    token_provenance["semantic.interaction.selection"] = derived(
        "selection", "palette-owned-selection-policy-v1",
    )
    package["metadata"]["provenance"]["tokens"] = token_provenance
    package["metadata"]["provenance"]["semantic_hash"] = package_semantic_identity(package)
    return root

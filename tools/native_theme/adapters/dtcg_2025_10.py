"""Strict DTCG 2025.10 subset adapter with bounded alias resolution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

from native_theme_v1 import LIMITS, package_semantic_identity

from .common import (
    AdapterProvenance,
    capability_code,
    derived,
    explicit,
    inherited,
    normalized_root,
    parse_json,
    reject,
)


_PROFILE = "dtcg-2025.10-instrument-studio-v1"
_ROOT_FIELDS = {"declared_layer", "profile_version", "tokens"}
_GROUP_METADATA = {"$description", "$extensions", "$type"}
_TOKEN_FIELDS = {"$description", "$extensions", "$type", "$value"}
_SUPPORTED_TYPES = {
    "border", "color", "cubicBezier", "dimension", "duration", "fontFamily",
    "fontWeight", "gradient", "number", "shadow", "transition", "typography",
}
_ALIAS_RE = re.compile(r"^\{([A-Za-z0-9][A-Za-z0-9_.-]{0,255})\}$")
_EXTENSION_PREFIX = "org.constructresearch.instrumentstudio."


@dataclass(frozen=True)
class _Token:
    name: str
    token_type: str
    value: object
    inherited_type: bool


def _number(value: object, label: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject("E_PROFILE_STRUCTURE", f"{label} must be a finite number")
    number = float(value)
    if low is not None and number < low or high is not None and number > high:
        reject("E_PROFILE_STRUCTURE", f"{label} is outside its supported range")
    return number


def _exact(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        reject("E_PROFILE_STRUCTURE", f"{label} must have exact fields {','.join(sorted(fields))}")
    return value


def _extensions(value: object, label: str) -> None:
    if not isinstance(value, dict):
        reject("E_EXTENSION_UNSUPPORTED", f"{label} must be an extension object")
    for key in value:
        if not key.startswith(_EXTENSION_PREFIX):
            reject("E_EXTENSION_UNSUPPORTED", f"unsupported extension namespace {key}")


def _description(value: object, label: str) -> None:
    if not isinstance(value, str) or not value:
        reject("E_PROFILE_STRUCTURE", f"{label} must be non-empty text")


def _reject_capabilities(value: object, location: str = "tokens") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not key.startswith("$") and capability_code(key, child) is not None:
                reject("E_EXECUTABLE", f"{location}.{key} requests executable/runtime content")
            _reject_capabilities(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_capabilities(child, f"{location}[{index}]")


def _dimension(value: object, label: str) -> None:
    item = _exact(value, {"unit", "value"}, label)
    if item["unit"] not in {"px", "rem"}:
        reject("E_PROFILE_STRUCTURE", f"{label}.unit is unsupported")
    _number(item["value"], f"{label}.value")


def _duration(value: object, label: str) -> None:
    item = _exact(value, {"unit", "value"}, label)
    if item["unit"] not in {"ms", "s"}:
        reject("E_PROFILE_STRUCTURE", f"{label}.unit is unsupported")
    _number(item["value"], f"{label}.value", low=0)


def _color(value: object, label: str) -> str:
    item = _exact(value, {"alpha", "colorSpace", "components"}, label)
    if item["colorSpace"] != "srgb":
        reject("E_COLOR_SPACE", f"{label}.colorSpace must be srgb")
    components = item["components"]
    if not isinstance(components, list) or len(components) != 3:
        reject("E_COLOR_COMPONENT", f"{label}.components must contain three channels")
    channels = []
    for index, component in enumerate(components):
        if isinstance(component, bool) or not isinstance(component, (int, float)) or not 0 <= component <= 1:
            reject("E_COLOR_COMPONENT", f"{label}.components[{index}] must be in 0..1")
        channels.append(component)
    alpha = item["alpha"]
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0 <= alpha <= 1:
        reject("E_COLOR_COMPONENT", f"{label}.alpha must be in 0..1")
    quantized: list[int] = []
    for component in channels + [alpha]:
        decimal = Decimal(str(component))
        quantized.append(int((decimal * Decimal(255)).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
    return "#" + "".join(f"{component:02x}" for component in quantized)


def _bezier(value: object, label: str) -> None:
    if not isinstance(value, list) or len(value) != 4:
        reject("E_PROFILE_STRUCTURE", f"{label} must contain four numbers")
    numbers = [_number(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if not 0 <= numbers[0] <= 1 or not 0 <= numbers[2] <= 1:
        reject("E_PROFILE_STRUCTURE", f"{label} x coordinates must be in 0..1")


def _font_family(value: object, label: str) -> None:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values):
        reject("E_PROFILE_STRUCTURE", f"{label} must be a non-empty font-family string/list")


def _gradient(value: object, label: str) -> None:
    if not isinstance(value, list) or not value:
        reject("E_PROFILE_STRUCTURE", f"{label} must contain gradient stops")
    previous = -1.0
    for index, raw_stop in enumerate(value):
        stop = _exact(raw_stop, {"color", "position"}, f"{label}[{index}]")
        _color(stop["color"], f"{label}[{index}].color")
        position = _number(stop["position"], f"{label}[{index}].position", low=0, high=1)
        if position < previous:
            reject("E_PROFILE_STRUCTURE", f"{label} positions must be monotonic")
        previous = position


def _shadow_item(value: object, label: str) -> None:
    shadow = _exact(value, {"blur", "color", "offsetX", "offsetY", "spread"}, label)
    for field in ("blur", "offsetX", "offsetY", "spread"):
        _dimension(shadow[field], f"{label}.{field}")
    _color(shadow["color"], f"{label}.color")


def _shadow(value: object, label: str) -> None:
    if isinstance(value, list):
        if not value:
            reject("E_PROFILE_STRUCTURE", f"{label} cannot be empty")
        for index, item in enumerate(value):
            _shadow_item(item, f"{label}[{index}]")
    else:
        _shadow_item(value, label)


def _transition(value: object, label: str) -> None:
    transition = _exact(value, {"delay", "duration", "timingFunction"}, label)
    _duration(transition["delay"], f"{label}.delay")
    _duration(transition["duration"], f"{label}.duration")
    _bezier(transition["timingFunction"], f"{label}.timingFunction")


def _typography(value: object, label: str) -> None:
    typography = _exact(
        value,
        {"fontFamily", "fontSize", "fontWeight", "letterSpacing", "lineHeight"},
        label,
    )
    _font_family(typography["fontFamily"], f"{label}.fontFamily")
    _dimension(typography["fontSize"], f"{label}.fontSize")
    _font_weight(typography["fontWeight"], f"{label}.fontWeight")
    _dimension(typography["letterSpacing"], f"{label}.letterSpacing")
    _number(typography["lineHeight"], f"{label}.lineHeight", low=0)


def _font_weight(value: object, label: str) -> None:
    if isinstance(value, str):
        if value not in {"normal", "bold"}:
            reject("E_PROFILE_STRUCTURE", f"{label} keyword is unsupported")
        return
    _number(value, label, low=1, high=1000)


def _validate_literal(token_type: str, value: object, label: str) -> str | None:
    if token_type == "color":
        return _color(value, label)
    if token_type == "border":
        border = _exact(value, {"color", "style", "width"}, label)
        _color(border["color"], f"{label}.color")
        if border["style"] not in {"solid", "dashed", "dotted", "double"}:
            reject("E_PROFILE_STRUCTURE", f"{label}.style is unsupported")
        _dimension(border["width"], f"{label}.width")
    elif token_type == "dimension":
        _dimension(value, label)
    elif token_type == "duration":
        _duration(value, label)
    elif token_type == "cubicBezier":
        _bezier(value, label)
    elif token_type == "fontFamily":
        _font_family(value, label)
    elif token_type == "fontWeight":
        _font_weight(value, label)
    elif token_type == "gradient":
        _gradient(value, label)
    elif token_type == "number":
        _number(value, label)
    elif token_type == "shadow":
        _shadow(value, label)
    elif token_type == "transition":
        _transition(value, label)
    else:
        _typography(value, label)
    return None


def _collect(tokens: dict[str, object]) -> dict[str, _Token]:
    collected: dict[str, _Token] = {}

    def walk(value: object, path: tuple[str, ...], inherited_type: str | None) -> None:
        if not isinstance(value, dict):
            reject("E_PROFILE_STRUCTURE", f"token/group {'.'.join(path)} must be an object")
        if "$description" in value:
            _description(value["$description"], f"{'.'.join(path)}.$description")
        if "$extensions" in value:
            _extensions(value["$extensions"], f"{'.'.join(path)}.$extensions")
        local_type = value.get("$type")
        if local_type is not None and (not isinstance(local_type, str) or local_type not in _SUPPORTED_TYPES):
            reject("E_TYPE_UNSUPPORTED", f"{'.'.join(path)} has unsupported $type")
        if inherited_type is not None and local_type is not None and local_type != inherited_type:
            reject("E_TYPE_INHERITED", f"{'.'.join(path)} conflicts with inherited type {inherited_type}")
        effective_type = local_type or inherited_type
        if "$value" in value:
            extras = set(value) - _TOKEN_FIELDS
            if extras:
                reject("E_FIELD_FORBIDDEN", f"token {'.'.join(path)} has child/unknown fields")
            if not path or effective_type is None:
                reject("E_PROFILE_STRUCTURE", f"token {'.'.join(path)} has no declared/inherited type")
            name = ".".join(path)
            collected[name] = _Token(name, effective_type, value["$value"], local_type is None)
            return
        unknown_metadata = {key for key in value if key.startswith("$")} - _GROUP_METADATA
        if unknown_metadata:
            reject("E_FIELD_FORBIDDEN", f"group {'.'.join(path)} has unsupported field {sorted(unknown_metadata)[0]}")
        children = [key for key in value if not key.startswith("$")]
        if not children and path:
            reject("E_PROFILE_STRUCTURE", f"group {'.'.join(path)} is empty")
        for key in sorted(children):
            if not key or "." in key:
                reject("E_PROFILE_STRUCTURE", "DTCG group/token names must be bounded path segments")
            walk(value[key], path + (key,), effective_type)

    walk(tokens, (), None)
    if not collected:
        reject("E_PROFILE_STRUCTURE", "DTCG source contains no tokens")
    if len(collected) > LIMITS["tokens"]:
        reject("E_LIMIT_TOKENS", "DTCG token count exceeds 1024")
    return collected


def _resolve(tokens: dict[str, _Token]) -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    resolved: dict[str, object] = {}
    provenance: dict[str, dict[str, str]] = {}
    visiting: list[str] = []

    def resolve(name: str, depth: int = 0) -> object:
        if name in resolved:
            return resolved[name]
        if depth > LIMITS["alias_depth"]:
            reject("E_LIMIT_ALIAS_DEPTH", f"alias {name} exceeds depth 32")
        if name in visiting:
            cycle = visiting[visiting.index(name):] + [name]
            reject("E_ALIAS_CYCLE", "alias cycle: " + " -> ".join(cycle))
        token = tokens[name]
        alias = _ALIAS_RE.fullmatch(token.value) if isinstance(token.value, str) else None
        if alias is not None:
            target = alias.group(1)
            if target not in tokens:
                reject("E_ALIAS_UNRESOLVED", f"alias {name} targets unknown token {target}")
            if tokens[target].token_type != token.token_type:
                reject("E_TYPE_INHERITED", f"alias {name} conflicts with target type")
            visiting.append(name)
            result = resolve(target, depth + 1)
            visiting.pop()
            provenance[name] = derived(target, "curly-alias-resolution")
        else:
            result = token.value
            _validate_literal(token.token_type, result, name)
            provenance[name] = inherited(name) if token.inherited_type else explicit(name)
        resolved[name] = result
        return result

    for name in sorted(tokens):
        resolve(name)
    return resolved, provenance


def adapt_dtcg_2025_10(raw: bytes, template_package: object, provenance: AdapterProvenance) -> dict[str, object]:
    value = parse_json(raw)
    _reject_capabilities(value)
    missing = _ROOT_FIELDS - set(value)
    if missing:
        reject("E_PROFILE_STRUCTURE", "DTCG root requires declared_layer, profile_version, and tokens")
    extras = set(value) - _ROOT_FIELDS
    if extras:
        reject("E_FIELD_FORBIDDEN", f"DTCG root has unsupported field {sorted(extras)[0]}")
    if value["profile_version"] != _PROFILE:
        reject("E_VERSION_PROFILE", f"expected profile_version {_PROFILE}")
    if value["declared_layer"] not in {"components", "primitives", "semantic"}:
        reject("E_PROFILE_LAYER", "DTCG adapter accepts only declared profile layers")
    if not isinstance(value["tokens"], dict):
        reject("E_PROFILE_STRUCTURE", "DTCG tokens must be an object")
    tokens = _collect(value["tokens"])
    resolved, token_provenance = _resolve(tokens)
    root, package = normalized_root(
        raw, template_package, provenance,
        source_format="dtcg-json",
        profile_version=_PROFILE,
        preserved_tokens=value["tokens"],
        token_provenance=token_provenance,
    )

    # Only the one committed stable role is runtime-authoritative in this
    # release. All other validated composites remain inert metadata.
    if "group.canvas" not in tokens or tokens["group.canvas"].token_type != "color":
        reject("E_FIELD_REQUIRED", "DTCG source must declare stable color role group.canvas")
    canvas = _validate_literal("color", resolved["group.canvas"], "group.canvas")
    dark = package["variants"]["dark"]
    for domain, role in (
        ("primitives", "canvas"),
        ("semantic", "surface.canvas"),
        ("semantic", "terminal.background"),
    ):
        dark[domain][role] = canvas
        token_provenance[f"runtime.{domain}.{role}"] = inherited("group.canvas")
    package["metadata"]["provenance"]["tokens"] = token_provenance
    package["metadata"]["provenance"]["semantic_hash"] = package_semantic_identity(package)
    return root

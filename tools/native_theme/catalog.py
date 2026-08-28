#!/usr/bin/env python3
"""Deterministic, fail-closed NativeTheme catalog generator and verifier.

The library API consumes caller-supplied bytes and objects.  Only ``main`` and
its small path helpers have filesystem authority, always beneath explicit roots.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import NoReturn

from adapters import (
    AdapterError,
    AdapterProvenance,
    adapt_base16,
    adapt_base24,
    adapt_dtcg_2025_10,
    adapt_omarchy_palette,
)
from compiler_core import CompilerError, compile_normalized
from native_theme_v1 import (
    ContractError,
    LIMITS,
    canonical_json_bytes,
    package_semantic_identity,
    validate_package,
)


CATALOG_SCHEMA = "native-theme-catalog-v1"
GENERATION_SCHEMA = "native-theme-catalog-generation-v1"
INSPECT_SCHEMA = "native-theme-inspect-v1"
COMPARE_SCHEMA = "native-theme-compare-v1"
DESCRIPTOR_SCHEMA = "native-theme-catalog-source-v1"
RECEIPT_SCHEMA = "native-theme-catalog-receipt-v1"
SUPPORTED_COMPILER_VERSION = "1.0.0"
SUPPORTED_PACKAGE_SCHEMA = "1.0.0"
EXPECTED_ENTRY_COUNT = 4
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
OUTPUT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.json$")
ADAPTERS = {
    "base16": adapt_base16,
    "base24": adapt_base24,
    "dtcg-2025.10": adapt_dtcg_2025_10,
    "omarchy-colors-toml": adapt_omarchy_palette,
}
ADAPTER_IDENTITIES = {
    "base16": ("base16-json", "base16-v1"),
    "base24": ("base24-json", "base24-v1"),
    "dtcg-2025.10": ("dtcg-json", "dtcg-2025.10-instrument-studio-v1"),
    "omarchy-colors-toml": ("omarchy-colors-toml", "omarchy-colors-toml-v1"),
}
DESCRIPTOR_FIELDS = {
    "schema_version", "compiler_version", "package_schema_version",
    "template_path", "template_hash", "budgets", "entries",
}
ENTRY_FIELDS = {
    "id", "adapter", "source_path", "source_identity", "source_format",
    "profile_version", "license", "expected",
}
EXPECTED_FIELDS = {"source_hash", "semantic_hash", "package_hash", "receipt_hash"}
LICENSE_FIELDS = {"spdx", "attribution", "notice"}
BUDGET_FIELDS = {
    "max_entries", "max_catalog_bytes", "max_package_bytes", "max_receipt_bytes",
    "max_tokens", "max_assets", "max_decoded_asset_bytes",
    "max_decoded_assets_total_bytes",
}
REQUIRED_BUDGETS = {
    "max_entries": EXPECTED_ENTRY_COUNT,
    "max_catalog_bytes": LIMITS["catalog_bytes"],
    "max_package_bytes": LIMITS["compiled_pack_bytes"],
    "max_receipt_bytes": 16 * 1024,
    "max_tokens": LIMITS["tokens"],
    "max_assets": LIMITS["semantic_assets"],
    "max_decoded_asset_bytes": LIMITS["decoded_asset_bytes"],
    "max_decoded_assets_total_bytes": LIMITS["decoded_assets_total_bytes"],
}
ARTIFACT_METADATA_MAX_BYTES = 256 * 1024


class CatalogError(ValueError):
    """One stable catalog rejection."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _reject(code: str, message: str) -> NoReturn:
    raise CatalogError(code, message)


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        return canonical_json_bytes(value)
    except ContractError as exc:
        match = re.match(r"^(E_[A-Z0-9_]+):\s*(.*)$", str(exc))
        if match is not None:
            _reject(match.group(1), match.group(2))
        _reject("E_CANONICAL", str(exc))
    except (TypeError, ValueError) as exc:
        _reject("E_CANONICAL", f"value is not canonical JSON: {exc}")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _reject("E_JSON_DUPLICATE", f"duplicate JSON key {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> NoReturn:
    _reject("E_NUMBER_NONFINITE", f"non-finite JSON number {value}")


def _parse_json(raw: object, *, code: str, max_bytes: int) -> dict[str, object]:
    if not isinstance(raw, bytes):
        _reject("E_BYTES_REQUIRED", "input must be bytes")
    if len(raw) > max_bytes:
        _reject(code, f"input exceeds {max_bytes} bytes")
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs,
                           parse_constant=_nonfinite)
    except CatalogError:
        raise
    except UnicodeDecodeError:
        _reject("E_UTF8", "input must be strict UTF-8")
    except RecursionError:
        _reject("E_LIMIT_NESTING", "JSON nesting exceeds the supported limit")
    except json.JSONDecodeError as exc:
        _reject("E_JSON_PARSE", f"invalid JSON at line {exc.lineno} column {exc.colno}")
    except ValueError:
        _reject("E_JSON_PARSE", "invalid JSON numeric value")
    if not isinstance(value, dict):
        _reject("E_JSON_ROOT", "JSON root must be an object")
    return value


def _exact(value: object, fields: set[str], code: str, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        _reject(code, f"{label} must have exact fields {','.join(sorted(fields))}")
    return value


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _reject("E_PATH", f"{label} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute():
        _reject("E_PATH_OUTSIDE_ROOT", f"{label} must be relative")
    if value != path.as_posix():
        _reject("E_PATH_TRAVERSAL", f"{label} must be a canonical POSIX path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        _reject("E_PATH_TRAVERSAL", f"{label} contains traversal or empty segments")
    return value


def _expected_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _reject("E_HASH_FORMAT", f"{label} must be canonical sha256")
    return value


def parse_descriptor_bytes(raw: object) -> dict[str, object]:
    """Parse and validate one canonical catalog source descriptor."""
    descriptor = _parse_json(raw, code="E_LIMIT_DESCRIPTOR", max_bytes=256 * 1024)
    if _canonical(descriptor) + b"\n" != raw:
        _reject("E_NONCANONICAL", "descriptor must be compact sorted JSON with one newline")
    _exact(descriptor, DESCRIPTOR_FIELDS, "E_DESCRIPTOR_FIELDS", "descriptor")
    if descriptor["schema_version"] != DESCRIPTOR_SCHEMA:
        _reject("E_VERSION_DESCRIPTOR", "unsupported descriptor schema")
    if descriptor["compiler_version"] != SUPPORTED_COMPILER_VERSION:
        _reject("E_VERSION_COMPILER", "unsupported compiler version")
    if descriptor["package_schema_version"] != SUPPORTED_PACKAGE_SCHEMA:
        _reject("E_VERSION_SCHEMA", "unsupported package schema")
    _safe_relative(descriptor["template_path"], "template_path")
    _expected_hash(descriptor["template_hash"], "template_hash")
    budgets = _exact(descriptor["budgets"], BUDGET_FIELDS, "E_BUDGET_FIELDS", "budgets")
    if budgets != REQUIRED_BUDGETS:
        _reject("E_BUDGET_INCOMPATIBLE", "descriptor budgets must equal supported fail-closed limits")
    entries = descriptor["entries"]
    if not isinstance(entries, list) or len(entries) != EXPECTED_ENTRY_COUNT:
        _reject("E_ENTRY_COUNT", "descriptor must contain exactly four entries")
    ids: set[str] = set()
    identities: set[str] = set()
    previous = ""
    for entry in entries:
        item = _exact(entry, ENTRY_FIELDS, "E_ENTRY_FIELDS", "entry")
        identifier = item["id"]
        if not isinstance(identifier, str) or ID_RE.fullmatch(identifier) is None:
            _reject("E_ID", "entry id must be canonical kebab-case")
        if identifier in ids:
            _reject("E_ID_DUPLICATE", f"duplicate entry id {identifier}")
        if identifier <= previous:
            _reject("E_ENTRY_ORDER", "entries must be sorted by id")
        previous = identifier
        ids.add(identifier)
        if item["adapter"] not in ADAPTERS:
            _reject("E_ADAPTER_UNKNOWN", f"unknown adapter {item['adapter']}")
        source_path = _safe_relative(item["source_path"], "source_path")
        identity = _safe_relative(item["source_identity"], "source_identity")
        if source_path != identity:
            _reject("E_SOURCE_IDENTITY", "source_path and source_identity must match")
        if identity in identities:
            _reject("E_SOURCE_IDENTITY_DUPLICATE", f"duplicate source identity {identity}")
        identities.add(identity)
        for field in ("source_format", "profile_version"):
            if not isinstance(item[field], str) or not item[field]:
                _reject("E_IDENTITY", f"{field} must be non-empty")
        source_format, profile_version = ADAPTER_IDENTITIES[item["adapter"]]
        if item["source_format"] != source_format:
            _reject("E_SOURCE_FORMAT", "source format is incompatible with adapter")
        if item["profile_version"] != profile_version:
            _reject("E_PROFILE_IDENTITY", "profile identity is incompatible with adapter")
        license_data = _exact(item["license"], LICENSE_FIELDS, "E_LICENSE_FIELDS", "license")
        if license_data["spdx"] != "BSD-3-Clause":
            _reject("E_LICENSE", "catalog sources require BSD-3-Clause")
        if not isinstance(license_data["attribution"], str) or not license_data["attribution"]:
            _reject("E_ATTRIBUTION", "attribution is required")
        if not isinstance(license_data["notice"], str) or not license_data["notice"]:
            _reject("E_LICENSE_NOTICE", "license notice is required")
        expected = _exact(item["expected"], EXPECTED_FIELDS, "E_EXPECTED_FIELDS", "expected")
        for field in sorted(EXPECTED_FIELDS):
            _expected_hash(expected[field], field)
    expected_ids = {f"instrument-studio-{name}" for name in ("base16", "base24", "dtcg", "omarchy")}
    if ids != expected_ids:
        _reject("E_ID_SET", "descriptor must bind the four approved catalog ids")
    return copy.deepcopy(descriptor)


def _adapter_error(exc: Exception) -> NoReturn:
    if isinstance(exc, (AdapterError, CompilerError)):
        _reject(exc.code, exc.message)
    if isinstance(exc, ContractError):
        match = re.match(r"^(E_[A-Z0-9_]+):\s*(.*)$", str(exc))
        if match is not None:
            _reject(match.group(1), match.group(2))
    _reject("E_PACKAGE_VALIDATION", str(exc))


def _package_metrics(package: dict[str, object]) -> dict[str, int]:
    token_count = 0
    asset_ids: set[str] = set()
    decoded_total = 0
    largest_asset = 0
    for variant in package["variants"].values():
        token_count += sum(len(variant[layer]) for layer in ("primitives", "semantic", "components", "terminal"))
        for asset_id, asset in variant["assets"]["items"].items():
            asset_ids.add(asset_id)
            decoded_total += asset["decoded_bytes"]
            largest_asset = max(largest_asset, asset["decoded_bytes"])
    return {
        "asset_count": len(asset_ids),
        "decoded_asset_bytes": largest_asset,
        "decoded_assets_total_bytes": decoded_total,
        "token_count": token_count,
    }


def _public_metrics(metrics: dict[str, int]) -> dict[str, int]:
    return {
        "asset_count": metrics["asset_count"],
        "largest_decoded_asset_bytes": metrics["decoded_asset_bytes"],
        "token_count": metrics["token_count"],
        "total_decoded_asset_bytes": metrics["decoded_assets_total_bytes"],
    }


def build_entry_artifacts(entry: object, source_bytes: object, template_bytes: object,
                          budgets: object) -> tuple[bytes, bytes, dict[str, object]]:
    """Compile one validated entry from supplied bytes, without checking expectations."""
    item = _exact(entry, ENTRY_FIELDS, "E_ENTRY_FIELDS", "entry")
    limits = _exact(budgets, BUDGET_FIELDS, "E_BUDGET_FIELDS", "budgets")
    if not isinstance(source_bytes, bytes) or not isinstance(template_bytes, bytes):
        _reject("E_BYTES_REQUIRED", "source and template must be bytes")
    source_hash = _hash(source_bytes)
    provenance_data = item["license"]
    try:
        provenance = AdapterProvenance(
            source_identity=item["source_identity"],
            license_spdx=provenance_data["spdx"],
            attribution=provenance_data["attribution"],
            notice=provenance_data["notice"],
        )
        normalized = ADAPTERS[item["adapter"]](source_bytes, template_bytes, provenance)
        result = compile_normalized(normalized)
        validate_package(result.package)
    except (AdapterError, CompilerError, ContractError, TypeError, ValueError) as exc:
        _adapter_error(exc)
    package_provenance = result.package["metadata"]["provenance"]
    package_license = result.package["metadata"]["license"]
    expected_provenance = {
        "source_identity": item["source_identity"],
        "source_format": item["source_format"],
        "profile_version": item["profile_version"],
        "compiler_version": SUPPORTED_COMPILER_VERSION,
        "content_hash": source_hash,
        "semantic_hash": result.semantic_hash,
        "license": provenance_data["spdx"],
        "attribution": provenance_data["attribution"],
    }
    for field, expected_value in expected_provenance.items():
        if package_provenance[field] != expected_value:
            _reject("E_PROVENANCE_BINDING", f"package provenance {field} is not descriptor-bound")
    if package_license != {
        "notice": provenance_data["notice"],
        "spdx": provenance_data["spdx"],
    }:
        _reject("E_PROVENANCE_BINDING", "package license is not descriptor-bound")
    package_bytes = _canonical(result.package) + b"\n"
    if len(package_bytes) > limits["max_package_bytes"]:
        _reject("E_LIMIT_PACK", "package exceeds catalog package budget")
    metrics = _package_metrics(result.package)
    if metrics["token_count"] > limits["max_tokens"]:
        _reject("E_LIMIT_TOKENS", "package token budget exceeded")
    if metrics["asset_count"] > limits["max_assets"]:
        _reject("E_LIMIT_ASSETS", "package asset budget exceeded")
    if metrics["decoded_asset_bytes"] > limits["max_decoded_asset_bytes"]:
        _reject("E_LIMIT_ASSET_BYTES", "single decoded asset budget exceeded")
    if metrics["decoded_assets_total_bytes"] > limits["max_decoded_assets_total_bytes"]:
        _reject("E_LIMIT_ASSETS_TOTAL", "decoded asset total budget exceeded")
    package_hash = _hash(package_bytes)
    receipt = {
        "adapter": item["adapter"],
        "attribution": package_provenance["attribution"],
        "compiler_version": package_provenance["compiler_version"],
        "id": item["id"],
        "license": package_provenance["license"],
        "metrics": metrics,
        "package_bytes": len(package_bytes),
        "package_hash": package_hash,
        "package_schema_version": SUPPORTED_PACKAGE_SCHEMA,
        "profile_version": package_provenance["profile_version"],
        "schema_version": RECEIPT_SCHEMA,
        "semantic_hash": package_provenance["semantic_hash"],
        "source_format": package_provenance["source_format"],
        "source_hash": package_provenance["content_hash"],
        "source_identity": package_provenance["source_identity"],
    }
    receipt_bytes = _canonical(receipt) + b"\n"
    if len(receipt_bytes) > limits["max_receipt_bytes"]:
        _reject("E_LIMIT_RECEIPT", "receipt exceeds catalog receipt budget")
    return package_bytes, receipt_bytes, receipt


def _validate_source_map(descriptor: dict[str, object], supplied: object) -> dict[str, bytes]:
    if not isinstance(supplied, dict) or any(not isinstance(k, str) or not isinstance(v, bytes) for k, v in supplied.items()):
        _reject("E_SOURCE_MAP", "sources must be a string-to-bytes object")
    expected = {descriptor["template_path"], *(entry["source_path"] for entry in descriptor["entries"])}
    if set(supplied) != expected:
        _reject("E_SOURCE_INVENTORY", "supplied sources differ from descriptor inventory")
    return supplied


def generate_catalog(descriptor: object, supplied_sources: object) -> dict[str, bytes]:
    """Generate the complete catalog in memory from validated supplied inputs."""
    if not isinstance(descriptor, dict):
        _reject("E_DESCRIPTOR_TYPE", "descriptor must be a validated object")
    canonical_descriptor = _canonical(descriptor) + b"\n"
    checked = parse_descriptor_bytes(canonical_descriptor)
    sources = _validate_source_map(checked, supplied_sources)
    template = sources[checked["template_path"]]
    if _hash(template) != checked["template_hash"]:
        _reject("E_TEMPLATE_HASH_DRIFT", "template hash differs from descriptor")
    artifacts: dict[str, bytes] = {}
    index_entries: list[dict[str, object]] = []
    aggregate = {
        "asset_count": 0,
        "entry_count": len(checked["entries"]),
        "largest_decoded_asset_bytes": 0,
        "package_bytes": 0,
        "receipt_bytes": 0,
        "token_count": 0,
        "total_decoded_asset_bytes": 0,
    }
    for entry in checked["entries"]:
        source = sources[entry["source_path"]]
        if _hash(source) != entry["expected"]["source_hash"]:
            _reject("E_SOURCE_HASH_DRIFT", f"source hash drift for {entry['id']}")
        package_bytes, receipt_bytes, receipt = build_entry_artifacts(entry, source, template, checked["budgets"])
        if receipt["semantic_hash"] != entry["expected"]["semantic_hash"]:
            _reject("E_SEMANTIC_HASH_DRIFT", f"semantic hash drift for {entry['id']}")
        if receipt["package_hash"] != entry["expected"]["package_hash"]:
            _reject("E_PACKAGE_HASH_DRIFT", f"package hash drift for {entry['id']}")
        receipt_hash = _hash(receipt_bytes)
        if receipt_hash != entry["expected"]["receipt_hash"]:
            _reject("E_RECEIPT_HASH_DRIFT", f"receipt hash drift for {entry['id']}")
        package_file = f"{entry['id']}.package.json"
        receipt_file = f"{entry['id']}.receipt.json"
        if package_file in artifacts or receipt_file in artifacts:
            _reject("E_OUTPUT_COLLISION", f"artifact collision for {entry['id']}")
        artifacts[package_file] = package_bytes
        artifacts[receipt_file] = receipt_bytes
        metrics = receipt["metrics"]
        aggregate["asset_count"] += metrics["asset_count"]
        aggregate["largest_decoded_asset_bytes"] = max(
            aggregate["largest_decoded_asset_bytes"], metrics["decoded_asset_bytes"])
        aggregate["package_bytes"] += len(package_bytes)
        aggregate["receipt_bytes"] += len(receipt_bytes)
        aggregate["token_count"] += metrics["token_count"]
        aggregate["total_decoded_asset_bytes"] += metrics["decoded_assets_total_bytes"]
        package_license = json.loads(package_bytes)["metadata"]["license"]
        index_entries.append({
            "adapter": entry["adapter"], "attribution": receipt["attribution"],
            "compiler_version": receipt["compiler_version"], "id": entry["id"],
            "license_spdx": receipt["license"], "notice": package_license["notice"],
            "package_file": package_file, "package_hash": receipt["package_hash"],
            "package_schema_version": receipt["package_schema_version"],
            "profile_version": receipt["profile_version"], "receipt_file": receipt_file,
            "receipt_hash": receipt_hash, "semantic_hash": receipt["semantic_hash"],
            "source_format": receipt["source_format"], "source_hash": receipt["source_hash"],
            "source_identity": receipt["source_identity"],
        })
    index = {
        "aggregate": aggregate,
        "budgets": copy.deepcopy(checked["budgets"]),
        "entries": index_entries,
        "schema_version": CATALOG_SCHEMA,
    }
    artifacts["catalog-index.json"] = _canonical(index) + b"\n"
    manifest_items = [
        {"file": name, "sha256": _hash(artifacts[name]), "size": len(artifacts[name])}
        for name in sorted(artifacts)
    ]
    manifest = {
        "artifacts": manifest_items,
        "descriptor_hash": _hash(canonical_descriptor),
        "schema_version": GENERATION_SCHEMA,
    }
    artifacts["generation-manifest.json"] = _canonical(manifest) + b"\n"
    artifacts = {name: artifacts[name] for name in sorted(artifacts)}
    if sum(map(len, artifacts.values())) > checked["budgets"]["max_catalog_bytes"]:
        _reject("E_LIMIT_CATALOG", "generated catalog exceeds total budget")
    return artifacts


def _artifact_limit(name: str, budgets: dict[str, int]) -> tuple[int, str]:
    if name.endswith(".package.json"):
        return budgets["max_package_bytes"], "E_LIMIT_PACK"
    if name.endswith(".receipt.json"):
        return budgets["max_receipt_bytes"], "E_LIMIT_RECEIPT"
    return ARTIFACT_METADATA_MAX_BYTES, "E_LIMIT_ARTIFACT_METADATA"


def _check_artifact_budgets(artifacts: dict[str, bytes], budgets: dict[str, int]) -> None:
    total = 0
    for name in sorted(artifacts):
        maximum, code = _artifact_limit(name, budgets)
        if len(artifacts[name]) > maximum:
            _reject(code, f"artifact {name} exceeds {maximum} bytes")
        total += len(artifacts[name])
        if total > budgets["max_catalog_bytes"]:
            _reject("E_LIMIT_CATALOG", "supplied artifacts exceed total catalog budget")


def verify_catalog(descriptor: object, supplied_sources: object,
                   supplied_artifacts: object) -> dict[str, object]:
    """Verify an explicit artifact map against a fresh deterministic generation."""
    if not isinstance(supplied_artifacts, dict) or any(
        not isinstance(k, str) or not isinstance(v, bytes) for k, v in supplied_artifacts.items()
    ):
        _reject("E_ARTIFACT_MAP", "artifacts must be a string-to-bytes object")
    if not isinstance(descriptor, dict):
        _reject("E_DESCRIPTOR_TYPE", "descriptor must be a validated object")
    checked = parse_descriptor_bytes(_canonical(descriptor) + b"\n")
    _check_artifact_budgets(supplied_artifacts, checked["budgets"])
    expected = generate_catalog(checked, supplied_sources)
    if set(supplied_artifacts) != set(expected):
        missing = sorted(set(expected) - set(supplied_artifacts))
        unexpected = sorted(set(supplied_artifacts) - set(expected))
        _reject("E_ARTIFACT_INVENTORY", f"missing={missing} unexpected={unexpected}")
    for name in sorted(expected):
        raw = supplied_artifacts[name]
        limit, code = _artifact_limit(name, checked["budgets"])
        parsed = _parse_json(raw, code=code, max_bytes=limit)
        if _canonical(parsed) + b"\n" != raw:
            _reject("E_NONCANONICAL", f"artifact {name} is not canonical")
        if raw != expected[name]:
            _reject("E_ARTIFACT_DRIFT", f"artifact drift in {name}")
    return json.loads(expected["generation-manifest.json"])


def _package_object(value: object) -> tuple[dict[str, object], bytes]:
    if isinstance(value, bytes):
        package = _parse_json(value, code="E_LIMIT_PACK", max_bytes=LIMITS["compiled_pack_bytes"])
        canonical = _canonical(package) + b"\n"
        if value != canonical:
            _reject("E_NONCANONICAL", "package bytes are not canonical with one newline")
    elif isinstance(value, dict):
        package = copy.deepcopy(value)
        canonical = _canonical(package) + b"\n"
    else:
        _reject("E_PACKAGE_TYPE", "package must be bytes or an object")
    try:
        validate_package(package)
    except ContractError as exc:
        _adapter_error(exc)
    return package, canonical


def inspect_package(value: object) -> dict[str, object]:
    """Return stable public inspection data for supplied canonical package bytes/object."""
    package, raw = _package_object(value)
    metrics = _package_metrics(package)
    provenance = package["metadata"]["provenance"]
    counts = {"derived": 0, "explicit": 0, "inherited": 0, "total": 0}
    for token in provenance["tokens"].values():
        counts[token["kind"]] += 1
        counts["total"] += 1
    return {
        "compiler_version": provenance["compiler_version"],
        "attribution": provenance["attribution"],
        "license": copy.deepcopy(package["metadata"]["license"]),
        "metrics": _public_metrics(metrics),
        "package_hash": _hash(raw),
        "package_schema_version": package["schema_version"],
        "profile": copy.deepcopy(package["profile"]),
        "schema_version": INSPECT_SCHEMA,
        "semantic_hash": provenance["semantic_hash"],
        "source": {
            "content_hash": provenance["content_hash"],
            "format": provenance["source_format"],
            "identity": provenance["source_identity"],
            "profile_version": provenance["profile_version"],
        },
        "theme": copy.deepcopy(package["theme"]),
        "token_provenance_counts": counts,
        "variants": sorted(package["variants"]),
    }


def _pointer(segment: object) -> str:
    return str(segment).replace("~", "~0").replace("/", "~1")


def _diff(left: object, right: object, pointer: str = "") -> list[dict[str, object]]:
    if type(left) is not type(right):
        return [{"left": left, "pointer": pointer or "/", "right": right}]
    if isinstance(left, dict):
        differences: list[dict[str, object]] = []
        for key in sorted(set(left) | set(right)):
            child = pointer + "/" + _pointer(key)
            if key not in left:
                differences.append({"left_missing": True, "pointer": child, "right": right[key]})
            elif key not in right:
                differences.append({"left": left[key], "pointer": child, "right_missing": True})
            else:
                differences.extend(_diff(left[key], right[key], child))
        return differences
    if isinstance(left, list):
        differences = []
        for index in range(max(len(left), len(right))):
            child = pointer + "/" + str(index)
            if index >= len(left):
                differences.append({"left_missing": True, "pointer": child, "right": right[index]})
            elif index >= len(right):
                differences.append({"left": left[index], "pointer": child, "right_missing": True})
            else:
                differences.extend(_diff(left[index], right[index], child))
        return differences
    return [] if left == right else [{"left": left, "pointer": pointer or "/", "right": right}]


def compare_packages(left: object, right: object) -> dict[str, object]:
    """Separate renderable and inert-metadata differences by JSON pointer."""
    left_package, left_raw = _package_object(left)
    right_package, right_raw = _package_object(right)
    left_semantic_hash = package_semantic_identity(left_package)
    right_semantic_hash = package_semantic_identity(right_package)
    left_metadata = left_package.pop("metadata")
    right_metadata = right_package.pop("metadata")
    renderable = _diff(left_package, right_package)
    metadata = _diff(left_metadata, right_metadata, "/metadata")
    hashes_equal = left_semantic_hash == right_semantic_hash
    renderably_equal = not renderable
    if hashes_equal != renderably_equal:
        _reject("E_COMPARE_SEMANTIC", "semantic hashes disagree with renderable differences")
    return {
        "inert_metadata_differences": metadata,
        "left": {"package_hash": _hash(left_raw), "semantic_hash": left_semantic_hash},
        "renderable_differences": renderable,
        "right": {"package_hash": _hash(right_raw), "semantic_hash": right_semantic_hash},
        "schema_version": COMPARE_SCHEMA,
        "semantically_equal": hashes_equal and renderably_equal,
    }


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def _resolved_root(root: object) -> Path:
    try:
        raw = os.fspath(root)
    except TypeError:
        _reject("E_PATH", "explicit root must be a filesystem path")
    if not isinstance(raw, str) or not raw or "\\" in raw:
        _reject("E_PATH", "explicit root must be a non-empty POSIX path")
    if raw != PurePosixPath(raw).as_posix() or raw.startswith("//"):
        _reject("E_PATH_TRAVERSAL", "explicit root must be a canonical POSIX path")
    candidate = Path(raw)
    try:
        root_stat = os.lstat(candidate)
    except OSError:
        _reject("E_IO", "cannot inspect explicit root")
    if stat.S_ISLNK(root_stat.st_mode):
        _reject("E_SYMLINK", "explicit root cannot be a symlink")
    if not stat.S_ISDIR(root_stat.st_mode):
        _reject("E_ROOT", "explicit root must be a directory")
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        _reject("E_IO", "cannot resolve explicit root")


def _open_root(root: object) -> tuple[Path, int]:
    boundary = _resolved_root(root)
    descriptor = -1
    try:
        descriptor = os.open(boundary, _DIRECTORY_FLAGS)
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            _close(descriptor)
            descriptor = -1
            _reject("E_ROOT", "explicit root must be a directory")
        return boundary, descriptor
    except CatalogError:
        raise
    except OSError:
        if descriptor >= 0:
            _close(descriptor)
        _reject("E_IO", "cannot open explicit root")


def _relative_parts(path: object, boundary: Path) -> tuple[str, ...]:
    try:
        raw = os.fspath(path)
    except TypeError:
        _reject("E_PATH", "path must be a filesystem path")
    if not isinstance(raw, str) or not raw or "\\" in raw:
        _reject("E_PATH", "path must be a non-empty POSIX path")
    lexical = PurePosixPath(raw)
    if raw != lexical.as_posix():
        _reject("E_PATH_TRAVERSAL", "path must be a canonical POSIX path")
    if lexical.is_absolute():
        try:
            lexical = lexical.relative_to(PurePosixPath(boundary.as_posix()))
        except ValueError:
            _reject("E_PATH_OUTSIDE_ROOT", "path is outside explicit root")
    if lexical == PurePosixPath("."):
        return ()
    relative = lexical.as_posix()
    _safe_relative(relative, "path")
    return tuple(relative.split("/"))


def _symlink_at(directory_fd: int, name: str) -> bool:
    try:
        return stat.S_ISLNK(os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _close(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _open_directory_at(directory_fd: int, name: str, *, type_code: str) -> int:
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
    except OSError:
        if _symlink_at(directory_fd, name):
            _reject("E_SYMLINK", "symlink directory components are forbidden")
        _reject(type_code, "path directory component is unavailable or not a directory")


def _walk_directories(root_fd: int, parts: tuple[str, ...], *, create: bool,
                      type_code: str) -> int:
    try:
        current = os.dup(root_fd)
    except OSError:
        _reject("E_IO", "cannot duplicate root descriptor")
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                except OSError:
                    _reject("E_ATOMIC_WRITE", "cannot create output parent directory")
            child = _open_directory_at(current, part, type_code=type_code)
            _close(current)
            current = child
        return current
    except BaseException:
        _close(current)
        raise


def _read_leaf(directory_fd: int, name: str, maximum: int, limit_code: str,
               label: str) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(name, _FILE_FLAGS, dir_fd=directory_fd)
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            _reject("E_IO", f"{label} is not a regular file")
        if file_stat.st_size > maximum:
            _reject(limit_code, f"{label} exceeds {maximum} bytes")
        chunks: list[bytes] = []
        total = 0
        while total <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > maximum:
            _reject(limit_code, f"{label} exceeds {maximum} bytes")
        return b"".join(chunks)
    except CatalogError:
        raise
    except OSError:
        if descriptor < 0 and _symlink_at(directory_fd, name):
            _reject("E_SYMLINK", f"{label} cannot be a symlink")
        _reject("E_IO", f"cannot read {label}")
    finally:
        if descriptor >= 0:
            _close(descriptor)


def _read_from_root(path: object, boundary: Path, root_fd: int, maximum: int,
                    limit_code: str = "E_LIMIT_SOURCE") -> bytes:
    parts = _relative_parts(path, boundary)
    if not parts:
        _reject("E_IO", "explicit input is not a regular file")
    parent_fd = _walk_directories(root_fd, parts[:-1], create=False, type_code="E_IO")
    try:
        return _read_leaf(parent_fd, parts[-1], maximum, limit_code, "explicit input")
    finally:
        _close(parent_fd)


def _read(path: object, root: object, maximum: int,
          limit_code: str = "E_LIMIT_SOURCE") -> bytes:
    boundary, root_fd = _open_root(root)
    try:
        return _read_from_root(path, boundary, root_fd, maximum, limit_code)
    finally:
        _close(root_fd)


def _read_packages(paths: list[object], package_root: object) -> list[bytes]:
    boundary, root_fd = _open_root(package_root)
    try:
        return [
            _read_from_root(path, boundary, root_fd, LIMITS["compiled_pack_bytes"])
            for path in paths
        ]
    finally:
        _close(root_fd)


def _load_cli_inputs(descriptor_path: object, source_root: object) -> tuple[dict[str, object], dict[str, bytes]]:
    boundary, root_fd = _open_root(source_root)
    try:
        raw = _read_from_root(descriptor_path, boundary, root_fd, 256 * 1024)
        descriptor = parse_descriptor_bytes(raw)
        names = [descriptor["template_path"], *(entry["source_path"] for entry in descriptor["entries"])]
        sources = {
            name: _read_from_root(name, boundary, root_fd, LIMITS["source_bytes"])
            for name in names
        }
        return descriptor, sources
    finally:
        _close(root_fd)


def _artifact_names(descriptor: dict[str, object]) -> list[str]:
    names = ["catalog-index.json", "generation-manifest.json"]
    for entry in descriptor["entries"]:
        names.extend((f"{entry['id']}.package.json", f"{entry['id']}.receipt.json"))
    return sorted(names)


def _read_artifacts(directory: object, root: object, names: list[str],
                    budgets: dict[str, int]) -> dict[str, bytes]:
    boundary, root_fd = _open_root(root)
    catalog_fd = -1
    try:
        parts = _relative_parts(directory, boundary)
        catalog_fd = _walk_directories(root_fd, parts, create=False, type_code="E_IO")
        try:
            actual_names = sorted(os.listdir(catalog_fd))
        except OSError:
            _reject("E_IO", "cannot list catalog directory")
        if actual_names != names:
            _reject("E_ARTIFACT_INVENTORY", f"expected={names} actual={actual_names}")
        artifacts: dict[str, bytes] = {}
        total = 0
        for name in names:
            maximum, code = _artifact_limit(name, budgets)
            raw = _read_leaf(catalog_fd, name, maximum, code, f"artifact {name}")
            artifacts[name] = raw
            total += len(raw)
            if total > budgets["max_catalog_bytes"]:
                _reject("E_LIMIT_CATALOG", "supplied artifacts exceed total catalog budget")
        _check_artifact_budgets(artifacts, budgets)
        return artifacts
    finally:
        if catalog_fd >= 0:
            _close(catalog_fd)
        _close(root_fd)


def _validated_artifact_map(artifacts: object) -> dict[str, bytes]:
    if not isinstance(artifacts, dict):
        _reject("E_ARTIFACT_MAP", "artifacts must be a string-to-bytes object")
    for name, raw in artifacts.items():
        if (not isinstance(name, str) or OUTPUT_NAME_RE.fullmatch(name) is None
                or ".." in name or "\\" in name or PurePosixPath(name).name != name):
            _reject("E_OUTPUT_NAME", "artifact names must be safe leaf JSON names")
        if not isinstance(raw, bytes):
            _reject("E_ARTIFACT_MAP", "artifact values must be bytes")
    return artifacts


def _node_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError:
        _reject("E_IO", "cannot inspect atomic output state")


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(descriptor, raw[offset:offset + 64 * 1024])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _flat_directory_matches(parent_fd: int, name: str,
                            artifacts: dict[str, bytes]) -> bool:
    directory_fd = -1
    try:
        directory_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        if sorted(os.listdir(directory_fd)) != sorted(artifacts):
            return False
        for leaf, expected in artifacts.items():
            if _read_leaf(directory_fd, leaf, len(expected), "E_ATOMIC_WRITE",
                          "promoted artifact") != expected:
                return False
        return True
    except (CatalogError, OSError):
        return False
    finally:
        if directory_fd >= 0:
            _close(directory_fd)


def _cleanup_flat_directory(parent_fd: int, name: str) -> bool:
    directory_fd = -1
    try:
        directory_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        leaves = os.listdir(directory_fd)
        for leaf in leaves:
            node = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(node.st_mode):
                return False
        for leaf in leaves:
            os.unlink(leaf, dir_fd=directory_fd)
        os.fsync(directory_fd)
        _close(directory_fd)
        directory_fd = -1
        os.rmdir(name, dir_fd=parent_fd)
        return True
    except OSError:
        return False
    finally:
        if directory_fd >= 0:
            _close(directory_fd)


def _replace_at(parent_fd: int, source: str, destination: str) -> None:
    os.replace(source, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)


def _restore_backup(parent_fd: int, backup: str, destination: str) -> bool:
    try:
        _replace_at(parent_fd, backup, destination)
        return True
    except OSError:
        destination_node = _node_at(parent_fd, destination)
        backup_node = _node_at(parent_fd, backup)
        return (destination_node is not None and stat.S_ISDIR(destination_node.st_mode)
                and backup_node is None)


def _atomic_write(directory: object, root: object, artifacts: object) -> None:
    checked_artifacts = _validated_artifact_map(artifacts)
    boundary, root_fd = _open_root(root)
    parent_fd = -1
    stage_fd = -1
    stage_created = False
    promoted = False
    try:
        parts = _relative_parts(directory, boundary)
        if not parts:
            _reject("E_OUTPUT_ROOT", "output directory cannot equal its authority root")
        destination = parts[-1]
        stage = f".{destination}.stage"
        backup = f".{destination}.previous"
        parent_fd = _walk_directories(root_fd, parts[:-1], create=True,
                                      type_code="E_OUTPUT_TYPE")
        if _node_at(parent_fd, stage) is not None or _node_at(parent_fd, backup) is not None:
            _reject("E_ATOMIC_STATE", "preexisting stage or backup requires operator recovery")
        destination_node = _node_at(parent_fd, destination)
        if destination_node is not None and not stat.S_ISDIR(destination_node.st_mode):
            _reject("E_OUTPUT_TYPE", "existing output must be a real directory")
        try:
            os.mkdir(stage, mode=0o700, dir_fd=parent_fd)
            stage_created = True
            stage_fd = os.open(stage, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            for name in sorted(checked_artifacts):
                file_fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=stage_fd,
                )
                try:
                    _write_all(file_fd, checked_artifacts[name])
                    os.fsync(file_fd)
                finally:
                    _close(file_fd)
            os.fsync(stage_fd)
            _close(stage_fd)
            stage_fd = -1
        except OSError:
            _reject("E_ATOMIC_WRITE", "cannot prepare catalog stage")

        old_moved = False
        if destination_node is not None:
            try:
                _replace_at(parent_fd, destination, backup)
                old_moved = True
            except OSError:
                backup_node = _node_at(parent_fd, backup)
                destination_node = _node_at(parent_fd, destination)
                if (backup_node is not None and stat.S_ISDIR(backup_node.st_mode)
                        and destination_node is None):
                    old_moved = True
                if old_moved:
                    _restore_backup(parent_fd, backup, destination)
                _reject("E_ATOMIC_WRITE", "cannot move existing catalog to backup")
        try:
            _replace_at(parent_fd, stage, destination)
            stage_created = False
            promoted = True
        except OSError:
            stage_node = _node_at(parent_fd, stage)
            if stage_node is None and _flat_directory_matches(
                    parent_fd, destination, checked_artifacts):
                stage_created = False
                promoted = True
            else:
                if old_moved and not _restore_backup(parent_fd, backup, destination):
                    _reject("E_ATOMIC_WRITE", "catalog promotion and restoration failed")
                _reject("E_ATOMIC_WRITE", "catalog promotion failed")
        if promoted and old_moved:
            _cleanup_flat_directory(parent_fd, backup)
    finally:
        if stage_fd >= 0:
            _close(stage_fd)
        if stage_created and parent_fd >= 0:
            _cleanup_flat_directory(parent_fd, stage)
        if parent_fd >= 0:
            _close(parent_fd)
        _close(root_fd)


class _StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _reject("E_CLI_ARGUMENT", message)


def _parser() -> argparse.ArgumentParser:
    parser = _StableArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("generate", "verify"):
        item = sub.add_parser(command)
        item.add_argument("--descriptor", required=True)
        item.add_argument("--source-root", required=True)
        item.add_argument("--catalog-dir", required=True)
        item.add_argument("--catalog-root", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--package", required=True)
    inspect.add_argument("--package-root", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--left", required=True)
    compare.add_argument("--right", required=True)
    compare.add_argument("--package-root", required=True)
    return parser


def _emit(value: object) -> None:
    sys.stdout.buffer.write(_canonical(value) + b"\n")


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command in {"generate", "verify"}:
            descriptor, sources = _load_cli_inputs(args.descriptor, args.source_root)
            if args.command == "generate":
                artifacts = generate_catalog(descriptor, sources)
                _atomic_write(args.catalog_dir, args.catalog_root, artifacts)
                _emit(json.loads(artifacts["generation-manifest.json"]))
            else:
                artifacts = _read_artifacts(args.catalog_dir, args.catalog_root,
                                            _artifact_names(descriptor), descriptor["budgets"])
                _emit(verify_catalog(descriptor, sources, artifacts))
        elif args.command == "inspect":
            package, = _read_packages([args.package], args.package_root)
            _emit(inspect_package(package))
        else:
            left, right = _read_packages([args.left, args.right], args.package_root)
            _emit(compare_packages(left, right))
        return 0
    except CatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("E_IO: filesystem operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

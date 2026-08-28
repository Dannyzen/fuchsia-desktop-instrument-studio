#!/usr/bin/env python3
"""Independent strict verifier for the eight SQ-02 receipts.

This module intentionally does not import ``sq02_harness`` and treats every
receipt field as untrusted input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, NoReturn


RECEIPTS = (
    "source-toolchain-manifest.json", "cross-language-parity.json",
    "fuzz-corpus-manifest.json", "resource-bounds.json", "coverage.json",
    "reproducible-builds.json", "package-and-catalog-scan.json", "verdict.json",
)
INPUTS = RECEIPTS[:-1]
REQUIREMENTS = (
    "SQ02-BOUNDARY-262143", "SQ02-BOUNDARY-262144", "SQ02-BOUNDARY-262145",
    "SQ02-CORPUS-ALL", "SQ02-DIAGNOSTICS", "SQ02-FULL-FILE-HASH",
    "SQ02-PACKAGES-5", "SQ02-RETAINED-BYTES", "SQ02-SEMANTIC-HASH",
)
OPERATORS = (
    "asset-boundary", "byte-flip", "duplicate-key", "hash-tamper", "insertion",
    "invalid-utf8", "nesting-boundary", "nonfinite", "provenance-tamper",
    "schema-version", "semantic-failure", "string-boundary", "token-boundary",
    "truncation", "valid-inert-metadata", "whitespace-noncanonical",
)
HASH = re.compile(r"^[0-9a-f]{64}$")
PRIVATE = (
    re.compile(rb"/(?:home|Users|srv)/[^\s\"']+"),
    re.compile(rb"(?i)(?:api[_-]?key|authorization|bearer|client[_-]?secret)\s*[:=]"),
    re.compile(b"(?i)(?:\\." + b"beads|kan" + b"ban|her" + b"mes[_-]?(?:task|session|run)|orchestration[_-]?id)"),
)


class ReceiptError(ValueError):
    pass


def reject(message: str) -> NoReturn:
    raise ReceiptError(message)


def canonical(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError):
        reject("non-canonical JSON value")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes, label: str) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        reject(f"{label}: exactly one final LF required")
    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in rows:
            if key in result:
                reject(f"{label}: duplicate key")
            result[key] = value
        return result
    try:
        value = json.loads(raw[:-1].decode("ascii", "strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _value: reject(f"{label}: nonfinite number"))
    except ReceiptError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        reject(f"{label}: malformed JSON")
    if not isinstance(value, dict) or canonical(value) != raw:
        reject(f"{label}: non-canonical object")
    if any(pattern.search(raw) for pattern in PRIVATE):
        reject(f"{label}: private, orchestration, or credential marker")
    return value


def exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        reject(f"{label}: exact field set mismatch")
    return value


def integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        reject(f"{label}: invalid integer")
    return value


def text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        reject(f"{label}: invalid text")
    return value


def hash_text(value: Any, label: str) -> str:
    value = text(value, label)
    if not HASH.fullmatch(value):
        reject(f"{label}: invalid SHA-256")
    return value


def git(root: Path, *args: str) -> str:
    if tuple(args) not in (("rev-parse", "HEAD"), ("rev-parse", "HEAD^{tree}"), ("ls-files",)):
        reject("undeclared verifier git command")
    result = subprocess.run(["git", *args], cwd=root, shell=False, check=True,
                            capture_output=True, text=True)
    return result.stdout


def _manifest(root: Path, value: dict[str, Any], expected_sha: str, expected_tree: str) -> None:
    exact(value, {"authority", "base_sha", "command_schema", "environment", "fuchsia_pinned_revision",
                  "os_isolation", "python_dependencies", "python_version", "qualification_inputs", "source_sha", "source_tree",
                  "toolchain", "tracked_source_hashes"}, "manifest")
    if value["authority"] != "non-authoritative-harness" or value["source_sha"] != expected_sha or value["source_tree"] != expected_tree:
        reject("manifest: authority or source identity mismatch")
    if value["base_sha"] != "036944123fa15d5b5fac5718899b08a44691727c":
        reject("manifest: base SHA drift")
    if value["fuchsia_pinned_revision"] != "7f75b7f6ffdacf5a818dd8d207263edd45126ddd":
        reject("manifest: Fuchsia revision drift")
    text(value["command_schema"], "command schema")
    text(value["python_version"], "Python version")
    if value["python_dependencies"] != {"coverage": "7.6.12", "jsonschema": "4.25.1"}:
        reject("manifest: Python pins drift")
    environment = exact(value["environment"], {"CARGO_NET_OFFLINE", "LANG", "LC_ALL", "NATIVE_THEME_SQ02_NETWORK",
                                                 "PYTHONHASHSEED", "RUSTUP_NO_UPDATE_CHECK", "TZ"}, "environment")
    if environment != {"CARGO_NET_OFFLINE": "true", "LANG": "C", "LC_ALL": "C",
                       "NATIVE_THEME_SQ02_NETWORK": "deny", "PYTHONHASHSEED": "0",
                       "RUSTUP_NO_UPDATE_CHECK": "1", "TZ": "UTC"}:
        reject("manifest: fixed environment drift")
    isolation = exact(value["os_isolation"], {"child_raw_socket_blocked", "error_class", "namespace_changed",
                                               "namespace_mode", "parent_identity_compared"}, "os isolation")
    if isolation["namespace_changed"] is not True or isolation["child_raw_socket_blocked"] is not True or isolation["parent_identity_compared"] is not True:
        reject("manifest: OS isolation proof failed")
    if isolation["namespace_mode"] not in ("unprivileged-user-network", "ci-sudo-network") or isolation["error_class"] not in ("ENETUNREACH", "ENETDOWN", "EHOSTUNREACH"):
        reject("manifest: unstable or unknown isolation proof")
    toolchain = exact(value["toolchain"], {"cargo", "origin", "rust_channel", "rustc"}, "toolchain")
    if toolchain["rust_channel"] != "nightly-2026-08-13":
        reject("manifest: Rust channel drift")
    if toolchain["origin"] not in ("project-fuchsia-prebuilt", "hosted-official-nightly"):
        reject("manifest: unknown toolchain origin")
    for name in ("cargo", "rustc"):
        row = exact(toolchain[name], {"binary_sha256", "name", "version"}, name)
        if row["name"] != name:
            reject(f"manifest: {name} identity drift")
        hash_text(row["binary_sha256"], f"{name} binary hash")
        text(row["version"], f"{name} version")
    if "1.99.0-nightly" not in toolchain["rustc"]["version"] or "1.99.0-nightly" not in toolchain["cargo"]["version"]:
        reject("manifest: unknown Cargo/Rust compiler version")
    tracked = value["tracked_source_hashes"]
    expected_files = git(root, "ls-files").splitlines()
    if not isinstance(tracked, dict) or sorted(tracked) != expected_files:
        reject("manifest: tracked file inventory mismatch")
    for relative in expected_files:
        if hash_text(tracked[relative], f"tracked hash {relative}") != digest((root / relative).read_bytes()):
            reject("manifest: tracked source hash mismatch")
    inputs = exact(value["qualification_inputs"], {"catalog", "corpus_bytes_sha256", "corpus_manifest_sha256",
                                                    "packages", "rust_record_sha256"}, "qualification inputs")
    hash_text(inputs["corpus_bytes_sha256"], "corpus bytes input")
    hash_text(inputs["corpus_manifest_sha256"], "corpus manifest input")
    hash_text(inputs["rust_record_sha256"], "Rust record input")
    if not isinstance(inputs["catalog"], dict) or not isinstance(inputs["packages"], list) or len(inputs["packages"]) != 5:
        reject("manifest: qualification input inventory mismatch")
    for name, row in inputs["catalog"].items():
        if not isinstance(name, str) or Path(name).name != name:
            reject("manifest: unsafe catalog input name")
        exact(row, {"bytes", "sha256"}, "catalog input")
        integer(row["bytes"], "catalog input bytes", minimum=1)
        hash_text(row["sha256"], "catalog input hash")


def _parity(value: dict[str, Any]) -> None:
    exact(value, {"diagnostic_mapping", "package_count", "packages", "python_rust_corpus_accepted", "python_rust_corpus_executed",
                  "python_rust_corpus_rejected", "requirement_ids", "rust_record_sha256", "schema_version", "status"}, "parity")
    if value["schema_version"] != "sq02-cross-language-parity-v1" or value["status"] != "PASS":
        reject("parity: status/schema mismatch")
    if integer(value["package_count"], "package count") != 5 or not isinstance(value["packages"], list) or len(value["packages"]) != 5:
        reject("parity: exact five packages required")
    ids: set[str] = set()
    for row in value["packages"]:
        exact(row, {"bytes", "file", "id", "semantic_sha256", "sha256"}, "package")
        ids.add(text(row["id"], "package id")); integer(row["bytes"], "package bytes", minimum=1)
        hash_text(row["sha256"], "package hash"); hash_text(row["semantic_sha256"], "semantic hash")
        if Path(row["file"]).name != row["file"]:
            reject("parity: unsafe package filename")
    if len(ids) != 5:
        reject("parity: duplicate package IDs")
    mapping = value["diagnostic_mapping"]
    if not isinstance(mapping, list) or [row.get("mutation_operator") for row in mapping] != list(OPERATORS):
        reject("parity: diagnostic operator mapping drift")
    for row in mapping:
        exact(row, {"mutation_operator", "python_accepted", "python_codes", "rust_accepted", "rust_codes"}, "diagnostic mapping")
        if row["python_accepted"] != row["rust_accepted"] or len(row["python_accepted"]) != 1:
            reject("parity: accepted/rejected mapping mismatch")
        if not isinstance(row["python_codes"], list) or not isinstance(row["rust_codes"], list) or len(row["python_codes"]) != 1 or len(row["rust_codes"]) != 1:
            reject("parity: code mapping is not stable")
        pair = (row["python_codes"][0], row["rust_codes"][0])
        permitted = {(None, None), ("E_PROVENANCE", "E_HASH"), ("E_PROVENANCE", "E_IDENTITY")}
        if pair[0] != pair[1] and pair not in permitted:
            reject("parity: undeclared cross-language diagnostic mapping")
    executed = integer(value["python_rust_corpus_executed"], "parity executed")
    accepted = integer(value["python_rust_corpus_accepted"], "parity accepted")
    rejected = integer(value["python_rust_corpus_rejected"], "parity rejected")
    if executed != 256 or accepted + rejected != executed:
        reject("parity: corpus totals mismatch")
    if value["requirement_ids"] != list(REQUIREMENTS) or len(set(value["requirement_ids"])) != len(REQUIREMENTS):
        reject("parity: Rust requirement inventory mismatch")
    hash_text(value["rust_record_sha256"], "Rust record hash")


def _fuzz(value: dict[str, Any], parity: dict[str, Any]) -> None:
    exact(value, {"duplicate_hashes", "duplicate_ids", "executed", "generator_source_sha256", "generator_version",
                  "manifest_sha256", "operator_counts", "python_rust_parity", "seed", "skipped", "total_generated"}, "fuzz")
    for field in ("duplicate_hashes", "duplicate_ids", "skipped"):
        if integer(value[field], field) != 0:
            reject("fuzz: duplicate or skipped cases")
    if value["seed"] != 0 or value["generator_version"] != "sq02-corpus-v1":
        reject("fuzz: generator identity drift")
    for field in ("executed", "python_rust_parity", "total_generated"):
        if integer(value[field], field) != 256:
            reject("fuzz: execution total mismatch")
    if value["executed"] != parity["python_rust_corpus_executed"]:
        reject("fuzz: cross-receipt execution mismatch")
    counts = value["operator_counts"]
    if not isinstance(counts, dict) or set(counts) != set(OPERATORS) or any(counts[name] != 16 for name in OPERATORS):
        reject("fuzz: operator distribution mismatch")
    hash_text(value["generator_source_sha256"], "generator hash"); hash_text(value["manifest_sha256"], "corpus manifest hash")


def _bounds(value: dict[str, Any]) -> None:
    exact(value, {"dominated_relations", "limits", "observations", "rows", "runtime_accounting", "rust_rows", "schema_version", "status"}, "bounds")
    if value["schema_version"] != "sq02-resource-bounds-v1" or value["status"] != "PASS":
        reject("bounds: status/schema mismatch")
    limits = value["limits"]
    expected = {"assets": 64, "catalog_bytes": 8388608, "compiled_pack_bytes": 262144, "receipt_bytes": 16384,
                "runtime_snapshot_bytes": 524288, "source_bytes": 1048576, "string_bytes": 4096, "tokens": 1024}
    if limits != expected or limits["compiled_pack_bytes"] > limits["runtime_snapshot_bytes"]:
        reject("bounds: limit contract drift")
    if value["runtime_accounting"] != "same-retained-canonical-bytes-no-second-snapshot":
        reject("bounds: invented runtime accounting")
    if value["dominated_relations"] != [{"dominated": "runtime_snapshot_bytes",
                                          "proof": "compiled_pack_bytes <= runtime_snapshot_bytes",
                                          "stricter": "compiled_pack_bytes"}]:
        reject("bounds: dominated relation drift")
    observed = exact(value["observations"], {"catalog_bytes", "executed_asset_plus_one_cases",
                                              "executed_string_plus_one_or_more_cases", "executed_token_plus_one_cases",
                                              "largest_catalog_receipt_bytes", "largest_package_bytes", "largest_source_bytes"}, "bound observations")
    for field in observed:
        integer(observed[field], f"observed {field}", minimum=1)
    if observed["catalog_bytes"] > limits["catalog_bytes"] or observed["largest_catalog_receipt_bytes"] > limits["receipt_bytes"] or observed["largest_package_bytes"] > limits["compiled_pack_bytes"] or observed["largest_source_bytes"] > limits["source_bytes"]:
        reject("bounds: observed size escapes declared limit")
    if any(observed[field] != 16 for field in ("executed_asset_plus_one_cases", "executed_string_plus_one_or_more_cases", "executed_token_plus_one_cases")):
        reject("bounds: executed boundary corpus count mismatch")
    rows = value["rows"]
    rust_rows = value["rust_rows"]
    if not isinstance(rows, list) or not isinstance(rust_rows, list) or [row.get("bytes") for row in rows] != [262143, 262144, 262145] or [row.get("bytes") for row in rust_rows] != [262143, 262144, 262145]:
        reject("bounds: exact rows missing")
    for index, row in enumerate(rows):
        exact(row, {"bytes", "compiler", "contract"}, "Python boundary row")
        for label in ("compiler", "contract"):
            result = row[label]
            expected_fields = {"accepted", "code", "layer", "package_sha256", "semantic_sha256"} if index < 2 else {"accepted", "code", "layer"}
            exact(result, expected_fields, f"Python boundary {label}")
            if index < 2:
                hash_text(result["package_sha256"], "boundary package hash")
                hash_text(result["semantic_sha256"], "boundary semantic hash")
    for row in rust_rows:
        exact(row, {"accepted", "bytes", "code"}, "Rust boundary row")
    if rows[0]["contract"]["accepted"] is not True or rows[1]["contract"]["accepted"] is not True:
        reject("bounds: accepted edge mismatch")
    if rows[2]["compiler"] != {"accepted": False, "code": "E_CANONICAL_SIZE", "layer": "compiler"} or rows[2]["contract"]["code"] != "E_LIMIT_PACK":
        reject("bounds: Python +1 diagnostic mismatch")
    if rust_rows[0]["accepted"] is not True or rust_rows[1]["accepted"] is not True or rust_rows[2] != {"accepted": False, "bytes": 262145, "code": "E_LIMIT_PACK"}:
        reject("bounds: Rust boundary mismatch")


def _coverage(value: dict[str, Any]) -> None:
    exact(value, {"claim_scope", "machine_artifact_sha256", "production_modules", "python_safety_modules", "rust_claim",
                  "rust_requirement_ids", "schema_version", "status"}, "coverage")
    if value["schema_version"] != "sq02-coverage-v1" or value["status"] != "PASS" or value["rust_requirement_ids"] != list(REQUIREMENTS):
        reject("coverage: schema/status/requirements mismatch")
    hash_text(value["machine_artifact_sha256"], "coverage machine artifact hash")
    if value["claim_scope"] != "Python safety-bearing statement/branch/function execution; Rust requirement completeness only":
        reject("coverage: Python claim scope drift")
    if value["production_modules"] != {"gate": "established-source-bound", "reported_separately": True}:
        reject("coverage: production source-bound reporting drift")
    modules = value["python_safety_modules"]
    expected_modules = {"tools/native_theme/sq02_harness.py", "tools/native_theme/sq02_receipt_verifier.py"}
    if not isinstance(modules, dict) or set(modules) != expected_modules:
        reject("coverage: safety module inventory mismatch")
    fields = {"branches_covered", "branches_total", "functions_with_body_execution", "functions_total",
              "statements_covered", "statements_total"}
    for name, row in modules.items():
        exact(row, fields, f"coverage {name}")
        for field in fields:
            integer(row[field], f"coverage {name} {field}")
        if row["statements_total"] <= 0 or row["functions_total"] <= 0:
            reject("coverage: empty measurement")
        if row["statements_covered"] != row["statements_total"] or row["branches_covered"] != row["branches_total"] or row["functions_with_body_execution"] != row["functions_total"]:
            reject("coverage: safety-bearing gap")
    if value["rust_claim"] != "executed-requirement-ID-completeness-not-source-or-function-coverage":
        reject("coverage: Rust claim overreach")


def _reproducible(value: dict[str, Any]) -> None:
    exact(value, {"archive_materializations", "cargo_binary_equality_required", "comparisons", "schema_version", "status"}, "reproducible")
    if value["archive_materializations"] != 2 or value["cargo_binary_equality_required"] is not False or value["schema_version"] != "sq02-reproducible-builds-v1" or value["status"] != "PASS":
        reject("reproducible: contract mismatch")
    comparisons = exact(value["comparisons"], {"catalog_equal", "corpus_bytes_equal", "corpus_manifest_equal",
                                                 "package_bytes_equal", "rust_payload_equal"}, "comparisons")
    if any(item is not True for item in comparisons.values()):
        reject("reproducible: payload mismatch")


def _scan(value: dict[str, Any]) -> None:
    exact(value, {"audited_authority_files", "bounded_lexical_scan", "catalog_copy_only", "catalog_entry_count", "changed_files_scanned", "findings",
                  "fuchsia_forbidden_edges", "qualification_testonly", "receipts_scanned", "schema_version", "status", "tracked_files_considered"}, "scan")
    if value["bounded_lexical_scan"] is not True or value["catalog_copy_only"] is not True or value["qualification_testonly"] is not True or value["findings"] != [] or value["fuchsia_forbidden_edges"] != [] or value["status"] != "PASS":
        reject("scan: authority finding or status mismatch")
    if integer(value["catalog_entry_count"], "catalog entries") != 4 or value["receipts_scanned"] != 8 or not isinstance(value["audited_authority_files"], list) or integer(value["changed_files_scanned"], "changed scan", minimum=1) < 1 or integer(value["tracked_files_considered"], "tracked scan", minimum=1) < 1:
        reject("scan: counts mismatch")
    if len(value["audited_authority_files"]) != len(set(value["audited_authority_files"])) or any(
        not isinstance(name, str) or name.startswith("/") or ".." in Path(name).parts for name in value["audited_authority_files"]):
        reject("scan: audited authority file inventory invalid")


def _verdict(value: dict[str, Any], raw: dict[str, bytes], sha: str, tree: str) -> None:
    exact(value, {"authority", "cheapest_next_proof", "claims_excluded", "failure_classification", "receipt_hashes",
                  "required_skips", "residual_risks", "root_cause_status", "source_sha", "source_tree", "status"}, "verdict")
    if value["authority"] != "non-authoritative-harness" or value["status"] != "PASS" or value["source_sha"] != sha or value["source_tree"] != tree:
        reject("verdict: authority/status/source mismatch")
    if value["failure_classification"] is not None or value["root_cause_status"] != "none" or value["required_skips"] != 0:
        reject("verdict: PASS contains failure or skip")
    excluded = {"deploy", "independent approval", "merge", "Product Assembly/runtime inclusion", "release"}
    if set(value["claims_excluded"]) != excluded:
        reject("verdict: excluded authority drift")
    if len(value["claims_excluded"]) != len(excluded) or not isinstance(value["residual_risks"], list) or not value["residual_risks"] or any(not isinstance(item, str) or not item for item in value["residual_risks"]):
        reject("verdict: excluded claims or residual risks malformed")
    text(value["cheapest_next_proof"], "cheapest next proof")
    hashes = value["receipt_hashes"]
    if not isinstance(hashes, dict) or set(hashes) != set(INPUTS) or "verdict.json" in hashes:
        reject("verdict: receipt hash map is circular or incomplete")
    for name in INPUTS:
        if hash_text(hashes[name], f"verdict hash {name}") != digest(raw[name]):
            reject("verdict: cross-receipt hash mismatch")


def verify_directory(root: Path, directory: Path, *, expected_sha: str | None = None,
                     expected_tree: str | None = None) -> dict[str, dict[str, Any]]:
    names = sorted(path.name for path in directory.iterdir() if path.is_file())
    if names != sorted(RECEIPTS):
        reject("receipt directory must contain exactly eight named files")
    raw = {name: (directory / name).read_bytes() for name in RECEIPTS}
    parsed = {name: parse(raw[name], name) for name in RECEIPTS}
    sha = expected_sha or git(root, "rev-parse", "HEAD").strip()
    tree = expected_tree or git(root, "rev-parse", "HEAD^{tree}").strip()
    _manifest(root, parsed[RECEIPTS[0]], sha, tree)
    _parity(parsed[RECEIPTS[1]])
    inputs = parsed[RECEIPTS[0]]["qualification_inputs"]
    if inputs["packages"] != parsed[RECEIPTS[1]]["packages"] or inputs["rust_record_sha256"] != parsed[RECEIPTS[1]]["rust_record_sha256"]:
        reject("cross-receipt package or Rust input mismatch")
    _fuzz(parsed[RECEIPTS[2]], parsed[RECEIPTS[1]])
    if inputs["corpus_manifest_sha256"] != parsed[RECEIPTS[2]]["manifest_sha256"]:
        reject("cross-receipt corpus manifest mismatch")
    _bounds(parsed[RECEIPTS[3]])
    _coverage(parsed[RECEIPTS[4]])
    _reproducible(parsed[RECEIPTS[5]])
    _scan(parsed[RECEIPTS[6]])
    _verdict(parsed[RECEIPTS[7]], raw, sha, tree)
    return parsed

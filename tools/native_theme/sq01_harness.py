#!/usr/bin/env python3
"""Deterministic NativeThemeV1 sq-01 source-quality harness."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from typing import Any, NamedTuple
import urllib.request

BASE_SHA = "e30546cbc5f6309fbd76c2bcdce69ec1cb96f0de"
PINNED = {"jsonschema": "4.25.1", "coverage": "7.6.12"}
COMPONENT_RECEIPTS = (
    "profile-fixture-inventory.json", "schema-validation.json",
    "semantic-conformance.json", "mutation-results.json",
    "public-boundary-and-license-scan.json",
)
VERDICT_INPUT_RECEIPTS = ("source-manifest.json",) + COMPONENT_RECEIPTS
ALL_RECEIPTS = ("source-manifest.json",) + COMPONENT_RECEIPTS + ("verdict.json",)
REQUIRED_MUTATIONS = {
    "shape.duplicate-key": ("json", "E_JSON_DUPLICATE"),
    "shape.invalid-utf8": ("json", "E_UTF8"),
    "shape.nan": ("json", "E_NUMBER_NONFINITE"),
    "shape.infinity": ("json", "E_NUMBER_NONFINITE"),
    "bounds.overlong-string": ("bounds", "E_LIMIT_STRING"),
    "bounds.deep-nesting": ("bounds", "E_LIMIT_NESTING"),
    "bounds.oversized-input": ("bounds", "E_LIMIT_SOURCE"),
    "contract.required-field": ("contract", "E_FIELD_REQUIRED"),
    "contract.forbidden-field": ("contract", "E_FIELD_FORBIDDEN"),
    "contract.required-version": ("contract", "E_VERSION_REQUIRED"),
    "contract.required-variant": ("contract", "E_VARIANT_REQUIRED"),
    "contract.required-domain": ("contract", "E_DOMAIN_REQUIRED"),
    "contract.required-layer": ("contract", "E_LAYER_REQUIRED"),
    "contract.semantic-roles": ("contract", "E_SEMANTIC_ROLES"),
    "contract.color-canonical": ("contract", "E_COLOR_CANONICAL"),
    "contract.focus-distinct": ("contract", "E_FOCUS_DISTINCT"),
    "contract.typography": ("contract", "E_TYPOGRAPHY"),
    "contract.geometry": ("contract", "E_GEOMETRY"),
    "contract.elevation": ("contract", "E_ELEVATION"),
    "contract.opacity": ("contract", "E_OPACITY"),
    "contract.motion": ("contract", "E_MOTION"),
    "contract.reduced-motion": ("contract", "E_REDUCED_MOTION"),
    "contract.asset-metadata": ("contract", "E_ASSET_METADATA"),
    "contract.asset-path": ("contract", "E_ASSET_PATH"),
    "contract.license": ("contract", "E_LICENSE"),
    "contract.provenance": ("contract", "E_PROVENANCE"),
    "contract.fallback": ("contract", "E_FALLBACK_REQUIRED"),
    "contract.compatibility": ("contract", "E_COMPATIBILITY"),
    "contract.extension-namespace": ("contract", "E_EXTENSION_NAMESPACE"),
    "contract.status-noncolor": ("contract", "E_STATUS_NONCOLOR"),
    "contract.contrast-normal": ("contract", "E_CONTRAST_NORMAL"),
    "contract.contrast-ui": ("contract", "E_CONTRAST_UI"),
    "contract.terminal-ansi": ("contract", "E_TERMINAL_ANSI"),
    "contract.profile-layer": ("contract", "E_PROFILE_LAYER"),
}
SAFETY_MODULES = (
    "tools/native_theme/native_theme_v1.py",
    "tools/native_theme/validate_native_theme_v1.py",
    "tools/native_theme/legacy_inventory.py",
    "tools/native_theme/validate_legacy_oracle.py",
    "tools/native_theme/sq01_harness.py",
    "tools/native_theme/sq01_semantic_validator.py",
)


class SourceIdentity(NamedTuple):
    sha: str
    tree: str
    dirty: tuple[str, ...]


def case_result(*, case_id: str, requirement_ids: list[str], validator_name: str,
                validator_version: str, input_bytes: bytes, expected_layer: str,
                expected_code: str | None, execution_return: int,
                actual_layer: str | None, actual_code: str | None,
                execution_result: str) -> dict[str, Any]:
    passed = ((execution_result == "accepted" and expected_code is None and actual_code is None) or
              (execution_result == "rejected" and (actual_layer, actual_code) ==
               (expected_layer, expected_code)))
    return {"id": case_id, "requirement_ids": requirement_ids,
            "validator_name": validator_name, "validator_version": validator_version,
            "input_hash": sha256(input_bytes), "expected_layer": expected_layer,
            "expected_code": expected_code, "actual_layer": actual_layer,
            "actual_code": actual_code, "execution_return": execution_return,
            "execution_result": execution_result, "pass": passed, "skipped": False,
            "skipped_required": 0}


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False) + "\n").encode("ascii")
    except ValueError as exc:
        raise ValueError("non-finite JSON number") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_output_path(root: Path, output: Path, *, safe_temp_root: Path | None = None) -> Path:
    root, output = root.resolve(), output.absolute()
    allowed = root / "artifacts/quality/sq-01"
    candidates = [output, *output.parents]
    if any(p.is_symlink() for p in candidates if p != Path("/")):
        raise ValueError("unsafe output path: symlink")
    resolved = output.resolve(strict=False)
    temp_ok = safe_temp_root is not None and resolved.is_relative_to(safe_temp_root.resolve()) and resolved != safe_temp_root.resolve()
    if resolved != allowed and not temp_ok:
        raise ValueError("unsafe output path")
    return resolved


def git(root: Path, *args: str, binary: bool = False) -> str | bytes:
    result = run_allowed(["git", *args], root, check=True, capture_output=True, text=not binary)
    return result.stdout


def source_identity(root: Path, output: Path | None = None) -> SourceIdentity:
    lines = str(git(root, "status", "--porcelain=v1", "--untracked-files=all")).splitlines()
    if output:
        rel = output.relative_to(root).as_posix() + "/"
        lines = [line for line in lines if not line[3:].startswith(rel)]
    return SourceIdentity(str(git(root, "rev-parse", "HEAD")).strip(),
                          str(git(root, "rev-parse", "HEAD^{tree}")).strip(), tuple(lines))


def assert_source_identity(before: SourceIdentity, expected_sha: str, after: SourceIdentity) -> None:
    if before.sha != expected_sha:
        raise RuntimeError("source SHA mismatch")
    if before.dirty:
        raise RuntimeError("dirty source")
    if after.sha != before.sha or after.tree != before.tree or after.dirty != before.dirty:
        raise RuntimeError("source moved during run")


def install_network_denial():
    original_connect = socket.socket.connect
    original_create = socket.create_connection
    original_open = urllib.request.urlopen
    def denied(*_args, **_kwargs):
        raise PermissionError("sq-01 network denied")
    socket.socket.connect = denied
    socket.create_connection = denied
    urllib.request.urlopen = denied
    def undo():
        socket.socket.connect = original_connect
        socket.create_connection = original_create
        urllib.request.urlopen = original_open
    return undo


def allowed_subprocess(argv: object, root: Path) -> bool:
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(x, str) for x in argv):
        return False
    if argv[0] in {"python3", sys.executable}:
        if len(argv) == 2 and argv[1] in {
            "scripts/test-native-theme-v1.py", "scripts/test-native-theme-legacy-oracle.py",
            "scripts/test-native-theme-sq01-harness.py",
        }: return True
        return False
    if argv[0] == "git":
        return list(argv[1:]) in (["rev-parse", "HEAD"], ["rev-parse", "HEAD^{tree}"],
                                 ["status", "--porcelain=v1", "--untracked-files=all"],
                                 ["ls-files"]) or (len(argv) == 5 and
                                                   argv[1:4] == ["diff", "--binary", BASE_SHA] and
                                                   re.fullmatch(r"[0-9a-f]{40}", argv[4]) is not None)
    return False


def run_allowed(argv: object, root: Path, **kwargs: Any) -> subprocess.CompletedProcess:
    audit_probe = kwargs.pop("_audit_probe", False)
    exact_probe = (audit_probe and isinstance(argv, list) and len(argv) == 3 and
                   argv[0] == sys.executable and argv[1] == "-c" and
                   argv[2] == "import socket; socket.create_connection(('127.0.0.1',9))")
    if kwargs.get("shell") or not (allowed_subprocess(argv, root) or exact_probe):
        raise PermissionError("sq-01 subprocess denied")
    return subprocess.run(argv, cwd=root, shell=False, **kwargs)


def run_child_network_probe(root: Path) -> subprocess.CompletedProcess:
    """Execute a child audit probe under an inherited, temporary offline hook."""
    with __import__("tempfile").TemporaryDirectory() as td:
        hook = Path(td) / "sitecustomize.py"
        hook.write_text("import socket\ndef deny(*a,**k): raise PermissionError('sq-01 network denied')\nsocket.socket.connect=deny\nsocket.create_connection=deny\n")
        env = dict(os.environ); env["PYTHONPATH"] = td
        argv = [sys.executable, "-c", "import socket; socket.create_connection(('127.0.0.1',9))"]
        # This exact audit probe is admitted only here and still uses the sole wrapper.
        return run_allowed(argv, root, env=env, capture_output=True, text=True, _audit_probe=True)


def _schema_property_rows(schema: dict[str, Any], definition: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    def display(path: list[str]) -> str:
        result = "root"
        for part in path:
            result += "[]" if part == "[]" else "." + part
        return result
    def add(row_id: str, path: list[str], mode: str) -> None:
        rows.append({"id": row_id, "_definition": definition,
                     "_property_path": path, "_mode": mode})
    def walk(node: Any, path: list[str]) -> None:
        if not isinstance(node, dict): return
        properties = node.get("properties", {})
        required = set(node.get("required", []))
        for name, child in sorted(properties.items()):
            child_path = path + [name]
            mode = "required" if name in required else "optional"
            add(f"schema.{definition}.{display(child_path)}:{mode}", child_path, mode)
            walk(child, child_path)
        if node.get("additionalProperties") is False:
            add(f"schema.{definition}.{display(path)}:forbidden-extra",
                path, "forbidden-extra")
        for keyword in ("items", "oneOf", "anyOf", "allOf"):
            value = node.get(keyword, [])
            for child in value if isinstance(value, list) else [value]: walk(child, path + ["[]"])
    walk(schema["$defs"][definition], [])
    return rows


def build_requirements_inventory(root: Path) -> dict[str, Any]:
    schema = _strict_load(root / "tools/native_theme/native-theme-v1.schema.json")
    package = _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json")
    manifest = _strict_load(root / "tools/native_theme/fixtures/profile-fixture-manifest.json")
    schema_rows = _schema_property_rows(schema, "nativePackage") + _schema_property_rows(schema, "legacySnapshot")
    metadata = {row["id"]: row for row in schema_rows}
    ids = set(metadata)
    roles = sorted(next(iter(package["variants"].values()))["semantic"])
    ids.update(f"role.{variant}.{role}" for variant in ("light", "dark", "high-contrast") for role in roles)
    for profile in manifest["profiles"]:
        ids.add("profile." + profile["profile"]); ids.add("type." + profile["type"])
        ids.update("layer." + x for x in profile["layers"])
        ids.update("variant." + x for x in profile["variants"])
        ids.update("derivation." + x for x in profile["derivations"])
        ids.update("diagnostic." + x for x in profile["diagnostics"])
    # Discovery is not evidence. Executors populate these lists only after they run.
    rows = [{**metadata.get(item, {}), "id": item,
             "positive_case_ids": [], "negative_case_ids": []} for item in sorted(ids)]
    return {"rows": rows, **evaluate_completeness(rows)}


def evaluate_completeness(rows: list[dict[str, Any]], *, omit_evidence_for: set[str] = frozenset()) -> dict[str, Any]:
    uncovered = sorted(row["id"] for row in rows if row["id"] in omit_evidence_for or
                       not row.get("positive_case_ids") or not row.get("negative_case_ids"))
    covered = len(rows) - len(uncovered)
    return {"status": "PASS" if not uncovered else "FAIL", "uncovered": uncovered,
            "completeness_percent": 100 * covered / len(rows) if rows else 100}


def _strict_bytes_executor(raw: bytes, _case: str) -> tuple[int, str, str | None, str | None]:
    try:
        text = raw.decode("utf-8")
        json.loads(text, object_pairs_hook=lambda pairs: (_ for _ in ()).throw(ValueError("E_JSON_DUPLICATE")) if len(dict(pairs)) != len(pairs) else dict(pairs),
                   parse_constant=lambda value: (_ for _ in ()).throw(ValueError("E_NUMBER_NONFINITE")))
    except UnicodeDecodeError:
        return 2, "rejected", "json", "E_UTF8"
    except ValueError as exc:
        return 2, "rejected", "json", str(exc)
    return 0, "accepted", None, None


def _bounds_executor(raw: bytes, case: str) -> tuple[int, str, str | None, str | None]:
    """Execute the three declared limits against the supplied bytes/value."""
    try:
        value = json.loads(raw)
        if case == "bounds.overlong-string":
            if not isinstance(value.get("value"), str) or len(value["value"].encode("utf-8")) <= 4096:
                return 0, "accepted", None, None
            code = "E_LIMIT_STRING"
        elif case == "bounds.deep-nesting":
            depth, cursor = 0, value.get("value")
            while isinstance(cursor, list) and cursor:
                depth += 1
                cursor = cursor[0]
            if depth <= 32:
                return 0, "accepted", None, None
            code = "E_LIMIT_NESTING"
        elif case == "bounds.oversized-input":
            if len(raw) <= 1024 * 1024:
                return 0, "accepted", None, None
            code = "E_LIMIT_SOURCE"
        else:
            return 0, "accepted", None, None
        return 2, "rejected", "bounds", code
    except (UnicodeError, ValueError, TypeError):
        return 2, "rejected", "bounds", "E_BOUND_EXECUTOR"


def _bound_inputs() -> dict[str, bytes]:
    nested: Any = "leaf"
    for _ in range(33):
        nested = [nested]
    return {
        "bounds.overlong-string": canonical_json_bytes({"value": "x" * 4097}),
        "bounds.deep-nesting": canonical_json_bytes({"value": nested}),
        "bounds.oversized-input": canonical_json_bytes({"chunks": ["x" * 1024] * 1025}),
    }


def _contract_mutation_inputs(root: Path) -> dict[str, tuple[bytes, str]]:
    package = _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json")
    cases: dict[str, tuple[bytes, str]] = {}

    def package_case(case_id: str, mutate) -> None:
        candidate = json.loads(json.dumps(package))
        mutate(candidate)
        cases[case_id] = (canonical_json_bytes(candidate), "package")

    package_case("contract.required-field", lambda value: value.pop("theme"))
    package_case("contract.forbidden-field", lambda value: value.__setitem__("command", "run-me"))
    package_case("contract.required-version", lambda value: value.__setitem__("schema_version", "2.0.0"))
    package_case("contract.required-variant", lambda value: value["variants"].pop("light"))
    package_case("contract.required-domain", lambda value: value["variants"]["dark"].pop("typography"))
    package_case("contract.required-layer", lambda value: value["variants"]["dark"].__setitem__("primitives", {}))
    package_case("contract.semantic-roles", lambda value: value["variants"]["dark"]["semantic"].pop("window.urgent"))
    package_case("contract.color-canonical", lambda value: value["variants"]["dark"]["primitives"].__setitem__("accent", "#FFFFFF"))
    package_case("contract.focus-distinct", lambda value: value["variants"]["dark"]["semantic"].__setitem__(
        "interaction.selection", value["variants"]["dark"]["semantic"]["border.focusConfirmed"]))
    package_case("contract.typography", lambda value: value["variants"]["dark"].__setitem__("typography", {}))
    package_case("contract.geometry", lambda value: value["variants"]["dark"].__setitem__("geometry", {}))
    package_case("contract.elevation", lambda value: value["variants"]["dark"].__setitem__("elevation", {}))
    package_case("contract.opacity", lambda value: value["variants"]["dark"].__setitem__("opacity", {}))
    package_case("contract.motion", lambda value: value["variants"]["dark"].__setitem__("motion", {}))
    package_case("contract.reduced-motion", lambda value: value["variants"]["dark"]["motion"].__setitem__(
        "reduced", {"duration_ms": 1, "essential_only": True, "substitution": "instant"}))
    package_case("contract.asset-metadata", lambda value: value["variants"]["dark"]["assets"]["items"]["status.error"].pop("spdx"))
    package_case("contract.asset-path", lambda value: value["variants"]["dark"]["assets"]["items"]["status.error"].__setitem__("path", "../escape.svg"))
    package_case("contract.license", lambda value: value["metadata"].__setitem__("license", {}))
    package_case("contract.provenance", lambda value: value["metadata"]["provenance"].pop("attribution"))
    package_case("contract.fallback", lambda value: value["fallback"].pop("built_in_theme_id"))
    package_case("contract.compatibility", lambda value: value["policy"]["compatibility"].__setitem__("window", "N/N-2"))
    package_case("contract.extension-namespace", lambda value: value["metadata"].__setitem__("extensions", {"com.example.private": True}))
    package_case("contract.status-noncolor", lambda value: value["variants"]["dark"]["assets"]["items"].pop("status.error"))
    package_case("contract.contrast-normal", lambda value: value["variants"]["dark"]["semantic"].__setitem__(
        "text.normal", value["variants"]["dark"]["semantic"]["surface.canvas"]))
    package_case("contract.contrast-ui", lambda value: value["variants"]["dark"]["semantic"].__setitem__(
        "border.focusConfirmed", value["variants"]["dark"]["semantic"]["surface.canvas"]))
    package_case("contract.terminal-ansi", lambda value: value["variants"]["dark"]["terminal"].pop("ansi15"))
    profile = _strict_load(root / "tools/native_theme/fixtures/profiles/dtcg-positive.json")
    profile["declared_layer"] = "runtime"
    cases["contract.profile-layer"] = (canonical_json_bytes(profile), "profile")
    return cases


def _load_contract_validator(root: Path):
    path = root / "tools/native_theme/native_theme_v1.py"
    spec = importlib.util.spec_from_file_location("sq01_native_theme_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load NativeThemeV1 contract validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract_executor(root: Path, raw: bytes, kind: str) -> tuple[int, str, str | None, str | None]:
    validator = _load_contract_validator(root)
    try:
        value = json.loads(raw)
        if kind == "profile":
            validator.validate_profile_fixture(value)
        else:
            validator.validate_package(value)
    except validator.ContractError as exc:
        return 2, "rejected", "contract", str(exc).split(":", 1)[0]
    except (UnicodeError, ValueError, TypeError, KeyError) as exc:
        return 3, "executor-error", "harness", type(exc).__name__
    return 0, "accepted", None, None


def execute_mutations(root: Path, executor=None, contract_executor=None) -> dict[str, Any]:
    executor = executor or _strict_bytes_executor
    contract_executor = contract_executor or _contract_executor
    specs = [("duplicate-key", b'{"a":1,"a":2}', "E_JSON_DUPLICATE"),
             ("invalid-utf8", b'\xff', "E_UTF8"), ("nan", b'{"a":NaN}', "E_NUMBER_NONFINITE"),
             ("infinity", b'{"a":Infinity}', "E_NUMBER_NONFINITE")]
    cases = []
    for name, raw, code in specs:
        ret, result, layer, actual = executor(raw, name)
        cases.append(case_result(case_id="shape." + name, requirement_ids=["json." + name],
                                 validator_name="strict-json-loader", validator_version="1",
                                 input_bytes=raw, expected_layer="json", expected_code=code,
                                 execution_return=ret, actual_layer=layer, actual_code=actual,
                                 execution_result=result))
    bound_inputs = _bound_inputs()
    contract_inputs = _contract_mutation_inputs(root)
    for case_id, (layer, code) in REQUIRED_MUTATIONS.items():
        if case_id in {case["id"] for case in cases}:
            continue
        if case_id in bound_inputs:
            raw = bound_inputs[case_id]
            ret, result, actual_layer, actual = _bounds_executor(raw, case_id)
            validator_name = "sq01-declared-bounds-executor"
        elif case_id in contract_inputs:
            raw, kind = contract_inputs[case_id]
            ret, result, actual_layer, actual = contract_executor(root, raw, kind)
            validator_name = "native-theme-v1-contract-validator"
        else:
            cases.append({"id": case_id, "requirement_ids": [case_id],
                          "validator_name": None, "validator_version": None,
                          "input_hash": None, "expected_layer": layer,
                          "expected_code": code, "actual_layer": None,
                          "actual_code": None, "execution_return": None,
                          "execution_result": "not-executed", "pass": False,
                          "skipped": True, "skipped_required": 1})
            continue
        cases.append(case_result(case_id=case_id, requirement_ids=[case_id],
                                 validator_name=validator_name, validator_version="1",
                                 input_bytes=raw, expected_layer=layer, expected_code=code,
                                 execution_return=ret, actual_layer=actual_layer, actual_code=actual,
                                 execution_result=result))
    passed = sum(case["pass"] for case in cases)
    skipped = sum(case["skipped_required"] for case in cases)
    return {"schema_version": "1.0.0", "status": "PASS" if passed == len(cases) and not skipped else "FAIL",
            "cases": cases, "total": len(cases), "passed": passed,
            "failed": len(cases) - passed, "skipped_required": skipped}


def validate_receipt_bytes(raw: bytes, fields: set[str]) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("receipt fields differ")
    if raw != canonical_json_bytes(data):
        raise ValueError("receipt is noncanonical")
    return data


def verify_receipt_hash(raw: bytes, expected: str) -> bool:
    return sha256(raw) == expected


def derive_status(receipts: dict[str, dict[str, Any]]) -> str:
    return "PASS" if set(receipts) == set(VERDICT_INPUT_RECEIPTS) and all(
        r.get("status") == "PASS" and r.get("skipped_required", 0) == 0 for r in receipts.values()
    ) else "FAIL"


def skipped_required_evidence(receipts: dict[str, dict[str, Any]]) -> int:
    """Count required evidence at its leaf representation, never its aggregate twice."""
    total = receipts.get("source-manifest.json", {}).get("skipped_required", 0)
    total += len(receipts.get("profile-fixture-inventory.json", {}).get("uncovered", []))
    total += sum(row.get("skipped_required", 0) for row in
                 receipts.get("schema-validation.json", {}).get("negative_cases", []))
    total += receipts.get("semantic-conformance.json", {}).get("skipped_required", 0)
    total += sum(row.get("skipped_required", 0) for row in
                 receipts.get("mutation-results.json", {}).get("cases", []))
    total += sum(row.get("skipped_required", 0) for row in
                 receipts.get("public-boundary-and-license-scan.json", {}).get("checks", []))
    return total


def receipt_hash_map(receipt_bytes: dict[str, bytes]) -> dict[str, str]:
    if set(receipt_bytes) != set(VERDICT_INPUT_RECEIPTS):
        raise ValueError("receipt hash inputs differ")
    return {name: sha256(receipt_bytes[name]) for name in VERDICT_INPUT_RECEIPTS}


def command_schema() -> list[str]:
    return ["python3", "scripts/test-native-theme-sq01.py", "--source-sha", "${SOURCE_SHA}",
            "--output-dir", "artifacts/quality/sq-01"]


def synthetic_test_context(source_sha: str) -> dict[str, Any]:
    return {"source_sha": source_sha, "environment": {"TZ": "UTC", "LC_ALL": "C", "LANG": "C", "PYTHONHASHSEED": "0"}}


def build_synthetic_bundle(context: dict[str, Any]) -> dict[str, bytes]:
    return {name: canonical_json_bytes({"context": context, "name": name}) for name in ALL_RECEIPTS}


def _strict_load(path: Path) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("E_JSON_DUPLICATE")
            result[key] = value
        return result
    return json.loads(path.read_text("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("E_NUMBER_NONFINITE")))


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes())}


def _source_manifest(root: Path, ident: SourceIdentity) -> dict[str, Any]:
    tracked = sorted(str(git(root, "ls-files")).splitlines())
    records = [_file_record(root, root / p) for p in tracked]
    diff = bytes(git(root, "diff", "--binary", BASE_SHA, ident.sha, binary=True))
    def hashed(path: str) -> str:
        return sha256((root / path).read_bytes())
    versions = {}
    for line in (root / "versions.env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1); versions[key] = value
    return {
        "schema_version": "1.0.0", "status": "PASS", "source_sha": ident.sha,
        "source_tree": ident.tree, "comparison_base_sha": BASE_SHA,
        "binary_diff_serialization": "raw bytes from git diff --binary <base-sha> <source-sha>",
        "binary_diff_sha256": sha256(diff), "tracked_files": records,
        "tracked_manifest_sha256": sha256(canonical_json_bytes(records)),
        "schema_sha256": hashed("tools/native_theme/native-theme-v1.schema.json"),
        "profile_fixture_manifest_sha256": hashed("tools/native_theme/fixtures/profile-fixture-manifest.json"),
        "production_hashes": {p: hashed(p) for p in SAFETY_MODULES[:4]},
        "oracle_hashes": {p: hashed(p) for p in ("docs/native-theme-v1-legacy-oracle.json", "tools/native_theme/legacy_inventory.py")},
        "versions_env_sha256": hashed("versions.env"), "versions_env_pins": versions,
        "runtime_versions": {"python": ".".join(map(str, sys.version_info[:3])), **PINNED},
        "command_schema": command_schema(),
        "environment_pins": {k: os.environ.get(k, "") for k in ("TZ", "LC_ALL", "LANG", "PYTHONHASHSEED", "NATIVE_THEME_SQ01_NETWORK")},
        "skipped_required": 0,
    }


def _registry_case(case_id: str, polarity: str, requirement_id: str, raw: bytes,
                   validator: str, expected_layer: str, expected_code: str | None,
                   actual_layer: str | None, actual_code: str | None,
                   result: str) -> dict[str, Any]:
    case = case_result(case_id=case_id, requirement_ids=[requirement_id],
                       validator_name=validator, validator_version="1",
                       input_bytes=raw, expected_layer=expected_layer,
                       expected_code=expected_code, execution_return=0 if result == "accepted" else 2,
                       actual_layer=actual_layer, actual_code=actual_code,
                       execution_result=result)
    case["polarity"] = polarity
    return case


def _resolve_path(value: Any, path: list[str]) -> Any:
    cursor = value
    for part in path:
        if part == "[]":
            cursor = cursor[0]
        else:
            cursor = cursor[part]
    return cursor


def _schema_registry_cases(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import jsonschema
    schema = _strict_load(root / "tools/native_theme/native-theme-v1.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    baselines = {
        "nativePackage": _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json"),
        "legacySnapshot": _strict_load(root / "tools/native_theme/fixtures/base24-instrument-studio.golden.json"),
    }
    cases = []
    def leaves(errors):
        pending = list(errors); result = []
        while pending:
            error = pending.pop()
            if error.context: pending.extend(error.context)
            else: result.append(error)
        return result
    for row in (r for r in rows if r["id"].startswith("schema.")):
        rid, definition, path, mode = row["id"], row["_definition"], row["_property_path"], row["_mode"]
        baseline = baselines[definition]
        # Resolve the exact property/boundary before full-document validation.
        _resolve_path(baseline, path)
        errors = sorted(validator.iter_errors(baseline), key=lambda e: list(e.path))
        raw = canonical_json_bytes(baseline)
        cases.append(_registry_case("positive:" + rid, "positive", rid, raw,
                      "jsonschema.Draft202012Validator", "schema", None,
                      None if not errors else "schema", None if not errors else errors[0].validator,
                      "accepted" if not errors else "rejected"))
        candidate = json.loads(json.dumps(baseline))
        parent = _resolve_path(candidate, path[:-1]) if mode == "required" else _resolve_path(candidate, path)
        if mode == "required":
            del parent[path[-1]]
            expected_validator, expected_path = "required", path[:-1]
        elif mode == "forbidden-extra":
            parent["sq01_forbidden_extra"] = True
            expected_validator, expected_path = "additionalProperties", path
        else:
            raise RuntimeError("optional schema row requires an explicit invalid-value constructor")
        raw = canonical_json_bytes(candidate)
        errors = sorted(validator.iter_errors(candidate), key=lambda e: (list(e.path), list(e.schema_path)))
        leaf_errors = leaves(errors)
        match = next((e for e in leaf_errors if e.validator == expected_validator and
                      list(e.absolute_path) == expected_path), None)
        actual = match.validator if match else (errors[0].validator if errors else None)
        case = _registry_case("negative:" + rid, "negative", rid, raw,
                 "jsonschema.Draft202012Validator", "schema", expected_validator,
                 "schema" if errors else None, actual, "rejected" if errors else "accepted")
        case["jsonschema_path"] = list(match.path) if match else None
        case["jsonschema_schema_path"] = list(match.schema_path) if match else None
        case["pass"] = match is not None
        cases.append(case)
    return cases


def _contract_registry_cases(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validator = _load_contract_validator(root)
    package = _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json")
    cases = []
    for row in rows:
        rid = row["id"]
        if rid.startswith("role."):
            _, variant, role = rid.split(".", 2)
            value = package["variants"][variant]["semantic"][role]
            validator.validate_package(package)
            raw = canonical_json_bytes({"variant": variant, "role": role, "value": value})
            cases.append(_registry_case("positive:" + rid, "positive", rid, raw,
                         "native-theme-v1.validate_package", "contract", None, None, None, "accepted"))
            candidate = json.loads(json.dumps(package)); del candidate["variants"][variant]["semantic"][role]
            negraw = canonical_json_bytes(candidate)
            ret, result, layer, code = _contract_executor(root, negraw, "package")
            cases.append(_registry_case("negative:" + rid, "negative", rid, negraw,
                         "native-theme-v1.validate_package", "contract", "E_SEMANTIC_ROLES",
                         layer, code, result))
        elif rid.startswith("variant."):
            variant = rid.split(".", 1)[1]
            validator.validate_package(package); raw = canonical_json_bytes(package["variants"][variant])
            cases.append(_registry_case("positive:" + rid, "positive", rid, raw,
                         "native-theme-v1.validate_package", "contract", None, None, None, "accepted"))
            candidate = json.loads(json.dumps(package)); del candidate["variants"][variant]
            negraw = canonical_json_bytes(candidate); _, result, layer, code = _contract_executor(root, negraw, "package")
            cases.append(_registry_case("negative:" + rid, "negative", rid, negraw,
                         "native-theme-v1.validate_package", "contract", "E_VARIANT_REQUIRED", layer, code, result))
        elif rid.startswith("layer."):
            layer_name = rid.split(".", 1)[1]
            validator.validate_package(package)
            raw = canonical_json_bytes({v: package["variants"][v][layer_name] for v in package["variants"]})
            cases.append(_registry_case("positive:" + rid, "positive", rid, raw,
                         "native-theme-v1.validate_package", "contract", None, None, None, "accepted"))
            candidate = json.loads(json.dumps(package)); candidate["variants"]["dark"][layer_name] = {}
            negraw = canonical_json_bytes(candidate); _, result, layer, code = _contract_executor(root, negraw, "package")
            cases.append(_registry_case("negative:" + rid, "negative", rid, negraw,
                         "native-theme-v1.validate_package", "contract", "E_LAYER_REQUIRED", layer, code, result))
    return cases


def execute_diagnostic_rule(code: str, value: Any) -> str | None:
    """Evaluate one declared diagnostic rule against structure, never an expected-code marker."""
    if not isinstance(value, dict):
        return None
    if code == "E_ALIAS_CYCLE":
        graph = value.get("aliases", {}); seen = set(); node = next(iter(graph), None)
        while node in graph:
            if node in seen: return code
            seen.add(node); node = graph[node]
    elif code == "E_ALIAS_UNRESOLVED":
        graph = value.get("aliases", {}); return code if any(target not in graph and target not in value.get("tokens", {}) for target in graph.values()) else None
    elif code == "E_LIMIT_ALIAS_DEPTH":
        return code if len(value.get("chain", [])) > value.get("limit", 0) else None
    elif code == "E_TYPE_INHERITED":
        return code if value.get("inherited_type") != value.get("child_type") else None
    elif code == "E_COLOR_COMPONENT":
        c = value.get("components", []); return code if len(c) != 3 or any(not isinstance(x, (int, float)) or not 0 <= x <= 1 for x in c) else None
    elif code == "E_COLOR_SPACE": return code if value.get("colorSpace") not in {"srgb"} else None
    elif code == "E_EXECUTABLE": return code if set(value) & {"command", "shell", "template", "plugin"} else None
    elif code == "E_EXTENSION_UNSUPPORTED": return code if any(not k.startswith("org.designtokens.") for k in value.get("extensions", {})) else None
    elif code == "E_PATH_TRAVERSAL":
        p = value.get("path", ""); return code if isinstance(p, str) and (p.startswith("/") or ".." in Path(p).parts) else None
    elif code == "E_FIELD_REQUIRED": return code if value.get("required") not in value.get("tokens", {}) else None
    elif code == "E_FIELD_EXTRA": return code if set(value.get("tokens", {})) - set(value.get("allowed", [])) else None
    elif code == "E_FIELD_FORBIDDEN": return code if set(value.get("tokens", {})) & set(value.get("forbidden", [])) else None
    elif code == "E_COLOR_CANONICAL": return code if re.fullmatch(r"[0-9a-f]{6}", str(value.get("color", ""))) is None else None
    elif code == "E_PROFILE_LAYER": return code if value.get("declared_layer") == "runtime" else None
    elif code == "E_PROFILE_STRUCTURE": return code if not isinstance(value.get("tokens"), dict) else None
    elif code in {"E_HASH", "E_IDENTITY", "E_PROVENANCE", "E_PRIMITIVE_AUTHORITY"}:
        return code if value.get("actual") != value.get("expected") else None
    return None


def _diagnostic_structures(code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    p: dict[str, Any] = {}
    if code == "E_ALIAS_CYCLE": return ({**p, "aliases": {"a": "done"}, "tokens": {"done": 1}}, {**p, "aliases": {"a": "b", "b": "a"}})
    if code == "E_ALIAS_UNRESOLVED": return ({**p, "aliases": {"a": "done"}, "tokens": {"done": 1}}, {**p, "aliases": {"a": "missing"}})
    if code == "E_LIMIT_ALIAS_DEPTH": return ({**p, "chain": [1], "limit": 8}, {**p, "chain": list(range(9)), "limit": 8})
    if code == "E_TYPE_INHERITED": return ({**p, "inherited_type": "color", "child_type": "color"}, {**p, "inherited_type": "color", "child_type": "dimension"})
    if code == "E_COLOR_COMPONENT": return ({**p, "components": [0, .5, 1]}, {**p, "components": [0, 2, 1]})
    if code == "E_COLOR_SPACE": return ({**p, "colorSpace": "srgb"}, {**p, "colorSpace": "display-p3"})
    if code == "E_EXECUTABLE": return ({**p, "tokens": {}}, {**p, "command": "run"})
    if code == "E_EXTENSION_UNSUPPORTED": return ({**p, "extensions": {"org.designtokens.foo": {}}}, {**p, "extensions": {"com.example.bad": {}}})
    if code == "E_PATH_TRAVERSAL": return ({**p, "path": "assets/icon.svg"}, {**p, "path": "../escape"})
    if code == "E_FIELD_REQUIRED": return ({**p, "required": "base00", "tokens": {"base00": 1}}, {**p, "required": "base00", "tokens": {}})
    if code == "E_FIELD_EXTRA": return ({**p, "allowed": ["base00"], "tokens": {"base00": 1}}, {**p, "allowed": ["base00"], "tokens": {"base00": 1, "extra": 1}})
    if code == "E_FIELD_FORBIDDEN": return ({**p, "forbidden": ["command"], "tokens": {}}, {**p, "forbidden": ["command"], "tokens": {"command": 1}})
    if code == "E_COLOR_CANONICAL": return ({**p, "color": "abcdef"}, {**p, "color": "#ABC"})
    if code == "E_PROFILE_LAYER": return ({**p, "declared_layer": "primitives"}, {**p, "declared_layer": "runtime"})
    if code == "E_PROFILE_STRUCTURE": return ({**p, "tokens": {}}, {**p, "tokens": []})
    return ({**p, "actual": "source", "expected": "source"}, {**p, "actual": "mutated", "expected": "source"})


def _diagnostic_registry_cases(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = _strict_load(root / "tools/native_theme/fixtures/profile-fixture-manifest.json")
    owners = {code: sorted(p["positive_cases"][0]["file"] for p in manifest["profiles"] if code in p["diagnostics"])
              for code in {r["id"].split(".", 1)[1] for r in rows if r["id"].startswith("diagnostic.")}}
    cases = []
    for code in sorted(owners):
        rid = "diagnostic." + code; positive, negative = _diagnostic_structures(code)
        positive["owners"] = owners[code]
        # Hash every owning positive fixture as inspected input provenance.
        positive["owner_hashes"] = [sha256((root / "tools/native_theme/fixtures/profiles" / f).read_bytes()) for f in owners[code]]
        for polarity, value, expected in (("positive", positive, None), ("negative", negative, code)):
            actual = execute_diagnostic_rule(code, value); result = "rejected" if actual else "accepted"
            cases.append(_registry_case(polarity + ":" + rid, polarity, rid, canonical_json_bytes(value),
                         "sq01-independent-diagnostic-rule", "semantic", expected,
                         "semantic" if actual else None, actual, result))
    return cases


def _profile_registry_cases(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = _strict_load(root / "tools/native_theme/fixtures/profile-fixture-manifest.json")
    cases = []
    for entry in manifest["profiles"]:
        fixture_path = root / "tools/native_theme/fixtures/profiles" / entry["positive_cases"][0]["file"]
        fixture = _strict_load(fixture_path); raw = fixture_path.read_bytes()
        for category, declared in (("profile", entry["profile"]), ("type", entry["type"])):
            rid = category + "." + declared
            _, result, layer, code = _contract_executor(root, canonical_json_bytes(fixture), "profile")
            cases.append(_registry_case("positive:" + rid, "positive", rid, raw,
                         "native-theme-v1.validate_profile_fixture", "contract", None, layer, code, result))
            candidate = json.loads(json.dumps(fixture)); candidate["declared_layer"] = "runtime"
            negraw = canonical_json_bytes(candidate); _, result, layer, code = _contract_executor(root, negraw, "profile")
            cases.append(_registry_case("negative:" + rid, "negative", rid, negraw,
                         "native-theme-v1.validate_profile_fixture", "contract", "E_PROFILE_LAYER", layer, code, result))
    return cases


def _derivation_registry_cases(root: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_dir = root / "tools/native_theme/fixtures/profiles"
    profiles = {p.name: _strict_load(p) for p in profile_dir.glob("*-positive.json")}
    package = _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json")
    oracle = _strict_load(root / "docs/native-theme-v1-legacy-oracle.json")
    contract = _load_contract_validator(root)
    base16, base24 = profiles["base16-positive.json"]["tokens"], profiles["base24-positive.json"]["tokens"]
    omarchy, dtcg, legacy = (profiles[n]["tokens"] for n in
                             ("omarchy-positive.json", "dtcg-positive.json", "legacy-positive.json"))
    role_to_base = contract.ROLE_TO_BASE
    def operands(name: str) -> tuple[Any, Any]:
        if name == "curly-alias-resolution": return dtcg["aliased"]["$value"], "{group.canvas}"
        if name == "srgb-alpha-preservation":
            color = dtcg["group"]["canvas"]["$value"]
            return [color["colorSpace"], color["components"], color["alpha"]], ["srgb", color["components"], 1]
        if name == "base-role-map":
            dark = package["variants"]["dark"]["semantic"]
            provenance = package["metadata"]["provenance"]["tokens"]
            actual = {}
            for role, token in role_to_base.items():
                source = base24.get(token, base16.get(token))
                derived = provenance.get(role, {}).get("kind") == "derived"
                actual[role] = source is not None and (dark[role] == "#" + source + "ff" or derived)
            return actual, {role: True for role in role_to_base}
        if name == "base16-plus-bright-ansi":
            return ["#" + base24[f"base1{i}"] + "ff" for i in range(8)], [package["variants"]["dark"]["terminal"][f"ansi{i}"] for i in range(8, 16)]
        if name == "normal-bright-ansi":
            return [c + "ff" for c in omarchy["ansi.normal"] + omarchy["ansi.bright"]], [package["variants"]["dark"]["terminal"][f"ansi{i}"] for i in range(16)]
        if name == "ramp-role-map":
            variant = package["variants"]["dark"]
            roles = variant["semantic"]
            mapped = [roles[x][:-2] for x in ("surface.deep", "surface.canvas", "surface.raised", "text.muted")]
            mapped.extend([variant["terminal"]["ansi7"][:-2], roles["text.normal"][:-2]])
            return omarchy["background.ramp"] + omarchy["foreground.ramp"], mapped
        if name == "legacy-quantize-half-up":
            values = ["0.071", "0.5", "1"]
            return [contract.quantize_channel(v) for v in values], [18, 128, 255]
        declared = {k: v for k, v in legacy.items() if k != "proof_semantic_hash"}
        return declared, oracle["policies"]["legacy_token_roles"]
    def execute_derivation_rule(left: Any, right: Any) -> str | None:
        return None if left == right else "E_DERIVATION_MISMATCH"

    def mutate_operand(value: Any) -> Any:
        changed = json.loads(json.dumps(value))
        if isinstance(changed, dict) and changed:
            key = sorted(changed)[0]
            changed[key] = mutate_operand(changed[key])
            return changed
        if isinstance(changed, list) and changed:
            changed[0] = mutate_operand(changed[0])
            return changed
        if isinstance(changed, bool):
            return not changed
        if isinstance(changed, (int, float)):
            return changed + 1
        if isinstance(changed, str):
            return changed + "-mutated"
        return {"mutated": True}

    cases = []
    for row in (r for r in rows if r["id"].startswith("derivation.")):
        rid = row["id"]
        name = rid.split(".", 1)[1]; left, right = operands(name)
        for polarity, compared, expected in (("positive", right, None),
                                              ("negative", mutate_operand(right), "E_DERIVATION_MISMATCH")):
            actual = execute_derivation_rule(left, compared)
            result = "rejected" if actual else "accepted"
            proof = {"requirement": rid, "left": left, "right": compared}
            cases.append(_registry_case(polarity + ":" + rid, polarity, rid, canonical_json_bytes(proof),
                         "sq01-independent-derivation-rule", "derivation", expected,
                         "derivation" if actual else None, actual, result))
    return cases


def attach_registry_evidence(rows: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    attached = json.loads(json.dumps(rows))
    by_id = {row["id"]: row for row in attached}
    for case in cases:
        if not case.get("pass") or case.get("skipped"):
            continue
        for rid in case["requirement_ids"]:
            by_id[rid][case["polarity"] + "_case_ids"].append(case["id"])
    result = evaluate_completeness(attached)
    return {"rows": attached, **result}


def _inventory(root: Path) -> dict[str, Any]:
    discovered = build_requirements_inventory(root)
    rows = discovered["rows"]
    cases = (_schema_registry_cases(root, rows) + _contract_registry_cases(root, rows) +
             _profile_registry_cases(root, rows) + _diagnostic_registry_cases(root, rows) +
             _derivation_registry_cases(root, rows))
    cases.sort(key=lambda c: (c["requirement_ids"], c["polarity"], c["id"]))
    inventory = attach_registry_evidence(rows, cases)
    category_counts: dict[str, int] = {}
    for row in rows:
        category = row["id"].split(".", 1)[0]
        category_counts[category] = category_counts.get(category, 0) + 1
    inventory.update({"schema_version": "1.0.0", "case_registry": cases,
                      "category_counts": dict(sorted(category_counts.items())),
                      "executed_counts": {p: sum(c["polarity"] == p for c in cases)
                                          for p in ("negative", "positive")},
                      "skipped_required": len(inventory["uncovered"])})
    if any(not case["pass"] for case in cases): inventory["status"] = "FAIL"
    return inventory


def _schema_validation(root: Path) -> dict[str, Any]:
    import jsonschema
    schema = _strict_load(root / "tools/native_theme/native-theme-v1.schema.json")
    package = _strict_load(root / "tools/native_theme/fixtures/native-theme-v1-package.json")
    golden = _strict_load(root / "tools/native_theme/fixtures/base24-instrument-studio.golden.json")
    errors = []
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        validator.validate(package); validator.validate(golden)
    except Exception as exc:
        errors.append({"code": "E_SCHEMA", "detail": str(exc)})
    cases = []
    raw_cases = {
        "duplicate-key": b'{"a":1,"a":2}', "invalid-utf8": b'\xff',
        "nan": b'{"a":NaN}', "infinite": b'{"a":Infinity}',
    }
    for case_id, raw in raw_cases.items():
        rejected = False
        try:
            text = raw.decode("utf-8")
            json.loads(text, object_pairs_hook=lambda pairs: (_ for _ in ()).throw(ValueError()) if len(dict(pairs)) != len(pairs) else dict(pairs),
                       parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
        except (UnicodeError, ValueError):
            rejected = True
        cases.append({"id": case_id, "expected_layer": "json", "expected_code": "E_INPUT", "rejected": rejected})
    bound_names = {"overlong": "bounds.overlong-string", "deep": "bounds.deep-nesting",
                   "oversized": "bounds.oversized-input"}
    for case_id, mutation_id in bound_names.items():
        raw = _bound_inputs()[mutation_id]
        ret, result, layer, code = _bounds_executor(raw, mutation_id)
        expected = REQUIRED_MUTATIONS[mutation_id][1]
        cases.append({"id": case_id, "validator_name": "sq01-declared-bounds-executor",
                      "validator_version": "1", "input_hash": sha256(raw),
                      "expected_layer": "bounds", "expected_code": expected,
                      "actual_layer": layer, "actual_code": code,
                      "execution_return": ret, "execution_result": result,
                      "rejected": result == "rejected", "pass": result == "rejected" and code == expected,
                      "skipped": False, "skipped_required": 0})
    if not all(c["rejected"] for c in cases): errors.append({"code": "E_NEGATIVE_ACCEPTED", "detail": "structural negative"})
    skipped = sum(case.get("skipped_required", 0) for case in cases)
    return {"schema_version": "1.0.0", "status": "PASS" if not errors and not skipped else "FAIL",
            "draft": "2020-12", "complete_package_valid": not errors,
            "legacy_proof_valid": not errors, "negative_cases": cases, "errors": errors,
            "skipped_required": skipped}


def _public_scan(root: Path) -> dict[str, Any]:
    candidates = []
    docs = root / "docs"
    if docs.is_dir():
        candidates.extend(path for path in docs.glob("native-theme-v1-*") if path.is_file())
    native = root / "tools/native_theme"
    schema = native / "native-theme-v1.schema.json"
    if schema.is_file(): candidates.append(schema)
    for directory in (native / "fixtures", native / "snapshots"):
        if directory.is_dir(): candidates.extend(path for path in directory.rglob("*") if path.is_file())
    candidates = sorted(set(candidates))
    scope = [path.relative_to(root).as_posix() for path in candidates]
    findings = []
    patterns = {
        "beads_id": re.compile(r"(?i)(?:\bbeads?\s+(?:id\s*[:=]\s*)?|\b)sq-\d+\b"),
        "kanban_id": re.compile(r"(?i)(?:\bkanban\s+(?:id\s*[:=]\s*)?|\bKAN-)\d+\b"),
        "absolute_path": re.compile(r"/(?:home|srv|tmp)/[^\s\"']+"),
        "credential": re.compile(r"(?i)(?:api[_-]?key|password|private[_-]?key)\s*[:=]"),
    }
    texts: dict[str, str] = {}
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or path.stat().st_size > 2_000_000: continue
        text = path.read_text("utf-8", errors="replace")
        texts[rel] = text
        for kind, pattern in patterns.items():
            for match in pattern.finditer(text):
                findings.append({"path": rel, "kind": kind, "value_sha256": sha256(match.group().encode())})

    artifacts = {"package": [rel for rel in texts if rel.endswith("native-theme-v1-package.json")],
                 "profile": [rel for rel in texts if "profile-fixture-manifest" in rel or "/profiles/" in rel],
                 "spec": [rel for rel in texts if rel.endswith("native-theme-v1.schema.json") or rel.endswith(".md")],
                 "public": [rel for rel in texts if rel.startswith("docs/")]}
    allowlist = {"Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0", "MIT", "MPL-2.0"}
    checks = []
    for artifact, paths in artifacts.items():
        if not paths:
            for name in ("spdx", "source-url", "attribution", "license-allowlist"):
                checks.append({"id": f"{artifact}.{name}", "paths": [], "executed": False,
                               "pass": False, "skipped": True, "skipped_required": 1})
            continue
        body = "\n".join(texts[path] for path in paths)
        package_body = "\n".join(texts[p] for p in artifacts["package"])
        spdx_values = set(re.findall(r"\b(?:Apache-2\.0|BSD-[23]-Clause|CC0-1\.0|MIT|MPL-2\.0)\b", body))
        outcomes = {
            "spdx": bool(spdx_values or re.search(r'"spdx"\s*:', package_body)),
            "source-url": bool(re.search(r'"source_identity"\s*:\s*"[^\"]+"', package_body)),
            "attribution": bool(re.search(r'"attribution"\s*:\s*"[^\"]+"', package_body)),
            "license-allowlist": bool(set(re.findall(r"\b(?:Apache-2\.0|BSD-[23]-Clause|CC0-1\.0|MIT|MPL-2\.0)\b", body + package_body))) and set(re.findall(r"\b(?:Apache-2\.0|BSD-[23]-Clause|CC0-1\.0|MIT|MPL-2\.0)\b", body + package_body)) <= allowlist,
        }
        for name, passed in outcomes.items():
            checks.append({"id": f"{artifact}.{name}", "paths": paths, "executed": True,
                           "pass": passed, "skipped": False, "skipped_required": 0})
    skipped = sum(check["skipped_required"] for check in checks)
    passed = not findings and all(check["pass"] for check in checks) and not skipped
    return {"schema_version": "1.0.0", "status": "PASS" if passed else "FAIL",
            "scope": scope, "allowed_negative_fixtures": [], "unclassified_findings": findings,
            "checks": checks, "license_attribution_complete": all(check["pass"] for check in checks),
            "skipped_required": skipped}


def _write_coverage_support(temp: Path) -> Path:
    config = temp / "coverage.ini"
    config.write_text("[run]\nsource = tools/native_theme\nbranch = true\nparallel = true\nrelative_files = true\n")
    (temp / "sitecustomize.py").write_text("import coverage\ncoverage.process_startup()\n")
    return config.resolve()


def _coverage_run(root: Path, temp: Path, commands: list[str],
                  module_paths: tuple[str, ...] | None = None,
                  parent_coverage: Any | None = None) -> dict[str, Any]:
    import coverage as coverage_api
    config = _write_coverage_support(temp)
    data_file = (temp / ".coverage-sq01").resolve()
    env = dict(os.environ)
    env.update({"COVERAGE_PROCESS_START": str(config), "COVERAGE_FILE": str(data_file),
                "PYTHONDONTWRITEBYTECODE": "1"})
    old_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(temp.resolve()) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    test_results = []
    for script in commands:
        result = run_allowed([sys.executable, script], root, env=env, check=True,
                             capture_output=True, text=True)
        count = len(re.findall(r"^test_.*\.\.\. ok$", result.stderr, re.M))
        test_results.append({"script": script, "returncode": result.returncode, "tests": count})

    if parent_coverage is not None:
        parent_coverage.stop()
        parent_coverage.save()
    data_parts = sorted(temp.glob(data_file.name + ".*"))
    if not data_parts:
        raise RuntimeError("no coverage data produced by test processes")
    measured = coverage_api.Coverage(config_file=str(config), data_file=str(data_file))
    try:
        measured.combine(data_paths=[str(temp)], strict=True)
        measured.load()
    except coverage_api.CoverageException as exc:
        raise RuntimeError("coverage data combine failed") from exc
    report_path = temp / "coverage.json"
    measured.json_report(outfile=str(report_path))
    report = json.loads(report_path.read_text())
    modules = []
    total_functions = hit_functions = 0
    paths = module_paths if module_paths is not None else tuple(sorted(report["files"]))
    for rel in paths:
        entry = report["files"].get(rel, {"executed_lines": [], "missing_lines": [], "summary": {"num_branches": 0, "covered_branches": 0, "missing_branches": 0}})
        executed = set(entry["executed_lines"])
        tree = ast.parse((root / rel).read_text())
        functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        function_rows = []
        for fn in functions:
            body_lines = {getattr(node, "lineno", -1) for node in ast.walk(fn) if getattr(node, "lineno", -1) > fn.lineno}
            hit = bool(body_lines & executed)
            function_rows.append({"name": fn.name, "line": fn.lineno, "covered": hit})
        summary = entry["summary"]
        total_functions += len(functions); hit_functions += sum(r["covered"] for r in function_rows)
        modules.append({"path": rel, "statements": {"covered": summary.get("covered_lines", 0), "total": summary.get("num_statements", 0), "missing_lines": entry["missing_lines"]},
                        "functions": function_rows,
                        "branches": {"covered": summary.get("covered_branches", 0), "total": summary.get("num_branches", 0), "missing": entry.get("missing_branches", [])}})
    branch_total = sum(m["branches"]["total"] for m in modules); branch_hit = sum(m["branches"]["covered"] for m in modules)
    return {"tests": test_results, "modules": modules,
            "function_coverage": {"covered": hit_functions, "total": total_functions, "percent": 100 * hit_functions / total_functions if total_functions else 100},
            "branch_coverage": {"covered": branch_hit, "total": branch_total, "percent": 100 * branch_hit / branch_total if branch_total else 100},
            "target_met": hit_functions == total_functions and branch_hit == branch_total}


def _coverage(root: Path, temp: Path) -> dict[str, Any]:
    import coverage as coverage_api
    config = _write_coverage_support(temp)
    parent = coverage_api.Coverage(config_file=str(config),
                                   data_file=str((temp / ".coverage-sq01").resolve()),
                                   data_suffix=True)
    parent.start()
    try:
        commands = ["scripts/test-native-theme-v1.py", "scripts/test-native-theme-legacy-oracle.py",
                    "scripts/test-native-theme-sq01-harness.py"]
        return _coverage_run(root, temp, commands, SAFETY_MODULES, parent)
    finally:
        parent.stop()
        if temp.exists():
            shutil.rmtree(temp)


def run_gate(root: Path, source_sha: str, output: Path, *, safe_temp_root: Path | None = None) -> int:
    for name, version in PINNED.items():
        actual = importlib.metadata.version(name)
        if actual != version:
            raise RuntimeError(f"dependency version mismatch: {name}={actual}, required {version}")
    output = validate_output_path(root, output, safe_temp_root=safe_temp_root)
    before = source_identity(root, output if output.is_relative_to(root) else None)
    assert_source_identity(before, source_sha, before)
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True)
    receipts: dict[str, dict[str, Any]] = {}
    receipts["source-manifest.json"] = _source_manifest(root, before)
    receipts["profile-fixture-inventory.json"] = _inventory(root)
    receipts["schema-validation.json"] = _schema_validation(root)
    from sq01_semantic_validator import validate_paths
    semantic = validate_paths(root / "tools/native_theme/fixtures/native-theme-v1-package.json",
                              root / "tools/native_theme/native-theme-v1.schema.json",
                              root / "docs/native-theme-v1-legacy-oracle.json")
    semantic.update({"schema_version": "1.0.0", "skipped_required": 0})
    receipts["semantic-conformance.json"] = semantic
    receipts["mutation-results.json"] = execute_mutations(root)
    receipts["public-boundary-and-license-scan.json"] = _public_scan(root)
    temp_parent = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix="native-theme-sq01-coverage-", dir=temp_parent) as td:
        coverage = _coverage(root, Path(td))
    if not coverage["target_met"]:
        receipts["mutation-results.json"]["status"] = "FAIL"
        receipts["mutation-results.json"]["coverage_failure"] = True
    component_status = derive_status({k: receipts[k] for k in VERDICT_INPUT_RECEIPTS})
    for name, receipt in receipts.items():
        (output / name).write_bytes(canonical_json_bytes(receipt))
    hashes = receipt_hash_map({name: (output / name).read_bytes()
                               for name in VERDICT_INPUT_RECEIPTS})
    verdict = {"schema_version": "1.0.0", "status": component_status,
               "source_sha": before.sha, "source_tree": before.tree, "receipt_sha256": hashes,
               "test_counts": coverage["tests"], "requirements_completeness": receipts["profile-fixture-inventory.json"]["completeness_percent"],
               "coverage": coverage, "mutation_totals": {k: receipts["mutation-results.json"][k] for k in ("total", "passed", "failed")},
               "skipped_required_evidence": skipped_required_evidence(receipts),
               "failure_classification": "coverage-or-conformance" if component_status == "FAIL" else "none",
               "root_cause_status": "measured", "residual_risks": [] if component_status == "PASS" else ["uncovered safety-bearing code"],
               "cheapest_next_proof": "add focused tests for the exact uncovered functions and branches; production repair is outside this lane",
               "claims_excluded": ["merge", "deploy", "release"]}
    (output / "verdict.json").write_bytes(canonical_json_bytes(verdict))
    after = source_identity(root, output if output.is_relative_to(root) else None)
    assert_source_identity(before, source_sha, after)
    return 0 if component_status == "PASS" else 1

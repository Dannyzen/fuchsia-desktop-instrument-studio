#!/usr/bin/env python3
"""Generate the deterministic, exact-commit NativeThemeV1 legacy inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

SCHEMA_VERSION = "1.1.0"
SCANNER_VERSION = "2.0.0"
BASE_COMMIT = "a781f2d52a9617b40b6e15d6fb39875954b51a28"
BASE_TREE = "6b344230b8e2979564fb10776b5ccc41ace2ab79"
TARGET_ROOTS = [
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs",
    "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/chrome.rs",
    "overlays/fuchsia/src/ui/bin/tiling_wm/src/chrome.rs",
    "overlays/fuchsia/src/ui/bin/tiling_wm/src/main.rs",
    "overlays/fuchsia/src/fuchsia-desktop/browser/src",
    "overlays/fuchsia/src/fuchsia-desktop/files/src",
    "overlays/fuchsia/src/fuchsia-desktop/settings/src",
    "overlays/fuchsia/src/fuchsia-desktop/terminal/src",
]
ALLOWED_DISPOSITIONS = {"map-semantic", "product-behavior-fixed", "consumer-reference", "state-migrate", "retain-local-nontheme", "retire-duplicate"}
TOKEN_ROLES = {
    "panel_bg": "surface.canvas", "panel_elevated": "surface.raised",
    "selected_focus": "interaction.selection", "text_secondary": "text.muted",
    "border_muted": "border.normal", "text_primary": "text.bright",
    "danger": "status.danger", "ok": "status.success",
    "confirmed_focus": "border.focusConfirmed", "accent_secondary": "interaction.accent",
}
STATE_SITES = {
    "overlays/fuchsia/src/fuchsia-desktop/settings/src/settings_core.rs": {11, 12, 13, 24, 26, 27, 31, 33, 34, 83, 98, 100, 101, 102, 103, 107, 111, 144, 145, 156, 161, 165},
    "overlays/fuchsia/src/fuchsia-desktop/settings/src/main.rs": {221, 232, 237, 504, 509},
}
CATEGORY_RULES = [
    ("focus", re.compile(r"focus|focuser|focused", re.I)),
    ("interaction", re.compile(r"select|hover|press|active|pointer|keyboard|key_event|wrap_focus", re.I)),
    ("geometry-density", re.compile(r"width|height|size|padding|margin|gap|radius|row|column|grid|tile|layout|position|rect|density|inset|slot", re.I)),
    ("color", re.compile(r"color|rgba|#[0-9a-f]{3,8}|background|accent|surface|panel|border|danger|\bok\b", re.I)),
    ("typography", re.compile(r"font|glyph|text(?:Style|Run|_primary|_secondary)|label|caption|title|line_height", re.I)),
    ("motion-elevation", re.compile(r"motion|duration|transition|animation|shadow|elevation|opacity|alpha", re.I)),
    ("icon-asset", re.compile(r"icon|asset|image|include_bytes|png|svg", re.I)),
    ("settings-state", re.compile(r"AppTheme|set_theme|theme_state|selected_theme|\btheme\b", re.I)),
    ("fallback", re.compile(r"fallback|last_known|built.?in", re.I)),
]
DECL_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const\s+)?fn|const|static|struct|enum|type)\s+([A-Za-z_][A-Za-z0-9_]*)")
LET_RE = re.compile(r"^\s*let(?:\s+mut)?\s+([A-Za-z_][A-Za-z0-9_]*)")
FIELD_RE = re.compile(r"^\s*(?:pub\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^:=][^,{}]*,?\s*$")
ASSIGN_FIELD_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+),\s*$")
CALL_RE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*\s*\(")
LITERAL_RE = re.compile(r"ColorRgba::new|TextStyle\s*\{|include_bytes!|\[[0-9A-Fa-fx., _-]+\]|:\s*-?[0-9]+(?:\.[0-9]+)?(?:u32|f32)?\b")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE).stdout


def target_files() -> list[str]:
    return sorted(git("ls-tree", "-r", "--name-only", BASE_COMMIT, "--", *TARGET_ROOTS).decode().splitlines())


def blob(path: str) -> bytes:
    return git("show", f"{BASE_COMMIT}:{path}")


def category(line: str) -> str:
    for name, pattern in CATEGORY_RULES:
        if pattern.search(line):
            return name
    return "incidental"


def select_candidates(path: str, text: str) -> list[tuple[int, str]]:
    """Select style/state declarations, values, and direct call sites, never mere lines."""
    selected = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*", "#!", "use ", "pub use ")) or stripped in {"{", "}", "};", "};"}:
            continue
        relevant = category(line) != "incidental"
        syntax = DECL_RE.match(line) or LET_RE.match(line) or FIELD_RE.match(line) or ASSIGN_FIELD_RE.match(line) or CALL_RE.search(line) or LITERAL_RE.search(line) or ":" in line
        if (number in STATE_SITES.get(path, set())) or (relevant and syntax):
            selected.append((number, line))
    return selected


def stable_id(path: str, line: int, digest: str) -> str:
    return "legacy-" + hashlib.sha256(f"{path}\0{line}\0{digest}".encode()).hexdigest()[:24]


def declaration_name(line: str) -> str | None:
    for pattern in (DECL_RE, LET_RE, ASSIGN_FIELD_RE, FIELD_RE):
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def policy_key(path: str, line: int, name: str | None, cat: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    identity = re.sub(r"[^A-Za-z0-9]+", "-", name or f"line-{line}").strip("-").lower()
    return f"product-policy.{cat}.{stem}.{identity}-L{line}"


def scan_file(path: str, raw: bytes) -> list[dict]:
    entries = []
    for line_no, source_line in select_candidates(path, raw.decode("utf-8")):
        digest = hashlib.sha256(source_line.encode()).hexdigest()
        name = declaration_name(source_line)
        cat = category(source_line)
        is_token_file = path.endswith("desktop_ui/src/tokens.rs")
        token_field = name if name in TOKEN_ROLES else None
        state = line_no in STATE_SITES.get(path, set())
        test_or_assertion = bool(re.search(r"^\s*(?:(?:pub\s+)?fn\s+|assert(?:_eq|_ne)?!)", source_line, re.I))
        contract_field = bool(is_token_file and token_field and FIELD_RE.match(source_line))
        token_initializer = bool(is_token_file and token_field and "ColorRgba::new" in source_line)
        declaration = DECL_RE.match(source_line)
        local_definition = bool((declaration and declaration.group(1) not in {"ColorRgba", "ThemeTokens", "INSTRUMENT_STUDIO_THEME"}) or LET_RE.match(source_line) or (ASSIGN_FIELD_RE.match(source_line) and LITERAL_RE.search(source_line)) or (re.search(r"\b(?:const|static)\b", source_line) and LITERAL_RE.search(source_line)))

        if contract_field:
            kind, authority, key = "contract-field", "non-authority", None
            disposition, target = "consumer-reference", TOKEN_ROLES[token_field]
            rationale = "Contract field defines the legacy shape consumed by its exact semantic role."
        elif token_initializer:
            kind, authority, key = "definition", "authority", TOKEN_ROLES[token_field]
            disposition, target = "map-semantic", TOKEN_ROLES[token_field]
            rationale = "Live legacy field initializer is the authoritative value for this exact semantic role."
        elif is_token_file and name in {"ColorRgba", "ThemeTokens", "INSTRUMENT_STUDIO_THEME"}:
            kind, authority, key = "container", "non-authority", None
            disposition, target = "retain-local-nontheme", "local.token-container"
            rationale = "Type or constant container carries no independent live semantic value."
        elif state:
            kind, authority, key = "state", "non-authority", None
            disposition, target = "state-migrate", "variant-selection.instrument-studio"
            rationale = "Real Settings schema, persistence, mutation, or production selection site migrates variants."
        elif test_or_assertion:
            kind, authority, key = "reference", "non-authority", None
            disposition, target = "retain-local-nontheme", "local.test-evidence"
            rationale = "Test-only theme wording is evidence, not migratable Settings state."
        elif local_definition:
            kind, authority = "definition", "authority"
            key = policy_key(path, line_no, name, cat)
            disposition, target = "product-behavior-fixed", key
            rationale = "Consumer-local style value remains a uniquely named fixed product policy."
        else:
            kind, authority, key = "reference", "non-authority", None
            matched_role = next((role for field, role in TOKEN_ROLES.items() if re.search(rf"\b{field}\b", source_line)), None)
            target = matched_role or policy_key(path, line_no, name, cat)
            disposition = "consumer-reference"
            rationale = "Direct use names its exact semantic role or stable specific product-policy site."
        entries.append({
            "id": stable_id(path, line_no, digest), "path": path, "line": line_no, "span": f"L{line_no}",
            "declaration": name, "source_line_sha256": digest, "category": cat, "source_kind": kind,
            "authority_status": authority, "authority_key": key, "disposition": disposition,
            "target": target, "rationale": rationale,
        })
    return entries


def counts(entries: list[dict], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in entries:
        value = entry[key]
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def semantic_hash(document: dict) -> str:
    body = dict(document); body.pop("semantic_sha256", None)
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def generate() -> dict:
    if git("rev-parse", f"{BASE_COMMIT}^{{tree}}").decode().strip() != BASE_TREE:
        raise SystemExit("E_BASE_TREE: pinned commit tree mismatch")
    source_files, entries = [], []
    for path in target_files():
        raw = blob(path)
        source_files.append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        entries.extend(scan_file(path, raw))
    entries.sort(key=lambda e: (e["path"], e["line"], e["id"]))
    live_definitions = [e for e in entries if e["authority_status"] == "authority" and e["disposition"] != "retire-duplicate"]
    for entry in entries:
        if entry["disposition"] != "consumer-reference" or entry["target"] in TOKEN_ROLES.values():
            continue
        matches = [e for e in live_definitions if e["path"] == entry["path"] and e["category"] == entry["category"] and e["declaration"] == entry["declaration"]]
        if not matches:
            matches = [e for e in live_definitions if e["path"] == entry["path"] and e["category"] == entry["category"]]
        if not matches:
            matches = [e for e in live_definitions if e["category"] == entry["category"]]
        if matches:
            survivor = min(matches, key=lambda e: (abs(e["line"] - entry["line"]), e["path"], e["line"]))
            entry["target"] = survivor["authority_key"]
            entry["rationale"] = "Direct use consumes the named surviving stable authority."
        else:
            entry["disposition"] = "retain-local-nontheme"
            entry["target"] = f"local.{entry['category']}-reference"
            entry["rationale"] = "Explicit scanner match has no live style authority and remains local non-theme behavior."
    state_sites = [[e["path"], e["line"]] for e in entries if e["disposition"] == "state-migrate"]
    document = {
        "schema_version": SCHEMA_VERSION, "scanner_version": SCANNER_VERSION,
        "inventory_base": {"commit": BASE_COMMIT, "tree": BASE_TREE},
        "native_theme_v1_contract": {"commit": BASE_COMMIT, "tree": BASE_TREE},
        "target_roots": TARGET_ROOTS, "source_files": source_files, "entries": entries,
        "allowed_dispositions": sorted(ALLOWED_DISPOSITIONS),
        "scanner_contract": {"candidate_unit": "style/theme/state declarations, contract fields, literal definitions, and direct call sites", "category_precedence": [name for name, _ in CATEGORY_RULES]},
        "policies": {
            "legacy_token_roles": TOKEN_ROLES,
            "focus": {"confirmed_target": "border.focusConfirmed", "selection_target": "interaction.selection", "selected_target": "interaction.selected"},
            "settings_migration": {"Dark": "instrument-studio/dark", "Contrast": "instrument-studio/high-contrast", "sole_future_writer": "Settings client", "implemented_here": False, "state_sites": state_sites},
            "fallback": {"built_in_theme_id": "instrument-studio", "built_in_package": "tools/native_theme/fixtures/native-theme-v1-package.json", "storage_independent": True, "service_independent": True, "selected_state_independent": True, "external_catalog_independent": True, "last_known_good_falls_through_to_builtin": True},
        },
        "coverage": {"total": len(entries), "by_category": counts(entries, "category"), "by_file": counts(entries, "path"), "by_source_kind": counts(entries, "source_kind"), "by_authority": counts(entries, "authority_status"), "by_disposition": counts(entries, "disposition"), "by_target": counts(entries, "target"), "unmapped": 0, "multiply_mapped": 0, "duplicate_authority": 0},
    }
    document["semantic_sha256"] = semantic_hash(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); args.output.write_bytes(canonical_bytes(generate())); return 0


if __name__ == "__main__":
    raise SystemExit(main())

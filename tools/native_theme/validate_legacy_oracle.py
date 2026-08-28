#!/usr/bin/env python3
"""Independent stdlib validator for the exact-source legacy theme oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

BASE_COMMIT = "a781f2d52a9617b40b6e15d6fb39875954b51a28"
BASE_TREE = "6b344230b8e2979564fb10776b5ccc41ace2ab79"
ROOTS = ["overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/tokens.rs", "overlays/fuchsia/src/fuchsia-desktop/desktop_ui/src/chrome.rs", "overlays/fuchsia/src/ui/bin/tiling_wm/src/chrome.rs", "overlays/fuchsia/src/ui/bin/tiling_wm/src/main.rs", "overlays/fuchsia/src/fuchsia-desktop/browser/src", "overlays/fuchsia/src/fuchsia-desktop/files/src", "overlays/fuchsia/src/fuchsia-desktop/settings/src", "overlays/fuchsia/src/fuchsia-desktop/terminal/src"]
DISPOSITIONS = {"map-semantic", "product-behavior-fixed", "consumer-reference", "state-migrate", "retain-local-nontheme", "retire-duplicate"}
ROLES = {"panel_bg": "surface.canvas", "panel_elevated": "surface.raised", "selected_focus": "interaction.selection", "text_secondary": "text.muted", "border_muted": "border.normal", "text_primary": "text.bright", "danger": "status.danger", "ok": "status.success", "confirmed_focus": "border.focusConfirmed", "accent_secondary": "interaction.accent"}
STATE_SITES = sorted(
    [["overlays/fuchsia/src/fuchsia-desktop/settings/src/settings_core.rs", n] for n in (11, 12, 13, 24, 26, 27, 31, 33, 34, 83, 98, 100, 101, 102, 103, 107, 111, 144, 145, 156, 161, 165)]
    + [["overlays/fuchsia/src/fuchsia-desktop/settings/src/main.rs", n] for n in (221, 232, 237, 504, 509)]
)
GENERIC_TARGET = re.compile(r"^NativeThemeV1\.(?:color|typography|geometry-density|settings-state|focus|interaction|icon-asset|motion-elevation)$")
TOP = {"schema_version", "scanner_version", "inventory_base", "native_theme_v1_contract", "target_roots", "source_files", "entries", "allowed_dispositions", "scanner_contract", "policies", "coverage", "semantic_sha256"}

# These are deliberately independent patterns, not generator imports or generated expectations.
THEME_WORD = re.compile(r"focus|select|hover|press|active|pointer|keyboard|key_event|wrap_focus|color|rgba|background|accent|surface|panel|border|danger|\bok\b|font|glyph|text(?:Style|Run|_primary|_secondary)|label|caption|title|line_height|motion|duration|transition|animation|shadow|elevation|opacity|alpha|icon|asset|image|include_bytes|png|svg|width|height|size|padding|margin|gap|radius|row|column|grid|tile|layout|position|rect|density|inset|slot|AppTheme|set_theme|theme_state|selected_theme|\btheme\b|fallback|last_known|built.?in", re.I)
DECLARATION = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:const\s+)?fn|const|static|struct|enum|type)\s+[A-Za-z_][A-Za-z0-9_]*")
LOCAL = re.compile(r"^\s*let(?:\s+mut)?\s+[A-Za-z_][A-Za-z0-9_]*")
FIELD = re.compile(r"^\s*(?:pub\s+)?[A-Za-z_][A-Za-z0-9_]*\s*:\s*.+")
INVOKE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*::)*[A-Za-z_][A-Za-z0-9_]*\s*\(")
VALUE = re.compile(r"ColorRgba::new|TextStyle\s*\{|include_bytes!|\[[0-9A-Fa-fx., _-]+\]|:\s*-?[0-9]+(?:\.[0-9]+)?(?:u32|f32)?\b")


class Invalid(Exception):
    pass


def fail(code: str, message: object) -> None:
    raise Invalid(f"{code}: {message}")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE).stdout


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def safe(path: str) -> bool:
    parsed = PurePosixPath(path)
    return bool(path) and not parsed.is_absolute() and ".." not in parsed.parts and "\\" not in path


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key); yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def select_candidates(path: str, text: str) -> list[tuple[int, str]]:
    candidates = []
    for number, line in enumerate(text.splitlines(), 1):
        token = line.strip()
        if not token or token.startswith(("//", "/*", "*", "#!", "use ", "pub use ")) or token in {"{", "}", "};"}:
            continue
        state_site = [path, number] in STATE_SITES
        if state_site or (THEME_WORD.search(line) and (DECLARATION.match(line) or LOCAL.match(line) or FIELD.match(line) or INVOKE.search(line) or VALUE.search(line) or ":" in line)):
            candidates.append((number, line))
    return candidates


def stable_id(path: str, number: int, digest: str) -> str:
    return "legacy-" + hashlib.sha256(f"{path}\0{number}\0{digest}".encode()).hexdigest()[:24]


def validate(data: dict, raw: bytes) -> None:
    if set(data) != TOP: fail("E_SCHEMA", "unexpected or missing top-level fields")
    if canonical(data) != raw: fail("E_NONCANONICAL", "JSON is not canonical")
    if any(re.search(r"(?:/srv/|/home/|\\Users\\|\bbeads?\b|\bkanban\b|\bsq-[0-9]+\b)", value, re.I) for value in strings(data)): fail("E_PUBLIC_SAFETY", "private or local identifier")
    if data.get("inventory_base") != {"commit": BASE_COMMIT, "tree": BASE_TREE} or git("rev-parse", f"{BASE_COMMIT}^{{tree}}").decode().strip() != BASE_TREE: fail("E_BASE", "pinned commit/tree mismatch")
    if data.get("native_theme_v1_contract") != {"commit": BASE_COMMIT, "tree": BASE_TREE}: fail("E_CONTRACT", "wrong contract source")
    if any(not safe(path) for path in data.get("target_roots", [])): fail("E_PATH_SAFETY", "absolute or traversal path")
    if data.get("target_roots") != ROOTS: fail("E_TARGET_ROOTS", "target roots differ")
    paths = sorted(git("ls-tree", "-r", "--name-only", BASE_COMMIT, "--", *ROOTS).decode().splitlines())
    records = data.get("source_files", [])
    if [record.get("path") for record in records] != paths: fail("E_SOURCE_FILES", "source manifest differs")
    if any(not safe(path) for path in ROOTS + paths + [e.get("path", "") for e in data.get("entries", [])]): fail("E_PATH_SAFETY", "absolute or traversal path")

    expected_identity = []
    for record, path in zip(records, paths):
        source = git("show", f"{BASE_COMMIT}:{path}")
        if record.get("sha256") != hashlib.sha256(source).hexdigest() or record.get("bytes") != len(source): fail("E_FILE_HASH", path)
        for number, line in select_candidates(path, source.decode("utf-8")):
            digest = hashlib.sha256(line.encode()).hexdigest()
            expected_identity.append((path, number, digest, stable_id(path, number, digest)))
    ids = [e.get("id") for e in data["entries"]]
    if len(ids) != len(set(ids)): fail("E_DUPLICATE_ID", "stable IDs must be unique")
    actual_identity = [(e.get("path"), e.get("line"), e.get("source_line_sha256"), e.get("id")) for e in data.get("entries", [])]
    if len(actual_identity) != len(expected_identity): fail("E_CANDIDATES", "candidate count differs")
    for actual, expected in zip(actual_identity, expected_identity):
        if actual[:2] != expected[:2]: fail("E_CANDIDATES", "candidate identity differs")
        if actual[2] != expected[2]: fail("E_LINE_HASH", f"{expected[0]}:{expected[1]}")
        if actual[3] != expected[3]: fail("E_CANDIDATES", "stable candidate id differs")

    for entry in data["entries"]:
        if not isinstance(entry.get("disposition"), str) or entry.get("disposition") not in DISPOSITIONS: fail("E_DISPOSITION", entry.get("id"))
        if not entry.get("target") or not entry.get("rationale"): fail("E_MAPPING_DETAIL", entry.get("id"))
        if GENERIC_TARGET.match(entry["target"]): fail("E_GENERIC_TARGET", entry.get("id"))
        if entry.get("authority_status") not in {"authority", "non-authority"}: fail("E_AUTHORITY", entry.get("id"))
        if entry.get("authority_status") == "authority" and not entry.get("authority_key"): fail("E_AUTHORITY", entry.get("id"))
        if entry.get("disposition") == "retire-duplicate" and entry.get("target") == entry.get("authority_key"): fail("E_DUPLICATE_AUTHORITY", "retired duplicate must name survivor")

    live = [e.get("authority_key") for e in data["entries"] if e.get("authority_status") == "authority" and e.get("disposition") != "retire-duplicate"]
    if len(live) != len(set(live)): fail("E_DUPLICATE_AUTHORITY", "duplicate live authority")
    for entry in data["entries"]:
        if entry.get("disposition") == "consumer-reference" and entry.get("target") not in set(ROLES.values()) | set(live): fail("E_REFERENCE_TARGET", entry.get("id"))
    token_entries = [e for e in data["entries"] if e.get("path", "").endswith("desktop_ui/src/tokens.rs")]
    token_live = [e for e in token_entries if e.get("authority_status") == "authority" and e.get("target") in set(ROLES.values())]
    if {e.get("authority_key"): e.get("target") for e in token_live} != {role: role for role in ROLES.values()} or len(token_live) != 10 or any(e.get("disposition") != "map-semantic" for e in token_live): fail("E_TOKEN_MAPPING", "exact ten-role live mapping differs")
    fields = {e.get("declaration") for e in token_entries if e.get("source_kind") == "contract-field"}
    if fields != set(ROLES): fail("E_TOKEN_FIELDS", "legacy contract fields differ")
    if any(e.get("authority_status") == "authority" and e.get("declaration") in {"ColorRgba", "ThemeTokens", "INSTRUMENT_STUDIO_THEME"} for e in token_entries): fail("E_TOKEN_CONTAINER", "type/container cannot be authority")

    policy = data.get("policies", {})
    if policy.get("legacy_token_roles") != ROLES: fail("E_TOKEN_MAPPING", "policy mapping differs")
    focus = policy.get("focus", {})
    if focus.get("confirmed_target") != "border.focusConfirmed" or focus.get("confirmed_target") in {focus.get("selection_target"), focus.get("selected_target")}: fail("E_FOCUS_COLLAPSE", "focus must remain distinct")
    migration = policy.get("settings_migration", {})
    if migration.get("Dark") != "instrument-studio/dark" or migration.get("Contrast") != "instrument-studio/high-contrast" or migration.get("sole_future_writer") != "Settings client" or migration.get("implemented_here") is not False: fail("E_SETTINGS_MIGRATION", "invalid AppTheme mapping")
    submitted_state = [[e["path"], e["line"]] for e in data["entries"] if e.get("disposition") == "state-migrate"]
    if submitted_state != STATE_SITES or migration.get("state_sites") != STATE_SITES: fail("E_STATE_SITES", "Settings state inventory differs")
    corrupt = [e for e in data["entries"] if e.get("declaration") == "corrupt_theme_state_falls_back_to_dark_without_exposing_junk"]
    if not corrupt or any(e.get("source_kind") == "state" or e.get("disposition") == "state-migrate" for e in corrupt): fail("E_STATE_OVERBROAD", "test name misclassified")
    fallback = policy.get("fallback", {})
    required_true = ("storage_independent", "service_independent", "selected_state_independent", "external_catalog_independent", "last_known_good_falls_through_to_builtin")
    if fallback.get("built_in_theme_id") != "instrument-studio" or any(fallback.get(key) is not True for key in required_true): fail("E_FALLBACK_DEPENDENCY", "built-in fallback dependency")

    def tally(key: str) -> dict[str, int]:
        result = {}
        for entry in data["entries"]: result[entry[key]] = result.get(entry[key], 0) + 1
        return dict(sorted(result.items()))
    expected_coverage = {"total": len(expected_identity), "by_category": tally("category"), "by_file": tally("path"), "by_source_kind": tally("source_kind"), "by_authority": tally("authority_status"), "by_disposition": tally("disposition"), "by_target": tally("target"), "unmapped": 0, "multiply_mapped": 0, "duplicate_authority": 0}
    if data.get("coverage") != expected_coverage: fail("E_COVERAGE", "coverage does not close")
    if expected_coverage["by_disposition"].get("retain-local-nontheme", 0) * 2 >= len(expected_identity): fail("E_INCIDENTAL_INFLATION", "retained non-theme candidates are not a minority")
    if expected_coverage["by_authority"].get("authority", 0) < 15: fail("E_AUTHORITY_COVERAGE", "too few genuine live definitions")
    body = dict(data); claimed = body.pop("semantic_sha256", None)
    if claimed != hashlib.sha256(canonical(body)).hexdigest(): fail("E_SEMANTIC_HASH", "semantic hash mismatch")


def main() -> int:
    try:
        path = Path(sys.argv[1]); raw = path.read_bytes(); validate(json.loads(raw), raw)
    except (Invalid, OSError, json.JSONDecodeError, subprocess.CalledProcessError, KeyError, TypeError) as exc:
        print(exc, file=sys.stderr); return 1
    data = json.loads(raw)
    print(f"VALID legacy oracle: {len(data['source_files'])} files, {len(data['entries'])} candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

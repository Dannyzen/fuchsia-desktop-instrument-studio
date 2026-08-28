# NativeThemeV1 legacy migration oracle

This oracle freezes the complete legacy theme-relevant source surface at Git commit `a781f2d52a9617b40b6e15d6fb39875954b51a28` (tree `6b344230b8e2979564fb10776b5ccc41ace2ab79`). It inventories 21 files from the eight declared target roots. Scanner version 2.0.0 selects style/theme/state declarations, contract fields, literal definitions, and direct call sites. Blank lines, ordinary imports, braces, generic control flow, and comments are not candidates unless the line itself carries one of those semantic units. Exact commit-blob hashes provide complete file coverage separately from candidate coverage.

Generate and validate from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/native_theme/legacy_inventory.py --output docs/native-theme-v1-legacy-oracle.json
PYTHONDONTWRITEBYTECODE=1 python3 tools/native_theme/validate_legacy_oracle.py docs/native-theme-v1-legacy-oracle.json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test-native-theme-legacy-oracle.py
```

Both tools read committed blobs with `git show <commit>:<path>` and enumerate paths with `git ls-tree`; moving working-tree content is not an input. The validator independently repeats source discovery, blob hashing, line candidate identity, category selection, and policy checks. Canonical JSON is sorted, compact, newline-terminated, and must be byte-identical on repeated generation. The semantic SHA-256 covers the full oracle except its own field.

## Migration and fallback decisions

Confirmed focus maps only to `border.focusConfirmed`; selection remains `interaction.selection`/`interaction.selected`. Settings `AppTheme::Dark` migrates to packaged `instrument-studio/dark`, and `AppTheme::Contrast` migrates to packaged `instrument-studio/high-contrast`. A future Settings client is the sole selection writer; this inventory implements no writer or consumer changes.

The built-in default is the checked-in `tools/native_theme/fixtures/native-theme-v1-package.json`. It must boot without writable storage, a theme service, a selected-state file, or an external catalog. Last-known-good is a later service concern and falls through to this built-in package.

The `ColorRgba` and `ThemeTokens` types are containers, not live authorities. The ten legacy `ThemeTokens` color fields are contract-field definitions. Each corresponding `INSTRUMENT_STUDIO_THEME` initializer is the single live authority and maps exactly as follows: `panel_bg` → `surface.canvas`, `panel_elevated` → `surface.raised`, `selected_focus` → `interaction.selection`, `text_secondary` → `text.muted`, `border_muted` → `border.normal`, `text_primary` → `text.bright`, `danger` → `status.danger`, `ok` → `status.success`, `confirmed_focus` → `border.focusConfirmed`, and `accent_secondary` → `interaction.accent`.

Consumer-local literal definitions remain fixed under stable, repository-relative `product-policy.<category>.<declaration-id>` authorities. References name either an exact semantic role or one of those surviving authority keys. Settings state migration is limited to the enum/schema, persistence parse/serialization, stored field, mutation method, and production calls; tests, assertions, comments, and ordinary theme wording are not state authorities. Explicitly matched false positives may remain locally retained only with an individual scanner rationale. A duplicate live authority is invalid unless marked `retire-duplicate` and pointed at its survivor.

## Limits

This is documentation and validation only. It does not modify or activate shell, application, Settings, Rust, FIDL, services, persistence, Product Assembly, or live Fuchsia behavior. Changes to a target root, tracked file set, committed blob, scanner identity, mapping, authority, required policy, canonical encoding, or semantic hash fail closed with stable `E_*` diagnostics.

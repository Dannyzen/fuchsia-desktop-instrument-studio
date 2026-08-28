# NativeThemeV1 Phase 1 bounded proof

This directory contains the first reversible NativeThemeV1 proof. It is
intentionally narrower than the complete program in GitHub issue 3.

## What it proves

- The current built-in Instrument Studio Rust color constants can be quantized
  to 8-bit sRGB and emitted as a renderer-independent snapshot.
- One complete flat Base24 fixture can map to the same ten semantic color roles.
  The fixture is a clean-room hexadecimal transcription of this repository's existing `INSTRUMENT_STUDIO_THEME` constants, not a copied third-party theme.
- Semantic JSON is canonical and its SHA-256 digest is deterministic.
  The frozen proof digest is `sha256:455014e692f51a536550a1e0368b66b1758bdfb7e7037f35acc2dc570aa24051`.
- A second implementation validates exact fields, colors, exact per-profile provenance, bounds, and the semantic hash. It resolves the two repository-bound source identities and recomputes their SHA-256 digests from the actual source bytes.
- Malformed YAML, aliases, unknown or missing keys, invalid colors, oversized
  inputs, low text contrast, tampered hashes, and extra snapshot fields fail.

## Deliberate limits

This is not the general compiler. Successful compilation is restricted to the two checked-in repository sources so provenance can be independently verified. It accepts UTF-8 flat `key: value` YAML only,
with 64 KiB source, 256 tokens, 128-character identifiers, zero aliases, zero
assets, 8-bit sRGB, alpha fixed at 1.0, dark variant only, and WCAG 2.2 AA 4.5
checks for `text.bright` and `text.muted` over `surface.canvas`.

DTCG, Base16 derivation, Omarchy, general YAML, aliases, assets, typography,
geometry, motion, FIDL, runtime services, persistence, Settings, Product
Assembly, native consumers, deployment, and release remain out of scope.

## Commands

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test-native-theme-v1.py
python3 tools/native_theme/native_theme_v1.py compile-base24   --input tools/native_theme/fixtures/base24-instrument-studio.yaml   --output /tmp/native-theme-v1.json
python3 tools/native_theme/validate_native_theme_v1.py /tmp/native-theme-v1.json
```

Legacy equivalence is semantic for the ten proof roles. Float constants are
quantized with decimal half-up rounding to the nearest 8-bit channel. The test
requires identical colors and semantic hash between the Base24 and legacy paths.

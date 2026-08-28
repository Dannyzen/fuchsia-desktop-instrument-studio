# NativeThemeV1 normative and import profiles

NativeThemeV1 uses the Instrument Studio subset of **DTCG Format and Color Modules 2025.10** as its normative authoring profile. A package has primitive, stable semantic, and bounded component-adapter layers. Only stable semantic names are exposed to later runtime APIs; external palette names remain provenance-only.

## Color normalization

Canonical colors are lowercase `#rrggbbaa` encoded sRGB. The contract specifies that future DTCG adapters may accept sRGB, Display-P3, or OKLCH: convert components to linear light, transform through XYZ D65 when needed, apply the standard sRGB transfer function, clamp each out-of-gamut channel to `[0,1]`, quantize to 8-bit using round-half-up, and emit alpha the same way. **P1-C1 does not implement Display-P3 or OKLCH conversion.** Those conversion rules and fixtures are specification inputs for a later adapter, not an executable-capability claim. A clamp emits `W_COLOR_GAMUT_CLAMP`; malformed components emit `E_COLOR_COMPONENT`; unsupported executable color spaces currently emit `E_COLOR_SPACE`.

## Profiles and layers

| Profile version | Accepted layer | Required shape |
|---|---|---|
| `dtcg-2025.10-instrument-studio-v1` | primitive, semantic, component | DTCG groups/tokens and Color values |
| `base16-v1` | primitive | `base00`–`base0F` |
| `base24-v1` | primitive | Base16 plus `base10`–`base17` |
| `omarchy-colors-toml-v1` | primitive | palette-only `colors.toml`; no commands or templates |
| `native-legacy-v1` | semantic | deterministic mapping from the bounded Rust proof roles |

Tokens declared at a profile-inappropriate layer fail with `E_PROFILE_LAYER`. Unknown required profile versions fail with `E_VERSION_PROFILE`. Unknown optional metadata is allowed only under `org.constructresearch.instrumentstudio.*`.

The checked-in positive and negative fixtures are normative examples. The legacy profile and existing Base24 golden preserve the bounded proof; migration is deterministic decimal half-up quantization with its prior semantic hash retained by the proof tests.

`profile-fixture-manifest.json` is the coverage authority: it binds each profile to its type, accepted layers, variants, deterministic derivations, role map, diagnostics, positive fixtures, and expected-layer negative cases. The legacy entry covers only the P1-C1 declared proof constants and roles; it does not claim the later full consumer inventory.

## Canonical JSON and diagnostics

Canonical JSON is UTF-8, keys sorted by Unicode code point, with no insignificant whitespace or duplicate keys. Numbers are finite and use JSON's shortest normalized representation; negative zero is normalized to zero by producers. SHA-256 semantic identity is computed over exactly those canonical bytes. Stable rejection codes begin with `E_`; warnings begin with `W_`.

Limits are normative as recorded in the schema. Assets are package-relative semantic IDs, never executable, with no traversal or external lookup. Built-in IDs provide deterministic fallback.

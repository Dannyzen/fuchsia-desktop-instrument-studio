use crate::{
    DECODED_ASSET_BYTES_LIMIT, DECODED_ASSETS_TOTAL_BYTES_LIMIT, SEMANTIC_ASSET_LIMIT, TOKEN_LIMIT,
    ThemeError, reject,
};
use serde_json::{Map, Value};

const ROOT_FIELDS: &[&str] = &[
    "schema_version",
    "profile",
    "theme",
    "metadata",
    "variants",
    "fallback",
    "policy",
];
const VARIANT_FIELDS: &[&str] = &[
    "primitives",
    "semantic",
    "components",
    "typography",
    "geometry",
    "elevation",
    "opacity",
    "motion",
    "assets",
    "terminal",
];
const REQUIRED_VARIANTS: &[&str] = &["light", "dark", "high-contrast"];
const SEMANTIC_ROLES: &[&str] = &[
    "surface.canvas",
    "surface.deep",
    "surface.sunken",
    "surface.base",
    "surface.raised",
    "surface.overlay",
    "text.muted",
    "text.subtle",
    "text.normal",
    "text.strong",
    "text.bright",
    "text.inverse",
    "text.disabled",
    "border.subtle",
    "border.normal",
    "border.strong",
    "border.active",
    "border.focusConfirmed",
    "interaction.accent",
    "interaction.hover",
    "interaction.pressed",
    "interaction.selection",
    "interaction.selected",
    "interaction.disabled",
    "status.info",
    "status.success",
    "status.warning",
    "status.danger",
    "window.active",
    "window.inactive",
    "window.urgent",
    "terminal.background",
    "terminal.foreground",
    "terminal.cursor",
    "terminal.selection",
];
const TYPOGRAPHY_ROLES: &[&str] = &["caption", "label", "body", "title", "data-display"];
const ANSI_ROLES: &[&str] = &[
    "ansi0", "ansi1", "ansi2", "ansi3", "ansi4", "ansi5", "ansi6", "ansi7", "ansi8", "ansi9",
    "ansi10", "ansi11", "ansi12", "ansi13", "ansi14", "ansi15",
];

pub(crate) fn validate_package(value: &Value) -> Result<(), ThemeError> {
    let root = exact_object(
        value,
        ROOT_FIELDS,
        "E_FIELD_REQUIRED",
        "package root is incomplete",
    )?;
    if root.get("schema_version").and_then(Value::as_str) != Some("1.0.0") {
        return reject("E_VERSION_REQUIRED", "unsupported schema version");
    }
    validate_profile(required(root, "profile")?)?;
    validate_theme(required(root, "theme")?)?;
    validate_metadata(required(root, "metadata")?)?;
    validate_fallback(required(root, "fallback")?)?;
    validate_policy(required(root, "policy")?)?;

    let variants = exact_object(
        required(root, "variants")?,
        REQUIRED_VARIANTS,
        "E_VARIANT_REQUIRED",
        "light, dark, and high-contrast variants are required",
    )?;
    let mut token_count = 0usize;
    let mut decoded_assets_total = 0.0f64;
    for name in REQUIRED_VARIANTS {
        let (tokens, decoded) = validate_variant(name, required(variants, name)?)?;
        token_count += tokens;
        decoded_assets_total += decoded;
    }
    if token_count > TOKEN_LIMIT {
        return reject("E_LIMIT_TOKENS", "token count exceeds 1024");
    }
    if decoded_assets_total > DECODED_ASSETS_TOTAL_BYTES_LIMIT as f64 {
        return reject("E_LIMIT_ASSETS_TOTAL", "decoded asset total exceeds 4 MiB");
    }
    Ok(())
}

fn validate_profile(value: &Value) -> Result<(), ThemeError> {
    let profile = exact_object(
        value,
        &["name", "version"],
        "E_VERSION_PROFILE",
        "normative profile is incomplete",
    )?;
    if profile.get("name").and_then(Value::as_str) != Some("instrument-studio-dtcg-subset")
        || profile.get("version").and_then(Value::as_str) != Some("2025.10")
    {
        return reject("E_VERSION_PROFILE", "unsupported normative profile");
    }
    Ok(())
}

fn validate_theme(value: &Value) -> Result<(), ThemeError> {
    let theme = exact_object(
        value,
        &["id", "display_name", "revision"],
        "E_IDENTITY",
        "theme identity is incomplete",
    )?;
    for field in ["id", "display_name"] {
        if theme
            .get(field)
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
        {
            return reject("E_IDENTITY", "theme identity must use non-empty strings");
        }
    }
    if theme.get("revision").and_then(Value::as_u64).is_none() {
        return reject(
            "E_IDENTITY",
            "theme revision must be a non-negative integer",
        );
    }
    Ok(())
}

fn validate_metadata(value: &Value) -> Result<(), ThemeError> {
    let metadata = exact_object(
        value,
        &["license", "provenance", "extensions"],
        "E_METADATA_REQUIRED",
        "metadata is incomplete",
    )?;
    let license = exact_object(
        required(metadata, "license")?,
        &["spdx", "notice"],
        "E_LICENSE",
        "license metadata is incomplete",
    )?;
    if license
        .values()
        .any(|entry| entry.as_str().is_none_or(str::is_empty))
    {
        return reject("E_LICENSE", "SPDX identifier and notice are required");
    }

    let extensions = object(
        required(metadata, "extensions")?,
        "E_EXTENSION_NAMESPACE",
        "extensions must be an object",
    )?;
    if extensions
        .keys()
        .any(|key| !key.starts_with("org.constructresearch.instrumentstudio."))
    {
        return reject(
            "E_EXTENSION_NAMESPACE",
            "extension key is outside the reserved namespace",
        );
    }
    validate_provenance(required(metadata, "provenance")?)
}

fn validate_provenance(value: &Value) -> Result<(), ThemeError> {
    let provenance = exact_object(
        value,
        &[
            "source_format",
            "profile_version",
            "source_identity",
            "content_hash",
            "compiler_version",
            "semantic_hash",
            "license",
            "attribution",
            "tokens",
        ],
        "E_PROVENANCE",
        "provenance is incomplete",
    )?;
    for field in [
        "source_format",
        "profile_version",
        "compiler_version",
        "license",
        "attribution",
    ] {
        if provenance
            .get(field)
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
        {
            return reject("E_PROVENANCE", "provenance strings must be non-empty");
        }
    }
    for field in ["content_hash", "semantic_hash"] {
        if !is_sha256(provenance.get(field).and_then(Value::as_str)) {
            return reject("E_PROVENANCE", "provenance hash is malformed");
        }
    }
    let Some(identity) = provenance.get("source_identity").and_then(Value::as_str) else {
        return reject("E_IDENTITY", "source identity must be a string");
    };
    if identity.is_empty()
        || identity.starts_with('/')
        || identity.starts_with("http://")
        || identity.starts_with("https://")
        || identity.contains('\\')
        || identity.split('/').any(|part| part == "..")
    {
        return reject(
            "E_IDENTITY",
            "source identity violates repository-relative policy",
        );
    }
    let tokens = object(
        required(provenance, "tokens")?,
        "E_PROVENANCE",
        "token provenance must be an object",
    )?;
    for token in tokens.values() {
        let record = object(
            token,
            "E_PROVENANCE",
            "token provenance record must be an object",
        )?;
        if record
            .keys()
            .any(|key| !["kind", "source_token", "derivation"].contains(&key.as_str()))
            || !record.contains_key("kind")
            || !record.contains_key("source_token")
        {
            return reject(
                "E_PROVENANCE",
                "token provenance record has an invalid shape",
            );
        }
        if !matches!(
            record.get("kind").and_then(Value::as_str),
            Some("explicit" | "inherited" | "derived")
        ) || record
            .get("source_token")
            .and_then(Value::as_str)
            .is_none_or(str::is_empty)
            || record
                .get("derivation")
                .is_some_and(|entry| entry.as_str().is_none_or(str::is_empty))
        {
            return reject("E_PROVENANCE", "per-token provenance is invalid");
        }
    }
    Ok(())
}

fn validate_fallback(value: &Value) -> Result<(), ThemeError> {
    let fallback = exact_object(
        value,
        &[
            "built_in_theme_id",
            "missing_asset",
            "missing_token",
            "last_known_good",
            "storage_independent",
        ],
        "E_FALLBACK_REQUIRED",
        "fallback policy is incomplete",
    )?;
    if fallback
        .get("built_in_theme_id")
        .and_then(Value::as_str)
        .is_none_or(str::is_empty)
        || fallback.get("missing_asset").and_then(Value::as_str) != Some("builtin")
        || fallback.get("missing_token").and_then(Value::as_str) != Some("fail")
        || fallback.get("storage_independent") != Some(&Value::Bool(true))
    {
        return reject("E_FALLBACK_REQUIRED", "fallback policy is incomplete");
    }
    let last_known_good = exact_object(
        required(fallback, "last_known_good")?,
        &["identity", "required"],
        "E_FALLBACK_REQUIRED",
        "last-known-good policy is incomplete",
    )?;
    if last_known_good.get("identity").and_then(Value::as_str) != Some("semantic-hash")
        || last_known_good.get("required") != Some(&Value::Bool(true))
    {
        return reject(
            "E_FALLBACK_REQUIRED",
            "last-known-good must use semantic identity",
        );
    }
    Ok(())
}

fn validate_policy(value: &Value) -> Result<(), ThemeError> {
    let policy = exact_object(
        value,
        &[
            "activation",
            "compatibility",
            "compiler",
            "executable_content",
            "no_animation_required_for_correctness",
            "snapshot",
            "unknown_optional_metadata",
            "unknown_required_version",
        ],
        "E_COMPATIBILITY",
        "compatibility policy is incomplete",
    )?;
    let expected = [
        ("activation", "restart"),
        ("compiler", "host"),
        ("executable_content", "forbidden"),
        ("snapshot", "immutable"),
        ("unknown_optional_metadata", "allow-additive"),
        ("unknown_required_version", "fail-closed"),
    ];
    if expected
        .iter()
        .any(|(key, expected)| policy.get(*key).and_then(Value::as_str) != Some(*expected))
        || policy.get("no_animation_required_for_correctness") != Some(&Value::Bool(true))
    {
        return reject(
            "E_COMPATIBILITY",
            "required compatibility policy is not fail-closed",
        );
    }
    let compatibility = exact_object(
        required(policy, "compatibility")?,
        &["current", "previous", "window"],
        "E_COMPATIBILITY",
        "compatibility window is incomplete",
    )?;
    if compatibility.get("current").and_then(Value::as_str) != Some("1.0.0")
        || compatibility.get("previous").and_then(Value::as_str) != Some("0.x")
        || compatibility.get("window").and_then(Value::as_str) != Some("N/N-1")
    {
        return reject("E_COMPATIBILITY", "compatibility window must be N/N-1");
    }
    Ok(())
}

fn validate_variant(name: &str, value: &Value) -> Result<(usize, f64), ThemeError> {
    let variant = exact_object(
        value,
        VARIANT_FIELDS,
        "E_DOMAIN_REQUIRED",
        "variant domains are incomplete",
    )?;
    let primitives = nonempty_object(
        required(variant, "primitives")?,
        "E_LAYER_REQUIRED",
        "primitive layer is empty",
    )?;
    for color in primitives.values() {
        require_color(color)?;
    }
    let semantic = exact_object(
        required(variant, "semantic")?,
        SEMANTIC_ROLES,
        "E_SEMANTIC_ROLES",
        "semantic taxonomy is incomplete",
    )?;
    for color in semantic.values() {
        require_color(color)?;
    }
    let components = nonempty_object(
        required(variant, "components")?,
        "E_LAYER_REQUIRED",
        "component layer is empty",
    )?;
    for (token, value) in components {
        if token.ends_with("color") || value.as_str().is_some_and(|entry| entry.starts_with('#')) {
            require_color(value)?;
        }
    }
    validate_terminal(required(variant, "terminal")?)?;
    let decoded_assets = validate_assets(required(variant, "assets")?)?;
    validate_typography(required(variant, "typography")?)?;
    validate_geometry(required(variant, "geometry")?)?;
    validate_elevation(required(variant, "elevation")?)?;
    validate_opacity(required(variant, "opacity")?)?;
    validate_motion(required(variant, "motion")?)?;
    validate_contrast(name, semantic)?;
    Ok((
        primitives.len() + semantic.len() + components.len(),
        decoded_assets,
    ))
}

fn validate_terminal(value: &Value) -> Result<(), ThemeError> {
    let terminal = exact_object(
        value,
        ANSI_ROLES,
        "E_TERMINAL_ANSI",
        "exact ANSI 0 through 15 palette is required",
    )?;
    for color in terminal.values() {
        require_color(color).map_err(|_| ThemeError {
            code: "E_TERMINAL_ANSI",
            message: "terminal colors must use lowercase rgba strings",
        })?;
    }
    Ok(())
}

fn validate_assets(value: &Value) -> Result<f64, ThemeError> {
    let assets = exact_object(
        value,
        &["items", "fallback"],
        "E_ASSET_METADATA",
        "asset domain is incomplete",
    )?;
    if assets.get("fallback").and_then(Value::as_str) != Some("builtin-semantic-icon") {
        return reject("E_ASSET_METADATA", "asset fallback is invalid");
    }
    let items = object(
        required(assets, "items")?,
        "E_ASSET_METADATA",
        "asset items must be an object",
    )?;
    if items.len() > SEMANTIC_ASSET_LIMIT {
        return reject("E_LIMIT_ASSETS", "semantic asset count exceeds 64");
    }
    if !items.contains_key("status.error") {
        return reject(
            "E_STATUS_NONCOLOR",
            "status.error semantic asset is required",
        );
    }
    let mut decoded_total = 0.0;
    for asset in items.values() {
        let asset = exact_object(
            asset,
            &[
                "path",
                "kind",
                "variants",
                "width",
                "height",
                "decoded_bytes",
                "spdx",
                "attribution",
            ],
            "E_ASSET_METADATA",
            "asset metadata is incomplete",
        )?;
        if !matches!(
            asset.get("kind").and_then(Value::as_str),
            Some("svg" | "png")
        ) {
            return reject("E_ASSET_METADATA", "asset kind is unsupported");
        }
        let Some(path) = asset.get("path").and_then(Value::as_str) else {
            return reject("E_ASSET_PATH", "asset path must be a string");
        };
        if path.is_empty()
            || path.starts_with('/')
            || path.contains('\\')
            || path.contains("://")
            || path.split('/').any(|part| part == "..")
        {
            return reject("E_ASSET_PATH", "asset path must be package-relative");
        }
        for field in ["spdx", "attribution"] {
            if asset
                .get(field)
                .and_then(Value::as_str)
                .is_none_or(str::is_empty)
            {
                return reject("E_ASSET_METADATA", "asset license metadata is required");
            }
        }
        number_between(
            asset.get("width"),
            1.0,
            4096.0,
            "E_ASSET_METADATA",
            "asset width is out of bounds",
        )?;
        number_between(
            asset.get("height"),
            1.0,
            4096.0,
            "E_ASSET_METADATA",
            "asset height is out of bounds",
        )?;
        let decoded = number_between(
            asset.get("decoded_bytes"),
            1.0,
            DECODED_ASSET_BYTES_LIMIT as f64,
            "E_LIMIT_ASSET_BYTES",
            "decoded asset exceeds 512 KiB",
        )?;
        decoded_total += decoded;
        let Some(variants) = asset.get("variants").and_then(Value::as_array) else {
            return reject("E_ASSET_METADATA", "asset variants must be an array");
        };
        if variants.is_empty()
            || variants
                .iter()
                .any(|entry| !matches!(entry.as_str(), Some("light" | "dark" | "high-contrast")))
        {
            return reject("E_ASSET_METADATA", "asset variants are invalid");
        }
    }
    Ok(decoded_total)
}

fn validate_typography(value: &Value) -> Result<(), ThemeError> {
    let typography = exact_object(
        value,
        &[
            "families",
            "roles",
            "minimum_legible_px",
            "terminal_cell",
            "fallback",
        ],
        "E_TYPOGRAPHY",
        "typography domain is incomplete",
    )?;
    if typography.get("fallback").and_then(Value::as_str) != Some("builtin-system-stacks") {
        return reject("E_TYPOGRAPHY", "typography fallback is invalid");
    }
    number_between(
        typography.get("minimum_legible_px"),
        10.0,
        24.0,
        "E_TYPOGRAPHY",
        "minimum legible size is out of bounds",
    )?;
    let families = object(
        required(typography, "families")?,
        "E_TYPOGRAPHY",
        "font families must be an object",
    )?;
    if families
        .keys()
        .any(|key| !["ui", "monospace", "display"].contains(&key.as_str()))
        || !families.contains_key("ui")
        || !families.contains_key("monospace")
    {
        return reject(
            "E_TYPOGRAPHY",
            "ui and monospace family stacks are required",
        );
    }
    for stack in families.values() {
        let Some(stack) = stack.as_array() else {
            return reject("E_TYPOGRAPHY", "font family stack must be an array");
        };
        if stack.is_empty()
            || stack
                .iter()
                .any(|entry| entry.as_str().is_none_or(str::is_empty))
        {
            return reject("E_TYPOGRAPHY", "font family stack must contain names");
        }
    }
    let roles = exact_object(
        required(typography, "roles")?,
        TYPOGRAPHY_ROLES,
        "E_TYPOGRAPHY",
        "typography roles are incomplete",
    )?;
    for style in roles.values() {
        let style = exact_object(
            style,
            &[
                "family",
                "size_px",
                "line_height",
                "weight",
                "letter_spacing_em",
            ],
            "E_TYPOGRAPHY",
            "typography role is incomplete",
        )?;
        if !matches!(
            style.get("family").and_then(Value::as_str),
            Some("ui" | "monospace" | "display")
        ) {
            return reject("E_TYPOGRAPHY", "typography family selection is invalid");
        }
        number_between(
            style.get("size_px"),
            10.0,
            96.0,
            "E_TYPOGRAPHY",
            "font size is out of bounds",
        )?;
        number_between(
            style.get("line_height"),
            1.0,
            2.0,
            "E_TYPOGRAPHY",
            "line height is out of bounds",
        )?;
        number_between(
            style.get("weight"),
            100.0,
            900.0,
            "E_TYPOGRAPHY",
            "font weight is out of bounds",
        )?;
        number_between(
            style.get("letter_spacing_em"),
            -0.1,
            0.2,
            "E_TYPOGRAPHY",
            "letter spacing is out of bounds",
        )?;
    }
    let cell = exact_object(
        required(typography, "terminal_cell")?,
        &["width_px", "height_px"],
        "E_TYPOGRAPHY",
        "terminal cell is incomplete",
    )?;
    number_between(
        cell.get("width_px"),
        4.0,
        32.0,
        "E_TYPOGRAPHY",
        "terminal cell width is out of bounds",
    )?;
    number_between(
        cell.get("height_px"),
        8.0,
        64.0,
        "E_TYPOGRAPHY",
        "terminal cell height is out of bounds",
    )?;
    Ok(())
}

fn validate_geometry(value: &Value) -> Result<(), ThemeError> {
    let geometry = exact_object(
        value,
        &[
            "spacing",
            "gaps",
            "heights",
            "accent_rail_px",
            "panel",
            "radii",
            "border_widths",
            "icon_sizes",
            "minimum_hit_target_px",
            "density",
            "responsive",
        ],
        "E_GEOMETRY",
        "geometry domain is incomplete",
    )?;
    if !matches!(
        geometry.get("density").and_then(Value::as_str),
        Some("compact" | "comfortable" | "touch")
    ) {
        return reject("E_GEOMETRY", "geometry density is invalid");
    }
    for field in ["spacing", "gaps", "radii", "border_widths", "icon_sizes"] {
        if geometry.get(field).and_then(Value::as_array).is_none() {
            return reject("E_GEOMETRY", "geometry scale must be an array");
        }
    }
    exact_object(
        required(geometry, "heights")?,
        &["chrome_px", "control_px", "tile_header_px"],
        "E_GEOMETRY",
        "geometry heights are incomplete",
    )?;
    exact_object(
        required(geometry, "panel")?,
        &["inset_px", "max_width_px", "min_width_px"],
        "E_GEOMETRY",
        "panel geometry is incomplete",
    )?;
    number_between(
        geometry.get("accent_rail_px"),
        1.0,
        8.0,
        "E_GEOMETRY",
        "accent rail is out of bounds",
    )?;
    number_between(
        geometry.get("minimum_hit_target_px"),
        24.0,
        64.0,
        "E_GEOMETRY",
        "minimum hit target is out of bounds",
    )?;
    let responsive = exact_object(
        required(geometry, "responsive")?,
        &["narrow_max_px", "regular_max_px", "wide_min_px"],
        "E_GEOMETRY",
        "responsive thresholds are incomplete",
    )?;
    if responsive.get("narrow_max_px").and_then(Value::as_u64) != Some(719)
        || responsive.get("regular_max_px").and_then(Value::as_u64) != Some(1199)
        || responsive.get("wide_min_px").and_then(Value::as_u64) != Some(1200)
    {
        return reject(
            "E_GEOMETRY",
            "responsive thresholds differ from product constants",
        );
    }
    Ok(())
}

fn validate_elevation(value: &Value) -> Result<(), ThemeError> {
    let elevation = exact_object(
        value,
        &["levels"],
        "E_ELEVATION",
        "elevation domain is incomplete",
    )?;
    let levels = exact_object(
        required(elevation, "levels")?,
        &["flat", "raised", "overlay"],
        "E_ELEVATION",
        "elevation levels are incomplete",
    )?;
    for shadow in levels.values() {
        let shadow = exact_object(
            shadow,
            &["x_px", "y_px", "blur_px", "spread_px", "color"],
            "E_ELEVATION",
            "shadow is incomplete",
        )?;
        for field in ["x_px", "y_px", "spread_px"] {
            number(
                shadow.get(field),
                "E_ELEVATION",
                "shadow coordinate must be numeric",
            )?;
        }
        number_between(
            shadow.get("blur_px"),
            0.0,
            64.0,
            "E_ELEVATION",
            "shadow blur is out of bounds",
        )?;
        require_color(required(shadow, "color")?)?;
    }
    Ok(())
}

fn validate_opacity(value: &Value) -> Result<(), ThemeError> {
    let opacity = exact_object(
        value,
        &["disabled", "overlay"],
        "E_OPACITY",
        "opacity domain is incomplete",
    )?;
    for entry in opacity.values() {
        number_between(
            Some(entry),
            0.0,
            1.0,
            "E_OPACITY",
            "opacity is out of bounds",
        )?;
    }
    Ok(())
}

fn validate_motion(value: &Value) -> Result<(), ThemeError> {
    let motion = exact_object(
        value,
        &["durations_ms", "easing", "reduced"],
        "E_MOTION",
        "motion domain is incomplete",
    )?;
    let durations = exact_object(
        required(motion, "durations_ms")?,
        &["short", "medium", "long"],
        "E_MOTION",
        "motion durations are incomplete",
    )?;
    for duration in durations.values() {
        number_between(
            Some(duration),
            0.0,
            1000.0,
            "E_MOTION",
            "motion duration is out of bounds",
        )?;
    }
    let easing = exact_object(
        required(motion, "easing")?,
        &["standard", "emphasized"],
        "E_MOTION",
        "motion easing is incomplete",
    )?;
    if easing.values().any(|curve| {
        curve.as_array().is_none_or(|entries| {
            entries.iter().any(|entry| {
                number(Some(entry), "E_MOTION", "easing value must be numeric").is_err()
            })
        })
    }) {
        return reject("E_MOTION", "motion easing curve is invalid");
    }
    let reduced = exact_object(
        required(motion, "reduced")?,
        &["duration_ms", "substitution", "essential_only"],
        "E_REDUCED_MOTION",
        "reduced motion policy is incomplete",
    )?;
    if reduced.get("duration_ms").and_then(Value::as_u64) != Some(0)
        || reduced.get("substitution").and_then(Value::as_str) != Some("instant")
        || reduced.get("essential_only") != Some(&Value::Bool(true))
    {
        return reject("E_REDUCED_MOTION", "reduced motion must be deterministic");
    }
    Ok(())
}

fn validate_contrast(variant: &str, semantic: &Map<String, Value>) -> Result<(), ThemeError> {
    let foreground = semantic["text.normal"].as_str().expect("validated color");
    let background = semantic["surface.canvas"]
        .as_str()
        .expect("validated color");
    let focus = semantic["border.focusConfirmed"]
        .as_str()
        .expect("validated color");
    let selection = semantic["interaction.selection"]
        .as_str()
        .expect("validated color");
    if focus == selection {
        return reject(
            "E_FOCUS_DISTINCT",
            "confirmed focus and selection must differ",
        );
    }
    let text_target = if variant == "high-contrast" { 7.0 } else { 4.5 };
    let ui_target = if variant == "high-contrast" { 4.5 } else { 3.0 };
    if contrast(foreground, background) < text_target {
        return reject("E_CONTRAST_NORMAL", "normal text contrast is below target");
    }
    if contrast(focus, background) < ui_target {
        return reject("E_CONTRAST_UI", "focus contrast is below target");
    }
    if contrast(selection, background) < ui_target {
        return reject("E_CONTRAST_SELECTION", "selection contrast is below target");
    }
    Ok(())
}

fn contrast(first: &str, second: &str) -> f64 {
    let first = luminance(first);
    let second = luminance(second);
    let (high, low) = if first >= second {
        (first, second)
    } else {
        (second, first)
    };
    (high + 0.05) / (low + 0.05)
}

fn luminance(color: &str) -> f64 {
    let channel = |offset: usize| {
        let value = u8::from_str_radix(&color[offset..offset + 2], 16).expect("validated color")
            as f64
            / 255.0;
        if value <= 0.04045 {
            value / 12.92
        } else {
            ((value + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

fn require_color(value: &Value) -> Result<(), ThemeError> {
    if value.as_str().is_none_or(|color| {
        let bytes = color.as_bytes();
        bytes.len() != 9
            || bytes[0] != b'#'
            || bytes[1..]
                .iter()
                .any(|byte| !matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    }) {
        return reject(
            "E_COLOR_CANONICAL",
            "color must be lowercase #rrggbbaa sRGB",
        );
    }
    Ok(())
}

fn exact_object<'a>(
    value: &'a Value,
    fields: &[&str],
    missing_code: &'static str,
    missing_message: &'static str,
) -> Result<&'a Map<String, Value>, ThemeError> {
    let object = object(value, missing_code, missing_message)?;
    if object.keys().any(|key| !fields.contains(&key.as_str())) {
        return reject("E_FIELD_FORBIDDEN", "unknown structural field");
    }
    if fields.iter().any(|field| !object.contains_key(*field)) {
        return reject(missing_code, missing_message);
    }
    Ok(object)
}

fn nonempty_object<'a>(
    value: &'a Value,
    code: &'static str,
    message: &'static str,
) -> Result<&'a Map<String, Value>, ThemeError> {
    let value = object(value, code, message)?;
    if value.is_empty() {
        return reject(code, message);
    }
    Ok(value)
}

fn object<'a>(
    value: &'a Value,
    code: &'static str,
    message: &'static str,
) -> Result<&'a Map<String, Value>, ThemeError> {
    value.as_object().ok_or(ThemeError { code, message })
}

fn required<'a>(object: &'a Map<String, Value>, field: &str) -> Result<&'a Value, ThemeError> {
    object.get(field).ok_or(ThemeError {
        code: "E_FIELD_REQUIRED",
        message: "required field is missing",
    })
}

fn number(
    value: Option<&Value>,
    code: &'static str,
    message: &'static str,
) -> Result<f64, ThemeError> {
    value
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .ok_or(ThemeError { code, message })
}

fn number_between(
    value: Option<&Value>,
    low: f64,
    high: f64,
    code: &'static str,
    message: &'static str,
) -> Result<f64, ThemeError> {
    let value = number(value, code, message)?;
    if value < low || value > high {
        return reject(code, message);
    }
    Ok(value)
}

fn is_sha256(value: Option<&str>) -> bool {
    value.is_some_and(|hash| {
        hash.len() == 71
            && hash.starts_with("sha256:")
            && hash[7..]
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    })
}

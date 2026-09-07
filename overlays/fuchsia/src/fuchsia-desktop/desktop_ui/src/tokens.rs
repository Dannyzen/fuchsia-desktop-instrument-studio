// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Visual tokens for Instrument Studio.
//!
//! Values track design/sketches/01-instrument-studio (near-black panels,
//! cyan confirmed-focus, violet secondary).

use serde_json::Value;
use std::error::Error;
use std::fmt;
use theme_model::NativeThemeV1;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ColorRgba {
    pub red: f32,
    pub green: f32,
    pub blue: f32,
    pub alpha: f32,
}

impl ColorRgba {
    pub const fn new(red: f32, green: f32, blue: f32, alpha: f32) -> Self {
        Self { red, green, blue, alpha }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ThemeAdapterError {
    InvalidPackage,
    IdentityMismatch,
    MissingVariant,
    MissingSemanticRole(&'static str),
    InvalidColor(&'static str),
}

impl fmt::Display for ThemeAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidPackage => write!(formatter, "invalid canonical NativeThemeV1 package"),
            Self::IdentityMismatch => write!(formatter, "snapshot identity does not match canonical bytes"),
            Self::MissingVariant => write!(formatter, "requested NativeThemeV1 variant is absent"),
            Self::MissingSemanticRole(role) => write!(formatter, "missing semantic role {role}"),
            Self::InvalidColor(role) => write!(formatter, "semantic role {role} is not #RRGGBBAA"),
        }
    }
}

impl Error for ThemeAdapterError {}

const BUILTIN_NATIVE_THEME_PACKAGE: &[u8] = include_bytes!(
    "../../theme_catalog/catalog/instrument-studio-dtcg.package.json"
);

#[derive(Clone, Debug, PartialEq)]
pub struct ResolvedThemeSnapshot {
    pub tokens: ThemeTokens,
    pub theme_id: String,
    pub variant: String,
    pub semantic_sha256: [u8; 32],
}

impl ResolvedThemeSnapshot {
    pub fn from_canonical_snapshot(
        canonical_package: &[u8],
        expected_theme_id: &str,
        variant: &str,
        expected_semantic_sha256: [u8; 32],
    ) -> Result<Self, ThemeAdapterError> {
        let theme = NativeThemeV1::decode_canonical(canonical_package)
            .map_err(|_| ThemeAdapterError::InvalidPackage)?;
        if theme.theme_id() != expected_theme_id
            || theme.semantic_sha256() != expected_semantic_sha256
        {
            return Err(ThemeAdapterError::IdentityMismatch);
        }
        Ok(Self {
            tokens: ThemeTokens::from_native_theme(&theme, variant)?,
            theme_id: theme.theme_id().to_string(),
            variant: variant.to_string(),
            semantic_sha256: theme.semantic_sha256(),
        })
    }

    pub fn built_in() -> Self {
        let theme = NativeThemeV1::decode_canonical(BUILTIN_NATIVE_THEME_PACKAGE)
            .expect("checked-in built-in NativeThemeV1 must remain canonical");
        Self {
            tokens: ThemeTokens::from_native_theme(&theme, "dark")
                .expect("checked-in built-in NativeThemeV1 must contain dark semantic roles"),
            theme_id: theme.theme_id().to_string(),
            variant: "dark".to_string(),
            semantic_sha256: theme.semantic_sha256(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ThemeTokens {
    pub panel_bg: ColorRgba,
    pub panel_elevated: ColorRgba,
    pub border_muted: ColorRgba,
    pub text_primary: ColorRgba,
    pub text_secondary: ColorRgba,
    pub confirmed_focus: ColorRgba,
    pub selected_focus: ColorRgba,
    pub accent_secondary: ColorRgba,
    pub danger: ColorRgba,
    pub ok: ColorRgba,
    pub gap_px: u32,
    pub active_border_px: u32,
    pub panel_height_px: u32,
    pub rail_width_px: u32,
    pub inspector_height_px: u32,
}

impl ThemeTokens {
    pub fn from_canonical_package(
        canonical_package: &[u8],
        variant: &str,
    ) -> Result<Self, ThemeAdapterError> {
        let theme = NativeThemeV1::decode_canonical(canonical_package)
            .map_err(|_| ThemeAdapterError::InvalidPackage)?;
        Self::from_native_theme(&theme, variant)
    }

    pub fn from_canonical_snapshot(
        canonical_package: &[u8],
        expected_theme_id: &str,
        variant: &str,
        expected_semantic_sha256: [u8; 32],
    ) -> Result<Self, ThemeAdapterError> {
        Ok(ResolvedThemeSnapshot::from_canonical_snapshot(
            canonical_package,
            expected_theme_id,
            variant,
            expected_semantic_sha256,
        )?
        .tokens)
    }

    pub fn from_native_theme(
        theme: &NativeThemeV1,
        variant: &str,
    ) -> Result<Self, ThemeAdapterError> {
        let semantic = theme
            .variant(variant)
            .and_then(|value| value.get("semantic"))
            .and_then(Value::as_object)
            .ok_or(ThemeAdapterError::MissingVariant)?;
        Ok(Self {
            panel_bg: semantic_color(semantic, "surface.canvas")?,
            panel_elevated: semantic_color(semantic, "surface.raised")?,
            border_muted: semantic_color(semantic, "border.normal")?,
            text_primary: semantic_color(semantic, "text.bright")?,
            text_secondary: semantic_color(semantic, "text.muted")?,
            confirmed_focus: semantic_color(semantic, "border.focusConfirmed")?,
            selected_focus: semantic_color(semantic, "interaction.selection")?,
            accent_secondary: semantic_color(semantic, "interaction.accent")?,
            danger: semantic_color(semantic, "status.danger")?,
            ok: semantic_color(semantic, "status.success")?,
            ..INSTRUMENT_STUDIO_THEME
        })
    }
}

fn semantic_color(
    semantic: &serde_json::Map<String, Value>,
    role: &'static str,
) -> Result<ColorRgba, ThemeAdapterError> {
    let encoded = semantic
        .get(role)
        .and_then(Value::as_str)
        .ok_or(ThemeAdapterError::MissingSemanticRole(role))?;
    parse_rgba(encoded).ok_or(ThemeAdapterError::InvalidColor(role))
}

fn parse_rgba(encoded: &str) -> Option<ColorRgba> {
    if encoded.len() != 9 || !encoded.starts_with('#') {
        return None;
    }
    let channel = |offset| u8::from_str_radix(&encoded[offset..offset + 2], 16).ok();
    Some(ColorRgba::new(
        channel(1)? as f32 / 255.0,
        channel(3)? as f32 / 255.0,
        channel(5)? as f32 / 255.0,
        channel(7)? as f32 / 255.0,
    ))
}

/// Canonical Instrument Studio theme.
pub const INSTRUMENT_STUDIO_THEME: ThemeTokens = ThemeTokens {
    // near-black panels
    panel_bg: ColorRgba::new(0.07, 0.08, 0.10, 1.0),
    panel_elevated: ColorRgba::new(0.10, 0.12, 0.16, 1.0),
    border_muted: ColorRgba::new(0.20, 0.23, 0.28, 1.0),
    text_primary: ColorRgba::new(0.93, 0.95, 0.98, 1.0),
    text_secondary: ColorRgba::new(0.66, 0.70, 0.78, 1.0),
    // cyan confirmed focus (matches tiling_wm active ring)
    confirmed_focus: ColorRgba::new(0.0, 0.82, 1.0, 1.0),
    selected_focus: ColorRgba::new(0.45, 0.55, 0.72, 1.0),
    // violet secondary
    accent_secondary: ColorRgba::new(0.62, 0.40, 0.98, 1.0),
    danger: ColorRgba::new(0.95, 0.35, 0.40, 1.0),
    ok: ColorRgba::new(0.30, 0.85, 0.55, 1.0),
    gap_px: 12,
    active_border_px: 3,
    panel_height_px: 48,
    rail_width_px: 72,
    inspector_height_px: 160,
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirmed_focus_is_cyan_not_selected_gray() {
        let t = INSTRUMENT_STUDIO_THEME;
        assert!(t.confirmed_focus.green > 0.7);
        assert!(t.confirmed_focus.blue > 0.9);
        assert_ne!(t.confirmed_focus, t.selected_focus);
    }
}

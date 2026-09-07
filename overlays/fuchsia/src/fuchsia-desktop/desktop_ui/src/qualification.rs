// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use desktop_ui::{
    ColorRgba, INSTRUMENT_STUDIO_THEME, InstrumentStudioLayout, ResolvedThemeSnapshot,
    ThemeAdapterError, ThemeTokens,
};
use theme_model::NativeThemeV1;

const CANONICAL_PACKAGE: &[u8] =
    include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json");

#[test]
fn canonical_dark_snapshot_maps_the_oracle_semantic_roles() {
    let t = ThemeTokens::from_canonical_package(CANONICAL_PACKAGE, "dark").unwrap();
    assert_eq!(
        t.panel_bg,
        ColorRgba::new(
            0x12 as f32 / 255.0,
            0x14 as f32 / 255.0,
            0x1a as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.panel_elevated,
        ColorRgba::new(
            0x1a as f32 / 255.0,
            0x1f as f32 / 255.0,
            0x29 as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.confirmed_focus,
        ColorRgba::new(0.0, 0xd1 as f32 / 255.0, 1.0, 1.0)
    );
    assert_eq!(
        t.selected_focus,
        ColorRgba::new(
            0x81 as f32 / 255.0,
            0x50 as f32 / 255.0,
            0xd6 as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.border_muted,
        ColorRgba::new(
            0x73 as f32 / 255.0,
            0x8c as f32 / 255.0,
            0xb8 as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(t.text_primary, ColorRgba::new(1.0, 1.0, 1.0, 1.0));
    assert_eq!(
        t.text_secondary,
        ColorRgba::new(
            0xa8 as f32 / 255.0,
            0xb3 as f32 / 255.0,
            0xc7 as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.accent_secondary,
        ColorRgba::new(
            0x9e as f32 / 255.0,
            0x66 as f32 / 255.0,
            0xfa as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.danger,
        ColorRgba::new(
            0xf2 as f32 / 255.0,
            0x59 as f32 / 255.0,
            0x66 as f32 / 255.0,
            1.0
        )
    );
    assert_eq!(
        t.ok,
        ColorRgba::new(
            0x4d as f32 / 255.0,
            0xd9 as f32 / 255.0,
            0x8c as f32 / 255.0,
            1.0
        )
    );
    assert_ne!(t.confirmed_focus, t.selected_focus);
    assert_eq!(t.gap_px, INSTRUMENT_STUDIO_THEME.gap_px);
    assert_eq!(t.panel_height_px, INSTRUMENT_STUDIO_THEME.panel_height_px);
}

#[test]
fn responsive_layout_preserves_the_supplied_runtime_theme() {
    let tokens = ThemeTokens::from_canonical_package(CANONICAL_PACKAGE, "high-contrast").unwrap();
    let layout = InstrumentStudioLayout::with_theme(720, 1200, tokens).unwrap();
    assert_eq!(
        layout.theme.confirmed_focus,
        ColorRgba::new(1.0, 1.0, 0.0, 1.0)
    );
    assert_eq!(
        layout.theme.selected_focus,
        ColorRgba::new(0x65 as f32 / 255.0, 1.0, 1.0, 1.0)
    );
    assert_eq!(layout.theme.rail_width_px, 56);
}

#[test]
fn canonical_snapshot_rejects_identity_that_does_not_match_its_bytes() {
    let theme = NativeThemeV1::decode_canonical(CANONICAL_PACKAGE).unwrap();
    let mut wrong_hash = theme.semantic_sha256();
    wrong_hash[0] ^= 0xff;
    let error = ThemeTokens::from_canonical_snapshot(
        CANONICAL_PACKAGE,
        theme.theme_id(),
        "dark",
        wrong_hash,
    )
    .unwrap_err();
    assert_eq!(error, ThemeAdapterError::IdentityMismatch);
}

#[test]
fn built_in_snapshot_uses_the_checked_in_canonical_package() {
    let resolved = ResolvedThemeSnapshot::built_in();
    let decoded = NativeThemeV1::decode_canonical(CANONICAL_PACKAGE).unwrap();
    let expected = ThemeTokens::from_native_theme(&decoded, "dark").unwrap();
    assert_eq!(resolved.tokens, expected);
    assert_eq!(resolved.theme_id, decoded.theme_id());
    assert_eq!(resolved.variant, "dark");
    assert_eq!(resolved.semantic_sha256, decoded.semantic_sha256());
}

#[test]
fn invalid_package_is_rejected() {
    assert_eq!(
        ThemeTokens::from_canonical_package(b"{}", "dark").unwrap_err(),
        ThemeAdapterError::InvalidPackage
    );
}

#[test]
fn missing_variant_is_rejected() {
    assert_eq!(
        ThemeTokens::from_canonical_package(CANONICAL_PACKAGE, "sepia").unwrap_err(),
        ThemeAdapterError::MissingVariant
    );
}

fn rgba(channels: [u8; 4]) -> ColorRgba {
    ColorRgba::new(
        channels[0] as f32 / 255.0,
        channels[1] as f32 / 255.0,
        channels[2] as f32 / 255.0,
        channels[3] as f32 / 255.0,
    )
}

#[test]
fn all_variants_map_all_oracle_semantic_roles() {
    let cases = [
        (
            "light",
            [
                [0xff, 0xff, 0xff, 0xff],
                [0xff, 0xff, 0xff, 0xff],
                [0x73, 0x8c, 0xb8, 0xff],
                [0x00, 0x00, 0x00, 0xff],
                [0x47, 0x54, 0x67, 0xff],
                [0x17, 0x5c, 0xd3, 0xff],
                [0x81, 0x50, 0xd6, 0xff],
                [0x9e, 0x66, 0xfa, 0xff],
                [0xf2, 0x59, 0x66, 0xff],
                [0x4d, 0xd9, 0x8c, 0xff],
            ],
        ),
        (
            "dark",
            [
                [0x12, 0x14, 0x1a, 0xff],
                [0x1a, 0x1f, 0x29, 0xff],
                [0x73, 0x8c, 0xb8, 0xff],
                [0xff, 0xff, 0xff, 0xff],
                [0xa8, 0xb3, 0xc7, 0xff],
                [0x00, 0xd1, 0xff, 0xff],
                [0x81, 0x50, 0xd6, 0xff],
                [0x9e, 0x66, 0xfa, 0xff],
                [0xf2, 0x59, 0x66, 0xff],
                [0x4d, 0xd9, 0x8c, 0xff],
            ],
        ),
        (
            "high-contrast",
            [
                [0x00, 0x00, 0x00, 0xff],
                [0x00, 0x00, 0x00, 0xff],
                [0x00, 0x00, 0x00, 0xff],
                [0xff, 0xff, 0xff, 0xff],
                [0xff, 0xff, 0xff, 0xff],
                [0xff, 0xff, 0x00, 0xff],
                [0x65, 0xff, 0xff, 0xff],
                [0x00, 0x00, 0x00, 0xff],
                [0xff, 0x8a, 0x8a, 0xff],
                [0x65, 0xff, 0x9a, 0xff],
            ],
        ),
    ];
    for (variant, expected) in cases {
        let tokens = ThemeTokens::from_canonical_package(CANONICAL_PACKAGE, variant).unwrap();
        let actual = [
            tokens.panel_bg,
            tokens.panel_elevated,
            tokens.border_muted,
            tokens.text_primary,
            tokens.text_secondary,
            tokens.confirmed_focus,
            tokens.selected_focus,
            tokens.accent_secondary,
            tokens.danger,
            tokens.ok,
        ];
        assert_eq!(actual, expected.map(rgba), "variant {variant}");
        assert_ne!(
            tokens.confirmed_focus, tokens.selected_focus,
            "variant {variant}"
        );
    }
}

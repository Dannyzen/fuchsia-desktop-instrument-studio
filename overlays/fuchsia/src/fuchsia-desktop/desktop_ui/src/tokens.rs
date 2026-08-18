// Copyright 2026 The Fuchsia Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! Visual tokens for Instrument Studio.
//!
//! Values track design/sketches/01-instrument-studio (near-black panels,
//! cyan confirmed-focus, violet secondary).

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

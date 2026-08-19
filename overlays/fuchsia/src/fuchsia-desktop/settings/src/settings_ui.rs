// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiAction {
    ThemeDark,
    ThemeContrast,
    TemperatureCelsius,
    TemperatureFahrenheit,
}

/// Instrument Studio Settings hit-test.
/// Narrow tiles use a 56px sidebar + two cards.
/// Wide tiles keep the original 2x2 grid.
pub fn action_for_point(x: f32, y: f32, width: f32) -> Option<UiAction> {
    if width < 520.0 {
        let sidebar = 56.0;
        let card_x = sidebar + 8.0;
        let btn_x = card_x + 12.0;
        let btn_w = (width - btn_x - 20.0).max(80.0);
        if !(btn_x..btn_x + btn_w).contains(&x) {
            return None;
        }
        if (44.0..84.0).contains(&y) {
            return Some(UiAction::ThemeDark);
        }
        if (92.0..132.0).contains(&y) {
            return Some(UiAction::ThemeContrast);
        }
        if (200.0..240.0).contains(&y) {
            return Some(UiAction::TemperatureCelsius);
        }
        if (248.0..288.0).contains(&y) {
            return Some(UiAction::TemperatureFahrenheit);
        }
        return None;
    }
    if (192.0..272.0).contains(&y) {
        if (80.0..320.0).contains(&x) {
            return Some(UiAction::ThemeDark);
        }
        if (400.0..640.0).contains(&x) {
            return Some(UiAction::ThemeContrast);
        }
    }
    if (352.0..432.0).contains(&y) {
        if (80.0..320.0).contains(&x) {
            return Some(UiAction::TemperatureCelsius);
        }
        if (400.0..640.0).contains(&x) {
            return Some(UiAction::TemperatureFahrenheit);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::{action_for_point, UiAction};

    #[test]
    fn maps_theme_buttons() {
        assert_eq!(action_for_point(180.0, 230.0, 720.0), Some(UiAction::ThemeDark));
        assert_eq!(action_for_point(430.0, 230.0, 720.0), Some(UiAction::ThemeContrast));
    }

    #[test]
    fn maps_temperature_buttons() {
        assert_eq!(action_for_point(180.0, 390.0, 720.0), Some(UiAction::TemperatureCelsius));
        assert_eq!(action_for_point(430.0, 390.0, 720.0), Some(UiAction::TemperatureFahrenheit));
    }

    #[test]
    fn ignores_labels_gaps_and_system_info() {
        assert_eq!(action_for_point(80.0, 150.0, 720.0), None);
        assert_eq!(action_for_point(360.0, 230.0, 720.0), None);
        assert_eq!(action_for_point(360.0, 390.0, 720.0), None);
        assert_eq!(action_for_point(100.0, 700.0, 720.0), None);
    }

    #[test]
    fn maps_narrow_sidebar_card_buttons() {
        // 326px portrait tile: buttons live in the card column, not the 56px rail.
        assert_eq!(action_for_point(90.0, 60.0, 326.0), Some(UiAction::ThemeDark));
        assert_eq!(action_for_point(90.0, 110.0, 326.0), Some(UiAction::ThemeContrast));
        assert_eq!(action_for_point(90.0, 220.0, 326.0), Some(UiAction::TemperatureCelsius));
        assert_eq!(action_for_point(90.0, 260.0, 326.0), Some(UiAction::TemperatureFahrenheit));
        assert_eq!(action_for_point(20.0, 60.0, 326.0), None);
        assert_eq!(action_for_point(400.0, 230.0, 326.0), None);
    }
}

// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use crate::ControlId;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiAction {
    ThemeDark,
    ThemeContrast,
    TemperatureCelsius,
    TemperatureFahrenheit,
}

/// Instrument Studio Settings hit-test.
/// Narrow tiles use a 56px sidebar + two cards.
/// Hidden controls never produce an action, so callers cannot dispatch their FIDL requests.
pub fn action_for_point(
    x: f32,
    y: f32,
    width: f32,
    visible_controls: &[ControlId],
) -> Option<UiAction> {
    let theme_visible = visible_controls.contains(&ControlId::Theme);
    let temperature_visible = visible_controls.contains(&ControlId::Temperature);
    if width < 520.0 {
        let sidebar = 56.0;
        let card_x = sidebar + 8.0;
        let btn_x = card_x + 12.0;
        let btn_w = (width - btn_x - 20.0).max(80.0);
        if !(btn_x..btn_x + btn_w).contains(&x) {
            return None;
        }
        if theme_visible && (44.0..84.0).contains(&y) {
            return Some(UiAction::ThemeDark);
        }
        if theme_visible && (92.0..132.0).contains(&y) {
            return Some(UiAction::ThemeContrast);
        }
        if temperature_visible && (200.0..240.0).contains(&y) {
            return Some(UiAction::TemperatureCelsius);
        }
        if temperature_visible && (248.0..288.0).contains(&y) {
            return Some(UiAction::TemperatureFahrenheit);
        }
        return None;
    }
    if theme_visible && (192.0..272.0).contains(&y) {
        if (80.0..320.0).contains(&x) {
            return Some(UiAction::ThemeDark);
        }
        if (400.0..640.0).contains(&x) {
            return Some(UiAction::ThemeContrast);
        }
    }
    if temperature_visible && (352.0..432.0).contains(&y) {
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
    use super::{UiAction, action_for_point};
    use crate::ControlId;

    const ALL_BACKED: &[ControlId] = &[ControlId::Theme, ControlId::Temperature];

    #[test]
    fn maps_theme_buttons() {
        assert_eq!(action_for_point(180.0, 230.0, 720.0, ALL_BACKED), Some(UiAction::ThemeDark));
        assert_eq!(
            action_for_point(430.0, 230.0, 720.0, ALL_BACKED),
            Some(UiAction::ThemeContrast)
        );
    }

    #[test]
    fn maps_temperature_buttons() {
        assert_eq!(
            action_for_point(180.0, 390.0, 720.0, ALL_BACKED),
            Some(UiAction::TemperatureCelsius)
        );
        assert_eq!(
            action_for_point(430.0, 390.0, 720.0, ALL_BACKED),
            Some(UiAction::TemperatureFahrenheit)
        );
    }

    #[test]
    fn ignores_labels_gaps_and_system_info() {
        assert_eq!(action_for_point(80.0, 150.0, 720.0, ALL_BACKED), None);
        assert_eq!(action_for_point(360.0, 230.0, 720.0, ALL_BACKED), None);
        assert_eq!(action_for_point(360.0, 390.0, 720.0, ALL_BACKED), None);
        assert_eq!(action_for_point(100.0, 700.0, 720.0, ALL_BACKED), None);
    }

    #[test]
    fn maps_narrow_sidebar_card_buttons() {
        assert_eq!(action_for_point(90.0, 60.0, 326.0, ALL_BACKED), Some(UiAction::ThemeDark));
        assert_eq!(action_for_point(90.0, 110.0, 326.0, ALL_BACKED), Some(UiAction::ThemeContrast));
        assert_eq!(
            action_for_point(90.0, 220.0, 326.0, ALL_BACKED),
            Some(UiAction::TemperatureCelsius)
        );
        assert_eq!(
            action_for_point(90.0, 260.0, 326.0, ALL_BACKED),
            Some(UiAction::TemperatureFahrenheit)
        );
        assert_eq!(action_for_point(20.0, 60.0, 326.0, ALL_BACKED), None);
        assert_eq!(action_for_point(400.0, 230.0, 326.0, ALL_BACKED), None);
    }

    #[test]
    fn hidden_theme_control_yields_no_action() {
        let temperature_only = [ControlId::Temperature];
        assert_eq!(action_for_point(180.0, 230.0, 720.0, &temperature_only), None);
        assert_eq!(action_for_point(90.0, 60.0, 326.0, &temperature_only), None);
        assert_eq!(
            action_for_point(180.0, 390.0, 720.0, &temperature_only),
            Some(UiAction::TemperatureCelsius)
        );
    }
}

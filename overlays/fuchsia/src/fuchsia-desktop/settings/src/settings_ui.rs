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

pub fn action_for_point(x: f32, y: f32) -> Option<UiAction> {
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
        assert_eq!(action_for_point(180.0, 230.0), Some(UiAction::ThemeDark));
        assert_eq!(action_for_point(430.0, 230.0), Some(UiAction::ThemeContrast));
    }

    #[test]
    fn maps_temperature_buttons() {
        assert_eq!(action_for_point(180.0, 390.0), Some(UiAction::TemperatureCelsius));
        assert_eq!(action_for_point(430.0, 390.0), Some(UiAction::TemperatureFahrenheit));
    }

    #[test]
    fn ignores_labels_gaps_and_system_info() {
        assert_eq!(action_for_point(80.0, 150.0), None);
        assert_eq!(action_for_point(360.0, 230.0), None);
        assert_eq!(action_for_point(360.0, 390.0), None);
        assert_eq!(action_for_point(100.0, 700.0), None);
    }
}

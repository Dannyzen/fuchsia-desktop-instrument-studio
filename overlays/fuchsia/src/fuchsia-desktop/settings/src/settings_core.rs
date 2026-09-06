// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use std::fs;
use std::path::Path;

pub type SettingsResult<T> = Result<T, String>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppTheme {
    Dark,
    Contrast,
}

impl AppTheme {
    pub fn label(self) -> &'static str {
        match self {
            Self::Dark => "Dark",
            Self::Contrast => "High Contrast",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        match value {
            "dark" => Some(Self::Dark),
            "contrast" => Some(Self::Contrast),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum TemperatureUnit {
    #[default]
    Celsius,
    Fahrenheit,
}

impl TemperatureUnit {
    pub fn label(self) -> &'static str {
        match self {
            Self::Celsius => "Celsius",
            Self::Fahrenheit => "Fahrenheit",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControlId {
    Theme,
    Temperature,
    SystemInfo,
    Brightness,
    Accessibility,
    Keyboard,
    Network,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SettingsOwners {
    pub app_preferences: bool,
    pub intl_service: bool,
    pub build_info: bool,
    pub product_info: bool,
}

#[cfg(test)]
pub trait TemperatureService {
    fn set_temperature(&self, unit: TemperatureUnit) -> SettingsResult<()>;
}

pub struct SettingsController {
    owners: SettingsOwners,
    theme: AppTheme,
    legacy_theme: Option<AppTheme>,
    temperature: TemperatureUnit,
    status: String,
}

impl SettingsController {
    pub fn load(
        data_root: impl AsRef<Path>,
        owners: SettingsOwners,
        temperature: TemperatureUnit,
    ) -> SettingsResult<Self> {
        let data_root = data_root.as_ref();
        let preferences_path = data_root.join("preferences.txt");
        let (legacy_theme, status) = match fs::read_to_string(&preferences_path) {
            Ok(text) => {
                let value = text.lines().find_map(|line| line.strip_prefix("theme="));
                match value.and_then(AppTheme::parse) {
                    Some(theme) => (
                        Some(theme),
                        format!("Legacy {} theme awaiting migration", theme.label()),
                    ),
                    None => (
                        None,
                        "Ignored invalid legacy theme; using active theme".to_string(),
                    ),
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                (None, "Dark theme active".to_string())
            }
            Err(_) => (
                None,
                "Theme service state unavailable; using Dark".to_string(),
            ),
        };
        Ok(Self {
            owners,
            theme: AppTheme::Dark,
            legacy_theme,
            temperature,
            status,
        })
    }

    pub fn visible_controls(&self) -> Vec<ControlId> {
        let mut controls = Vec::new();
        if self.owners.app_preferences {
            controls.push(ControlId::Theme);
        }
        if self.owners.intl_service {
            controls.push(ControlId::Temperature);
        }
        if self.owners.build_info || self.owners.product_info {
            controls.push(ControlId::SystemInfo);
        }
        controls
    }

    pub fn hidden_controls(&self) -> Vec<ControlId> {
        let visible = self.visible_controls();
        [
            ControlId::Theme,
            ControlId::Temperature,
            ControlId::SystemInfo,
            ControlId::Brightness,
            ControlId::Accessibility,
            ControlId::Keyboard,
            ControlId::Network,
        ]
        .into_iter()
        .filter(|control| !visible.contains(control))
        .collect()
    }

    pub fn theme(&self) -> AppTheme {
        self.theme
    }
    pub fn set_active_theme(&mut self, theme: AppTheme) {
        self.theme = theme;
        self.status = format!("{} theme active", theme.label());
    }

    pub fn temperature(&self) -> TemperatureUnit {
        self.temperature
    }

    pub fn status(&self) -> &str {
        &self.status
    }

    pub fn legacy_theme(&self) -> Option<AppTheme> {
        self.legacy_theme
    }

    pub fn record_theme_request_result(
        &mut self,
        theme: AppTheme,
        result: SettingsResult<()>,
    ) -> SettingsResult<()> {
        if !self.owners.app_preferences {
            return Err("theme preferences are not available".to_string());
        }
        match result {
            Ok(()) => {
                self.status = format!("{} selected; restart required", theme.label());
                Ok(())
            }
            Err(error) => {
                self.status = format!("Theme selection failed: {error}");
                Err(error)
            }
        }
    }

    #[cfg(test)]
    pub fn apply_temperature<S: TemperatureService>(
        &mut self,
        unit: TemperatureUnit,
        service: &S,
    ) -> SettingsResult<()> {
        if !self.owners.intl_service {
            return Err("temperature setting is not available".to_string());
        }
        let previous = self.temperature;
        match service.set_temperature(unit) {
            Ok(()) => {
                self.temperature = unit;
                self.status = format!("Applied {} temperature unit", unit.label());
                Ok(())
            }
            Err(error) => {
                self.status = format!("Apply failed: {error}; retained {}", previous.label());
                Err(error)
            }
        }
    }

    pub fn record_temperature_result(
        &mut self,
        unit: TemperatureUnit,
        result: SettingsResult<()>,
    ) -> SettingsResult<()> {
        if !self.owners.intl_service {
            return Err("temperature setting is not available".to_string());
        }
        let previous = self.temperature;
        match result {
            Ok(()) => {
                self.temperature = unit;
                self.status = format!("Applied {} temperature unit", unit.label());
                Ok(())
            }
            Err(error) => {
                self.status = format!("Apply failed: {error}; retained {}", previous.label());
                Err(error)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        AppTheme, ControlId, SettingsController, SettingsOwners, TemperatureService,
        TemperatureUnit,
    };
    use std::cell::RefCell;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TestDir(PathBuf);
    impl TestDir {
        fn new() -> Self {
            let stamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let path = std::env::temp_dir().join(format!("fuchsia-settings-test-{stamp}"));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[derive(Default)]
    struct FakeTemperature {
        current: RefCell<TemperatureUnit>,
        fail_next: RefCell<Option<String>>,
        calls: RefCell<Vec<TemperatureUnit>>,
    }
    impl FakeTemperature {
        fn new(current: TemperatureUnit) -> Self {
            Self {
                current: RefCell::new(current),
                ..Default::default()
            }
        }
        fn fail_once(&self, error: &str) {
            *self.fail_next.borrow_mut() = Some(error.to_string());
        }
    }
    impl TemperatureService for FakeTemperature {
        fn set_temperature(&self, unit: TemperatureUnit) -> Result<(), String> {
            self.calls.borrow_mut().push(unit);
            if let Some(error) = self.fail_next.borrow_mut().take() {
                return Err(error);
            }
            *self.current.borrow_mut() = unit;
            Ok(())
        }
    }

    fn owners(intl: bool) -> SettingsOwners {
        SettingsOwners {
            app_preferences: true,
            intl_service: intl,
            build_info: true,
            product_info: true,
        }
    }

    #[test]
    fn exposes_only_controls_with_real_owners() {
        let root = TestDir::new();
        let settings = SettingsController::load(&root.0, owners(false), TemperatureUnit::Celsius)
            .expect("load settings");
        assert_eq!(
            settings.visible_controls(),
            vec![ControlId::Theme, ControlId::SystemInfo]
        );
        assert!(!settings.visible_controls().contains(&ControlId::Brightness));
        assert!(
            !settings
                .visible_controls()
                .contains(&ControlId::Accessibility)
        );
        assert!(!settings.visible_controls().contains(&ControlId::Keyboard));
        assert!(!settings.visible_controls().contains(&ControlId::Network));
    }

    #[test]
    fn intl_owner_exposes_temperature_control() {
        let root = TestDir::new();
        let settings = SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius)
            .expect("load settings");
        assert_eq!(
            settings.visible_controls(),
            vec![
                ControlId::Theme,
                ControlId::Temperature,
                ControlId::SystemInfo
            ]
        );
    }

    #[test]
    fn theme_control_is_hidden_without_owner() {
        let root = TestDir::new();
        let mut no_theme_owner = owners(true);
        no_theme_owner.app_preferences = false;
        let settings = SettingsController::load(
            &root.0,
            no_theme_owner,
            TemperatureUnit::Celsius,
        )
        .unwrap();
        assert!(!settings.visible_controls().contains(&ControlId::Theme));
    }

    #[test]
    fn active_theme_status_tracks_service_state() {
        let root = TestDir::new();
        let mut settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius).unwrap();
        settings.set_active_theme(AppTheme::Contrast);
        assert_eq!(settings.theme(), AppTheme::Contrast);
        assert_eq!(settings.status(), "High Contrast theme active");
    }

    #[test]
    fn pending_service_state_shows_restart_required() {
        let root = TestDir::new();
        let mut settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius)
                .expect("load settings");
        settings
            .record_theme_request_result(AppTheme::Contrast, Ok(()))
            .unwrap();
        assert_eq!(settings.theme(), AppTheme::Dark);
        assert!(settings.status().contains("restart required"));
    }

    #[test]
    fn corrupt_theme_state_falls_back_to_dark_without_exposing_junk() {
        let root = TestDir::new();
        fs::write(root.0.join("preferences.txt"), "theme=linux-desktop\n").unwrap();
        let settings = SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius)
            .expect("load settings");
        assert_eq!(settings.theme(), AppTheme::Dark);
        assert!(settings.status().contains("Ignored invalid"));
    }

    #[test]
    fn legacy_dark_maps_to_instrument_studio_dark() {
        let root = TestDir::new();
        fs::write(root.0.join("preferences.txt"), "theme=dark\n").unwrap();
        let settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius).unwrap();
        assert_eq!(settings.legacy_theme(), Some(AppTheme::Dark));
    }
    #[test]
    fn legacy_contrast_maps_to_instrument_studio_high_contrast() {
        let root = TestDir::new();
        fs::write(root.0.join("preferences.txt"), "theme=contrast\n").unwrap();
        let settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius).unwrap();
        assert_eq!(settings.legacy_theme(), Some(AppTheme::Contrast));
    }

    #[test]
    fn successful_temperature_apply_updates_visible_value() {
        let root = TestDir::new();
        let service = FakeTemperature::new(TemperatureUnit::Celsius);
        let mut settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius)
                .expect("load settings");
        settings
            .apply_temperature(TemperatureUnit::Fahrenheit, &service)
            .expect("apply");
        assert_eq!(settings.temperature(), TemperatureUnit::Fahrenheit);
        assert_eq!(*service.current.borrow(), TemperatureUnit::Fahrenheit);
        assert!(settings.status().contains("Fahrenheit"));
    }

    #[test]
    fn failed_temperature_apply_retains_prior_value_and_surfaces_error() {
        let root = TestDir::new();
        let service = FakeTemperature::new(TemperatureUnit::Celsius);
        service.fail_once("persistent storage unavailable");
        let mut settings =
            SettingsController::load(&root.0, owners(true), TemperatureUnit::Celsius)
                .expect("load settings");
        let error = settings
            .apply_temperature(TemperatureUnit::Fahrenheit, &service)
            .expect_err("failure must propagate");
        assert!(error.contains("persistent storage unavailable"));
        assert_eq!(settings.temperature(), TemperatureUnit::Celsius);
        assert_eq!(*service.current.borrow(), TemperatureUnit::Celsius);
        assert!(settings.status().contains("retained Celsius"));
    }

    #[test]
    fn absent_intl_owner_refuses_temperature_mutation() {
        let root = TestDir::new();
        let service = FakeTemperature::new(TemperatureUnit::Celsius);
        let mut settings =
            SettingsController::load(&root.0, owners(false), TemperatureUnit::Celsius)
                .expect("load settings");
        let error = settings
            .apply_temperature(TemperatureUnit::Fahrenheit, &service)
            .expect_err("unsupported control must fail closed");
        assert!(error.contains("not available"));
        assert!(service.calls.borrow().is_empty());
        assert_eq!(settings.temperature(), TemperatureUnit::Celsius);
    }
}

use fidl::endpoints::RequestStream;
use fidl_fuchsia_instrumentstudio_theme as ftheme;
use futures::TryStreamExt;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use theme_model::NativeThemeV1;

pub mod diagnostics;
pub mod persistence;
pub use diagnostics::Diagnostics;
// P3-S2 Inspect keys "selection_source" and "selection_error_code" are now
// owned, retained, and updated by the first-class diagnostics module.

pub const FALLBACK_THEME_ID: &str = "instrument-studio-builtin";
pub const MAX_DIAGNOSTIC_ERROR_BYTES: usize = 96;
pub const E_DUPLICATE_THEME_ID: &str = "E_DUPLICATE_THEME_ID";
pub const E_SELECTED_IDENTITY_INVALID: &str = "E_SELECTED_IDENTITY_INVALID";
pub const E_SELECTION_HISTORY_INVALID: &str = "E_SELECTION_HISTORY_INVALID";
pub const SELECTION_CATALOG_DEFAULT: &str = "catalog-default";
pub const SELECTION_BUILTIN_DEFAULT: &str = "built-in-default";
pub const SELECTION_SELECTED: &str = "selected";
pub const SELECTION_LAST_KNOWN_GOOD: &str = "last-known-good";
pub const SELECTION_BUILTIN_RESTORED: &str = "built-in-restored";
pub const SELECTION_BUILTIN_RECOVERY: &str = "built-in-recovery";

#[cfg(test)]
fn bounded_diagnostic_error(error: &str) -> &str {
    &error[..error.len().min(MAX_DIAGNOSTIC_ERROR_BYTES)]
}

#[derive(Debug, Eq, PartialEq)]
pub enum WatchAction<R> {
    Reply(R),
    Parked,
    BadState(R),
}

/// Hanging-get state owned by exactly one client connection.
pub struct ConnectionWatch<R> {
    pending: Option<(u64, R)>,
}

impl<R> Default for ConnectionWatch<R> {
    fn default() -> Self {
        Self { pending: None }
    }
}

impl<R> ConnectionWatch<R> {
    pub fn observe(&mut self, observed: u64, current: u64, responder: R) -> WatchAction<R> {
        if observed != current {
            WatchAction::Reply(responder)
        } else if self.pending.is_some() {
            WatchAction::BadState(responder)
        } else {
            self.pending = Some((observed, responder));
            WatchAction::Parked
        }
    }

    #[cfg(test)]
    pub fn drain_if_changed(&mut self, current: u64) -> Option<R> {
        if self
            .pending
            .as_ref()
            .is_some_and(|(observed, _)| *observed != current)
        {
            self.pending.take().map(|(_, responder)| responder)
        } else {
            None
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Snapshot {
    pub generation: u64,
    pub id: String,
    pub display_name: String,
    pub revision: u64,
    pub semantic_sha256: [u8; 32],
    pub variant: persistence::Variant,
    pub canonical_package: Arc<[u8]>,
}

impl Snapshot {
    fn fallback() -> Self {
        Self {
            generation: 0,
            id: FALLBACK_THEME_ID.into(),
            display_name: "Built-in".into(),
            revision: 0,
            semantic_sha256: [0; 32],
            variant: persistence::Variant::Dark,
            canonical_package: Arc::from([]),
        }
    }
}

/// Process-local read authority. No storage or mutation capability is held.
pub struct Authority {
    themes: BTreeMap<String, Snapshot>,
    current: Snapshot,
    load_error_code: Option<&'static str>,
    selection_source: &'static str,
    selection_error_code: Option<&'static str>,
}

impl Authority {
    pub fn from_packaged<'a>(packages: impl IntoIterator<Item = &'a [u8]>) -> Self {
        let mut themes: BTreeMap<String, Snapshot> = BTreeMap::new();
        let mut load_error_code = None;
        for bytes in packages {
            match NativeThemeV1::decode_canonical(bytes) {
                Ok(theme) => {
                    let snapshot = Snapshot {
                        generation: 1,
                        id: theme.theme_id().into(),
                        display_name: theme.display_name().into(),
                        revision: theme.revision(),
                        semantic_sha256: theme.semantic_sha256(),
                        variant: persistence::Variant::Dark,
                        canonical_package: Arc::from(bytes),
                    };
                    if let Some(existing) = themes.get_mut(&snapshot.id) {
                        if existing.semantic_sha256 != snapshot.semantic_sha256 {
                            load_error_code = Some(E_DUPLICATE_THEME_ID);
                            themes.clear();
                            break;
                        }
                        // Equivalent provenance adapters collapse by embedded theme.id.
                        // The lexicographically smallest canonical bytes are the stable,
                        // input-order-independent representative.
                        if snapshot.canonical_package.as_ref() < existing.canonical_package.as_ref()
                        {
                            *existing = snapshot;
                        }
                    } else {
                        themes.insert(snapshot.id.clone(), snapshot);
                    }
                }
                Err(error) => {
                    load_error_code = Some(error.code());
                    themes.clear();
                    break;
                }
            }
        }
        let current = themes
            .values()
            .next()
            .cloned()
            .unwrap_or_else(Snapshot::fallback);
        Self {
            themes,
            current,
            load_error_code,
            selection_source: SELECTION_CATALOG_DEFAULT,
            selection_error_code: None,
        }
    }

    /// Startup recovery order is selected -> last-known-good -> built-in.
    pub fn from_packaged_and_state<'a>(
        packages: impl IntoIterator<Item = &'a [u8]>,
        state_bytes: Option<&[u8]>,
    ) -> Self {
        let mut authority = Self::from_packaged(packages);
        let (chosen, selection_source, selection_error_code) = match state_bytes {
            None => (None, SELECTION_BUILTIN_DEFAULT, None),
            Some(bytes) => match persistence::decode(bytes) {
                Err(error) => (None, SELECTION_BUILTIN_RECOVERY, Some(error.code())),
                Ok(state) => match state.pending.as_ref() {
                    None => (None, SELECTION_BUILTIN_RESTORED, None),
                    Some(identity) => match authority.snapshot_for(identity) {
                        Some(snapshot) => (Some(snapshot), SELECTION_SELECTED, None),
                        None => match authority.snapshot_for(&state.last_known_good) {
                            Some(snapshot) => (
                                Some(snapshot),
                                SELECTION_LAST_KNOWN_GOOD,
                                Some(E_SELECTED_IDENTITY_INVALID),
                            ),
                            None => (
                                None,
                                SELECTION_BUILTIN_RECOVERY,
                                Some(E_SELECTION_HISTORY_INVALID),
                            ),
                        },
                    },
                },
            },
        };
        authority.current = chosen.unwrap_or_else(Snapshot::fallback);
        authority.selection_source = selection_source;
        authority.selection_error_code = selection_error_code;
        authority
    }

    fn snapshot_for(&self, identity: &persistence::Identity) -> Option<Snapshot> {
        self.themes
            .get(&identity.theme_id)
            .filter(|snapshot| snapshot.semantic_sha256 == identity.semantic_sha256)
            .cloned()
            .map(|mut snapshot| {
                snapshot.variant = identity.variant;
                snapshot
            })
    }

    pub fn current(&self) -> Snapshot {
        self.current.clone()
    }
    pub fn themes(&self) -> impl Iterator<Item = &Snapshot> {
        self.themes.values()
    }
    pub fn load_error_code(&self) -> Option<&'static str> {
        self.load_error_code
    }
    pub fn selection_source(&self) -> &'static str {
        self.selection_source
    }
    pub fn selection_error_code(&self) -> Option<&'static str> {
        self.selection_error_code
    }
}

pub struct SettingsControl {
    authority: Arc<Authority>,
    store: Mutex<persistence::AtomicStore>,
    diagnostics: Arc<Diagnostics>,
}

impl SettingsControl {
    pub fn new(
        authority: Arc<Authority>,
        state_path: impl Into<std::path::PathBuf>,
        diagnostics: Arc<Diagnostics>,
    ) -> Self {
        Self {
            authority,
            store: Mutex::new(persistence::AtomicStore::new(state_path)),
            diagnostics,
        }
    }
    fn active_identity(&self) -> persistence::Identity {
        let current = self.authority.current();
        persistence::Identity {
            theme_id: current.id,
            variant: current.variant,
            semantic_sha256: current.semantic_sha256,
        }
    }
    fn validate(&self, identity: &persistence::Identity) -> Result<(), zx_status::Status> {
        let Some(snapshot) = self.authority.themes.get(&identity.theme_id) else {
            return Err(zx_status::Status::NOT_FOUND);
        };
        if snapshot.semantic_sha256 != identity.semantic_sha256 {
            return Err(zx_status::Status::INVALID_ARGS);
        }
        Ok(())
    }
    pub fn state(&self) -> persistence::PersistedState {
        self.store
            .lock()
            .unwrap()
            .load()
            .ok()
            .flatten()
            .unwrap_or_else(|| persistence::PersistedState {
                pending: None,
                last_known_good: self.active_identity(),
            })
    }
    pub fn record_active_as_last_known_good(&self) {
        let active = self.active_identity();
        let mut store = self.store.lock().unwrap();
        let mut state = match store.load() {
            Ok(Some(state)) => state,
            Ok(None) => return,
            Err(_) => {
                drop(store);
                self.diagnostics.record_last_known_good_result(
                    &Err(zx_status::Status::IO_DATA_INTEGRITY),
                    None,
                );
                return;
            }
        };
        if state.pending.as_ref() == Some(&active) && state.last_known_good != active {
            let previous = state.clone();
            state.last_known_good = active;
            let result = store
                .commit(&state)
                .map(|_| ())
                .map_err(|_| zx_status::Status::IO);
            drop(store);
            let observed = if result.is_ok() { &state } else { &previous };
            self.diagnostics
                .record_last_known_good_result(&result, Some(observed));
        }
    }
    pub fn select(&self, identity: persistence::Identity) -> Result<(), zx_status::Status> {
        let result = self.validate(&identity).and_then(|()| {
            self.store
                .lock()
                .unwrap()
                .select(identity, self.active_identity())
                .map(|_| ())
                .map_err(|_| zx_status::Status::IO)
        });
        let state = self.state();
        self.diagnostics.record_selection_result(&result, &state);
        result
    }
    pub fn restore(&self) -> Result<(), zx_status::Status> {
        let result = self
            .store
            .lock()
            .unwrap()
            .restore(self.active_identity())
            .map(|_| ())
            .map_err(|_| zx_status::Status::IO);
        let state = self.state();
        self.diagnostics.record_restore_result(&result, &state);
        result
    }
    pub fn migrate_legacy(&self, identity: persistence::Identity) -> Result<(), zx_status::Status> {
        if let Err(status) = self.validate(&identity) {
            let result = Err(status);
            self.diagnostics.record_migration_result(&result, None);
            return result;
        }
        let mut store = self.store.lock().unwrap();
        let result = match store.load() {
            Ok(None) => store
                .select(identity, self.active_identity())
                .map(|_| ())
                .map_err(|_| zx_status::Status::IO),
            Ok(Some(state)) if state.pending.as_ref() == Some(&identity) => Ok(()),
            Ok(Some(_)) => Err(zx_status::Status::ALREADY_EXISTS),
            Err(_) => Err(zx_status::Status::IO_DATA_INTEGRITY),
        };
        drop(store);
        let state = self.state();
        self.diagnostics
            .record_migration_result(&result, Some(&state));
        result
    }
}

fn from_fidl_identity(identity: ftheme::ThemeIdentity) -> persistence::Identity {
    persistence::Identity {
        theme_id: identity.theme_id,
        variant: match identity.variant {
            ftheme::ThemeVariant::Light => persistence::Variant::Light,
            ftheme::ThemeVariant::Dark => persistence::Variant::Dark,
            ftheme::ThemeVariant::HighContrast => persistence::Variant::HighContrast,
        },
        semantic_sha256: identity.semantic_sha256,
    }
}

fn fidl_identity(identity: &persistence::Identity) -> ftheme::ThemeIdentity {
    ftheme::ThemeIdentity {
        theme_id: identity.theme_id.clone(),
        variant: match identity.variant {
            persistence::Variant::Light => ftheme::ThemeVariant::Light,
            persistence::Variant::Dark => ftheme::ThemeVariant::Dark,
            persistence::Variant::HighContrast => ftheme::ThemeVariant::HighContrast,
        },
        semantic_sha256: identity.semantic_sha256,
    }
}

pub async fn serve_native_theme_settings(
    control: Arc<SettingsControl>,
    mut stream: ftheme::NativeThemeSettingsRequestStream,
) -> Result<(), fidl::Error> {
    while let Some(request) = stream.try_next().await? {
        match request {
            ftheme::NativeThemeSettingsRequest::GetState { responder } => {
                let state = control.state();
                responder.send(&ftheme::NativeThemeSettingsState {
                    active: fidl_identity(&control.active_identity()),
                    pending: state.pending.as_ref().map(fidl_identity).map(Box::new),
                    last_known_good: Some(Box::new(fidl_identity(&state.last_known_good))),
                })?;
            }
            ftheme::NativeThemeSettingsRequest::Select {
                identity,
                responder,
            } => {
                responder.send(
                    control
                        .select(from_fidl_identity(identity))
                        .map_err(|s| s.into_raw()),
                )?;
            }
            ftheme::NativeThemeSettingsRequest::RestoreBuiltIn { responder } => {
                responder.send(control.restore().map_err(|s| s.into_raw()))?;
            }
            ftheme::NativeThemeSettingsRequest::MigrateLegacy {
                identity,
                responder,
            } => {
                responder.send(
                    control
                        .migrate_legacy(from_fidl_identity(identity))
                        .map_err(|s| s.into_raw()),
                )?;
            }
        }
    }
    Ok(())
}

/// Serves one generated-FIDL connection using connection-local hanging-get state.
// P3-S1's `serve_native_theme(authority, stream)` shape is extended only with
// the shared diagnostics observer; protocol behavior remains library-owned.
pub async fn serve_native_theme(
    authority: Arc<Authority>,
    diagnostics: Arc<Diagnostics>,
    mut stream: ftheme::NativeThemeRequestStream,
) -> Result<(), fidl::Error> {
    let mut watch_state = ConnectionWatch::default();
    while let Some(request) = stream.try_next().await? {
        match request {
            ftheme::NativeThemeRequest::ListThemes { responder } => responder.send(
                &authority
                    .themes()
                    .map(to_fidl)
                    .map(|s| s.metadata)
                    .collect::<Vec<_>>(),
            )?,
            ftheme::NativeThemeRequest::GetTheme { id, responder } => {
                let metadata = authority
                    .themes()
                    .find(|s| s.id == id)
                    .map(|s| to_fidl(s).metadata);
                responder.send(
                    metadata
                        .as_ref()
                        .ok_or_else(|| zx_status::Status::NOT_FOUND.into_raw()),
                )?;
            }
            ftheme::NativeThemeRequest::GetCurrent { responder } => {
                let current = authority.current();
                responder.send(&to_fidl(&current))?;
                diagnostics.record_consumer_ack(current.generation);
            }
            ftheme::NativeThemeRequest::WatchCurrent {
                observed_generation,
                responder,
            } => {
                let current = authority.current();
                match watch_state.observe(observed_generation, current.generation, responder) {
                    WatchAction::Reply(responder) => {
                        responder.send(&to_fidl(&current))?;
                        diagnostics.record_consumer_ack(current.generation);
                    }
                    WatchAction::Parked => {}
                    WatchAction::BadState(_responder) => {
                        diagnostics.record_consumer_stale(observed_generation);
                        stream
                            .control_handle()
                            .shutdown_with_epitaph(zx_status::Status::BAD_STATE);
                        // Poll the stream once more so generated bindings flush the epitaph
                        // before pending responders and the channel are dropped.
                        continue;
                    }
                }
            }
        }
    }
    Ok(())
}

pub fn to_fidl(snapshot: &Snapshot) -> ftheme::ThemeSnapshot {
    ftheme::ThemeSnapshot {
        generation: snapshot.generation,
        metadata: ftheme::ThemeMetadata {
            id: snapshot.id.clone(),
            display_name: snapshot.display_name.clone(),
            revision: snapshot.revision,
            semantic_sha256: snapshot.semantic_sha256,
        },
        identity: ftheme::ThemeIdentity {
            theme_id: snapshot.id.clone(),
            variant: match snapshot.variant {
                persistence::Variant::Light => ftheme::ThemeVariant::Light,
                persistence::Variant::Dark => ftheme::ThemeVariant::Dark,
                persistence::Variant::HighContrast => ftheme::ThemeVariant::HighContrast,
            },
            semantic_sha256: snapshot.semantic_sha256,
        },
        canonical_package: snapshot.canonical_package.to_vec(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use fidl::endpoints::create_proxy_and_stream;
    use std::sync::atomic::{AtomicUsize, Ordering};
    const VALID: &[u8] = include_bytes!("../../theme_model/testdata/native-theme-v1-package.json");
    const BASE16: &[u8] =
        include_bytes!("../../theme_catalog/catalog/instrument-studio-base16.package.json");
    const BASE24: &[u8] =
        include_bytes!("../../theme_catalog/catalog/instrument-studio-base24.package.json");
    const DTCG: &[u8] =
        include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json");
    const OMARCHY: &[u8] =
        include_bytes!("../../theme_catalog/catalog/instrument-studio-omarchy.package.json");
    // Exact generation: load DTCG with json.loads; set theme.revision=2; set
    // metadata.provenance.semantic_hash=compiler_core.package_semantic_identity(package);
    // write the bytes returned by compiler_core._validate_complete_package(package).
    const CONFLICT: &[u8] = include_bytes!("../testdata/instrument-studio-conflict.package.json");

    fn production_authority() -> Arc<Authority> {
        Arc::new(Authority::from_packaged([BASE16, BASE24, DTCG, OMARCHY]))
    }
    fn identity(variant: persistence::Variant) -> persistence::Identity {
        let snapshot = Authority::from_packaged([DTCG]).current();
        persistence::Identity {
            theme_id: snapshot.id,
            variant,
            semantic_sha256: snapshot.semantic_sha256,
        }
    }
    fn state(pending: Option<persistence::Identity>, lkg: persistence::Identity) -> Vec<u8> {
        persistence::encode(&persistence::PersistedState {
            pending,
            last_known_good: lkg,
        })
        .unwrap()
    }

    fn proxy(authority: Arc<Authority>) -> ftheme::NativeThemeProxy {
        let (proxy, stream) = create_proxy_and_stream::<ftheme::NativeThemeMarker>();
        fuchsia_async::Task::local(async move {
            let diagnostics = Arc::new(Diagnostics::record(
                &fuchsia_inspect::Inspector::default().root(),
                &authority,
                None,
            ));
            serve_native_theme(authority, diagnostics, stream)
                .await
                .expect("serve generated FIDL");
        })
        .detach();
        proxy
    }
    fn control_proxy(control: Arc<SettingsControl>) -> ftheme::NativeThemeSettingsProxy {
        let (proxy, stream) = create_proxy_and_stream::<ftheme::NativeThemeSettingsMarker>();
        fuchsia_async::Task::local(async move {
            serve_native_theme_settings(control, stream).await.unwrap();
        })
        .detach();
        proxy
    }
    fn test_control() -> (std::path::PathBuf, Arc<SettingsControl>) {
        let path = std::env::temp_dir().join(format!(
            "theme-control-{}-{:?}.v1",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_file(&path);
        (path.clone(), {
            let authority = production_authority();
            let inspector = fuchsia_inspect::Inspector::default();
            let diagnostics = Arc::new(Diagnostics::record(inspector.root(), &authority, None));
            Arc::new(SettingsControl::new(authority, path, diagnostics))
        })
    }
    fn fidl_id(variant: ftheme::ThemeVariant) -> ftheme::ThemeIdentity {
        let snapshot = production_authority().current();
        ftheme::ThemeIdentity {
            theme_id: snapshot.id,
            variant,
            semantic_sha256: snapshot.semantic_sha256,
        }
    }

    #[test]
    fn restart_baseline_is_zero() {
        assert_eq!(
            Authority::from_packaged([b"bad".as_slice()])
                .current()
                .generation,
            0
        );
    }
    #[test]
    fn equal_generation_parks_exactly_one_responder() {
        let mut state = ConnectionWatch::default();
        assert_eq!(state.observe(1, 1, 7), WatchAction::Parked);
        assert!(state.pending.is_some());
    }
    #[test]
    fn duplicate_outstanding_watch_is_bad_state() {
        let mut state = ConnectionWatch::default();
        assert_eq!(state.observe(1, 1, 7), WatchAction::Parked);
        assert_eq!(state.observe(1, 1, 8), WatchAction::BadState(8));
    }
    #[test]
    fn connections_retain_independent_responders() {
        let (mut first, mut second) = (ConnectionWatch::default(), ConnectionWatch::default());
        assert_eq!(first.observe(1, 1, "first"), WatchAction::Parked);
        assert_eq!(second.observe(1, 1, "second"), WatchAction::Parked);
        assert_eq!(first.drain_if_changed(2), Some("first"));
        assert_eq!(second.drain_if_changed(2), Some("second"));
    }
    #[test]
    fn unequal_generation_returns_immediately() {
        let mut state = ConnectionWatch::default();
        assert_eq!(state.observe(0, 1, "lower"), WatchAction::Reply("lower"));
        assert_eq!(
            state.observe(2, 1, "greater"),
            WatchAction::Reply("greater")
        );
    }
    #[test]
    fn future_generation_drains_once() {
        let mut state = ConnectionWatch::default();
        assert_eq!(state.observe(1, 1, 7), WatchAction::Parked);
        assert_eq!(state.drain_if_changed(2), Some(7));
        assert_eq!(state.drain_if_changed(2), None);
    }
    #[test]
    fn disconnect_drops_only_its_responder() {
        struct Token(Arc<AtomicUsize>);
        impl Drop for Token {
            fn drop(&mut self) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
        }
        let drops = Arc::new(AtomicUsize::new(0));
        let mut first = ConnectionWatch::default();
        let mut second = ConnectionWatch::default();
        assert!(matches!(
            first.observe(1, 1, Token(drops.clone())),
            WatchAction::Parked
        ));
        assert!(matches!(
            second.observe(1, 1, Token(drops.clone())),
            WatchAction::Parked
        ));
        drop(first);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert!(second.pending.is_some());
        drop(second);
        assert_eq!(drops.load(Ordering::SeqCst), 2);
    }
    #[test]
    fn invalid_package_falls_back() {
        assert_eq!(
            Authority::from_packaged([b"bad".as_slice()]).current().id,
            FALLBACK_THEME_ID
        );
    }
    #[test]
    fn mixed_valid_invalid_catalog_fails_closed() {
        let authority = Authority::from_packaged([VALID, b"bad".as_slice()]);
        assert_eq!(authority.current().id, FALLBACK_THEME_ID);
        assert_eq!(authority.themes().count(), 0);
        assert!(authority.load_error_code.is_some());
    }
    #[test]
    fn diagnostic_error_is_bounded() {
        let error = "x".repeat(MAX_DIAGNOSTIC_ERROR_BYTES + 1);
        assert_eq!(
            bounded_diagnostic_error(&error).len(),
            MAX_DIAGNOSTIC_ERROR_BYTES
        );
    }

    #[test]
    fn production_catalog_collapses_equivalent_adapters() {
        let authority = production_authority();
        let themes = authority.themes().collect::<Vec<_>>();
        assert_eq!(themes.len(), 1);
        assert_eq!(themes[0].id, "instrument-studio");
        assert_eq!(themes[0].display_name, "Instrument Studio");
        assert_eq!(themes[0].revision, 1);
        assert_eq!(
            themes[0].semantic_sha256,
            NativeThemeV1::decode_canonical(BASE16)
                .unwrap()
                .semantic_sha256()
        );
    }

    #[test]
    fn equivalent_duplicates_are_order_independent_and_choose_smallest_bytes() {
        let forward = Authority::from_packaged([BASE16, BASE24, DTCG, OMARCHY]);
        let reverse = Authority::from_packaged([OMARCHY, DTCG, BASE24, BASE16]);
        let expected = [BASE16, BASE24, DTCG, OMARCHY].into_iter().min().unwrap();
        assert_eq!(forward.current().canonical_package.as_ref(), expected);
        assert_eq!(reverse.current().canonical_package.as_ref(), expected);
    }

    #[test]
    fn conflicting_duplicate_theme_id_fails_closed() {
        NativeThemeV1::decode_canonical(CONFLICT).expect("compiler-generated conflict fixture");
        let authority = Authority::from_packaged([DTCG, CONFLICT]);
        assert_eq!(authority.current().id, FALLBACK_THEME_ID);
        assert_eq!(authority.themes().count(), 0);
        assert_eq!(authority.load_error_code(), Some(E_DUPLICATE_THEME_ID));
    }

    #[test]
    fn corrupt_state_reports_recovery_diagnostics() {
        let authority = Authority::from_packaged_and_state([DTCG], Some(b"corrupt"));
        assert_eq!(authority.current().id, FALLBACK_THEME_ID);
        assert_eq!(authority.selection_source(), SELECTION_BUILTIN_RECOVERY);
        assert_eq!(authority.selection_error_code(), Some("E_STATE_CORRUPT"));
    }
    #[test]
    fn invalid_selected_reports_lkg_recovery() {
        let mut invalid = identity(persistence::Variant::Light);
        invalid.theme_id = "missing-theme".into();
        let bytes = state(Some(invalid), identity(persistence::Variant::HighContrast));
        let authority = Authority::from_packaged_and_state([DTCG], Some(&bytes));
        assert_eq!(
            authority.current().variant,
            persistence::Variant::HighContrast
        );
        assert_eq!(authority.selection_source(), SELECTION_LAST_KNOWN_GOOD);
        assert_eq!(
            authority.selection_error_code(),
            Some(E_SELECTED_IDENTITY_INVALID)
        );
    }
    #[test]
    fn startup_uses_valid_selected_identity() {
        let selected = identity(persistence::Variant::HighContrast);
        let bytes = state(Some(selected), identity(persistence::Variant::Dark));
        let authority = Authority::from_packaged_and_state([DTCG], Some(&bytes));
        assert_eq!(
            authority.current().variant,
            persistence::Variant::HighContrast
        );
    }
    #[test]
    fn startup_falls_back_to_valid_lkg() {
        let mut selected = identity(persistence::Variant::Light);
        selected.semantic_sha256[0] ^= 1;
        let bytes = state(Some(selected), identity(persistence::Variant::Dark));
        assert_eq!(
            Authority::from_packaged_and_state([DTCG], Some(&bytes))
                .current()
                .variant,
            persistence::Variant::Dark
        );
    }
    #[test]
    fn startup_falls_back_to_builtin() {
        assert_eq!(
            Authority::from_packaged_and_state([DTCG], Some(b"corrupt"))
                .current()
                .id,
            FALLBACK_THEME_ID
        );
    }
    #[test]
    fn restart_after_restore_uses_builtin() {
        let bytes = state(None, identity(persistence::Variant::Dark));
        assert_eq!(
            Authority::from_packaged_and_state([DTCG], Some(&bytes))
                .current()
                .id,
            FALLBACK_THEME_ID
        );
    }
    #[test]
    fn selection_does_not_change_current_snapshot() {
        let (path, control) = test_control();
        let before = control.authority.current();
        control
            .select(identity(persistence::Variant::HighContrast))
            .unwrap();
        assert_eq!(control.authority.current(), before);
        assert_eq!(
            control.state().pending.unwrap().variant,
            persistence::Variant::HighContrast
        );
        let _ = std::fs::remove_file(path);
    }
    #[test]
    fn selection_does_not_change_generation_or_watch() {
        let (path, control) = test_control();
        let generation = control.authority.current().generation;
        let mut watch = ConnectionWatch::default();
        assert_eq!(
            watch.observe(generation, control.authority.current().generation, 7),
            WatchAction::Parked
        );
        control
            .select(identity(persistence::Variant::Light))
            .unwrap();
        assert_eq!(control.authority.current().generation, generation);
        assert_eq!(
            watch.drain_if_changed(control.authority.current().generation),
            None
        );
        let _ = std::fs::remove_file(path);
    }
    #[fuchsia::test]
    async fn control_proxy_queries_and_selects_pending() {
        let (path, control) = test_control();
        let proxy = control_proxy(control);
        proxy
            .select(&fidl_id(ftheme::ThemeVariant::HighContrast))
            .await
            .unwrap()
            .unwrap();
        let state = proxy.get_state().await.unwrap();
        assert_eq!(
            state.pending.unwrap().variant,
            ftheme::ThemeVariant::HighContrast
        );
        let _ = std::fs::remove_file(path);
    }
    #[test]
    fn control_rejects_unknown_id() {
        let (p, c) = test_control();
        let mut id = identity(persistence::Variant::Dark);
        id.theme_id = "missing".into();
        assert_eq!(c.select(id), Err(zx_status::Status::NOT_FOUND));
        let _ = std::fs::remove_file(p);
    }
    #[test]
    fn control_rejects_semantic_hash_mismatch() {
        let (p, c) = test_control();
        let mut id = identity(persistence::Variant::Dark);
        id.semantic_sha256[0] ^= 1;
        assert_eq!(c.select(id), Err(zx_status::Status::INVALID_ARGS));
        let _ = std::fs::remove_file(p);
    }
    #[fuchsia::test]
    async fn concurrent_settings_callers_are_serialized() {
        let (p, c) = test_control();
        let a = control_proxy(c.clone());
        let b = control_proxy(c);
        let (x, y) = futures::join!(
            a.select(&fidl_id(ftheme::ThemeVariant::Light)),
            b.select(&fidl_id(ftheme::ThemeVariant::Dark))
        );
        assert!(x.unwrap().is_ok());
        assert!(y.unwrap().is_ok());
        let _ = std::fs::remove_file(p);
    }
    #[test]
    fn control_restore_is_idempotent() {
        let (p, c) = test_control();
        assert!(c.restore().is_ok());
        assert!(c.restore().is_ok());
        let _ = std::fs::remove_file(p);
    }
    #[test]
    fn legacy_migration_is_guarded() {
        let (p, c) = test_control();
        assert!(
            c.migrate_legacy(identity(persistence::Variant::Dark))
                .is_ok()
        );
        assert!(
            c.migrate_legacy(identity(persistence::Variant::Dark))
                .is_ok()
        );
        assert_eq!(
            c.migrate_legacy(identity(persistence::Variant::Light)),
            Err(zx_status::Status::ALREADY_EXISTS)
        );
        let _ = std::fs::remove_file(p);
    }

    #[fuchsia::test]
    async fn proxy_list_get_current_and_not_found() {
        let proxy = proxy(production_authority());
        let themes = proxy.list_themes().await.unwrap();
        assert_eq!(themes.len(), 1);
        assert_eq!(themes[0].id, "instrument-studio");
        assert_eq!(
            proxy.get_theme("instrument-studio").await.unwrap().unwrap(),
            themes[0]
        );
        assert_eq!(
            proxy.get_theme("missing").await.unwrap(),
            Err(zx_status::Status::NOT_FOUND.into_raw())
        );
        let current = proxy.get_current().await.unwrap();
        assert_eq!(current.metadata, themes[0]);
        assert_eq!(
            current.canonical_package.as_slice(),
            production_authority().current().canonical_package.as_ref()
        );
    }

    #[fuchsia::test]
    async fn proxy_unequal_watch_replies_immediately() {
        let snapshot = proxy(production_authority())
            .watch_current(0)
            .await
            .unwrap();
        assert_eq!(snapshot.generation, 1);
    }

    #[fuchsia::test]
    async fn proxy_equal_watch_stays_pending_until_disconnect() {
        let proxy = proxy(production_authority());
        let mut watch = Box::pin(proxy.watch_current(1));
        assert!(futures::poll!(&mut watch).is_pending());
        drop(watch);
        drop(proxy);
    }

    #[fuchsia::test]
    async fn proxy_duplicate_watch_closes_with_bad_state() {
        let proxy = proxy(production_authority());
        let (first, second) = futures::join!(proxy.watch_current(1), proxy.watch_current(1));
        for result in [first, second] {
            assert!(
                matches!(result, Err(fidl::Error::ClientChannelClosed { epitaph, .. }) if epitaph == zx_status::Status::BAD_STATE),
                "unexpected duplicate-watch result: {result:?}"
            );
        }
    }

    #[fuchsia::test]
    async fn two_proxies_park_and_disconnect_independently() {
        let authority = production_authority();
        let first = proxy(authority.clone());
        let second = proxy(authority);
        let mut first_watch = Box::pin(first.watch_current(1));
        let mut second_watch = Box::pin(second.watch_current(1));
        assert!(futures::poll!(&mut first_watch).is_pending());
        assert!(futures::poll!(&mut second_watch).is_pending());
        drop(first_watch);
        drop(first);
        assert!(futures::poll!(&mut second_watch).is_pending());
        drop(second_watch);
        drop(second);
    }

    #[fuchsia::test]
    async fn restart_reconnect_get_current_then_watch() {
        let first = proxy(production_authority());
        assert_eq!(first.get_current().await.unwrap().generation, 1);
        drop(first); // old process channel closes before reconnect

        let second = proxy(Arc::new(Authority::from_packaged([DTCG])));
        // Contractual reconnect sequence: GetCurrent first, then watch the new generation.
        let current = second.get_current().await.unwrap();
        let snapshot = second.watch_current(current.generation + 1).await.unwrap();
        assert_eq!(snapshot.generation, current.generation);
        assert_eq!(snapshot.metadata.id, "instrument-studio");
    }
}

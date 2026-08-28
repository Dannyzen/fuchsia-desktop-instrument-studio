use fidl_fuchsia_instrumentstudio_theme as ftheme;
use fuchsia_inspect::{Node, UintProperty};
use std::collections::BTreeMap;
use std::sync::Arc;
use theme_model::NativeThemeV1;

pub const FALLBACK_THEME_ID: &str = "instrument-studio-builtin";
pub const MAX_DIAGNOSTIC_ERROR_BYTES: usize = 96;

fn bounded_diagnostic_error(error: &str) -> &str {
    &error[..error.len().min(MAX_DIAGNOSTIC_ERROR_BYTES)]
}

#[derive(Debug, Eq, PartialEq)]
pub enum WatchAction<R> {
    Reply(R),
    Parked,
    BadState,
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
            WatchAction::BadState
        } else {
            self.pending = Some((observed, responder));
            WatchAction::Parked
        }
    }

    #[cfg(test)]
    pub fn drain_if_changed(&mut self, current: u64) -> Option<R> {
        if self.pending.as_ref().is_some_and(|(observed, _)| *observed != current) {
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
            canonical_package: Arc::from([]),
        }
    }
}

/// Process-local read authority. No storage or mutation capability is held.
pub struct Authority {
    themes: BTreeMap<String, Snapshot>,
    current: Snapshot,
    load_error_code: Option<&'static str>,
}

impl Authority {
    pub fn from_packaged<'a>(packages: impl IntoIterator<Item = &'a [u8]>) -> Self {
        let mut themes = BTreeMap::new();
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
                        canonical_package: Arc::from(bytes),
                    };
                    themes.insert(snapshot.id.clone(), snapshot);
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
        }
    }

    pub fn current(&self) -> Snapshot {
        self.current.clone()
    }
    pub fn themes(&self) -> impl Iterator<Item = &Snapshot> {
        self.themes.values()
    }
}

pub struct Diagnostics {
    _node: Node,
    _generation: UintProperty,
    _valid_theme_count: UintProperty,
}

impl Diagnostics {
    pub fn record(root: &Node, authority: &Authority) -> Self {
        let node = root.create_child("native_theme");
        let generation = node.create_uint("generation", authority.current.generation);
        let count = node.create_uint("valid_theme_count", authority.themes.len() as u64);
        node.record_string("active_theme_id", authority.current.id.as_str());
        node.record_string(
            "load_status",
            if authority.themes.is_empty() {
                "fallback"
            } else {
                "ok"
            },
        );
        let error = authority.load_error_code.unwrap_or("none");
        node.record_string(
            "load_error_code",
            bounded_diagnostic_error(error),
        );
        Self {
            _node: node,
            _generation: generation,
            _valid_theme_count: count,
        }
    }
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
        canonical_package: snapshot.canonical_package.to_vec(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    const VALID: &[u8] = include_bytes!("../../theme_model/testdata/native-theme-v1-package.json");

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
        assert_eq!(state.observe(1, 1, 8), WatchAction::BadState);
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
        assert_eq!(state.observe(2, 1, "greater"), WatchAction::Reply("greater"));
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
            fn drop(&mut self) { self.0.fetch_add(1, Ordering::SeqCst); }
        }
        let drops = Arc::new(AtomicUsize::new(0));
        let mut first = ConnectionWatch::default();
        let mut second = ConnectionWatch::default();
        assert!(matches!(first.observe(1, 1, Token(drops.clone())), WatchAction::Parked));
        assert!(matches!(second.observe(1, 1, Token(drops.clone())), WatchAction::Parked));
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
        assert_eq!(bounded_diagnostic_error(&error).len(), MAX_DIAGNOSTIC_ERROR_BYTES);
    }
}

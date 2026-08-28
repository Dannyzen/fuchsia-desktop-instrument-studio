use fidl::endpoints::RequestStream;
use fidl_fuchsia_instrumentstudio_theme as ftheme;
use fuchsia_inspect::{Node, UintProperty};
use futures::TryStreamExt;
use std::collections::BTreeMap;
use std::sync::Arc;
use theme_model::NativeThemeV1;

pub const FALLBACK_THEME_ID: &str = "instrument-studio-builtin";
pub const MAX_DIAGNOSTIC_ERROR_BYTES: usize = 96;
pub const E_DUPLICATE_THEME_ID: &str = "E_DUPLICATE_THEME_ID";

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
        }
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
}

/// Serves one generated-FIDL connection using connection-local hanging-get state.
pub async fn serve_native_theme(
    authority: Arc<Authority>,
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
                responder.send(&to_fidl(&authority.current()))?
            }
            ftheme::NativeThemeRequest::WatchCurrent {
                observed_generation,
                responder,
            } => {
                let current = authority.current();
                match watch_state.observe(observed_generation, current.generation, responder) {
                    WatchAction::Reply(responder) => responder.send(&to_fidl(&current))?,
                    WatchAction::Parked => {}
                    WatchAction::BadState(_responder) => {
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
        node.record_string("load_error_code", bounded_diagnostic_error(error));
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

    fn proxy(authority: Arc<Authority>) -> ftheme::NativeThemeProxy {
        let (proxy, stream) = create_proxy_and_stream::<ftheme::NativeThemeMarker>();
        fuchsia_async::Task::local(async move {
            serve_native_theme(authority, stream)
                .await
                .expect("serve generated FIDL");
        })
        .detach();
        proxy
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

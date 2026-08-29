//! Bounded, code-only lifecycle diagnostics for the native theme authority.

use super::{Authority, FALLBACK_THEME_ID, SELECTION_LAST_KNOWN_GOOD, persistence};
use fuchsia_inspect::{Node, Property, StringProperty, UintProperty};
use std::sync::Mutex;

pub const DIAGNOSTICS_SCHEMA_VERSION: u64 = 1;
pub const MAX_DIAGNOSTIC_CODE_BYTES: usize = 32;
pub const MAX_DIAGNOSTIC_ID_BYTES: usize = 64;
pub const SEMANTIC_HASH_PREFIX_BYTES: usize = 8;
pub const MAX_RECEIPT_BYTES: usize = 1280;

pub const JOURNEY_CRASH: &str = "crash";
pub const JOURNEY_RESTART: &str = "restart";
pub const JOURNEY_CORRUPT_STATE: &str = "corrupt-state";
pub const JOURNEY_INVALID_THEME: &str = "invalid-theme";
pub const JOURNEY_STALE_CONSUMER: &str = "stale-consumer";
pub const JOURNEY_RECOVERY: &str = "recovery";
pub const JOURNEY_SHELL_SURVIVAL: &str = "shell-survival";
pub const EVENT_STARTUP_ACTIVE: &str = "startup-active";
pub const EVENT_STARTUP_RECOVERED: &str = "startup-recovered";
pub const EVENT_SELECTION_STAGED: &str = "selection-staged";
pub const EVENT_RESTORE_STAGED: &str = "restore-staged";
pub const EVENT_MIGRATION_STAGED: &str = "migration-staged";
pub const EVENT_LKG_RECORDED: &str = "lkg-recorded";
pub const EVENT_CONSUMER_ACK: &str = "consumer-ack";
pub const EVENT_CONSUMER_STALE: &str = "consumer-stale";
pub const EVENT_PROCESS_CRASH: &str = "process-crash";
pub const EVENT_RECOVERY_COMPLETE: &str = "recovery-complete";
pub const EVENT_SHELL_SURVIVED: &str = "shell-survived";
pub const RESULT_OK: &str = "ok";
pub const RESULT_RECOVERED: &str = "recovered";
pub const RESULT_REJECTED: &str = "rejected";
pub const RESULT_STORAGE_ERROR: &str = "storage-error";

fn bounded(value: &str, limit: usize) -> String {
    value
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || "-_.".contains(*c))
        .take(limit)
        .collect()
}
fn code(value: &str) -> String {
    bounded(value, MAX_DIAGNOSTIC_CODE_BYTES)
}
fn id(value: &str) -> String {
    bounded(value, MAX_DIAGNOSTIC_ID_BYTES)
}
fn hash_prefix(hash: &[u8; 32]) -> String {
    hash[..SEMANTIC_HASH_PREFIX_BYTES]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
fn variant(value: persistence::Variant) -> &'static str {
    match value {
        persistence::Variant::Light => "light",
        persistence::Variant::Dark => "dark",
        persistence::Variant::HighContrast => "high-contrast",
    }
}
fn result_code(result: &Result<(), zx_status::Status>) -> &'static str {
    match result {
        Ok(()) => RESULT_OK,
        Err(status)
            if *status == zx_status::Status::IO
                || *status == zx_status::Status::IO_DATA_INTEGRITY =>
        {
            RESULT_STORAGE_ERROR
        }
        Err(_) => RESULT_REJECTED,
    }
}

#[derive(Clone)]
struct Receipt {
    journey_code: String,
    event_code: String,
    result_code: String,
    active_theme_id: String,
    selected_theme_id: String,
    fallback_theme_id: String,
    last_known_good_theme_id: String,
    theme_revision: u64,
    theme_variant: String,
    semantic_sha256_prefix: String,
    generation: u64,
    validation_result_code: String,
    selection_source: String,
    selection_error_code: String,
    consumer_ack_count: u64,
    last_ack_generation: u64,
    elapsed_micros: u64,
    resource_result_code: String,
}

impl Receipt {
    fn machine_receipt(&self) -> String {
        // Every string enters through `bounded`; fixed field order makes this deterministic.
        let receipt = format!(
            concat!(
                "{{\"schema_version\":{},\"journey_code\":\"{}\",\"event_code\":\"{}\",\"result_code\":\"{}\",",
                "\"active_theme_id\":\"{}\",\"selected_theme_id\":\"{}\",\"fallback_theme_id\":\"{}\",",
                "\"last_known_good_theme_id\":\"{}\",\"theme_revision\":{},\"theme_variant\":\"{}\",",
                "\"semantic_sha256_prefix\":\"{}\",\"generation\":{},\"validation_result_code\":\"{}\",",
                "\"selection_source\":\"{}\",\"selection_error_code\":\"{}\",\"consumer_ack_count\":{},",
                "\"last_ack_generation\":{},\"elapsed_micros\":{},\"resource_result_code\":\"{}\"}}"
            ),
            DIAGNOSTICS_SCHEMA_VERSION,
            self.journey_code,
            self.event_code,
            self.result_code,
            self.active_theme_id,
            self.selected_theme_id,
            self.fallback_theme_id,
            self.last_known_good_theme_id,
            self.theme_revision,
            self.theme_variant,
            self.semantic_sha256_prefix,
            self.generation,
            self.validation_result_code,
            self.selection_source,
            self.selection_error_code,
            self.consumer_ack_count,
            self.last_ack_generation,
            self.elapsed_micros,
            self.resource_result_code
        );
        assert!(receipt.len() <= MAX_RECEIPT_BYTES);
        receipt
    }
}

struct Inner {
    receipt: Receipt,
    _active_theme_id: StringProperty,
    selected_theme_id: StringProperty,
    last_known_good_theme_id: StringProperty,
    selection_error_code: StringProperty,
    consumer_ack_count: UintProperty,
    last_ack_generation: UintProperty,
    elapsed_micros: UintProperty,
    resource_result_code: StringProperty,
    last_receipt: StringProperty,
}

pub struct Diagnostics {
    _node: Node,
    inner: Mutex<Inner>,
}

impl Diagnostics {
    pub fn record(root: &Node, authority: &Authority, state_bytes: Option<&[u8]>) -> Self {
        let current = authority.current();
        let persisted = state_bytes.and_then(|bytes| persistence::decode(bytes).ok());
        let selected = persisted
            .as_ref()
            .and_then(|state| state.pending.as_ref())
            .map(|i| id(&i.theme_id))
            .unwrap_or_default();
        let lkg = persisted
            .as_ref()
            .map(|state| id(&state.last_known_good.theme_id))
            .unwrap_or_default();
        let recovered = authority.selection_error_code().is_some()
            || authority.load_error_code().is_some()
            || authority.selection_source() == SELECTION_LAST_KNOWN_GOOD;
        let journey = if authority
            .selection_error_code()
            .is_some_and(|value| value.starts_with("E_STATE_"))
        {
            JOURNEY_CORRUPT_STATE
        } else if authority.load_error_code().is_some()
            || authority.selection_error_code().is_some_and(|value| {
                value == super::E_SELECTED_IDENTITY_INVALID
                    || value == super::E_SELECTION_HISTORY_INVALID
            })
        {
            JOURNEY_INVALID_THEME
        } else if recovered {
            JOURNEY_RECOVERY
        } else {
            JOURNEY_RESTART
        };
        let receipt = Receipt {
            journey_code: code(journey),
            event_code: code(if recovered {
                EVENT_STARTUP_RECOVERED
            } else {
                EVENT_STARTUP_ACTIVE
            }),
            result_code: code(if recovered {
                RESULT_RECOVERED
            } else {
                RESULT_OK
            }),
            active_theme_id: id(&current.id),
            selected_theme_id: selected,
            fallback_theme_id: id(FALLBACK_THEME_ID),
            last_known_good_theme_id: lkg,
            theme_revision: current.revision,
            theme_variant: code(variant(current.variant)),
            semantic_sha256_prefix: hash_prefix(&current.semantic_sha256),
            generation: current.generation,
            validation_result_code: code(authority.load_error_code().unwrap_or(RESULT_OK)),
            selection_source: code(authority.selection_source()),
            selection_error_code: code(authority.selection_error_code().unwrap_or("none")),
            consumer_ack_count: 0,
            last_ack_generation: 0,
            elapsed_micros: 0,
            resource_result_code: code("not-served"),
        };
        let node = root.create_child("native_theme");
        node.record_uint("schema_version", DIAGNOSTICS_SCHEMA_VERSION);
        let active_theme_id = node.create_string("active_theme_id", &receipt.active_theme_id);
        let selected_theme_id = node.create_string("selected_theme_id", &receipt.selected_theme_id);
        node.record_string("fallback_theme_id", &receipt.fallback_theme_id);
        let last_known_good_theme_id = node.create_string(
            "last_known_good_theme_id",
            &receipt.last_known_good_theme_id,
        );
        node.record_uint("theme_revision", receipt.theme_revision);
        node.record_string("theme_variant", &receipt.theme_variant);
        node.record_string("semantic_sha256_prefix", &receipt.semantic_sha256_prefix);
        node.record_uint("generation", receipt.generation);
        node.record_string("validation_result_code", &receipt.validation_result_code);
        node.record_string("selection_source", &receipt.selection_source);
        let selection_error_code =
            node.create_string("selection_error_code", &receipt.selection_error_code);
        let consumer_ack_count = node.create_uint("consumer_ack_count", 0);
        let last_ack_generation = node.create_uint("last_ack_generation", 0);
        let elapsed_micros = node.create_uint("elapsed_micros", 0);
        let resource_result_code =
            node.create_string("resource_result_code", &receipt.resource_result_code);
        let initial_receipt = receipt.machine_receipt();
        log::info!(
            target: "native_theme_lifecycle",
            "NATIVE_THEME_LIFECYCLE_RECEIPT {}",
            initial_receipt
        );
        let last_receipt = node.create_string("last_receipt", &initial_receipt);
        Self {
            _node: node,
            inner: Mutex::new(Inner {
                receipt,
                _active_theme_id: active_theme_id,
                selected_theme_id,
                last_known_good_theme_id,
                selection_error_code,
                consumer_ack_count,
                last_ack_generation,
                elapsed_micros,
                resource_result_code,
                last_receipt,
            }),
        }
    }
    fn update(inner: &mut Inner, journey: &str, event: &str, result: &str) {
        inner.receipt.journey_code = code(journey);
        inner.receipt.event_code = code(event);
        inner.receipt.result_code = code(result);
        let receipt = inner.receipt.machine_receipt();
        inner.last_receipt.set(&receipt);
        log::info!(
            target: "native_theme_lifecycle",
            "NATIVE_THEME_LIFECYCLE_RECEIPT {}",
            receipt
        );
    }
    fn settings(
        &self,
        event: &str,
        result: &Result<(), zx_status::Status>,
        state: Option<&persistence::PersistedState>,
    ) {
        let mut inner = self.inner.lock().unwrap();
        if let Some(state) = state {
            inner.receipt.selected_theme_id = state
                .pending
                .as_ref()
                .map(|identity| id(&identity.theme_id))
                .unwrap_or_default();
            inner.receipt.last_known_good_theme_id = id(&state.last_known_good.theme_id);
            inner
                .selected_theme_id
                .set(&inner.receipt.selected_theme_id);
            inner
                .last_known_good_theme_id
                .set(&inner.receipt.last_known_good_theme_id);
        }
        inner.receipt.selection_error_code = code(if result.is_ok() {
            "none"
        } else {
            result_code(result)
        });
        inner
            .selection_error_code
            .set(&inner.receipt.selection_error_code);
        inner.receipt.resource_result_code = code(result_code(result));
        inner
            .resource_result_code
            .set(&inner.receipt.resource_result_code);
        Self::update(&mut inner, JOURNEY_RESTART, event, result_code(result));
    }
    pub fn record_selection_result(
        &self,
        result: &Result<(), zx_status::Status>,
        state: &persistence::PersistedState,
    ) {
        self.settings(EVENT_SELECTION_STAGED, result, Some(state));
    }
    pub fn record_restore_result(
        &self,
        result: &Result<(), zx_status::Status>,
        state: &persistence::PersistedState,
    ) {
        self.settings(EVENT_RESTORE_STAGED, result, Some(state));
    }
    pub fn record_migration_result(
        &self,
        result: &Result<(), zx_status::Status>,
        state: Option<&persistence::PersistedState>,
    ) {
        self.settings(EVENT_MIGRATION_STAGED, result, state);
    }
    pub fn record_last_known_good_result(
        &self,
        result: &Result<(), zx_status::Status>,
        state: Option<&persistence::PersistedState>,
    ) {
        self.settings(EVENT_LKG_RECORDED, result, state);
    }
    pub fn record_consumer_ack(&self, generation: u64) {
        let mut inner = self.inner.lock().unwrap();
        inner.receipt.consumer_ack_count += 1;
        inner.receipt.last_ack_generation = generation;
        inner
            .consumer_ack_count
            .set(inner.receipt.consumer_ack_count);
        inner.last_ack_generation.set(generation);
        Self::update(&mut inner, JOURNEY_RESTART, EVENT_CONSUMER_ACK, RESULT_OK);
    }
    pub fn record_consumer_stale(&self, generation: u64) {
        let mut inner = self.inner.lock().unwrap();
        inner.receipt.last_ack_generation = generation;
        inner.last_ack_generation.set(generation);
        Self::update(
            &mut inner,
            JOURNEY_STALE_CONSUMER,
            EVENT_CONSUMER_STALE,
            RESULT_REJECTED,
        );
    }
    pub fn record_shell_survival(&self, elapsed_micros: u64) {
        let mut inner = self.inner.lock().unwrap();
        inner.receipt.elapsed_micros = elapsed_micros;
        inner.elapsed_micros.set(elapsed_micros);
        inner.receipt.resource_result_code = code(RESULT_OK);
        inner.resource_result_code.set(RESULT_OK);
        Self::update(
            &mut inner,
            JOURNEY_SHELL_SURVIVAL,
            EVENT_SHELL_SURVIVED,
            RESULT_OK,
        );
    }
    pub fn record_process_crash(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.receipt.resource_result_code = code(RESULT_REJECTED);
        inner.resource_result_code.set(RESULT_REJECTED);
        Self::update(
            &mut inner,
            JOURNEY_CRASH,
            EVENT_PROCESS_CRASH,
            RESULT_REJECTED,
        );
    }
    pub fn record_recovery(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.receipt.resource_result_code = code(RESULT_RECOVERED);
        inner.resource_result_code.set(RESULT_RECOVERED);
        Self::update(
            &mut inner,
            JOURNEY_RECOVERY,
            EVENT_RECOVERY_COMPLETE,
            RESULT_RECOVERED,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const VALID: &[u8] = include_bytes!("../../theme_model/testdata/native-theme-v1-package.json");
    fn diagnostics(bytes: Option<&[u8]>) -> Diagnostics {
        let inspector = fuchsia_inspect::Inspector::default();
        let authority = Authority::from_packaged_and_state([VALID], bytes);
        Diagnostics::record(inspector.root(), &authority, bytes)
    }
    #[test]
    fn receipt_is_deterministic_and_bounded() {
        let a = diagnostics(None);
        let b = diagnostics(None);
        let x = a.inner.lock().unwrap().receipt.machine_receipt();
        let y = b.inner.lock().unwrap().receipt.machine_receipt();
        assert_eq!(x, y);
        assert!(x.len() <= MAX_RECEIPT_BYTES);
    }
    #[test]
    fn identifiers_are_bounded() {
        let value = id(&format!("{}../", "x".repeat(200)));
        assert!(value.len() <= MAX_DIAGNOSTIC_ID_BYTES);
        assert!(!value.contains('/'));
    }
    #[test]
    fn receipt_never_contains_payload_or_path() {
        let d = diagnostics(None);
        let receipt = d.inner.lock().unwrap().receipt.machine_receipt();
        assert!(!receipt.contains(&["canonical", "package"].join("_")));
        assert!(!receipt.contains("/data/"));
    }
    #[test]
    fn recovery_is_distinct_from_normal_activation() {
        let normal = diagnostics(None);
        let recovered = diagnostics(Some(b"corrupt payload /data/secret"));
        assert_ne!(
            normal.inner.lock().unwrap().receipt.event_code,
            recovered.inner.lock().unwrap().receipt.event_code
        );
    }
    #[test]
    fn runtime_event_updates_receipt() {
        let d = diagnostics(None);
        d.record_consumer_ack(7);
        let inner = d.inner.lock().unwrap();
        assert_eq!(inner.receipt.consumer_ack_count, 1);
        assert_eq!(inner.receipt.last_ack_generation, 7);
        assert!(inner.receipt.machine_receipt().contains(EVENT_CONSUMER_ACK));
    }
    fn identity(theme_id: &str) -> persistence::Identity {
        let authority = Authority::from_packaged([VALID]);
        let current = authority.current();
        persistence::Identity {
            theme_id: theme_id.into(),
            variant: current.variant,
            semantic_sha256: current.semantic_sha256,
        }
    }
    #[test]
    fn corrupt_state_receipt_names_corrupt_journey() {
        let d = diagnostics(Some(b"corrupt"));
        assert_eq!(
            d.inner.lock().unwrap().receipt.journey_code,
            JOURNEY_CORRUPT_STATE
        );
    }
    #[test]
    fn invalid_selected_receipt_names_invalid_theme_journey() {
        let state = persistence::PersistedState {
            pending: Some(identity("missing-theme")),
            last_known_good: identity("instrument-studio"),
        };
        let bytes = persistence::encode(&state).unwrap();
        let d = diagnostics(Some(&bytes));
        assert_eq!(
            d.inner.lock().unwrap().receipt.journey_code,
            JOURNEY_INVALID_THEME
        );
    }
    #[test]
    fn storage_result_and_timing_are_observable() {
        let d = diagnostics(None);
        let state = persistence::PersistedState {
            pending: None,
            last_known_good: identity("instrument-studio"),
        };
        d.record_selection_result(&Err(zx_status::Status::IO), &state);
        assert_eq!(
            d.inner.lock().unwrap().receipt.resource_result_code,
            RESULT_STORAGE_ERROR
        );
        d.record_shell_survival(37);
        assert_eq!(d.inner.lock().unwrap().receipt.elapsed_micros, 37);
    }
    #[test]
    fn successful_lkg_promotion_updates_retained_identity() {
        let d = diagnostics(None);
        let state = persistence::PersistedState {
            pending: Some(identity("new-theme")),
            last_known_good: identity("new-theme"),
        };
        d.record_last_known_good_result(&Ok(()), Some(&state));
        let inner = d.inner.lock().unwrap();
        assert_eq!(inner.receipt.last_known_good_theme_id, "new-theme");
        assert_eq!(inner.receipt.resource_result_code, RESULT_OK);
        assert_eq!(inner.receipt.event_code, EVENT_LKG_RECORDED);
    }
    #[test]
    fn crash_journey_has_a_machine_receipt_hook() {
        let d = diagnostics(None);
        d.record_process_crash();
        let inner = d.inner.lock().unwrap();
        assert_eq!(inner.receipt.journey_code, JOURNEY_CRASH);
        assert!(inner.receipt.machine_receipt().contains(JOURNEY_CRASH));
    }
    #[test]
    fn required_runtime_journey_hooks_emit_distinct_receipts() {
        let d = diagnostics(None);
        d.record_consumer_stale(1);
        assert_eq!(
            d.inner.lock().unwrap().receipt.journey_code,
            JOURNEY_STALE_CONSUMER
        );
        d.record_recovery();
        assert_eq!(
            d.inner.lock().unwrap().receipt.journey_code,
            JOURNEY_RECOVERY
        );
        d.record_shell_survival(9);
        assert_eq!(
            d.inner.lock().unwrap().receipt.journey_code,
            JOURNEY_SHELL_SURVIVAL
        );
        d.record_process_crash();
        assert_eq!(d.inner.lock().unwrap().receipt.journey_code, JOURNEY_CRASH);
    }
    #[test]
    fn receipt_max_values_are_json_safe_and_bounded() {
        let max_id = "x".repeat(MAX_DIAGNOSTIC_ID_BYTES);
        let max_code = "C".repeat(MAX_DIAGNOSTIC_CODE_BYTES);
        let receipt = Receipt {
            journey_code: max_code.clone(),
            event_code: max_code.clone(),
            result_code: max_code.clone(),
            active_theme_id: max_id.clone(),
            selected_theme_id: max_id.clone(),
            fallback_theme_id: max_id.clone(),
            last_known_good_theme_id: max_id,
            theme_revision: u64::MAX,
            theme_variant: max_code.clone(),
            semantic_sha256_prefix: "f".repeat(SEMANTIC_HASH_PREFIX_BYTES * 2),
            generation: u64::MAX,
            validation_result_code: max_code.clone(),
            selection_source: max_code.clone(),
            selection_error_code: max_code.clone(),
            consumer_ack_count: u64::MAX,
            last_ack_generation: u64::MAX,
            elapsed_micros: u64::MAX,
            resource_result_code: max_code,
        };
        let encoded = receipt.machine_receipt();
        assert!(encoded.starts_with('{') && encoded.ends_with('}'));
        assert_eq!(encoded.matches("\"schema_version\"").count(), 1);
        assert!(!encoded.contains('\n'));
        assert!(encoded.len() <= MAX_RECEIPT_BYTES);
        println!("MAX_RECEIPT_JSON={encoded}");
    }
}

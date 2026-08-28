//! Strict, immutable NativeThemeV1 package decoding.

mod codec;
mod validate;

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::error::Error;
use std::fmt;

pub const SOURCE_BYTES_LIMIT: usize = 1_048_576;
pub const COMPILED_PACK_BYTES_LIMIT: usize = 262_144;
pub const CATALOG_BYTES_LIMIT: usize = 8_388_608;
pub const TOKEN_LIMIT: usize = 1_024;
pub const ALIAS_LIMIT: usize = 2_048;
pub const ALIAS_DEPTH_LIMIT: usize = 32;
pub const NESTING_LIMIT: usize = 32;
pub const STRING_BYTES_LIMIT: usize = 4_096;
pub const SEMANTIC_ASSET_LIMIT: usize = 64;
pub const DECODED_ASSET_BYTES_LIMIT: usize = 524_288;
pub const DECODED_ASSETS_TOTAL_BYTES_LIMIT: usize = 4_194_304;
pub const RUNTIME_SNAPSHOT_BYTES_LIMIT: usize = 524_288;
pub(crate) const COMPILED_PACK_BYTES_UNIT: &str =
    "canonical_utf8_package_file_bytes_including_final_lf";
pub(crate) const RUNTIME_SNAPSHOT_BYTES_UNIT: &str =
    "retained_canonical_utf8_package_file_bytes_including_final_lf";
pub(crate) const LIMIT_RELATIONS: [(&str, &str, usize, &str); 1] = [(
    "compiled_pack_bytes",
    "runtime_snapshot_bytes",
    0,
    "compiled_pack_bytes <= runtime_snapshot_bytes",
)];

const _: () = assert!(COMPILED_PACK_BYTES_LIMIT <= RUNTIME_SNAPSHOT_BYTES_LIMIT);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ThemeError {
    code: &'static str,
    message: &'static str,
}

impl ThemeError {
    pub fn code(&self) -> &'static str {
        self.code
    }

    pub fn message(&self) -> &'static str {
        self.message
    }
}

impl fmt::Display for ThemeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for ThemeError {}

pub(crate) fn reject<T>(code: &'static str, message: &'static str) -> Result<T, ThemeError> {
    Err(ThemeError { code, message })
}

/// An immutable, fully validated NativeThemeV1 package.
#[derive(Clone, Debug)]
pub struct NativeThemeV1 {
    value: Value,
    canonical_bytes: Box<[u8]>,
    semantic_sha256: [u8; 32],
}

impl NativeThemeV1 {
    pub fn decode_canonical(bytes: &[u8]) -> Result<Self, ThemeError> {
        let value = codec::decode_canonical_value(bytes)?;
        assert!(
            bytes.len() <= RUNTIME_SNAPSHOT_BYTES_LIMIT,
            "compiled package escaped runtime snapshot dominance"
        );
        validate::validate_package(&value)?;
        let semantic_sha256 = semantic_digest(&value)?;
        let declared = value["metadata"]["provenance"]["semantic_hash"]
            .as_str()
            .expect("validated semantic hash");
        if declared != format!("sha256:{}", hex::encode(semantic_sha256)) {
            return reject("E_HASH", "semantic identity hash mismatch");
        }
        Ok(Self {
            value,
            canonical_bytes: bytes.into(),
            semantic_sha256,
        })
    }

    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    pub fn runtime_snapshot_bytes(&self) -> usize {
        self.canonical_bytes.len()
    }

    pub fn semantic_sha256(&self) -> [u8; 32] {
        self.semantic_sha256
    }

    pub fn semantic_sha256_hex(&self) -> String {
        hex::encode(self.semantic_sha256)
    }

    pub fn schema_version(&self) -> &str {
        self.value["schema_version"]
            .as_str()
            .expect("validated schema version")
    }

    pub fn profile_name(&self) -> &str {
        self.value["profile"]["name"]
            .as_str()
            .expect("validated profile name")
    }

    pub fn profile_version(&self) -> &str {
        self.value["profile"]["version"]
            .as_str()
            .expect("validated profile version")
    }

    pub fn theme_id(&self) -> &str {
        self.value["theme"]["id"]
            .as_str()
            .expect("validated theme id")
    }

    pub fn display_name(&self) -> &str {
        self.value["theme"]["display_name"]
            .as_str()
            .expect("validated display name")
    }

    pub fn revision(&self) -> u64 {
        self.value["theme"]["revision"]
            .as_u64()
            .expect("validated revision")
    }

    pub fn variants(&self) -> &Map<String, Value> {
        self.value["variants"]
            .as_object()
            .expect("validated variants")
    }

    pub fn variant(&self, name: &str) -> Option<&Value> {
        self.variants().get(name)
    }

    pub fn fallback(&self) -> &Value {
        &self.value["fallback"]
    }

    pub fn policy(&self) -> &Value {
        &self.value["policy"]
    }

    pub fn metadata(&self) -> &Value {
        &self.value["metadata"]
    }

    pub fn metadata_extensions(&self) -> &Map<String, Value> {
        self.value["metadata"]["extensions"]
            .as_object()
            .expect("validated metadata extensions")
    }
}

fn semantic_digest(value: &Value) -> Result<[u8; 32], ThemeError> {
    let mut projected = value.clone();
    projected
        .as_object_mut()
        .expect("validated package object")
        .remove("metadata");
    let bytes = codec::canonical_json_bytes(&projected)?;
    let digest = Sha256::digest(bytes);
    let mut output = [0u8; 32];
    output.copy_from_slice(&digest);
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::{
        COMPILED_PACK_BYTES_LIMIT, COMPILED_PACK_BYTES_UNIT, LIMIT_RELATIONS, NativeThemeV1,
        RUNTIME_SNAPSHOT_BYTES_LIMIT, RUNTIME_SNAPSHOT_BYTES_UNIT, STRING_BYTES_LIMIT,
    };
    use serde_json::{Map, Value};
    use sha2::{Digest, Sha256};

    const GOLDEN: &[u8] = include_bytes!("../testdata/native-theme-v1-package.json");
    const GOLDEN_BYTE_HASH: &str =
        "f1975d2511b5b4c711ef8b299389a07793b3113077cad32bb8272dcde7b1738b";
    const GOLDEN_SEMANTIC_HASH: &str =
        "5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a";

    fn code(bytes: &[u8]) -> &'static str {
        NativeThemeV1::decode_canonical(bytes).unwrap_err().code()
    }

    fn golden_value() -> Value {
        serde_json::from_slice(GOLDEN).unwrap()
    }

    fn canonical_with_hash(mut value: Value) -> Vec<u8> {
        let mut projected = value.clone();
        projected.as_object_mut().unwrap().remove("metadata");
        let semantic_bytes = super::codec::canonical_json_bytes(&projected).unwrap();
        let semantic_hash = format!("sha256:{}", hex::encode(Sha256::digest(&semantic_bytes)));
        value["metadata"]["provenance"]["semantic_hash"] = Value::String(semantic_hash);
        let mut bytes = super::codec::canonical_json_bytes(&value).unwrap();
        bytes.push(b'\n');
        bytes
    }

    fn package_with_exact_length(target: usize) -> Vec<u8> {
        const PADDING_ITERATION_CAP: usize = 128;
        const PADDING_PREFIX: &str = "org.constructresearch.instrumentstudio.boundary_padding_";

        let mut value = golden_value();
        let baseline = canonical_with_hash(value.clone());
        assert_eq!(baseline, GOLDEN);
        assert!(target >= baseline.len());

        // Every ASCII string entry adds one comma, two key quotes, a colon, and two value
        // quotes. Find a bounded number of entries whose combined string capacity reaches
        // the target, then serialize only once after distributing the exact payload.
        let mut empty_entry_bytes = 0usize;
        let mut selected = None;
        for index in 0..PADDING_ITERATION_CAP {
            let key = format!("{PADDING_PREFIX}{index:03}");
            empty_entry_bytes += key.len() + 6;
            if target >= baseline.len() + empty_entry_bytes {
                let payload_bytes = target - baseline.len() - empty_entry_bytes;
                if payload_bytes <= (index + 1) * STRING_BYTES_LIMIT {
                    selected = Some((index + 1, payload_bytes));
                    break;
                }
            }
        }
        let (chunk_count, mut payload_bytes) = selected.unwrap_or_else(|| {
            panic!(
                "exact package length {target} was not reachable within {PADDING_ITERATION_CAP} padding entries"
            )
        });
        let extensions = value["metadata"]["extensions"].as_object_mut().unwrap();
        for index in 0..chunk_count {
            let chunk_bytes = payload_bytes.min(STRING_BYTES_LIMIT);
            payload_bytes -= chunk_bytes;
            let key = format!("{PADDING_PREFIX}{index:03}");
            assert!(extensions
                .insert(key, Value::String("x".repeat(chunk_bytes)))
                .is_none());
        }
        assert_eq!(payload_bytes, 0, "padding payload was not exhausted");

        super::validate::validate_package(&value).unwrap();
        let declared = value["metadata"]["provenance"]["semantic_hash"]
            .as_str()
            .unwrap();
        assert_eq!(
            declared,
            format!(
                "sha256:{}",
                hex::encode(super::semantic_digest(&value).unwrap())
            )
        );
        let bytes = canonical_with_hash(value);
        assert_eq!(bytes.len(), target);
        assert_eq!(
            bytes
                .iter()
                .rev()
                .take_while(|byte| **byte == b'\n')
                .count(),
            1
        );
        bytes
    }

    #[test]
    fn semantic_identity_excludes_inert_metadata_only() {
        let baseline = NativeThemeV1::decode_canonical(GOLDEN).unwrap();
        let mut metadata_only = golden_value();
        metadata_only["metadata"]["provenance"]["source_identity"] =
            Value::String("profiles/other-source.json".to_string());
        metadata_only["metadata"]["provenance"]["content_hash"] =
            Value::String(format!("sha256:{}", "1".repeat(64)));
        metadata_only["metadata"]["provenance"]["license"] = Value::String("MIT".to_string());
        metadata_only["metadata"]["provenance"]["attribution"] =
            Value::String("Other contributor".to_string());
        metadata_only["metadata"]["license"]["spdx"] = Value::String("MIT".to_string());
        metadata_only["metadata"]["license"]["notice"] =
            Value::String("Other notice".to_string());
        metadata_only["metadata"]["extensions"] = serde_json::json!({
            "org.constructresearch.instrumentstudio.other": {"source": "different"}
        });
        let metadata_theme = NativeThemeV1::decode_canonical(&canonical_with_hash(metadata_only)).unwrap();
        assert_eq!(metadata_theme.semantic_sha256(), baseline.semantic_sha256());
        assert_ne!(metadata_theme.canonical_bytes(), baseline.canonical_bytes());

        let mut renderable = golden_value();
        renderable["variants"]["dark"]["primitives"]["accent"] =
            Value::String("#000000ff".to_string());
        let renderable_theme = NativeThemeV1::decode_canonical(&canonical_with_hash(renderable)).unwrap();
        assert_ne!(renderable_theme.semantic_sha256(), baseline.semantic_sha256());
    }

    #[test]
    fn golden_decode_hash_and_read_only_accessors() {
        assert_eq!(hex::encode(Sha256::digest(GOLDEN)), GOLDEN_BYTE_HASH);
        let theme = NativeThemeV1::decode_canonical(GOLDEN).unwrap();
        assert_eq!(theme.schema_version(), "1.0.0");
        assert_eq!(theme.profile_name(), "instrument-studio-dtcg-subset");
        assert_eq!(theme.profile_version(), "2025.10");
        assert_eq!(theme.theme_id(), "instrument-studio");
        assert_eq!(theme.display_name(), "Instrument Studio");
        assert_eq!(theme.revision(), 1);
        assert_eq!(theme.semantic_sha256_hex(), GOLDEN_SEMANTIC_HASH);
        assert_eq!(hex::encode(theme.semantic_sha256()), GOLDEN_SEMANTIC_HASH);
        assert_eq!(theme.runtime_snapshot_bytes(), GOLDEN.len());
        assert_eq!(
            theme.variant("dark").unwrap()["semantic"]["interaction.selection"],
            "#8150d6ff"
        );
        assert_eq!(theme.variants().len(), 3);
        assert_eq!(theme.fallback()["missing_token"], "fail");
        assert_eq!(theme.policy()["unknown_required_version"], "fail-closed");
        assert_eq!(theme.metadata()["license"]["spdx"], "BSD-3-Clause");
    }

    #[test]
    fn golden_round_trip_preserves_exact_bytes() {
        let theme = NativeThemeV1::decode_canonical(GOLDEN).unwrap();
        assert_eq!(theme.canonical_bytes(), GOLDEN);
        let decoded_again = NativeThemeV1::decode_canonical(theme.canonical_bytes()).unwrap();
        assert_eq!(decoded_again.canonical_bytes(), GOLDEN);
    }

    #[test]
    fn duplicate_keys_are_rejected_distinctly() {
        assert_eq!(
            code(b"{\"schema_version\":\"1.0.0\",\"schema_version\":\"1.0.0\"}\n"),
            "E_JSON_DUPLICATE"
        );
    }

    #[test]
    fn unknown_schema_and_profile_versions_fail_closed() {
        let schema = String::from_utf8(GOLDEN.to_vec()).unwrap().replace(
            "\"schema_version\":\"1.0.0\"",
            "\"schema_version\":\"2.0.0\"",
        );
        assert_eq!(code(schema.as_bytes()), "E_VERSION_REQUIRED");

        let profile = String::from_utf8(GOLDEN.to_vec())
            .unwrap()
            .replace("\"version\":\"2025.10\"", "\"version\":\"2026.1\"");
        assert_eq!(code(profile.as_bytes()), "E_VERSION_PROFILE");
    }

    #[test]
    fn additive_namespaced_metadata_is_preserved_exactly() {
        let mut value = golden_value();
        value["metadata"]["extensions"]["org.constructresearch.instrumentstudio.future"] =
            serde_json::json!({"enabled": true, "label": "Δ"});
        let bytes = canonical_with_hash(value);
        let theme = NativeThemeV1::decode_canonical(&bytes).unwrap();
        assert_eq!(theme.canonical_bytes(), bytes);
        assert_eq!(
            theme.metadata_extensions()["org.constructresearch.instrumentstudio.future"]["label"],
            "Δ"
        );
    }

    #[test]
    fn package_string_nesting_and_token_limits_are_bounded() {
        // Padding probes only preflight ordering; malformed padding is not schema acceptance.
        assert_eq!(code(&vec![b' '; 262_143]), "E_JSON_NONCANONICAL");
        assert_eq!(code(&vec![b' '; 262_144]), "E_JSON_NONCANONICAL");
        assert_eq!(code(&vec![b' '; 262_145]), "E_LIMIT_PACK");

        let long_string = format!("{{\"x\":\"{}\"}}\n", "x".repeat(4097));
        assert_eq!(code(long_string.as_bytes()), "E_LIMIT_STRING");

        let deeply_nested = format!("{{\"x\":{}0{}}}\n", "[".repeat(33), "]".repeat(33));
        assert_eq!(code(deeply_nested.as_bytes()), "E_LIMIT_NESTING");

        let mut value = golden_value();
        let variants = value["variants"].as_object_mut().unwrap();
        let current: usize = variants
            .values()
            .map(|variant| {
                ["primitives", "semantic", "components"]
                    .iter()
                    .map(|layer| variant[*layer].as_object().unwrap().len())
                    .sum::<usize>()
            })
            .sum();
        let primitives = variants.get_mut("dark").unwrap()["primitives"]
            .as_object_mut()
            .unwrap();
        for index in 0..(1025 - current) {
            primitives.insert(
                format!("extra{index:04}"),
                Value::String("#000000ff".into()),
            );
        }
        assert_eq!(code(&canonical_with_hash(value)), "E_LIMIT_TOKENS");
    }

    #[test]
    fn schema_valid_packages_enforce_exact_compiled_pack_boundaries() {
        for expected_length in [COMPILED_PACK_BYTES_LIMIT - 1, COMPILED_PACK_BYTES_LIMIT] {
            let bytes = package_with_exact_length(expected_length);
            let theme = NativeThemeV1::decode_canonical(&bytes).unwrap();
            assert_eq!(theme.canonical_bytes(), bytes.as_slice());
            assert_eq!(theme.runtime_snapshot_bytes(), expected_length);
        }

        let over_limit = package_with_exact_length(COMPILED_PACK_BYTES_LIMIT + 1);
        assert_eq!(code(&over_limit), "E_LIMIT_PACK");
    }

    #[test]
    fn machine_limit_contract_is_exact_and_runtime_is_dominated() {
        assert_eq!(COMPILED_PACK_BYTES_LIMIT, 262_144);
        assert_eq!(RUNTIME_SNAPSHOT_BYTES_LIMIT, 524_288);
        assert!(COMPILED_PACK_BYTES_LIMIT <= RUNTIME_SNAPSHOT_BYTES_LIMIT);
        assert_eq!(
            COMPILED_PACK_BYTES_UNIT,
            "canonical_utf8_package_file_bytes_including_final_lf"
        );
        assert_eq!(
            RUNTIME_SNAPSHOT_BYTES_UNIT,
            "retained_canonical_utf8_package_file_bytes_including_final_lf"
        );
        assert_eq!(
            LIMIT_RELATIONS,
            [(
                "compiled_pack_bytes",
                "runtime_snapshot_bytes",
                0,
                "compiled_pack_bytes <= runtime_snapshot_bytes",
            )]
        );
    }

    #[test]
    fn asset_count_individual_and_total_decoded_limits_are_bounded() {
        let mut count_value = golden_value();
        let items = count_value["variants"]["dark"]["assets"]["items"]
            .as_object_mut()
            .unwrap();
        let template = items["status.error"].clone();
        for index in items.len()..65 {
            items.insert(format!("extra.asset.{index:02}"), template.clone());
        }
        assert_eq!(code(&canonical_with_hash(count_value)), "E_LIMIT_ASSETS");

        let mut individual_value = golden_value();
        individual_value["variants"]["dark"]["assets"]["items"]["status.error"]["decoded_bytes"] =
            Value::from(524_289);
        assert_eq!(
            code(&canonical_with_hash(individual_value)),
            "E_LIMIT_ASSET_BYTES"
        );

        let mut total_value = golden_value();
        for variant in total_value["variants"]
            .as_object_mut()
            .unwrap()
            .values_mut()
        {
            for asset in variant["assets"]["items"]
                .as_object_mut()
                .unwrap()
                .values_mut()
            {
                asset["decoded_bytes"] = Value::from(524_288);
            }
        }
        assert_eq!(
            code(&canonical_with_hash(total_value)),
            "E_LIMIT_ASSETS_TOTAL"
        );
    }

    #[test]
    fn noncanonical_and_malformed_json_are_distinct() {
        let mut spaced = GOLDEN.to_vec();
        spaced.insert(1, b' ');
        assert_eq!(code(&spaced), "E_JSON_NONCANONICAL");
        assert_eq!(code(b"{\"x\":-0}\n"), "E_JSON_NONCANONICAL");
        assert_eq!(code(b"{\"x\":1.0}\n"), "E_JSON_NONCANONICAL");
        assert_eq!(code(b"{\"b\":0,\"a\":0}\n"), "E_JSON_NONCANONICAL");
        assert_eq!(code(b"{\"x\":0}"), "E_JSON_NONCANONICAL");
        assert_eq!(code(b"{\"x\":01}\n"), "E_JSON_MALFORMED");
        assert_eq!(code(b"{\"x\":NaN}\n"), "E_NUMBER_NONFINITE");
        assert_eq!(code(b"{\"x\":1e400}\n"), "E_NUMBER_NONFINITE");
    }

    #[test]
    fn invalid_utf8_is_rejected_distinctly() {
        assert_eq!(
            code(&[b'{', b'\"', 0xff, b'\"', b':', b'0', b'}', b'\n']),
            "E_UTF8"
        );
    }

    #[test]
    fn unknown_structural_fields_are_rejected_outside_extensions() {
        let mut root = golden_value();
        root.as_object_mut()
            .unwrap()
            .insert("command".into(), Value::String("no".into()));
        assert_eq!(code(&canonical_with_hash(root)), "E_FIELD_FORBIDDEN");

        let mut nested = golden_value();
        nested["theme"]
            .as_object_mut()
            .unwrap()
            .insert("future".into(), Value::Bool(true));
        assert_eq!(code(&canonical_with_hash(nested)), "E_FIELD_FORBIDDEN");

        let mut variant = golden_value();
        variant["variants"]["dark"]
            .as_object_mut()
            .unwrap()
            .insert("script".into(), Value::String("no".into()));
        assert_eq!(code(&canonical_with_hash(variant)), "E_FIELD_FORBIDDEN");
    }

    #[test]
    fn identity_hash_and_provenance_tampering_are_distinct() {
        let mut identity = golden_value();
        identity["metadata"]["provenance"]["source_identity"] = Value::String("../secret".into());
        assert_eq!(code(&canonical_with_hash(identity)), "E_IDENTITY");

        let mut hash = GOLDEN.to_vec();
        let position = hash
            .windows(64)
            .position(|window| window == GOLDEN_SEMANTIC_HASH.as_bytes())
            .unwrap();
        hash[position] = b'0';
        assert_eq!(code(&hash), "E_HASH");

        let mut provenance = golden_value();
        provenance["metadata"]["provenance"]["tokens"]["surface.canvas"]["kind"] =
            Value::String("invented".into());
        assert_eq!(code(&canonical_with_hash(provenance)), "E_PROVENANCE");
    }

    #[test]
    fn semantic_color_focus_and_contrast_rules_are_enforced() {
        let mut color = golden_value();
        color["variants"]["dark"]["semantic"]["text.normal"] = Value::String("#FFFFFFff".into());
        assert_eq!(code(&canonical_with_hash(color)), "E_COLOR_CANONICAL");

        let mut focus = golden_value();
        let selection = focus["variants"]["dark"]["semantic"]["interaction.selection"].clone();
        focus["variants"]["dark"]["semantic"]["border.focusConfirmed"] = selection;
        assert_eq!(code(&canonical_with_hash(focus)), "E_FOCUS_DISTINCT");

        let mut contrast = golden_value();
        contrast["variants"]["dark"]["semantic"]["text.normal"] =
            contrast["variants"]["dark"]["semantic"]["surface.canvas"].clone();
        assert_eq!(code(&canonical_with_hash(contrast)), "E_CONTRAST_NORMAL");
    }

    #[test]
    fn extensions_reject_unreserved_namespaces() {
        let mut value = golden_value();
        value["metadata"]["extensions"]
            .as_object_mut()
            .unwrap()
            .insert("com.example.unsupported".into(), Value::Object(Map::new()));
        assert_eq!(code(&canonical_with_hash(value)), "E_EXTENSION_NAMESPACE");
    }
}

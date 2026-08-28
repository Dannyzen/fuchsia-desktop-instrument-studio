use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use theme_model::{NativeThemeV1, COMPILED_PACK_BYTES_LIMIT, RUNTIME_SNAPSHOT_BYTES_LIMIT, STRING_BYTES_LIMIT};

const GOLDEN: &[u8] = include_bytes!("../testdata/native-theme-v1-package.json");
const PACKAGE_SHA256: &str = "f1975d2511b5b4c711ef8b299389a07793b3113077cad32bb8272dcde7b1738b";
const SEMANTIC_SHA256: &str = "5270267e6a857aaae560e5a161b110ae643b4ad3b016c2eceaae90331ae7230a";
const PACKAGES: [(&str, &[u8], &str); 5] = [
    ("base16", include_bytes!("../../theme_catalog/catalog/instrument-studio-base16.package.json"),
     "ad24d3ec8be53f673ad0ec7effc76500f22facf71eaa1e279fab2bcbcfc67adf"),
    ("base24", include_bytes!("../../theme_catalog/catalog/instrument-studio-base24.package.json"),
     "7b455463d66bea711f547f0381da0763fe2450753f4fa4a8a4e2048283939f49"),
    ("dtcg", include_bytes!("../../theme_catalog/catalog/instrument-studio-dtcg.package.json"),
     "125d66a027b4e4e4f1bfed6b99b6b13651368200a5a903be4491c8990ae11f4d"),
    ("legacy", GOLDEN, PACKAGE_SHA256),
    ("omarchy", include_bytes!("../../theme_catalog/catalog/instrument-studio-omarchy.package.json"),
     "ce97b2f0a64b9dbf1c23983bd6695b37a1eff66e47a0fbd43016d01e00d964e1"),
];

fn code(bytes: &[u8]) -> &'static str {
    NativeThemeV1::decode_canonical(bytes).unwrap_err().code()
}

fn package_with_exact_length(target: usize) -> Vec<u8> {
    const PADDING_ITERATION_CAP: usize = 128;
    const PADDING_PREFIX: &str = "org.constructresearch.instrumentstudio.boundary_padding_";
    const EXTENSIONS_MARKER: &[u8] = br#""extensions":{"#;

    let marker = GOLDEN
        .windows(EXTENSIONS_MARKER.len())
        .position(|window| window == EXTENSIONS_MARKER)
        .expect("canonical extensions object marker");
    assert!(GOLDEN[marker + 1..]
        .windows(EXTENSIONS_MARKER.len())
        .all(|window| window != EXTENSIONS_MARKER));
    assert!(target >= GOLDEN.len());

    let mut empty_entry_bytes = 0usize;
    let mut selected = None;
    for index in 0..PADDING_ITERATION_CAP {
        let key = format!("{PADDING_PREFIX}{index:03}");
        empty_entry_bytes += key.len() + 6;
        if target >= GOLDEN.len() + empty_entry_bytes {
            let payload_bytes = target - GOLDEN.len() - empty_entry_bytes;
            if payload_bytes <= (index + 1) * STRING_BYTES_LIMIT {
                selected = Some((index + 1, payload_bytes));
                break;
            }
        }
    }
    let (chunk_count, mut payload_bytes) = selected.expect("boundary size is reachable");
    let mut entries = Vec::with_capacity(target - GOLDEN.len());
    let mut previous_key = None;
    for index in 0..chunk_count {
        let key = format!("{PADDING_PREFIX}{index:03}");
        if let Some(previous) = previous_key.as_ref() {
            assert!(previous < &key);
        }
        previous_key = Some(key.clone());
        let chunk_bytes = payload_bytes.min(STRING_BYTES_LIMIT);
        payload_bytes -= chunk_bytes;
        entries.push(b'\"');
        entries.extend_from_slice(key.as_bytes());
        entries.extend_from_slice(b"\":\"");
        entries.extend(std::iter::repeat_n(b'x', chunk_bytes));
        entries.push(b'\"');
        entries.push(b',');
    }
    assert_eq!(payload_bytes, 0);

    let insertion = marker + EXTENSIONS_MARKER.len();
    let mut bytes = Vec::with_capacity(target);
    bytes.extend_from_slice(&GOLDEN[..insertion]);
    bytes.extend_from_slice(&entries);
    bytes.extend_from_slice(&GOLDEN[insertion..]);
    assert_eq!(bytes.len(), target);
    assert_eq!(bytes.iter().rev().take_while(|byte| **byte == b'\n').count(), 1);
    bytes
}

#[test]
fn host_or_target_qualification_emits_one_canonical_record() {
    let theme = NativeThemeV1::decode_canonical(GOLDEN).unwrap();
    assert_eq!(hex::encode(Sha256::digest(GOLDEN)), PACKAGE_SHA256);
    assert_eq!(theme.canonical_bytes(), GOLDEN);
    assert_eq!(theme.runtime_snapshot_bytes(), GOLDEN.len());
    assert_eq!(theme.semantic_sha256_hex(), SEMANTIC_SHA256);
    let mut package_rows = Vec::new();
    for (profile, bytes, expected_hash) in PACKAGES {
        let checked = NativeThemeV1::decode_canonical(bytes).unwrap();
        assert_eq!(checked.semantic_sha256_hex(), SEMANTIC_SHA256);
        assert_eq!(checked.canonical_bytes(), bytes);
        assert_eq!(checked.runtime_snapshot_bytes(), bytes.len());
        assert_eq!(hex::encode(Sha256::digest(bytes)), expected_hash);
        package_rows.push(json!({"bytes": bytes.len(), "id": profile, "sha256": expected_hash}));
    }
    assert_eq!(code(b"{\"x\":0}"), "E_JSON_NONCANONICAL");
    assert_eq!(code(b"{\"x\":NaN}\n"), "E_NUMBER_NONFINITE");
    assert_eq!(code(&[b'{', b'\"', 0xff, b'\"', b':', b'0', b'}', b'\n']), "E_UTF8");
    assert_eq!(code(&vec![b' '; COMPILED_PACK_BYTES_LIMIT + 1]), "E_LIMIT_PACK");
    for size in [COMPILED_PACK_BYTES_LIMIT - 1, COMPILED_PACK_BYTES_LIMIT] {
        let bytes = package_with_exact_length(size);
        let checked = NativeThemeV1::decode_canonical(&bytes).unwrap();
        assert_eq!(checked.canonical_bytes(), bytes);
        assert_eq!(checked.runtime_snapshot_bytes(), size);
    }
    assert_eq!(code(&package_with_exact_length(COMPILED_PACK_BYTES_LIMIT + 1)), "E_LIMIT_PACK");
    assert!(COMPILED_PACK_BYTES_LIMIT <= RUNTIME_SNAPSHOT_BYTES_LIMIT);

    let record = json!({
        "authority": "parent-integration-gate-only",
        "boundary_codes": {"262145": "E_LIMIT_PACK"},
        "package_count": 5,
        "packages": package_rows,
        "retained_bytes": GOLDEN.len(),
        "schema_version": "sq02-fuchsia-qualification-v1",
        "semantic_sha256": SEMANTIC_SHA256,
        "status": "PASS"
    });
    let encoded = serde_json::to_string(&record).unwrap();
    let reparsed: Value = serde_json::from_str(&encoded).unwrap();
    assert_eq!(reparsed, record);
    println!("SQ02_RUST:{encoded}");
}

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use theme_model::NativeThemeV1;

const PREFIX: &str = "SQ02_RUST:";
const REQUIRED_IDS: &[&str] = &[
    "SQ02-BOUNDARY-262143",
    "SQ02-BOUNDARY-262144",
    "SQ02-BOUNDARY-262145",
    "SQ02-CORPUS-ALL",
    "SQ02-DIAGNOSTICS",
    "SQ02-FULL-FILE-HASH",
    "SQ02-PACKAGES-5",
    "SQ02-RETAINED-BYTES",
    "SQ02-SEMANTIC-HASH",
];

fn fail(message: &str) -> ! {
    eprintln!("CI_QUALIFICATION_FAILURE: {message}");
    std::process::exit(2)
}

fn hash(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn read_json(path: &Path) -> Value {
    let raw = fs::read(path).unwrap_or_else(|_| fail("input read failed"));
    if !raw.ends_with(b"\n") || raw.ends_with(b"\n\n") {
        fail("manifest is not one-LF canonical JSON")
    }
    let value: Value = serde_json::from_slice(&raw[..raw.len() - 1])
        .unwrap_or_else(|_| fail("manifest JSON failed"));
    let mut canonical = serde_json::to_vec(&value).unwrap_or_else(|_| fail("manifest encode failed"));
    canonical.push(b'\n');
    if canonical != raw {
        fail("manifest is not canonical JSON")
    }
    value
}

fn read_named(directory: &Path, file: &str) -> Vec<u8> {
    let relative = Path::new(file);
    if relative.is_absolute() || relative.components().count() != 1 || relative.file_name().and_then(|name| name.to_str()) != Some(file) {
        fail("input filename is not a safe basename")
    }
    let path = directory.join(relative);
    let metadata = fs::symlink_metadata(&path).unwrap_or_else(|_| fail("input metadata failed"));
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        fail("input is not a regular non-symlink file")
    }
    fs::read(path).unwrap_or_else(|_| fail("input read failed"))
}

fn exact_fields(value: &Value, expected: &[&str], label: &str) {
    let object = value.as_object().unwrap_or_else(|| fail(label));
    let actual: BTreeSet<&str> = object.keys().map(String::as_str).collect();
    let expected: BTreeSet<&str> = expected.iter().copied().collect();
    if actual != expected {
        fail(label)
    }
}

fn exact_args() -> (PathBuf, PathBuf) {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 || args[1] != "--packages" || args[3] != "--corpus" {
        fail("expected --packages DIR --corpus DIR")
    }
    (PathBuf::from(&args[2]), PathBuf::from(&args[4]))
}

fn packages(directory: &Path) -> Vec<Value> {
    let manifest = read_json(&directory.join("manifest.json"));
    exact_fields(&manifest, &["packages", "schema_version"], "package manifest fields mismatch");
    let rows = manifest["packages"].as_array().unwrap_or_else(|| fail("package rows missing"));
    if rows.len() != 5 {
        fail("exactly five packages required")
    }
    let mut output = Vec::new();
    let mut ids = BTreeSet::new();
    for row in rows {
        exact_fields(row, &["bytes", "file", "id", "semantic_sha256", "sha256"], "package row fields mismatch");
        let file = row["file"].as_str().unwrap_or_else(|| fail("package file missing"));
        let id = row["id"].as_str().unwrap_or_else(|| fail("package id missing"));
        if !ids.insert(id.to_string()) {
            fail("duplicate package id")
        }
        let bytes = read_named(directory, file);
        let theme = NativeThemeV1::decode_canonical(&bytes)
            .unwrap_or_else(|error| fail(&format!("package rejected: {}", error.code())));
        let byte_hash = hash(&bytes);
        if row["sha256"] != byte_hash || row["semantic_sha256"] != theme.semantic_sha256_hex() {
            fail("package identity mismatch")
        }
        if theme.canonical_bytes() != bytes || theme.runtime_snapshot_bytes() != bytes.len() {
            fail("package retained-byte mismatch")
        }
        output.push(json!({
            "bytes": bytes.len(),
            "id": row["id"],
            "semantic_sha256": theme.semantic_sha256_hex(),
            "sha256": byte_hash,
        }));
    }
    output
}

fn boundaries(directory: &Path) -> Vec<Value> {
    let mut output = Vec::new();
    for (size, accepted, code) in [
        (262_143usize, true, ""),
        (262_144usize, true, ""),
        (262_145usize, false, "E_LIMIT_PACK"),
    ] {
        let bytes = fs::read(directory.join(format!("boundary-{size}.json")))
            .unwrap_or_else(|_| fail("boundary input missing"));
        if bytes.len() != size {
            fail("boundary byte size mismatch")
        }
        match NativeThemeV1::decode_canonical(&bytes) {
            Ok(theme) if accepted && theme.runtime_snapshot_bytes() == size => {
                output.push(json!({"accepted": true, "bytes": size, "code": Value::Null}));
            }
            Err(error) if !accepted && error.code() == code => {
                output.push(json!({"accepted": false, "bytes": size, "code": code}));
            }
            _ => fail("boundary behavior mismatch"),
        }
    }
    output
}

fn corpus(directory: &Path) -> (Vec<Value>, usize, usize) {
    let manifest = read_json(&directory.join("manifest.json"));
    exact_fields(&manifest, &["cases", "generator_version", "schema_version", "seed"], "corpus manifest fields mismatch");
    let rows = manifest["cases"].as_array().unwrap_or_else(|| fail("corpus rows missing"));
    if rows.len() < 256 {
        fail("corpus is too small")
    }
    let mut ids = BTreeSet::new();
    let mut hashes = BTreeSet::new();
    let mut results = Vec::new();
    let mut accepted = 0usize;
    let mut rejected = 0usize;
    for row in rows {
        exact_fields(row, &["accepted_package_sha256", "accepted_semantic_sha256", "file", "id",
                            "mutation_operator", "python_accepted", "python_code", "python_layer",
                            "rust_accepted", "rust_code", "sha256"], "corpus row fields mismatch");
        let id = row["id"].as_str().unwrap_or_else(|| fail("case id missing"));
        if !ids.insert(id.to_string()) {
            fail("duplicate corpus id")
        }
        let file = row["file"].as_str().unwrap_or_else(|| fail("case file missing"));
        let bytes = read_named(directory, file);
        let bytes_hash = hash(&bytes);
        if row["sha256"] != bytes_hash {
            fail("case hash mismatch")
        }
        if !hashes.insert(bytes_hash) {
            fail("duplicate corpus byte hash")
        }
        let expected_accepted = row["rust_accepted"].as_bool().unwrap_or_else(|| fail("case expected status missing"));
        let expected_code = row["rust_code"].as_str();
        let (actual_accepted, actual_code, package_hash, semantic_hash) =
            match NativeThemeV1::decode_canonical(&bytes) {
                Ok(theme) => (true, None, Some(hash(theme.canonical_bytes())), Some(theme.semantic_sha256_hex())),
                Err(error) => (false, Some(error.code()), None, None),
            };
        if actual_accepted != expected_accepted || actual_code != expected_code {
            fail("corpus parity mismatch")
        }
        if actual_accepted {
            accepted += 1;
            if row["accepted_package_sha256"].as_str() != package_hash.as_deref()
                || row["accepted_semantic_sha256"].as_str() != semantic_hash.as_deref()
            {
                fail("accepted corpus identity mismatch")
            }
        } else {
            rejected += 1;
        }
        results.push(json!({"accepted": actual_accepted, "code": actual_code, "id": id,
                            "package_sha256": package_hash, "semantic_sha256": semantic_hash}));
    }
    (results, accepted, rejected)
}

fn main() {
    let (package_dir, corpus_dir) = exact_args();
    let package_rows = packages(&package_dir);
    let boundary_rows = boundaries(&package_dir);
    let (case_rows, accepted, rejected) = corpus(&corpus_dir);
    let mut requirements: Vec<Value> = REQUIRED_IDS.iter().map(|id| Value::String((*id).into())).collect();
    requirements.sort_by(|left, right| left.as_str().cmp(&right.as_str()));
    let mut root = Map::new();
    root.insert("boundaries".into(), Value::Array(boundary_rows));
    root.insert("corpus".into(), json!({"accepted": accepted, "executed": case_rows.len(),
                                       "rejected": rejected, "results": case_rows}));
    root.insert("packages".into(), Value::Array(package_rows));
    root.insert("requirement_ids".into(), Value::Array(requirements));
    root.insert("schema_version".into(), Value::String("sq02-rust-qualifier-v1".into()));
    println!("{PREFIX}{}", serde_json::to_string(&Value::Object(root)).unwrap());
}

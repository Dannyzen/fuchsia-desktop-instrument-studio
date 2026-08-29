use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const STATE_VERSION: u32 = 1;
pub const MAX_STATE_BYTES: usize = 1024;
pub const MAX_THEME_ID_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Variant {
    Light,
    Dark,
    HighContrast,
}

impl Variant {
    fn encode(self) -> &'static str {
        match self {
            Self::Light => "light",
            Self::Dark => "dark",
            Self::HighContrast => "high-contrast",
        }
    }
    fn decode(value: &str) -> Result<Self, StateError> {
        match value {
            "light" => Ok(Self::Light),
            "dark" => Ok(Self::Dark),
            "high-contrast" => Ok(Self::HighContrast),
            _ => Err(StateError::InvalidVariant),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Identity {
    pub theme_id: String,
    pub variant: Variant,
    pub semantic_sha256: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedState {
    pub pending: Option<Identity>,
    pub last_known_good: Identity,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StateError {
    Oversize,
    Corrupt,
    DuplicateField,
    UnknownField,
    UnsupportedVersion,
    InvalidHash,
    InvalidVariant,
    MissingHistory,
}

impl StateError {
    pub fn code(self) -> &'static str {
        match self {
            Self::Oversize => "E_STATE_OVERSIZE",
            Self::Corrupt => "E_STATE_CORRUPT",
            Self::DuplicateField => "E_STATE_DUPLICATE_FIELD",
            Self::UnknownField => "E_STATE_UNKNOWN_FIELD",
            Self::UnsupportedVersion => "E_STATE_UNSUPPORTED_VERSION",
            Self::InvalidHash => "E_STATE_INVALID_HASH",
            Self::InvalidVariant => "E_STATE_INVALID_VARIANT",
            Self::MissingHistory => "E_STATE_MISSING_HISTORY",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FailurePoint {
    Write,
    FileSync,
    Rename,
    DirectorySync,
}

pub struct AtomicStore {
    path: PathBuf,
    #[cfg(test)]
    failure: Option<FailurePoint>,
    #[cfg(test)]
    commits: usize,
}

impl AtomicStore {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            #[cfg(test)]
            failure: None,
            #[cfg(test)]
            commits: 0,
        }
    }
    #[cfg(test)]
    pub(crate) fn fail_for_test(&mut self, point: FailurePoint) {
        self.failure = Some(point);
    }
    pub fn load(&self) -> Result<Option<PersistedState>, StateError> {
        match fs::read(&self.path) {
            Ok(bytes) => decode(&bytes).map(Some),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(_) => Err(StateError::Corrupt),
        }
    }
    pub fn commit(&mut self, state: &PersistedState) -> Result<bool, StateError> {
        if self.load().ok().flatten().as_ref() == Some(state) {
            return Ok(false);
        }
        let prior = fs::read(&self.path).ok();
        let bytes = encode(state)?;
        let temporary = self.path.with_extension("tmp");
        let mut file = self.write_temporary(&temporary, &bytes)?;
        self.sync_temporary(&mut file)?;
        drop(file);
        self.replace(&temporary)?;
        if let Err(error) = self.sync_parent() {
            self.restore_prior_after_failed_sync(prior.as_deref());
            return Err(error);
        }
        #[cfg(test)]
        {
            self.commits += 1;
        }
        Ok(true)
    }
    pub fn select(
        &mut self,
        identity: Identity,
        last_known_good: Identity,
    ) -> Result<bool, StateError> {
        let mut state = match self.load() {
            Ok(Some(state)) => state,
            Ok(None) | Err(_) => PersistedState {
                pending: None,
                last_known_good,
            },
        };
        state.pending = Some(identity);
        self.commit(&state)
    }
    pub fn restore(&mut self, last_known_good: Identity) -> Result<bool, StateError> {
        let mut state = match self.load() {
            Ok(Some(state)) => state,
            Ok(None) | Err(_) => PersistedState {
                pending: None,
                last_known_good,
            },
        };
        state.pending = None;
        self.commit(&state)
    }
    fn fails(&self, point: FailurePoint) -> bool {
        #[cfg(test)]
        {
            return self.failure == Some(point);
        }
        #[cfg(not(test))]
        {
            let _ = point;
            false
        }
    }
    fn write_temporary(&self, temporary: &Path, bytes: &[u8]) -> Result<File, StateError> {
        if self.fails(FailurePoint::Write) {
            return Err(StateError::Corrupt);
        }
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(temporary)
            .map_err(|_| StateError::Corrupt)?;
        file.write_all(bytes).map_err(|_| StateError::Corrupt)?;
        Ok(file)
    }
    fn sync_temporary(&self, file: &mut File) -> Result<(), StateError> {
        if self.fails(FailurePoint::FileSync) {
            return Err(StateError::Corrupt);
        }
        file.sync_all().map_err(|_| StateError::Corrupt)
    }
    fn replace(&self, temporary: &Path) -> Result<(), StateError> {
        if self.fails(FailurePoint::Rename) {
            return Err(StateError::Corrupt);
        }
        fs::rename(temporary, &self.path).map_err(|_| StateError::Corrupt)
    }
    fn sync_parent(&self) -> Result<(), StateError> {
        if self.fails(FailurePoint::DirectorySync) {
            return Err(StateError::Corrupt);
        }
        let parent = self.path.parent().ok_or(StateError::Corrupt)?;
        File::open(parent)
            .and_then(|file| file.sync_all())
            .map_err(|_| StateError::Corrupt)
    }
    fn restore_prior_after_failed_sync(&self, prior: Option<&[u8]>) {
        if let Some(bytes) = prior {
            let rollback = self.path.with_extension("rollback");
            if let Ok(mut file) = OpenOptions::new()
                .create(true)
                .truncate(true)
                .write(true)
                .open(&rollback)
            {
                if file.write_all(bytes).is_ok() && file.sync_all().is_ok() {
                    let _ = fs::rename(&rollback, &self.path);
                }
            }
        } else {
            let _ = fs::remove_file(&self.path);
        }
        if let Some(parent) = self.path.parent() {
            let _ = File::open(parent).and_then(|file| file.sync_all());
        }
    }
}

fn encode_identity(identity: &Identity) -> String {
    let hash = identity
        .semantic_sha256
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    format!(
        "{}|{}|{}",
        identity.theme_id,
        identity.variant.encode(),
        hash
    )
}

fn decode_identity(value: &str) -> Result<Identity, StateError> {
    let parts = value.split('|').collect::<Vec<_>>();
    if parts.len() != 3
        || parts[0].is_empty()
        || !parts[0]
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-._".contains(&b))
    {
        return Err(StateError::Corrupt);
    }
    if parts[0].len() > MAX_THEME_ID_BYTES {
        return Err(StateError::Oversize);
    }
    if parts[2].len() != 64
        || !parts[2]
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return Err(StateError::InvalidHash);
    }
    let mut hash = [0; 32];
    for (index, byte) in hash.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&parts[2][index * 2..index * 2 + 2], 16)
            .map_err(|_| StateError::InvalidHash)?;
    }
    Ok(Identity {
        theme_id: parts[0].to_string(),
        variant: Variant::decode(parts[1])?,
        semantic_sha256: hash,
    })
}

pub fn encode(state: &PersistedState) -> Result<Vec<u8>, StateError> {
    let pending = state
        .pending
        .as_ref()
        .map(encode_identity)
        .unwrap_or_else(|| "builtin".into());
    let bytes = format!(
        "version={STATE_VERSION}\npending={pending}\nlast-known-good={}\n",
        encode_identity(&state.last_known_good)
    )
    .into_bytes();
    if bytes.len() > MAX_STATE_BYTES {
        Err(StateError::Oversize)
    } else {
        Ok(bytes)
    }
}

pub fn decode(bytes: &[u8]) -> Result<PersistedState, StateError> {
    if bytes.len() > MAX_STATE_BYTES {
        return Err(StateError::Oversize);
    }
    let text = std::str::from_utf8(bytes).map_err(|_| StateError::Corrupt)?;
    if !text.ends_with('\n') {
        return Err(StateError::Corrupt);
    }
    let mut fields = BTreeMap::new();
    for line in text.lines() {
        let (key, value) = line.split_once('=').ok_or(StateError::Corrupt)?;
        if !matches!(key, "version" | "pending" | "last-known-good") {
            return Err(StateError::UnknownField);
        }
        if fields.insert(key, value).is_some() {
            return Err(StateError::DuplicateField);
        }
    }
    let version = fields
        .get("version")
        .ok_or(StateError::Corrupt)?
        .parse::<u32>()
        .map_err(|_| StateError::Corrupt)?;
    if version != STATE_VERSION {
        return Err(StateError::UnsupportedVersion);
    }
    let pending = match *fields.get("pending").ok_or(StateError::Corrupt)? {
        "builtin" => None,
        value => Some(decode_identity(value)?),
    };
    let last_known_good = decode_identity(
        fields
            .get("last-known-good")
            .ok_or(StateError::MissingHistory)?,
    )?;
    if fields.len() != 3 {
        return Err(StateError::Corrupt);
    }
    Ok(PersistedState {
        pending,
        last_known_good,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn id() -> Identity {
        Identity {
            theme_id: "instrument-studio".into(),
            variant: Variant::Dark,
            semantic_sha256: [0xab; 32],
        }
    }
    fn valid() -> Vec<u8> {
        encode(&PersistedState {
            pending: Some(id()),
            last_known_good: id(),
        })
        .unwrap()
    }
    struct TestDir(PathBuf);
    impl TestDir {
        fn new() -> Self {
            let p = std::env::temp_dir()
                .join(format!("theme-store-{}", std::process::id()))
                .join(format!("{:?}", std::thread::current().id()));
            fs::create_dir_all(&p).unwrap();
            Self(p)
        }
    }
    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    fn store() -> (TestDir, AtomicStore) {
        let dir = TestDir::new();
        let store = AtomicStore::new(dir.0.join("state.v1"));
        (dir, store)
    }
    #[test]
    fn codec_round_trip_is_canonical() {
        let bytes = valid();
        assert_eq!(encode(&decode(&bytes).unwrap()).unwrap(), bytes);
    }
    #[test]
    fn codec_rejects_corrupt_state() {
        assert_eq!(decode(b"garbage"), Err(StateError::Corrupt));
    }
    #[test]
    fn codec_rejects_duplicate_fields() {
        let mut b = valid();
        b.extend_from_slice(b"pending=builtin\n");
        assert_eq!(decode(&b), Err(StateError::DuplicateField));
    }
    #[test]
    fn codec_rejects_unknown_fields() {
        let mut b = valid();
        b.extend_from_slice(b"path=/data/secret\n");
        assert_eq!(decode(&b), Err(StateError::UnknownField));
    }
    #[test]
    fn codec_rejects_older_version() {
        let b = String::from_utf8(valid())
            .unwrap()
            .replace("version=1", "version=0");
        assert_eq!(decode(b.as_bytes()), Err(StateError::UnsupportedVersion));
    }
    #[test]
    fn codec_rejects_newer_version() {
        let b = String::from_utf8(valid())
            .unwrap()
            .replace("version=1", "version=2");
        assert_eq!(decode(b.as_bytes()), Err(StateError::UnsupportedVersion));
    }
    #[test]
    fn codec_rejects_malformed_hash() {
        let b = String::from_utf8(valid())
            .unwrap()
            .replace(&"ab".repeat(32), "xyz");
        assert_eq!(decode(b.as_bytes()), Err(StateError::InvalidHash));
    }
    #[test]
    fn codec_rejects_unknown_variant() {
        let b = String::from_utf8(valid())
            .unwrap()
            .replace("|dark|", "|sepia|");
        assert_eq!(decode(b.as_bytes()), Err(StateError::InvalidVariant));
    }
    #[test]
    fn codec_rejects_oversize_identity() {
        let b = String::from_utf8(valid())
            .unwrap()
            .replace("instrument-studio", &"x".repeat(129));
        assert_eq!(decode(b.as_bytes()), Err(StateError::Oversize));
    }
    #[test]
    fn codec_rejects_missing_history() {
        let b = String::from_utf8(valid())
            .unwrap()
            .lines()
            .filter(|l| !l.starts_with("last-known-good="))
            .collect::<Vec<_>>()
            .join("\n")
            + "\n";
        assert_eq!(decode(b.as_bytes()), Err(StateError::MissingHistory));
    }
    fn prior_state_failure(point: FailurePoint) {
        let (_d, mut s) = store();
        let prior = PersistedState {
            pending: None,
            last_known_good: id(),
        };
        s.commit(&prior).unwrap();
        s.failure = Some(point);
        let changed = PersistedState {
            pending: Some(id()),
            last_known_good: id(),
        };
        assert!(s.commit(&changed).is_err());
        assert_eq!(s.load().unwrap(), Some(prior));
    }
    #[test]
    fn store_preserves_prior_state_on_write_failure() {
        prior_state_failure(FailurePoint::Write);
    }
    #[test]
    fn store_preserves_prior_state_on_file_sync_failure() {
        prior_state_failure(FailurePoint::FileSync);
    }
    #[test]
    fn store_preserves_prior_state_on_rename_failure() {
        prior_state_failure(FailurePoint::Rename);
    }
    #[test]
    fn store_reports_directory_sync_failure_after_replace() {
        let (_d, mut s) = store();
        let prior = PersistedState {
            pending: None,
            last_known_good: id(),
        };
        s.commit(&prior).unwrap();
        s.failure = Some(FailurePoint::DirectorySync);
        let mut changed = prior.clone();
        changed.pending = Some(id());
        assert!(s.commit(&changed).is_err());
        assert_eq!(s.load().unwrap(), Some(prior));
    }
    #[test]
    fn store_ignores_temporary_residue() {
        let (d, s) = store();
        fs::write(d.0.join("state.tmp"), b"junk").unwrap();
        assert_eq!(s.load().unwrap(), None);
    }
    #[test]
    fn corrupt_store_can_be_repaired_by_select() {
        let (d, mut s) = store();
        fs::write(d.0.join("state.v1"), b"corrupt").unwrap();
        assert!(s.select(id(), id()).unwrap());
        let repaired = s.load().unwrap().unwrap();
        assert_eq!(repaired.pending, Some(id()));
        assert_eq!(repaired.last_known_good, id());
    }
    #[test]
    fn corrupt_store_can_be_repaired_by_restore() {
        let (d, mut s) = store();
        fs::write(d.0.join("state.v1"), b"corrupt").unwrap();
        assert!(s.restore(id()).unwrap());
        let repaired = s.load().unwrap().unwrap();
        assert_eq!(repaired.pending, None);
        assert_eq!(repaired.last_known_good, id());
    }
    #[test]
    fn same_select_is_idempotent() {
        let (_d, mut s) = store();
        assert!(s.select(id(), id()).unwrap());
        assert!(!s.select(id(), id()).unwrap());
        assert_eq!(s.commits, 1);
    }
    #[test]
    fn same_restore_is_idempotent() {
        let (_d, mut s) = store();
        assert!(s.restore(id()).unwrap());
        assert!(!s.restore(id()).unwrap());
        assert_eq!(s.commits, 1);
    }
}

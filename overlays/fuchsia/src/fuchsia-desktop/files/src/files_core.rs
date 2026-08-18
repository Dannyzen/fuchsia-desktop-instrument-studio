// Copyright 2026 The Fuchsia Desktop Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

use std::fs::{self, OpenOptions};
use std::io::{Read as _, Write as _};
use std::path::{Component, Path, PathBuf};

const MAX_TEXT_BYTES: u64 = 64 * 1024;

pub type FilesResult<T> = Result<T, String>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntryKind {
    Directory,
    File,
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub name: String,
    pub kind: EntryKind,
    pub size: u64,
}

#[derive(Debug)]
pub struct PendingDelete {
    path: PathBuf,
}

#[derive(Debug)]
pub struct RootedFiles {
    root: PathBuf,
}

impl RootedFiles {
    pub fn new(root: impl AsRef<Path>) -> FilesResult<Self> {
        let root = root.as_ref().canonicalize().map_err(|error| {
            format!("open bounded root {}: {error}", root.as_ref().display())
        })?;
        if !root.is_dir() {
            return Err(format!("bounded root is not a directory: {}", root.display()));
        }
        Ok(Self { root })
    }

    pub fn list(&self, relative: impl AsRef<Path>) -> FilesResult<Vec<Entry>> {
        let directory = self.resolve_existing(relative.as_ref())?;
        if !directory.is_dir() {
            return Err(format!("not a directory: {}", relative.as_ref().display()));
        }
        let mut entries = Vec::new();
        for result in fs::read_dir(&directory)
            .map_err(|error| format!("list {}: {error}", relative.as_ref().display()))?
        {
            let entry = result.map_err(|error| format!("read directory entry: {error}"))?;
            let metadata = entry
                .metadata()
                .map_err(|error| format!("inspect {}: {error}", entry.path().display()))?;
            let kind = if metadata.is_dir() {
                EntryKind::Directory
            } else if metadata.is_file() {
                EntryKind::File
            } else {
                EntryKind::Other
            };
            entries.push(Entry {
                name: entry.file_name().to_string_lossy().into_owned(),
                kind,
                size: metadata.len(),
            });
        }
        entries.sort_by(|left, right| {
            let left_rank = matches!(left.kind, EntryKind::Directory) as u8;
            let right_rank = matches!(right.kind, EntryKind::Directory) as u8;
            right_rank.cmp(&left_rank).then_with(|| left.name.cmp(&right.name))
        });
        Ok(entries)
    }

    pub fn read_text(&self, relative: impl AsRef<Path>) -> FilesResult<String> {
        let path = self.resolve_existing(relative.as_ref())?;
        let metadata = fs::metadata(&path)
            .map_err(|error| format!("inspect {}: {error}", relative.as_ref().display()))?;
        if !metadata.is_file() {
            return Err(format!("not a file: {}", relative.as_ref().display()));
        }
        if metadata.len() > MAX_TEXT_BYTES {
            return Err(format!("file exceeds {MAX_TEXT_BYTES} byte preview limit"));
        }
        let mut file = fs::File::open(&path)
            .map_err(|error| format!("open {}: {error}", relative.as_ref().display()))?;
        let mut text = String::new();
        file.read_to_string(&mut text)
            .map_err(|error| format!("read {} as UTF-8: {error}", relative.as_ref().display()))?;
        Ok(text)
    }

    pub fn create_file(&self, relative: impl AsRef<Path>, contents: &[u8]) -> FilesResult<()> {
        let path = self.resolve_destination(relative.as_ref())?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|error| format!("create {}: {error}", relative.as_ref().display()))?;
        file.write_all(contents)
            .map_err(|error| format!("write {}: {error}", relative.as_ref().display()))
    }

    pub fn create_dir(&self, relative: impl AsRef<Path>) -> FilesResult<()> {
        let path = self.resolve_destination(relative.as_ref())?;
        fs::create_dir(&path)
            .map_err(|error| format!("create directory {}: {error}", relative.as_ref().display()))
    }

    pub fn rename(
        &self,
        source: impl AsRef<Path>,
        destination: impl AsRef<Path>,
    ) -> FilesResult<()> {
        self.move_entry(source, destination)
    }

    pub fn copy_file(
        &self,
        source: impl AsRef<Path>,
        destination: impl AsRef<Path>,
    ) -> FilesResult<()> {
        let source_path = self.resolve_existing(source.as_ref())?;
        if !source_path.is_file() {
            return Err(format!("copy source is not a file: {}", source.as_ref().display()));
        }
        let destination_path = self.resolve_destination(destination.as_ref())?;
        let mut input = fs::File::open(&source_path)
            .map_err(|error| format!("open copy source {}: {error}", source.as_ref().display()))?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&destination_path)
            .map_err(|error| {
                format!("create copy destination {}: {error}", destination.as_ref().display())
            })?;
        std::io::copy(&mut input, &mut output)
            .map_err(|error| format!("copy {}: {error}", source.as_ref().display()))?;
        Ok(())
    }

    pub fn move_entry(
        &self,
        source: impl AsRef<Path>,
        destination: impl AsRef<Path>,
    ) -> FilesResult<()> {
        let source_path = self.resolve_existing(source.as_ref())?;
        let destination_path = self.resolve_destination(destination.as_ref())?;
        fs::rename(&source_path, &destination_path).map_err(|error| {
            format!(
                "move {} to {}: {error}",
                source.as_ref().display(),
                destination.as_ref().display()
            )
        })
    }

    pub fn prepare_delete(&self, relative: impl AsRef<Path>) -> FilesResult<PendingDelete> {
        let path = self.resolve_existing(relative.as_ref())?;
        Ok(PendingDelete { path })
    }

    pub fn confirm_delete(&self, pending: PendingDelete) -> FilesResult<()> {
        let canonical = pending
            .path
            .canonicalize()
            .map_err(|error| format!("confirm delete {}: {error}", pending.path.display()))?;
        if !canonical.starts_with(&self.root) || canonical == self.root {
            return Err("delete target escaped bounded root".to_string());
        }
        if canonical.is_dir() {
            fs::remove_dir(&canonical).map_err(|error| {
                format!("delete empty directory {}: {error}", canonical.display())
            })
        } else {
            fs::remove_file(&canonical)
                .map_err(|error| format!("delete file {}: {error}", canonical.display()))
        }
    }

    fn resolve_existing(&self, relative: &Path) -> FilesResult<PathBuf> {
        self.validate_relative(relative)?;
        let path = self.root.join(relative).canonicalize().map_err(|error| {
            format!("resolve existing path {}: {error}", relative.display())
        })?;
        if !path.starts_with(&self.root) {
            return Err(format!("path escapes bounded root: {}", relative.display()));
        }
        Ok(path)
    }

    fn resolve_destination(&self, relative: &Path) -> FilesResult<PathBuf> {
        self.validate_relative(relative)?;
        let name = relative
            .file_name()
            .ok_or_else(|| "destination must name an entry".to_string())?;
        let parent = relative.parent().unwrap_or_else(|| Path::new(""));
        let parent = self.resolve_existing(parent)?;
        if !parent.is_dir() {
            return Err(format!("destination parent is not a directory: {}", relative.display()));
        }
        let destination = parent.join(name);
        if destination.exists() {
            return Err(format!("destination already exists: {}", relative.display()));
        }
        Ok(destination)
    }

    fn validate_relative(&self, relative: &Path) -> FilesResult<()> {
        for component in relative.components() {
            match component {
                Component::Normal(_) | Component::CurDir => {}
                Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                    return Err(format!("path is outside bounded root: {}", relative.display()));
                }
            }
        }
        Ok(())
    }
}

pub struct FilesController {
    files: RootedFiles,
    current_directory: PathBuf,
    entries: Vec<Entry>,
    selected: Option<String>,
    pending_delete: Option<PendingDelete>,
    status: String,
}

impl FilesController {
    pub fn new(root: impl AsRef<Path>) -> FilesResult<Self> {
        let files = RootedFiles::new(root)?;
        let mut controller = Self {
            files,
            current_directory: PathBuf::new(),
            entries: Vec::new(),
            selected: None,
            pending_delete: None,
            status: "Ready".to_string(),
        };
        controller.seed_if_missing()?;
        controller.refresh()?;
        Ok(controller)
    }

    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    pub fn current_directory(&self) -> String {
        self.current_directory.to_string_lossy().into_owned()
    }

    pub fn selected_name(&self) -> Option<&str> {
        self.selected.as_deref()
    }

    pub fn status(&self) -> &str {
        &self.status
    }

    pub fn select(&mut self, name: &str) -> FilesResult<()> {
        if !self.entries.iter().any(|entry| entry.name == name) {
            return Err(format!("entry is not visible: {name}"));
        }
        self.selected = Some(name.to_string());
        self.pending_delete = None;
        self.status = format!("Selected {name}");
        Ok(())
    }

    pub fn open_selected(&mut self) -> FilesResult<()> {
        let name = self.selected.clone().ok_or_else(|| "select an entry first".to_string())?;
        let entry = self
            .entries
            .iter()
            .find(|entry| entry.name == name)
            .cloned()
            .ok_or_else(|| format!("entry disappeared: {name}"))?;
        let relative = self.current_directory.join(&name);
        match entry.kind {
            EntryKind::Directory => {
                self.current_directory = relative;
                self.selected = None;
                self.pending_delete = None;
                self.refresh()?;
                self.status = format!("Opened /{}", self.current_directory.display());
            }
            EntryKind::File => {
                let text = self.files.read_text(&relative)?;
                self.status = format!("{name}: {text}");
            }
            EntryKind::Other => return Err(format!("unsupported entry type: {name}")),
        }
        Ok(())
    }

    pub fn go_up(&mut self) -> FilesResult<()> {
        if self.current_directory.pop() {
            self.selected = None;
            self.pending_delete = None;
            self.refresh()?;
            self.status = format!("Opened /{}", self.current_directory.display());
        } else {
            self.status = "Already at Files root".to_string();
        }
        Ok(())
    }

    pub fn create_file(&mut self) -> FilesResult<()> {
        let mut index = 1;
        let name = loop {
            let candidate = if index == 1 {
                "Untitled.txt".to_string()
            } else {
                format!("Untitled {index}.txt")
            };
            if !self.entries.iter().any(|entry| entry.name == candidate) {
                break candidate;
            }
            index += 1;
        };
        let relative = self.current_directory.join(&name);
        self.files.create_file(&relative, b"")?;
        self.refresh()?;
        self.selected = Some(name.clone());
        self.pending_delete = None;
        self.status = format!("Created {name}");
        Ok(())
    }

    pub fn rename_selected(&mut self) -> FilesResult<()> {
        let name = self.selected.clone().ok_or_else(|| "select an entry first".to_string())?;
        let renamed = derived_name(&name, " Renamed");
        let source = self.current_directory.join(&name);
        let destination = self.current_directory.join(&renamed);
        self.files.rename(&source, &destination)?;
        self.refresh()?;
        self.selected = Some(renamed.clone());
        self.pending_delete = None;
        self.status = format!("Renamed {name} to {renamed}");
        Ok(())
    }

    pub fn copy_selected(&mut self) -> FilesResult<()> {
        let name = self.selected.clone().ok_or_else(|| "select an entry first".to_string())?;
        let entry = self
            .entries
            .iter()
            .find(|entry| entry.name == name)
            .ok_or_else(|| format!("entry disappeared: {name}"))?;
        if entry.kind != EntryKind::File {
            return Err("copy supports files only".to_string());
        }
        let copy = derived_name(&name, " Copy");
        let source = self.current_directory.join(&name);
        let destination = self.current_directory.join(&copy);
        self.files.copy_file(&source, &destination)?;
        self.refresh()?;
        self.status = format!("Copied {name} to {copy}");
        Ok(())
    }

    pub fn move_selected(&mut self) -> FilesResult<()> {
        let name = self.selected.clone().ok_or_else(|| "select an entry first".to_string())?;
        let entry = self
            .entries
            .iter()
            .find(|entry| entry.name == name)
            .ok_or_else(|| format!("entry disappeared: {name}"))?;
        if entry.kind != EntryKind::File {
            return Err("move supports files only".to_string());
        }
        let source = self.current_directory.join(&name);
        let destination = if self.current_directory.as_os_str().is_empty() {
            PathBuf::from("Documents").join(&name)
        } else {
            PathBuf::from(&name)
        };
        self.files.move_entry(&source, &destination)?;
        self.refresh()?;
        self.selected = None;
        self.pending_delete = None;
        self.status = format!("Moved {name}");
        Ok(())
    }

    pub fn delete_selected(&mut self) -> FilesResult<()> {
        if let Some(pending) = self.pending_delete.take() {
            let name = self.selected.take().unwrap_or_else(|| "entry".to_string());
            self.files.confirm_delete(pending)?;
            self.refresh()?;
            self.status = format!("Deleted {name}");
            return Ok(());
        }
        let name = self.selected.clone().ok_or_else(|| "select an entry first".to_string())?;
        let relative = self.current_directory.join(&name);
        self.pending_delete = Some(self.files.prepare_delete(&relative)?);
        self.status = format!("Confirm delete {name}");
        Ok(())
    }

    fn refresh(&mut self) -> FilesResult<()> {
        self.entries = self.files.list(&self.current_directory)?;
        Ok(())
    }

    fn seed_if_missing(&mut self) -> FilesResult<()> {
        let entries = self.files.list("")?;
        if !entries.iter().any(|entry| entry.name == "Documents") {
            self.files.create_dir("Documents")?;
        }
        if !entries.iter().any(|entry| entry.name == "Welcome.txt") {
            self.files.create_file("Welcome.txt", b"Welcome to Fuchsia Files")?;
        }
        if !entries.iter().any(|entry| entry.name == "Notes.txt") {
            self.files.create_file("Notes.txt", b"Bounded storage is active")?;
        }
        Ok(())
    }
}

fn derived_name(name: &str, suffix: &str) -> String {
    let path = Path::new(name);
    let stem = path.file_stem().unwrap_or_default().to_string_lossy();
    match path.extension() {
        Some(extension) => format!("{stem}{suffix}.{}", extension.to_string_lossy()),
        None => format!("{stem}{suffix}"),
    }
}

#[cfg(test)]
mod tests {
    use super::{EntryKind, FilesController, RootedFiles};
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_ID: AtomicU64 = AtomicU64::new(1);

    struct TestRoot(PathBuf);

    impl TestRoot {
        fn new() -> Self {
            let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "fuchsia_files_core_test_{}_{}",
                std::process::id(),
                id
            ));
            fs::create_dir(&path).expect("create test root");
            Self(path)
        }
    }

    impl Drop for TestRoot {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).ok();
        }
    }

    #[test]
    fn rejects_parent_and_absolute_paths() {
        let root = TestRoot::new();
        let files = RootedFiles::new(&root.0).expect("open root");

        assert!(files.read_text("../outside.txt").is_err());
        assert!(files.read_text("/pkg/meta/package").is_err());
        assert!(files.create_file("nested/../../outside.txt", b"no").is_err());
    }

    #[cfg(unix)]
    #[test]
    fn rejects_symlink_escape() {
        use std::os::unix::fs::symlink;

        let root = TestRoot::new();
        let outside = TestRoot::new();
        fs::write(outside.0.join("secret.txt"), "secret").expect("write outside file");
        symlink(outside.0.join("secret.txt"), root.0.join("escape.txt"))
            .expect("create symlink");
        let files = RootedFiles::new(&root.0).expect("open root");

        assert!(files.read_text("escape.txt").is_err());
    }

    #[test]
    fn lists_entries_and_opens_text() {
        let root = TestRoot::new();
        fs::create_dir(root.0.join("Documents")).expect("create directory");
        fs::write(root.0.join("Welcome.txt"), "Welcome to Files").expect("write file");
        let files = RootedFiles::new(&root.0).expect("open root");

        let entries = files.list("").expect("list root");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name, "Documents");
        assert_eq!(entries[0].kind, EntryKind::Directory);
        assert_eq!(entries[1].name, "Welcome.txt");
        assert_eq!(files.read_text("Welcome.txt").expect("read file"), "Welcome to Files");
    }

    #[test]
    fn creates_and_renames_file() {
        let root = TestRoot::new();
        let files = RootedFiles::new(&root.0).expect("open root");

        files.create_file("Notes.txt", b"hello").expect("create file");
        files.rename("Notes.txt", "Ideas.txt").expect("rename file");

        assert!(!root.0.join("Notes.txt").exists());
        assert_eq!(fs::read_to_string(root.0.join("Ideas.txt")).unwrap(), "hello");
    }

    #[test]
    fn copies_and_moves_between_directories() {
        let root = TestRoot::new();
        let files = RootedFiles::new(&root.0).expect("open root");
        files.create_dir("Documents").expect("create directory");
        files.create_file("Draft.txt", b"draft").expect("create file");

        files.copy_file("Draft.txt", "Draft copy.txt").expect("copy file");
        files.move_entry("Draft.txt", "Documents/Draft.txt").expect("move file");

        assert_eq!(fs::read_to_string(root.0.join("Draft copy.txt")).unwrap(), "draft");
        assert_eq!(fs::read_to_string(root.0.join("Documents/Draft.txt")).unwrap(), "draft");
        assert!(!root.0.join("Draft.txt").exists());
    }

    #[test]
    fn delete_requires_explicit_confirmation() {
        let root = TestRoot::new();
        let files = RootedFiles::new(&root.0).expect("open root");
        files.create_file("Remove.txt", b"temporary").expect("create file");

        let pending = files.prepare_delete("Remove.txt").expect("prepare delete");
        assert!(root.0.join("Remove.txt").exists());
        files.confirm_delete(pending).expect("confirm delete");

        assert!(!root.0.join("Remove.txt").exists());
    }

    #[test]
    fn controller_bootstraps_opens_and_navigates() {
        let root = TestRoot::new();
        let mut controller = FilesController::new(&root.0).expect("create controller");

        assert!(controller.entries().iter().any(|entry| entry.name == "Documents"));
        assert!(controller.entries().iter().any(|entry| entry.name == "Welcome.txt"));
        controller.select("Welcome.txt").expect("select welcome");
        controller.open_selected().expect("open welcome");
        assert!(controller.status().contains("Welcome to Fuchsia Files"));
        controller.select("Documents").expect("select documents");
        controller.open_selected().expect("open documents");
        assert_eq!(controller.current_directory(), "Documents");
        controller.go_up().expect("go up");
        assert_eq!(controller.current_directory(), "");
    }

    #[test]
    fn controller_create_rename_copy_and_move_are_real() {
        let root = TestRoot::new();
        let mut controller = FilesController::new(&root.0).expect("create controller");

        controller.create_file().expect("create from action");
        let created = controller.selected_name().expect("created selection").to_string();
        assert!(root.0.join(&created).exists());
        controller.rename_selected().expect("rename from action");
        let renamed = controller.selected_name().expect("renamed selection").to_string();
        assert_ne!(renamed, created);
        controller.copy_selected().expect("copy from action");
        assert!(controller.entries().iter().any(|entry| entry.name.contains("Copy")));
        controller.move_selected().expect("move from action");
        assert!(root.0.join("Documents").join(&renamed).exists());
    }

    #[test]
    fn controller_delete_needs_two_actions() {
        let root = TestRoot::new();
        let mut controller = FilesController::new(&root.0).expect("create controller");
        controller.select("Notes.txt").expect("select notes");

        controller.delete_selected().expect("arm delete");
        assert!(root.0.join("Notes.txt").exists());
        assert!(controller.status().contains("Confirm delete"));
        controller.delete_selected().expect("confirm delete");

        assert!(!root.0.join("Notes.txt").exists());
        assert!(controller.status().contains("Deleted"));
    }

    #[test]
    fn refuses_recursive_delete_of_non_empty_directory() {
        let root = TestRoot::new();
        let files = RootedFiles::new(&root.0).expect("open root");
        files.create_dir("Documents").expect("create directory");
        files.create_file("Documents/Keep.txt", b"keep").expect("create file");

        let pending = files.prepare_delete("Documents").expect("prepare delete");
        assert!(files.confirm_delete(pending).is_err());
        assert!(root.0.join("Documents/Keep.txt").exists());
    }
}

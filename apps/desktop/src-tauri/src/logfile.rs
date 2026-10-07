//! The application's own log (FR-032).
//!
//! It records what the native side did — state changes, failure classes,
//! exits, the workspace, how a stop ended — and nothing else. Its entries are
//! built only from typed values and fixed text, so no credential, no part of
//! the environment and no session content can be passed to it: a failure is
//! logged by its class, never by its message, which may quote the Core.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use crate::supervisor::{FailureClass, State};

pub const FILE_NAME: &str = "comodor-desktop.log";
/// Past this size the log is moved aside (one previous file is kept).
pub const MAX_BYTES: u64 = 1024 * 1024;

pub struct Log {
    path: PathBuf,
    write: Mutex<()>,
}

/// One thing worth recording.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Entry {
    State(State),
    Failure(FailureClass),
    Started { pid: u32 },
    Exited { code: Option<i32> },
    Workspace(PathBuf),
    Note(&'static str),
}

impl Entry {
    fn text(&self) -> String {
        match self {
            Entry::State(state) => format!("core state {}", name(state)),
            Entry::Failure(class) => format!("core failure {}", name(class)),
            Entry::Started { pid } => format!("core started pid {pid}"),
            Entry::Exited { code: Some(code) } => format!("core exited code {code}"),
            Entry::Exited { code: None } => "core exited by a signal".into(),
            Entry::Workspace(path) => format!("workspace {}", path.display()),
            Entry::Note(text) => (*text).to_string(),
        }
    }
}

/// The snake-case name a state or class serialises to.
fn name(value: &impl serde::Serialize) -> String {
    serde_json::to_value(value).ok()
        .and_then(|value| value.as_str().map(str::to_owned))
        .unwrap_or_default()
}

impl Log {
    pub fn in_dir(dir: &Path) -> Self {
        Self { path: dir.join(FILE_NAME), write: Mutex::new(()) }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one entry. A log that cannot be written never stops the
    /// application.
    pub fn record(&self, entry: Entry) {
        let _held = self.write.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if std::fs::metadata(&self.path).map(|meta| meta.is_file() && meta.len() > MAX_BYTES)
            .unwrap_or(false) {
            let _ = std::fs::rename(&self.path, self.path.with_extension("log.1"));
        }
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&self.path) {
            let _ = writeln!(file, "{} {}", now(), entry.text());
        }
    }
}

fn now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs()).unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!("comodor-log-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            Self(path)
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn entries_are_one_line_each_and_name_only_typed_facts() {
        let dir = Dir::new("lines");
        let log = Log::in_dir(&dir.0);
        log.record(Entry::State(State::Ready));
        log.record(Entry::Failure(FailureClass::ProtocolFault));
        log.record(Entry::Started { pid: 42 });
        log.record(Entry::Exited { code: Some(3) });
        log.record(Entry::Exited { code: None });
        log.record(Entry::Workspace(PathBuf::from("/work/project")));
        log.record(Entry::Note("stopped before it finished"));
        let text = std::fs::read_to_string(log.path()).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 7, "{text}");
        assert!(lines[0].ends_with("core state ready"), "{}", lines[0]);
        assert!(lines[1].ends_with("core failure protocol_fault"), "{}", lines[1]);
        assert!(lines[2].ends_with("core started pid 42"));
        assert!(lines[3].ends_with("core exited code 3"));
        assert!(lines[4].ends_with("core exited by a signal"));
        assert!(lines[5].ends_with("workspace /work/project"));
        assert!(lines[6].ends_with("stopped before it finished"));
        assert!(lines.iter().all(|line| line.split(' ').next().unwrap().parse::<u64>().is_ok()),
                "each line starts with a time");
    }

    #[test]
    fn a_full_log_is_moved_aside_and_one_previous_file_kept() {
        let dir = Dir::new("rotate");
        let log = Log::in_dir(&dir.0);
        std::fs::create_dir_all(&dir.0).unwrap();
        std::fs::write(log.path(), vec![b'x'; MAX_BYTES as usize + 1]).unwrap();
        log.record(Entry::Note("after the move"));
        let current = std::fs::read_to_string(log.path()).unwrap();
        assert!(current.ends_with("after the move\n") && current.len() < 100, "{current}");
        let previous = log.path().with_extension("log.1");
        assert_eq!(std::fs::metadata(&previous).unwrap().len(), MAX_BYTES + 1);
    }

    #[test]
    fn a_log_that_cannot_be_written_is_not_fatal() {
        let dir = Dir::new("blocked");
        std::fs::create_dir_all(&dir.0).unwrap();
        // The log's own path is a directory: every write fails, quietly.
        let log = Log::in_dir(&dir.0);
        std::fs::create_dir_all(log.path()).unwrap();
        log.record(Entry::Note("nowhere to go"));
    }
}

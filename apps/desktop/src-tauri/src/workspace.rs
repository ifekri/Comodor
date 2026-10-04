//! Which folder the Core works in, decided once per launch (data-model.md
//! §8, OD-3, FR-021, FR-022).
//!
//! 1. A command-line path that is a readable directory: used, no chooser.
//! 2. One that is not: reported, then 3.
//! 3. The chooser, opened at the last selected folder (or the system default
//!    if that folder is gone). A choice is stored as the last selected
//!    folder; a dismissal starts no Core.
//!
//! The result is kept for the whole launch: reloads and every kind of restart
//! reuse it, and only `choose_workspace` changes it.

use std::ffi::OsStr;
use std::path::{Path, PathBuf};

use crate::prefs::Preferences;
use crate::supervisor::{Failure, FailureClass};

/// The folder chooser. The application's is a thin wrapper over the dialog
/// plugin; the tests' records the start directory it was given.
pub trait Chooser {
    fn choose(&mut self, start: Option<&Path>) -> Option<PathBuf>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    CommandLine,
    Chooser,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Resolution {
    Chosen { source: Source, path: PathBuf, report: Option<String> },
    Dismissed { notice: String },
}

/// The notice shown after a dismissal.
pub const NO_WORKSPACE: &str = "No workspace chosen.";

/// Is `path` a directory the Core can work in?
pub fn check(path: &Path) -> Result<(), Failure> {
    let unavailable = |why: String| Failure::new(FailureClass::WorkspaceUnavailable,
        format!("The workspace {} is not available: {why}", path.display()));
    let metadata = std::fs::metadata(path).map_err(|problem| unavailable(match problem.kind() {
        std::io::ErrorKind::NotFound => "it does not exist.".into(),
        _ => format!("it cannot be read ({problem})."),
    }))?;
    if !metadata.is_dir() {
        return Err(unavailable("it is not a folder.".into()));
    }
    std::fs::read_dir(path)
        .map_err(|problem| unavailable(format!("it cannot be read ({problem}).")))?;
    Ok(())
}

/// Ask the chooser, starting at the last selected folder while it exists, and
/// store a choice.
pub fn choose(preferences: &mut Preferences, chooser: &mut dyn Chooser) -> Option<PathBuf> {
    let start = preferences.last_selected_folder.as_deref().filter(|folder| folder.is_dir());
    let chosen = chooser.choose(start)?;
    preferences.last_selected_folder = Some(chosen.clone());
    Some(chosen)
}

/// Decide the launch's workspace.
pub fn resolve_launch(command_line: Option<&OsStr>, preferences: &mut Preferences,
                      chooser: &mut dyn Chooser) -> Resolution {
    let mut report = None;
    if let Some(given) = command_line {
        let path = std::path::absolute(given).unwrap_or_else(|_| PathBuf::from(given));
        match check(&path) {
            Ok(()) => return Resolution::Chosen { source: Source::CommandLine, path, report: None },
            Err(failure) => report = Some(failure.message),
        }
    }
    match choose(preferences, chooser) {
        Some(path) => Resolution::Chosen { source: Source::Chooser, path, report },
        None => Resolution::Dismissed { notice: match report {
            Some(report) => format!("{report} {NO_WORKSPACE}"),
            None => NO_WORKSPACE.into(),
        } },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Recorder {
        starts: Vec<Option<PathBuf>>,
        answers: Vec<Option<PathBuf>>,
    }

    impl Recorder {
        fn answering(answers: Vec<Option<PathBuf>>) -> Self {
            Self { starts: vec![], answers }
        }
    }

    impl Chooser for Recorder {
        fn choose(&mut self, start: Option<&Path>) -> Option<PathBuf> {
            self.starts.push(start.map(Path::to_path_buf));
            if self.answers.is_empty() { None } else { self.answers.remove(0) }
        }
    }

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("comodor-ws-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn prefs_at(folder: Option<&Path>) -> Preferences {
        Preferences { last_selected_folder: folder.map(Path::to_path_buf),
                      ..Preferences::default() }
    }

    #[test]
    fn a_valid_command_line_path_is_used_with_no_chooser() {
        let dir = Dir::new("cli");
        let mut chooser = Recorder::answering(vec![]);
        let mut prefs = prefs_at(None);
        let resolution = resolve_launch(Some(dir.0.as_os_str()), &mut prefs, &mut chooser);
        assert_eq!(resolution, Resolution::Chosen { source: Source::CommandLine,
                                                    path: dir.0.clone(), report: None });
        assert!(chooser.starts.is_empty(), "no chooser");
        assert_eq!(prefs.last_selected_folder, None, "a command-line path is not a choice");
    }

    #[test]
    fn a_relative_command_line_path_is_made_absolute() {
        let mut prefs = prefs_at(None);
        match resolve_launch(Some(OsStr::new("src")), &mut prefs, &mut Recorder::answering(vec![])) {
            Resolution::Chosen { path, .. } => {
                assert!(path.is_absolute(), "{path:?}");
                assert_eq!(path, std::env::current_dir().unwrap().join("src"));
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn an_invalid_command_line_path_is_reported_and_the_chooser_opens() {
        let stored = Dir::new("stored-a");
        let chosen = Dir::new("chosen-a");
        let missing = stored.0.join("does-not-exist");
        let mut chooser = Recorder::answering(vec![Some(chosen.0.clone())]);
        let mut prefs = prefs_at(Some(&stored.0));
        match resolve_launch(Some(missing.as_os_str()), &mut prefs, &mut chooser) {
            Resolution::Chosen { source, path, report } => {
                assert_eq!(source, Source::Chooser);
                assert_eq!(path, chosen.0);
                let report = report.expect("the bad path is reported");
                assert!(report.contains(&missing.display().to_string()), "{report}");
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(chooser.starts, vec![Some(stored.0.clone())]);
    }

    #[test]
    fn no_path_gives_the_chooser_exactly_the_last_selected_folder() {
        let stored = Dir::new("stored-b");
        let mut chooser = Recorder::answering(vec![Some(stored.0.clone())]);
        let mut prefs = prefs_at(Some(&stored.0));
        resolve_launch(None, &mut prefs, &mut chooser);
        assert_eq!(chooser.starts, vec![Some(stored.0.clone())]);
    }

    #[test]
    fn a_folder_that_is_gone_opens_the_chooser_at_the_system_default() {
        let gone = std::env::temp_dir().join(format!("comodor-ws-gone-{}", std::process::id()));
        let mut chooser = Recorder::answering(vec![]);
        let mut prefs = prefs_at(Some(&gone));
        resolve_launch(None, &mut prefs, &mut chooser);
        assert_eq!(chooser.starts, vec![None]);
    }

    #[test]
    fn a_choice_is_stored_as_the_last_selected_folder() {
        let chosen = Dir::new("chosen-c");
        let mut chooser = Recorder::answering(vec![Some(chosen.0.clone())]);
        let mut prefs = prefs_at(None);
        assert_eq!(resolve_launch(None, &mut prefs, &mut chooser),
                   Resolution::Chosen { source: Source::Chooser, path: chosen.0.clone(), report: None });
        assert_eq!(prefs.last_selected_folder, Some(chosen.0.clone()));
    }

    #[test]
    fn a_dismissal_starts_nothing_and_says_no_workspace_chosen() {
        let mut chooser = Recorder::answering(vec![None]);
        let mut prefs = prefs_at(None);
        assert_eq!(resolve_launch(None, &mut prefs, &mut chooser),
                   Resolution::Dismissed { notice: NO_WORKSPACE.into() });
        assert_eq!(prefs.last_selected_folder, None);
    }

    #[test]
    fn a_dismissal_after_a_bad_path_still_reports_the_path() {
        let missing = std::env::temp_dir().join(format!("comodor-ws-none-{}", std::process::id()));
        let mut prefs = prefs_at(None);
        match resolve_launch(Some(missing.as_os_str()), &mut prefs, &mut Recorder::answering(vec![None])) {
            Resolution::Dismissed { notice } => {
                assert!(notice.contains(NO_WORKSPACE));
                assert!(notice.contains(&missing.display().to_string()), "{notice}");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn choose_again_opens_at_the_last_choice_and_stores_the_new_one() {
        let first = Dir::new("first");
        let second = Dir::new("second");
        let mut prefs = prefs_at(Some(&first.0));
        let mut chooser = Recorder::answering(vec![Some(second.0.clone())]);
        assert_eq!(choose(&mut prefs, &mut chooser), Some(second.0.clone()));
        assert_eq!(chooser.starts, vec![Some(first.0.clone())]);
        assert_eq!(prefs.last_selected_folder, Some(second.0.clone()));
    }

    #[test]
    fn a_missing_or_non_directory_path_is_workspace_unavailable() {
        let dir = Dir::new("check");
        assert_eq!(check(&dir.0), Ok(()));
        let missing = dir.0.join("missing");
        let failure = check(&missing).expect_err("missing");
        assert_eq!(failure.class, FailureClass::WorkspaceUnavailable);
        assert!(failure.message.contains(&missing.display().to_string()));
        let file = dir.0.join("file.txt");
        std::fs::write(&file, "x").unwrap();
        let failure = check(&file).expect_err("a file");
        assert_eq!(failure.class, FailureClass::WorkspaceUnavailable);
        assert!(failure.message.contains("not a folder"), "{}", failure.message);
    }

    #[cfg(unix)]
    #[test]
    fn an_unreadable_directory_is_workspace_unavailable() {
        use std::os::unix::fs::PermissionsExt;
        let dir = Dir::new("unreadable");
        let locked = dir.0.join("locked");
        std::fs::create_dir(&locked).unwrap();
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o000)).unwrap();
        let readable_anyway = std::fs::read_dir(&locked).is_ok(); // running as root
        let result = check(&locked);
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o755)).unwrap();
        if !readable_anyway {
            let failure = result.expect_err("unreadable");
            assert_eq!(failure.class, FailureClass::WorkspaceUnavailable);
            assert!(failure.message.contains("cannot be read"), "{}", failure.message);
        }
    }
}

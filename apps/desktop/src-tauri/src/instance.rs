//! A second launch (contracts/core-supervision.md §6, FR-019, SC-008).
//!
//! The single-instance plugin hands the running application the second
//! launch's arguments. It is not a fresh launch: the window is focused and
//! the workspace stays. Only an explicit path to a different folder may
//! change it, and only after the person confirms in a native dialog; the
//! change goes through the stop sequence, and no second Core is ever started.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

/// The confirmation dialog. The application's is native; the test build's
/// is a double.
pub trait Confirm {
    /// Whether to switch to `to`. No answer counts as no.
    fn switch_workspace(&mut self, from: &Path, to: &Path) -> bool;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Decision {
    /// Bring the window forward; nothing else.
    Focus,
    /// The person is asked whether to switch to this folder.
    Ask(PathBuf),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    Focus,
    /// Stop the Core (reason `workspace_change`) and start one here.
    Switch(PathBuf),
}

/// What a second launch with `args` (after the program), started in `cwd`,
/// asks of a window working in `current`.
pub fn decide(current: Option<&Path>, args: &[OsString], cwd: &Path) -> Decision {
    let Some(given) = args.iter().find(|arg| !arg.to_string_lossy().starts_with('-')) else {
        return Decision::Focus;
    };
    let path = cwd.join(given);
    if !path.is_dir() {
        return Decision::Focus;
    }
    let same = current.is_some_and(|current| same_folder(current, &path));
    if same { Decision::Focus } else { Decision::Ask(std::path::absolute(&path).unwrap_or(path)) }
}

fn same_folder(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

/// The decision, carried out with the person's answer where one is needed.
pub fn resolve(decision: Decision, current: Option<&Path>, confirm: &mut dyn Confirm) -> Action {
    match decision {
        Decision::Focus => Action::Focus,
        Decision::Ask(to) => {
            let from = current.unwrap_or_else(|| Path::new(""));
            if confirm.switch_workspace(from, &to) { Action::Switch(to) } else { Action::Focus }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Answer {
        yes: bool,
        asked: Vec<(PathBuf, PathBuf)>,
    }

    impl Confirm for Answer {
        fn switch_workspace(&mut self, from: &Path, to: &Path) -> bool {
            self.asked.push((from.to_path_buf(), to.to_path_buf()));
            self.yes
        }
    }

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir().join(format!("comodor-instance-{label}-{}", std::process::id()));
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn os(items: &[&Path]) -> Vec<OsString> {
        items.iter().map(|p| p.as_os_str().to_owned()).collect()
    }

    #[test]
    fn no_path_only_focuses() {
        let current = Dir::new("current-a");
        assert_eq!(decide(Some(&current.0), &[], &current.0), Decision::Focus);
        assert_eq!(decide(Some(&current.0), &["--flag".into()], &current.0), Decision::Focus);
    }

    #[test]
    fn the_current_path_only_focuses() {
        let current = Dir::new("current-b");
        assert_eq!(decide(Some(&current.0), &os(&[&current.0]), Path::new("/")), Decision::Focus);
        // The same folder written relative to the second launch's directory.
        let parent = current.0.parent().unwrap();
        let name = current.0.file_name().unwrap();
        assert_eq!(decide(Some(&current.0), &[name.to_owned()], parent), Decision::Focus);
    }

    #[test]
    fn a_different_valid_path_is_asked_about() {
        let current = Dir::new("current-c");
        let other = Dir::new("other-c");
        assert_eq!(decide(Some(&current.0), &os(&[&other.0]), Path::new("/")), Decision::Ask(other.0.clone()));
    }

    #[test]
    fn a_path_that_is_not_a_folder_only_focuses() {
        let current = Dir::new("current-d");
        let missing = current.0.join("no-such-folder");
        assert_eq!(decide(Some(&current.0), &os(&[&missing]), Path::new("/")), Decision::Focus);
    }

    #[test]
    fn confirmed_switches_and_declined_keeps() {
        let current = Dir::new("current-e");
        let other = Dir::new("other-e");
        let mut yes = Answer { yes: true, asked: vec![] };
        assert_eq!(resolve(Decision::Ask(other.0.clone()), Some(&current.0), &mut yes),
                   Action::Switch(other.0.clone()));
        assert_eq!(yes.asked, vec![(current.0.clone(), other.0.clone())]);
        let mut no = Answer { yes: false, asked: vec![] };
        assert_eq!(resolve(Decision::Ask(other.0.clone()), Some(&current.0), &mut no), Action::Focus);
        let mut never = Answer { yes: true, asked: vec![] };
        assert_eq!(resolve(Decision::Focus, Some(&current.0), &mut never), Action::Focus);
        assert!(never.asked.is_empty(), "nothing to ask");
    }

    #[test]
    fn without_a_workspace_yet_a_path_is_still_asked_about() {
        let other = Dir::new("other-f");
        assert_eq!(decide(None, &os(&[&other.0]), Path::new("/")), Decision::Ask(other.0.clone()));
    }
}

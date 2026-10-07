//! Finding the Core to start (contracts/core-supervision.md §1, FR-002).
//!
//! In order, stopping at the first that exists:
//! 1. `COMODOR_BIN`, with `COMODOR_ARGS` split on whitespace as its leading
//!    arguments — the terminal interface's convention;
//! 2. `comodor` on `PATH`.
//!
//! A bare name in `COMODOR_BIN` is looked up on `PATH` too, the way a shell
//! would, but nothing is ever run through a shell.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

use crate::platform::CoreCommand;
use crate::supervisor::{Failure, FailureClass};

/// What locating reads, injectable so tests need no real environment.
pub struct Lookup<'a> {
    pub var: &'a dyn Fn(&str) -> Option<OsString>,
    pub is_file: &'a dyn Fn(&Path) -> bool,
}

/// Locate the Core from this process's environment and file system.
pub fn locate_from_environment() -> Result<CoreCommand, Failure> {
    locate(&Lookup {
        var: &|name| std::env::var_os(name),
        is_file: &|path| path.is_file(),
    })
}

/// Locate the Core, or fail with `not_found` naming every place tried.
pub fn locate(lookup: &Lookup) -> Result<CoreCommand, Failure> {
    let mut tried = Vec::new();
    match (lookup.var)("COMODOR_BIN").filter(|bin| !bin.is_empty()) {
        Some(bin) => {
            let args = (lookup.var)("COMODOR_ARGS")
                .map(|text| text.to_string_lossy().split_whitespace().map(OsString::from).collect())
                .unwrap_or_default();
            match find(Path::new(&bin), lookup, &mut tried) {
                Some(program) => return Ok(CoreCommand { program: program.into(), args }),
                None => tried.insert(0, format!("COMODOR_BIN ({})", Path::new(&bin).display())),
            }
        }
        None => tried.push("COMODOR_BIN is not set".into()),
    }
    if let Some(program) = find(Path::new("comodor"), lookup, &mut tried) {
        return Ok(CoreCommand { program: program.into(), args: vec![] });
    }
    Err(Failure::new(FailureClass::NotFound, format!(
        "Comodor was not found. Tried: {}. Install Comodor (`pipx install comodor` or          `pip install comodor`), or set COMODOR_BIN to the `comodor` executable.",
        tried.join("; "))))
}

/// `program` itself when it names a path; otherwise each `PATH` directory,
/// with the executable extensions on Windows. Every place looked is noted.
fn find(program: &Path, lookup: &Lookup, tried: &mut Vec<String>) -> Option<PathBuf> {
    if program.components().count() > 1 || program.is_absolute() {
        return candidates(program, lookup).into_iter().find(|path| (lookup.is_file)(path));
    }
    let path = (lookup.var)("PATH").unwrap_or_default();
    for directory in std::env::split_paths(&path).filter(|dir| !dir.as_os_str().is_empty()) {
        let joined = directory.join(program);
        tried.push(joined.display().to_string());
        if let Some(found) = candidates(&joined, lookup).into_iter().find(|p| (lookup.is_file)(p)) {
            return Some(found);
        }
    }
    None
}

fn candidates(path: &Path, lookup: &Lookup) -> Vec<PathBuf> {
    let mut all = vec![path.to_path_buf()];
    if cfg!(windows) && path.extension().is_none() {
        let extensions = (lookup.var)("PATHEXT")
            .map(|text| text.to_string_lossy().into_owned())
            .unwrap_or_else(|| ".COM;.EXE;.BAT;.CMD".into());
        for extension in extensions.split(';').filter(|e| !e.is_empty()) {
            let mut with = path.as_os_str().to_owned();
            with.push(extension.to_ascii_lowercase());
            all.push(PathBuf::from(with));
        }
    }
    all
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{HashMap, HashSet};

    const SEP: &str = if cfg!(windows) { ";" } else { ":" };

    fn root(name: &str) -> PathBuf {
        if cfg!(windows) { PathBuf::from(format!(r"C:\{name}")) } else { PathBuf::from(format!("/{name}")) }
    }

    fn exe(name: &str) -> String {
        if cfg!(windows) { format!("{name}.exe") } else { name.to_string() }
    }

    struct World {
        vars: HashMap<String, OsString>,
        files: HashSet<PathBuf>,
    }

    impl World {
        fn new() -> Self {
            Self { vars: HashMap::new(), files: HashSet::new() }
        }
        fn var(mut self, name: &str, value: impl Into<OsString>) -> Self {
            self.vars.insert(name.into(), value.into());
            self
        }
        fn file(mut self, path: PathBuf) -> Self {
            self.files.insert(path);
            self
        }
        fn locate(&self) -> Result<CoreCommand, Failure> {
            let var = |name: &str| self.vars.get(name).cloned();
            let is_file = |path: &Path| self.files.contains(path);
            locate(&Lookup { var: &var, is_file: &is_file })
        }
    }

    #[test]
    fn comodor_bin_is_used_with_comodor_args_split_on_whitespace() {
        let bin = root("tools").join(exe("python"));
        let world = World::new()
            .var("COMODOR_BIN", bin.clone())
            .var("COMODOR_ARGS", "  /fixtures/core.py   echo ")
            .file(bin.clone());
        let command = world.locate().expect("found");
        assert_eq!(command.program, OsString::from(bin));
        assert_eq!(command.args, vec![OsString::from("/fixtures/core.py"), OsString::from("echo")]);
    }

    #[test]
    fn a_bare_name_in_comodor_bin_is_found_on_path() {
        let dir = root("bin");
        let world = World::new()
            .var("COMODOR_BIN", "python")
            .var("PATH", format!("{}{SEP}{}", root("empty").display(), dir.display()))
            .file(dir.join(exe("python")));
        let command = world.locate().expect("found");
        assert_eq!(command.program, OsString::from(dir.join(exe("python"))));
        assert!(command.args.is_empty());
    }

    #[test]
    fn without_comodor_bin_comodor_on_path_is_used() {
        let dir = root("venv").join("bin");
        let world = World::new()
            .var("PATH", dir.as_os_str().to_owned())
            .file(dir.join(exe("comodor")));
        let command = world.locate().expect("found");
        assert_eq!(command.program, OsString::from(dir.join(exe("comodor"))));
        assert!(command.args.is_empty(), "COMODOR_ARGS belongs to COMODOR_BIN only");
    }

    #[test]
    fn a_missing_comodor_bin_falls_back_to_path() {
        let dir = root("bin");
        let world = World::new()
            .var("COMODOR_BIN", root("gone").join(exe("comodor")))
            .var("PATH", dir.as_os_str().to_owned())
            .file(dir.join(exe("comodor")));
        assert_eq!(world.locate().expect("found").program, OsString::from(dir.join(exe("comodor"))));
    }

    #[test]
    fn not_found_lists_every_location_tried_and_how_to_fix_it() {
        let gone = root("gone").join(exe("comodor"));
        let world = World::new()
            .var("COMODOR_BIN", gone.clone())
            .var("PATH", format!("{}{SEP}{}", root("a").display(), root("b").display()));
        let failure = world.locate().expect_err("nothing to find");
        assert_eq!(failure.class, FailureClass::NotFound);
        let message = failure.message;
        assert!(message.contains(&gone.display().to_string()), "{message}");
        assert!(message.contains(&root("a").display().to_string()), "{message}");
        assert!(message.contains(&root("b").display().to_string()), "{message}");
        assert!(message.contains("COMODOR_BIN"), "{message}");
        assert!(message.contains("pipx install comodor"), "{message}");
    }

    #[test]
    fn not_found_says_when_comodor_bin_is_not_set() {
        let failure = World::new().var("PATH", root("a").as_os_str().to_owned())
            .locate().expect_err("nothing to find");
        assert!(failure.message.contains("COMODOR_BIN is not set"), "{}", failure.message);
    }
}

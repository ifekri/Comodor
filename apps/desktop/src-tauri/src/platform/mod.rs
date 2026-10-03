//! Starting the Core process, and stopping its whole tree.
//!
//! The Core is started directly — no shell, so a path never meets quoting
//! rules — with the workspace as its working directory, the environment
//! inherited unchanged, and all three standard streams piped: stdin and
//! stdout are the protocol, stderr is diagnostics (contracts/core-supervision.md
//! §2). Everything platform-specific is behind the `imp` module.

use std::ffi::OsString;
use std::io;
use std::path::Path;
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Arc;

#[cfg(unix)]
#[path = "unix.rs"]
mod imp;
#[cfg(windows)]
#[path = "windows.rs"]
mod imp;

/// The executable and the leading arguments; `core --stdio` is appended.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CoreCommand {
    pub program: OsString,
    pub args: Vec<OsString>,
}

impl CoreCommand {
    /// Exactly the arguments the Core is started with.
    pub fn full_args(&self) -> Vec<OsString> {
        let mut args = self.args.clone();
        args.push("core".into());
        args.push("--stdio".into());
        args
    }
}

/// A started Core, and what keeps its process tree under this application.
pub struct SpawnedCore {
    pub child: Child,
    pub pid: u32,
    tree: Stopper,
}

/// Ends the Core and every process it started. Shared, so it can be used
/// while another thread waits on the Core's exit.
#[derive(Clone)]
pub struct Stopper(Arc<imp::Tree>);

impl Stopper {
    pub fn terminate(&self) -> io::Result<()> {
        self.0.terminate()
    }
}

impl SpawnedCore {
    /// The three pipes. Called once, by whoever reads and writes them.
    pub fn take_streams(&mut self) -> (ChildStdin, ChildStdout, ChildStderr) {
        (
            self.child.stdin.take().expect("stdin is piped and taken once"),
            self.child.stdout.take().expect("stdout is piped and taken once"),
            self.child.stderr.take().expect("stderr is piped and taken once"),
        )
    }

    pub fn stopper(&self) -> Stopper {
        self.tree.clone()
    }

    /// End the Core and every process it started, now.
    pub fn force_stop(&mut self) -> io::Result<()> {
        self.tree.terminate()
    }
}

/// The command as it is spawned. `test_env` is empty in the application; the
/// integration tests use it to give each Core its own temporary home without
/// changing their own process's environment.
pub fn build_command(command: &CoreCommand, workspace: &Path,
                     test_env: &[(OsString, OsString)]) -> Command {
    let mut built = Command::new(&command.program);
    built.args(command.full_args())
        .current_dir(workspace)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in test_env {
        built.env(key, value);
    }
    imp::configure(&mut built);
    built
}

/// Start the Core in `workspace`.
pub fn spawn_core(command: &CoreCommand, workspace: &Path,
                  test_env: &[(OsString, OsString)]) -> io::Result<SpawnedCore> {
    let mut child = build_command(command, workspace, test_env).spawn()?;
    let tree = match imp::Tree::adopt(&child) {
        Ok(tree) => tree,
        Err(problem) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(problem);
        }
    };
    let pid = child.id();
    Ok(SpawnedCore { child, pid, tree: Stopper(Arc::new(tree)) })
}

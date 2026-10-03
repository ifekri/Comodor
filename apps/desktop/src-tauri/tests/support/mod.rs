//! Shared helpers for the desktop's integration tests.
//!
//! Every Core these tests start is offline: the scripted Core fixture, a Core
//! double, or a real `comodor core --stdio` whose only provider is the `fake`
//! one. Each test gets its own temporary `COMODOR_HOME` and workspace, passed
//! to the Core as explicit environment overrides rather than by mutating this
//! process's environment, so tests running in parallel never share a home.

#![allow(dead_code)]

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use comodor_desktop::platform::CoreCommand;

/// The repository root, from this crate's manifest directory.
pub fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("..")
        .canonicalize().expect("repository root")
}

/// The Python fixtures directory.
pub fn fixtures() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests").join("fixtures")
}

/// The interpreter the Core runs on: `COMODOR_PYTHON`, else `python`.
pub fn python() -> OsString {
    std::env::var_os("COMODOR_PYTHON").unwrap_or_else(|| OsString::from("python"))
}

static NEXT: AtomicU64 = AtomicU64::new(0);

/// A temporary directory removed when dropped.
pub struct Scratch {
    pub root: PathBuf,
}

impl Scratch {
    pub fn new(label: &str) -> Self {
        let n = NEXT.fetch_add(1, Ordering::SeqCst);
        let root = std::env::temp_dir().join(format!(
            "comodor-desktop-{label}-{}-{n}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).expect("scratch directory");
        Self { root }
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

/// How the offline home is configured.
#[derive(Clone, Debug)]
pub struct HomeOptions {
    /// The provider's credential. A unique value makes it a canary.
    pub api_key: String,
    /// False writes a configuration with no provider at all.
    pub configured: bool,
    pub model: String,
}

impl Default for HomeOptions {
    fn default() -> Self {
        Self { api_key: "test".into(), configured: true, model: "fake-1".into() }
    }
}

/// A temporary `COMODOR_HOME` and workspace for one test.
pub struct CoreHome {
    pub scratch: Scratch,
    pub home: PathBuf,
    pub workspace: PathBuf,
}

impl CoreHome {
    pub fn new(label: &str) -> Self {
        Self::with(label, HomeOptions::default())
    }

    pub fn with(label: &str, options: HomeOptions) -> Self {
        let scratch = Scratch::new(label);
        let home = scratch.root.join("home");
        let workspace = scratch.root.join("workspace");
        fs::create_dir_all(&home).expect("home");
        fs::create_dir_all(&workspace).expect("workspace");
        write_config(&home, &options);
        Self { scratch, home, workspace }
    }

    /// Replace the configuration, as `comodor setup` would.
    pub fn configure(&self, options: &HomeOptions) {
        write_config(&self.home, options);
    }

    /// The environment overrides a Core needs to use this home offline.
    pub fn env(&self) -> Vec<(OsString, OsString)> {
        vec![
            ("COMODOR_HOME".into(), self.home.clone().into()),
            ("PYTHONPATH".into(), repo_root().join("src").into()),
            ("PYTHONIOENCODING".into(), "utf-8".into()),
        ]
    }
}

fn write_config(home: &Path, options: &HomeOptions) {
    let mut config = serde_json::json!({
        "agent": { "mode": "act", "loop": false },
        "learning": { "enabled": false },
        "mcp": { "enabled": false },
        "cron": { "enabled": false },
        "skills": { "enabled": false },
    });
    if options.configured {
        config["provider"] = "fake".into();
        config["model"] = options.model.clone().into();
        config["providers"] = serde_json::json!({
            "fake": { "name": "fake", "kind": "fake", "base_url": "offline",
                      "api_key": options.api_key, "model": options.model,
                      "label": "Fake" }
        });
    }
    fs::write(home.join("config.json"), config.to_string()).expect("config.json");
}

/// The command for a fixture: `<python> <fixture> <argument>`, to which the
/// application appends `core --stdio` itself.
pub fn fixture_command(fixture: &str, argument: &str) -> CoreCommand {
    CoreCommand {
        program: python(),
        args: vec![fixtures().join(fixture).into(), argument.into()],
    }
}

/// The real Core: `<python> -m comodor`, plus `core --stdio`.
pub fn real_core_command() -> CoreCommand {
    CoreCommand { program: python(), args: vec!["-m".into(), "comodor".into()] }
}

/// One explicit release point in a fixture (`COMODOR_TEST_HOLD`).
pub struct HoldPoint {
    pub address: String,
}

impl HoldPoint {
    pub fn new(label: &str, scratch: &Scratch) -> Self {
        let n = NEXT.fetch_add(1, Ordering::SeqCst);
        #[cfg(windows)]
        let address = {
            let _ = scratch;
            format!(r"\\.\pipe\comodor-hold-{label}-{}-{n}", std::process::id())
        };
        #[cfg(unix)]
        let address = scratch.root.join(format!("hold-{label}-{n}.sock"))
            .to_string_lossy().into_owned();
        Self { address }
    }

    pub fn env(&self) -> (OsString, OsString) {
        ("COMODOR_TEST_HOLD".into(), self.address.clone().into())
    }

    /// Let the fixture go past its hold point. One framed message, in the
    /// format `multiprocessing.connection` reads: a message-mode pipe write
    /// on Windows, a 4-byte big-endian length prefix on a Unix socket.
    pub fn release(&self) {
        let body = b"release";
        #[cfg(windows)]
        {
            use std::io::Write;
            let mut pipe = fs::OpenOptions::new().write(true).open(&self.address)
                .expect("open the hold pipe");
            pipe.write_all(body).expect("release the hold");
        }
        #[cfg(unix)]
        {
            use std::io::Write;
            let mut stream = std::os::unix::net::UnixStream::connect(&self.address)
                .expect("connect to the hold socket");
            stream.write_all(&(body.len() as i32).to_be_bytes()).expect("length");
            stream.write_all(body).expect("release the hold");
        }
    }
}

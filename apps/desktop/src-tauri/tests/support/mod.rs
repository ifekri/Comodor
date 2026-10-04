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
use std::cell::RefCell;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::time::Duration;

use comodor_desktop::platform::CoreCommand;
use comodor_desktop::supervisor::{Failure, Options, PageSink, Supervisor};
use serde_json::Value;

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

#[cfg(unix)]
impl Drop for HoldPoint {
    /// A socket left by a fixture that was killed would refuse the next bind.
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.address);
    }
}

impl HoldPoint {
    pub fn new(label: &str, scratch: &Scratch) -> Self {
        let n = NEXT.fetch_add(1, Ordering::SeqCst);
        #[cfg(windows)]
        let address = {
            let _ = scratch;
            format!(r"\\.\pipe\comodor-hold-{label}-{}-{n}", std::process::id())
        };
        // A Unix socket path is limited to about 100 bytes (104 on macOS),
        // which a test's temporary folder can exceed: a short name in /tmp.
        #[cfg(unix)]
        let address = {
            let _ = (scratch, label);
            format!("/tmp/comodor-hold-{}-{n}.sock", std::process::id())
        };
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

/// How long any one wait may take before the test fails. A bound on failure,
/// never a delay: every wait returns as soon as its condition holds.
pub const DEADLINE: Duration = Duration::from_secs(60);

/// A supervisor for one test, whose Core is `command`, in `home`.
pub fn launch(command: CoreCommand, home: &CoreHome) -> Supervisor {
    launch_with_env(command, home, vec![])
}

/// The same, with variables added for this test's Cores only.
pub fn launch_with_env(command: CoreCommand, home: &CoreHome,
                       extra: Vec<(OsString, OsString)>) -> Supervisor {
    let mut env = home.env();
    env.extend(extra);
    Supervisor::launch(Options { locate: Box::new(move || Ok(command.clone())), test_env: env, log: None })
}

/// A supervisor whose locating has already happened, successfully or not.
pub fn launch_located(located: Result<CoreCommand, Failure>, home: &CoreHome) -> Supervisor {
    Supervisor::launch(Options { locate: Box::new(move || located.clone()), test_env: home.env(),
                                log: None })
}

/// A page, as far as the native side can tell: everything sent to it, in
/// order.
pub struct Page {
    sender: Sender<Value>,
    receiver: Receiver<Value>,
    seen: RefCell<Vec<Value>>,
}

struct PageEnd(Sender<Value>);

impl PageSink for PageEnd {
    fn send(&self, message: Value) {
        let _ = self.0.send(message);
    }
}

impl Page {
    pub fn new() -> Self {
        let (sender, receiver) = channel();
        Self { sender, receiver, seen: RefCell::new(vec![]) }
    }

    pub fn sink(&self) -> Box<dyn PageSink> {
        Box::new(PageEnd(self.sender.clone()))
    }

    /// The next message, by the failure deadline.
    fn next(&self) -> Value {
        let message = self.receiver.recv_timeout(DEADLINE).expect("a message by the deadline");
        self.seen.borrow_mut().push(message.clone());
        message
    }

    /// Wait for the message satisfying `wanted`, keeping every earlier one.
    pub fn until(&self, wanted: impl Fn(&Value) -> bool) -> Value {
        if let Some(found) = self.seen.borrow().iter().find(|m| wanted(m)) {
            return found.clone();
        }
        loop {
            let message = self.next();
            if wanted(&message) {
                return message;
            }
        }
    }

    /// The protocol answer to the page's request `id`.
    pub fn answer(&self, id: &str) -> Value {
        let line = self.until(|m| m["kind"] == "line" && serde_json::from_str::<Value>(
            m["line"].as_str().unwrap_or("")).map(|l| l["id"] == id).unwrap_or(false));
        serde_json::from_str(line["line"].as_str().unwrap()).unwrap()
    }

    /// Every protocol line received so far, after waiting for one that
    /// satisfies `wanted`.
    pub fn lines_until(&self, wanted: impl Fn(&Value) -> bool) -> Vec<Value> {
        self.until(|m| m["kind"] == "line"
            && serde_json::from_str::<Value>(m["line"].as_str().unwrap_or("")).map(|l| wanted(&l)).unwrap_or(false));
        self.seen.borrow().iter().filter(|m| m["kind"] == "line")
            .map(|m| serde_json::from_str(m["line"].as_str().unwrap()).unwrap()).collect()
    }

    /// The status states received, in order, once `state` has been seen
    /// `count` times.
    pub fn states_until(&self, count: usize, state: &str) -> Vec<String> {
        let states = || -> Vec<String> {
            self.seen.borrow().iter().filter(|m| m["kind"] == "status")
                .map(|m| m["status"]["state"].as_str().unwrap_or("").to_string()).collect()
        };
        while states().iter().filter(|s| *s == state).count() < count {
            self.next();
        }
        states()
    }
}

impl Page {
    /// The params of the first `event` satisfying `wanted`, waiting for it.
    pub fn event(&self, name: &str, wanted: impl Fn(&Value) -> bool) -> Value {
        let line = self.until(|m| m["kind"] == "line" && serde_json::from_str::<Value>(
            m["line"].as_str().unwrap_or(""))
            .map(|l| l["type"] == "event" && l["event"] == name && wanted(&l["params"]))
            .unwrap_or(false));
        let line: Value = serde_json::from_str(line["line"].as_str().unwrap()).unwrap();
        line["params"].clone()
    }
}

/// One protocol request line from the page.
pub fn request(id: &str, method: &str, params: Value) -> String {
    serde_json::json!({ "version": 2, "type": "request", "id": id, "method": method,
                        "params": params }).to_string()
}

impl Page {
    /// How many messages have been seen: a point to wait from.
    pub fn mark(&self) -> usize {
        self.seen.borrow().len()
    }

    /// The params of the first `event` after `mark` satisfying `wanted`.
    pub fn event_since(&self, mark: usize, name: &str, wanted: impl Fn(&Value) -> bool) -> Value {
        let matches = |m: &Value| m["kind"] == "line" && serde_json::from_str::<Value>(
            m["line"].as_str().unwrap_or(""))
            .map(|l| l["type"] == "event" && l["event"] == name && wanted(&l["params"]))
            .unwrap_or(false);
        loop {
            if let Some(found) = self.seen.borrow().iter().skip(mark).find(|m| matches(m)) {
                let line: Value = serde_json::from_str(found["line"].as_str().unwrap()).unwrap();
                return line["params"].clone();
            }
            self.next();
        }
    }
}

/// End a process at once, as a crash would.
pub fn kill(pid: u32) {
    #[cfg(windows)]
    let status = std::process::Command::new("taskkill")
        .args(["/F", "/PID", &pid.to_string()])
        .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null())
        .status();
    #[cfg(unix)]
    let status = std::process::Command::new("kill").args(["-9", &pid.to_string()]).status();
    assert!(status.map(|s| s.success()).unwrap_or(false), "could not kill {pid}");
}

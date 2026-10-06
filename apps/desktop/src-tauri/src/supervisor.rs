//! The Core's lifecycle (data-model.md §1, contracts/core-supervision.md).
//!
//! `Machine` is the whole policy and nothing else: it takes one observed
//! input at a time — a spawn result, a line, an exit, a person's action — and
//! answers with the effects to carry out. It never touches a process, a pipe
//! or a clock, so every transition is tested directly, deadlines included.
//! The driver (below) owns the process and turns effects into I/O.

use std::collections::{HashMap, VecDeque};
use std::ffi::OsString;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{ChildStdin, Command};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};

use crate::diag::{self, DiagnosticTail};
use crate::logfile::{Entry, Log};
use crate::platform::{build_command, spawn_core, CoreCommand, Stopper};
use crate::relay;
use crate::restart::{RestartPolicy, Turns};
use crate::shutdown::{self, StopOutcome, StopReason};
use crate::workspace;

pub type CoreId = u64;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Absent,
    Starting,
    Handshaking,
    Ready,
    Restarting,
    Failed,
    Stopping,
    Stopped,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailureClass {
    NotFound,
    SpawnFailed,
    WorkspaceUnavailable,
    ExitedBeforeReady,
    ProtocolMismatch,
    ProtocolFault,
    Crashed,
}

/// A failure as the window shows it: its class and its own message.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Failure {
    pub class: FailureClass,
    pub message: String,
}

impl Failure {
    pub fn new(class: FailureClass, message: impl Into<String>) -> Self {
        Self { class, message: message.into() }
    }
}

/// What the machine is told.
#[derive(Clone, Debug, PartialEq)]
pub enum Input {
    /// A workspace is decided: start a Core there.
    Start { workspace: PathBuf },
    /// The launch chooser was dismissed, or a command-line path was refused.
    NoWorkspace { notice: String },
    /// The driver started the Core for `core`.
    Spawned { core: CoreId, pid: u32 },
    /// The driver could not start it: `not_found`, `spawn_failed` or
    /// `workspace_unavailable`.
    SpawnFailed { core: CoreId, failure: Failure },
    /// One line from the Core's stdout.
    Line { core: CoreId, line: String },
    /// The Core's process exited.
    Exited { core: CoreId, code: Option<i32> },
    /// The person's "Try again".
    Retry,
    /// Stop the Core, for this reason (contracts/core-supervision.md §5).
    Stop { reason: StopReason },
    /// The grace for stopping `core` ran out.
    DeadlinePassed { core: CoreId },
    /// The person's "Quit now", while stopping.
    QuitNow,
}

/// What the driver is asked to do.
#[derive(Clone, Debug, PartialEq)]
pub enum Effect {
    Spawn { core: CoreId, workspace: PathBuf },
    Write { core: CoreId, line: String },
    CloseStdin { core: CoreId },
    ForceStop { core: CoreId },
    /// The status changed: tell the page.
    StatusChanged,
    /// A protocol line for the page of `generation`.
    ToPage { generation: u64, line: String },
    /// The page of `generation` lost its Core: it must reconnect.
    PageClosed { generation: u64, reason: String },
    /// Tell the machine `DeadlinePassed` for `core` after this long.
    Deadline { core: CoreId, after: Duration },
    /// A fixed line for the application's log.
    Note(&'static str),
    /// The Core has stopped and the application should end.
    Finished,
}

/// The `status` command's answer and the channel's `status` message.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Status {
    pub state: State,
    /// For display: a path that is not UTF-8 loses bytes here.
    pub workspace: Option<String>,
    /// Which workspace, losslessly: it changes exactly when the folder
    /// does, and is never reused within a launch.
    pub workspace_id: Option<String>,
    pub failure: Option<Failure>,
    pub restart_count: u32,
    pub restart_limit: u32,
    pub closing: Option<Value>,
    pub stop_outcome: Option<StopOutcome>,
    pub core: Option<CoreIdentity>,
    pub notice: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CoreIdentity {
    pub name: String,
    pub version: String,
}

/// The restart limit (OD-1): automatic restarts stop at this crash.
pub const RESTART_LIMIT: u32 = crate::restart::LIMIT;

pub struct Machine {
    state: State,
    workspace: Option<PathBuf>,
    /// Bumped whenever the workspace becomes a different folder.
    workspace_epoch: u64,
    /// This launch, so a `workspace_id` never repeats one from another.
    launch: u32,
    /// The Core whose observations count; anything from another is stale.
    core: Option<CoreId>,
    /// A Core stopped for a fault that has not exited yet: no other Core
    /// starts until it has.
    faulted: Option<CoreId>,
    /// A start waiting for `faulted` to exit.
    deferred: bool,
    next_core: CoreId,
    failure: Option<Failure>,
    notice: Option<String>,
    identity: Option<CoreIdentity>,
    restarts: RestartPolicy,
    turns: Turns,
    relay: relay::Relay,
    clock: Arc<dyn Fn() -> Instant + Send + Sync>,
    /// The stop in progress: why, and since when.
    stopping: Option<(StopReason, Instant)>,
    forced: bool,
    stop_outcome: Option<StopOutcome>,
}

impl Default for Machine {
    fn default() -> Self {
        Self::new()
    }
}

impl Machine {
    pub fn new() -> Self {
        Self::with_clock(Arc::new(Instant::now))
    }

    /// A machine whose idea of now is `clock` (the tests' is moved by hand).
    pub fn with_clock(clock: Arc<dyn Fn() -> Instant + Send + Sync>) -> Self {
        Self {
            state: State::Absent,
            workspace: None,
            workspace_epoch: 0,
            launch: std::process::id(),
            core: None,
            faulted: None,
            deferred: false,
            next_core: 1,
            failure: None,
            notice: None,
            identity: None,
            restarts: RestartPolicy::new(),
            turns: Turns::new(),
            relay: relay::Relay::new(),
            clock,
            stopping: None,
            forced: false,
            stop_outcome: None,
        }
    }

    pub fn state(&self) -> State {
        self.state
    }

    /// The workspace exactly, as a path (`status` has it for display only).
    pub fn workspace(&self) -> Option<&Path> {
        self.workspace.as_deref()
    }

    pub fn status(&self) -> Status {
        Status {
            state: self.state,
            workspace: self.workspace.as_ref().map(|path| path.display().to_string()),
            workspace_id: self.workspace.as_ref().map(|_| format!("{}:{}", self.launch, self.workspace_epoch)),
            failure: self.failure.clone(),
            restart_count: self.restarts.count(),
            restart_limit: RESTART_LIMIT,
            closing: self.stopping.as_ref().map(|(_, since)| json!({
                "seconds_remaining": shutdown::seconds_remaining((self.clock)() - *since),
            })),
            stop_outcome: self.stop_outcome,
            core: self.identity.clone(),
            notice: self.notice.clone(),
        }
    }

    /// The cached `client.hello` result, once the Core is ready.
    pub fn handshake(&self) -> Option<&Value> {
        self.relay.handshake()
    }

    /// Was `url` a link in a line the current page was shown?
    pub fn displayed(&self, url: &str) -> bool {
        self.relay.displayed(url)
    }

    /// A page connects: its generation.
    pub fn connect(&mut self) -> u64 {
        self.relay.connect()
    }

    /// One protocol request from the page of `generation`.
    pub fn send_line(&mut self, generation: u64, line: &str) -> Result<Vec<Effect>, String> {
        let ready = self.state == State::Ready;
        match self.relay.from_page(generation, line, ready)? {
            relay::FromPage::Answer(answer) => Ok(vec![Effect::ToPage { generation, line: answer }]),
            relay::FromPage::ToCore { line, observed } => {
                let core = self.core.filter(|_| ready).ok_or("the Core is not ready")?;
                for observation in &observed {
                    self.turns.observe(observation);
                }
                Ok(vec![Effect::Write { core, line }])
            }
        }
    }

    /// A protocol line from a ready Core.
    fn core_line(&mut self, line: &str) -> Vec<Effect> {
        let answers_native = serde_json::from_str::<Value>(line).ok()
            .and_then(|envelope| envelope.get("id").and_then(Value::as_str).map(str::to_owned))
            .is_some_and(|id| id.starts_with("native:"));
        if answers_native {
            return vec![];
        }
        let relayed = self.relay.from_core(line);
        let mut effects: Vec<Effect> = relayed.to_page
            .map(|(generation, line)| vec![Effect::ToPage { generation, line }])
            .unwrap_or_default();
        // Only a completed turn resets the crash count (data-model.md §3).
        let before = self.restarts.count();
        for observation in &relayed.observed {
            if self.turns.observe(observation) {
                self.restarts.completed();
            }
        }
        if self.restarts.count() != before {
            effects.push(Effect::StatusChanged);
        }
        effects
    }

    /// One input, its effects; a person's action that does not apply now is
    /// refused with the reason.
    pub fn handle(&mut self, input: Input) -> Result<Vec<Effect>, String> {
        match input {
            Input::Start { workspace } => {
                if !matches!(self.state, State::Absent | State::Failed | State::Stopped) {
                    return Err("a Core is already running in this window".into());
                }
                self.set_workspace(workspace);
                self.notice = None;
                Ok(self.start())
            }
            Input::NoWorkspace { notice } => {
                if self.workspace.is_some() {
                    return Ok(vec![]);
                }
                self.state = State::Absent;
                self.notice = Some(notice);
                Ok(vec![Effect::StatusChanged])
            }
            Input::Spawned { core, .. } => {
                if !self.is_current(core) || !matches!(self.state, State::Starting | State::Restarting) {
                    return Ok(vec![]);
                }
                self.state = State::Handshaking;
                Ok(vec![Effect::Write { core, line: relay::hello_request() }, Effect::StatusChanged])
            }
            Input::SpawnFailed { core, failure } => {
                if !self.is_current(core) {
                    return Ok(vec![]);
                }
                self.core = None;
                Ok(self.fail(failure))
            }
            Input::Line { core, line } => {
                if !self.is_current(core) {
                    return Ok(vec![]);
                }
                Ok(match self.state {
                    State::Handshaking => self.handshake_line(core, &line),
                    State::Ready if !relay::is_envelope(&line) => self.fault(core, &line),
                    State::Ready => self.core_line(&line),
                    _ => vec![],
                })
            }
            Input::Exited { core, code } => {
                if self.faulted == Some(core) {
                    self.faulted = None;
                    if self.stopping.is_some() {
                        self.deferred = false;
                        return Ok(self.stopped());
                    }
                    // Its last output is read now: the status is told again,
                    // and the window fetches the complete diagnostics.
                    return Ok(if std::mem::take(&mut self.deferred) { self.spawn() }
                              else { vec![Effect::StatusChanged] });
                }
                if !self.is_current(core) {
                    return Ok(vec![]);
                }
                self.core = None;
                Ok(match self.state {
                    State::Stopping => self.stopped(),
                    State::Starting | State::Restarting | State::Handshaking => self.fail(Failure::new(
                        FailureClass::ExitedBeforeReady,
                        format!("The Core exited before it was ready ({}). Its last output is \
                                 below.", describe_exit(code)))),
                    State::Ready => self.crashed(Failure::new(
                        FailureClass::Crashed,
                        format!("The Core stopped unexpectedly ({}).", describe_exit(code)))),
                    _ => vec![],
                })
            }
            Input::Stop { reason } => {
                if let Some((pending, _)) = &mut self.stopping {
                    // Closing or quitting while a workspace change or "Check
                    // again" is stopping the Core: the application ends when
                    // it has stopped, instead of starting another.
                    if reason.ends_application() && !pending.ends_application() {
                        *pending = reason;
                        return Ok(vec![]);
                    }
                    return Err("the Core is already stopping".into());
                }
                Ok(self.stop(reason))
            }
            Input::DeadlinePassed { core } => {
                if self.stopping.is_none() || !self.is_current(core) {
                    return Ok(vec![]);
                }
                Ok(self.force(core))
            }
            Input::QuitNow => {
                if self.stopping.is_none() {
                    return Err("\"Quit now\" applies only while closing".into());
                }
                Ok(self.core.map(|core| self.force(core)).unwrap_or_default())
            }
            Input::Retry => {
                if self.state != State::Failed || self.workspace.is_none() {
                    return Err("\"Try again\" applies only after a failure".into());
                }
                // A person's "Try again" leaves the count as it is (OD-1).
                self.notice = None;
                Ok(self.start())
            }
        }
    }

    /// The stop sequence: `shutdown` (to a Core that can take it), stdin
    /// closed, then the wait for the exit, bounded by the grace (OD-2).
    fn stop(&mut self, reason: StopReason) -> Vec<Effect> {
        self.deferred = false;
        // A Core stopped for a fault is still a Core until it has exited: the
        // stop waits for it as for any other (it was signalled already).
        let Some(core) = self.core.or(self.faulted) else {
            // Nothing runs: stopped already.
            self.stop_outcome = Some(StopOutcome::Orderly);
            self.stopping = Some((reason, (self.clock)()));
            return self.after_stop();
        };
        let ready = self.state == State::Ready;
        self.stopping = Some((reason, (self.clock)()));
        self.forced = false;
        self.stop_outcome = None;
        self.state = State::Stopping;
        let mut effects = vec![Effect::StatusChanged];
        if ready {
            effects.push(Effect::Write { core, line: shutdown::shutdown_request() });
        }
        effects.push(Effect::CloseStdin { core });
        effects.push(Effect::Deadline { core, after: shutdown::GRACE });
        effects
    }

    /// The grace ran out, or the person chose "Quit now": end the Core and
    /// everything it started.
    fn force(&mut self, core: CoreId) -> Vec<Effect> {
        if self.forced {
            return vec![];
        }
        self.forced = true;
        vec![Effect::ForceStop { core }, Effect::Note(shutdown::FORCED_LOG)]
    }

    /// The Core being stopped has exited.
    fn stopped(&mut self) -> Vec<Effect> {
        self.stop_outcome = Some(if self.forced { StopOutcome::Forced } else { StopOutcome::Orderly });
        self.turns.forget();
        self.after_stop()
    }

    /// What follows a stop, by its reason.
    fn after_stop(&mut self) -> Vec<Effect> {
        let (reason, _) = self.stopping.take().expect("a stop in progress");
        let closed = self.relay.core_gone();
        let forced = self.stop_outcome == Some(StopOutcome::Forced);
        let mut effects = match reason {
            StopReason::WindowClosed | StopReason::Quit | StopReason::OsSessionEnd => {
                self.state = State::Stopped;
                vec![Effect::StatusChanged, Effect::Finished]
            }
            StopReason::WorkspaceChange(path) => {
                self.set_workspace(path);
                self.failure = None;
                let effects = self.start();
                self.notice = forced.then(|| shutdown::FORCED_NOTICE.to_string());
                effects
            }
            StopReason::CheckAgain => {
                self.failure = None;
                let effects = self.start();
                self.notice = forced.then(|| shutdown::FORCED_NOTICE.to_string());
                effects
            }
        };
        if let Some(generation) = closed {
            effects.push(Effect::PageClosed { generation, reason: "the Core was stopped".into() });
        }
        effects
    }

    /// The workspace is now `path`; a different folder is a new identity,
    /// another spelling of the same folder is not.
    fn set_workspace(&mut self, path: PathBuf) {
        if !self.workspace.as_deref().is_some_and(|current| crate::instance::same_folder(current, &path)) {
            self.workspace_epoch += 1;
        }
        self.workspace = Some(path);
    }

    fn is_current(&self, core: CoreId) -> bool {
        self.core == Some(core)
    }

    /// A new Core in the current workspace.
    fn start(&mut self) -> Vec<Effect> {
        self.start_as(State::Starting)
    }

    fn start_as(&mut self, state: State) -> Vec<Effect> {
        self.state = state;
        self.turns.forget();
        self.failure = None;
        self.identity = None;
        if self.faulted.is_some() {
            // Never two Cores at once: this one starts when that one exits.
            self.core = None;
            self.deferred = true;
            return vec![Effect::StatusChanged];
        }
        self.spawn()
    }

    fn spawn(&mut self) -> Vec<Effect> {
        let core = self.next_core;
        self.next_core += 1;
        self.core = Some(core);
        let workspace = self.workspace.clone().expect("a start has a workspace");
        vec![Effect::Spawn { core, workspace }, Effect::StatusChanged]
    }

    fn handshake_line(&mut self, core: CoreId, line: &str) -> Vec<Effect> {
        match relay::read_handshake(line) {
            relay::Handshake::Ready(result) => {
                self.identity = Some(CoreIdentity {
                    name: result["core"]["name"].as_str().unwrap_or("").to_string(),
                    version: result["core"]["version"].as_str().unwrap_or("").to_string(),
                });
                self.relay.cache_handshake(result);
                self.state = State::Ready;
                self.notice = None;
                vec![Effect::StatusChanged]
            }
            relay::Handshake::Mismatch(message) | relay::Handshake::Refused(message) => {
                self.fail_and_stop(core, Failure::new(FailureClass::ProtocolMismatch, message))
            }
            relay::Handshake::NotYet => vec![],
            relay::Handshake::Fault => self.fault(core, line),
        }
    }

    /// A line that is not protocol (FR-007): the Core cannot be trusted to
    /// keep talking, so it is stopped.
    fn fault(&mut self, core: CoreId, line: &str) -> Vec<Effect> {
        let excerpt: String = line.chars().take(120).collect();
        self.fail_and_stop(core, Failure::new(FailureClass::ProtocolFault, format!(
            "The Core wrote a line that is not protocol on its output: {excerpt}")))
    }

    fn fail(&mut self, failure: Failure) -> Vec<Effect> {
        self.state = State::Failed;
        // The status first: a page told its connection closed must already
        // know the Core is not ready, or it would reconnect to nothing.
        let closed = self.relay.core_gone();
        let reason = failure.message.clone();
        self.failure = Some(failure);
        let mut effects = vec![Effect::StatusChanged];
        if let Some(generation) = closed {
            effects.push(Effect::PageClosed { generation, reason });
        }
        effects
    }

    fn fail_and_stop(&mut self, core: CoreId, failure: Failure) -> Vec<Effect> {
        let was_ready = self.state == State::Ready;
        self.core = None;
        self.faulted = Some(core);
        let mut effects = vec![Effect::CloseStdin { core }, Effect::ForceStop { core }];
        // A fault of a ready Core counts as a crash (data-model.md §1).
        effects.extend(if was_ready { self.crashed(failure) } else { self.fail(failure) });
        effects
    }

    /// A Core that had reached `ready` is gone. Restarted in the same
    /// workspace while the count allows (OD-1); otherwise it waits for "Try
    /// again". Nothing it was doing is replayed.
    fn crashed(&mut self, failure: Failure) -> Vec<Effect> {
        self.turns.forget();
        if !self.restarts.crashed() {
            let count = self.restarts.count();
            // The class says what the last one was: a crash, or a fault.
            return self.fail(Failure::new(failure.class, format!(
                "{} It stopped {count} times in a row, so it was not started again.",
                failure.message)));
        }
        let closed = self.relay.core_gone();
        self.notice = Some(format!("{} Starting it again ({} of {}).",
                                   failure.message, self.restarts.count(), RESTART_LIMIT));
        // The status (restarting) reaches the page before `closed` does.
        let mut effects = self.start_as(State::Restarting);
        if let Some(generation) = closed {
            effects.push(Effect::PageClosed { generation, reason: failure.message });
        }
        effects
    }
}

/// One line of the Core's stdout as text. A line that is not UTF-8 is not
/// protocol: it is marked so it can never parse as an envelope, rather than
/// having its bytes replaced and passing as one.
pub(crate) fn decoded(bytes: &[u8]) -> String {
    match std::str::from_utf8(bytes) {
        Ok(text) => text.to_string(),
        Err(_) => format!("(a line that is not UTF-8) {}", String::from_utf8_lossy(bytes)),
    }
}

fn describe_exit(code: Option<i32>) -> String {
    match code {
        Some(code) => format!("exit code {code}"),
        None => "ended by a signal".into(),
    }
}

/// The command a located Core is started with in `workspace`: exactly
/// `[<COMODOR_ARGS…>, core, --stdio]`, the environment inherited unchanged.
pub fn core_command(located: &CoreCommand, workspace: &Path) -> Command {
    build_command(located, workspace, &[])
}

// -- the driver ----------------------------------------------------------- //

/// Where the page's inbound channel messages go (`line`, `status`,
/// `closed`). The application's is the page's IPC channel; tests record.
pub trait PageSink: Send {
    fn send(&self, message: Value);
}

pub struct Options {
    /// Finds the Core to start, each time one is started.
    pub locate: Box<dyn Fn() -> Result<CoreCommand, Failure> + Send>,
    /// Empty in the application. Tests give their Cores a temporary home
    /// this way, without changing their own environment.
    pub test_env: Vec<(OsString, OsString)>,
    /// The application's log; none in tests that do not look at it.
    pub log: Option<Arc<Log>>,
    /// Called once the Core has stopped for a reason that ends the
    /// application (the application exits here).
    pub on_finished: Option<Box<dyn Fn() + Send>>,
}

enum Event {
    Input(Input, Option<Sender<Result<(), String>>>),
    Connect(Box<dyn PageSink>, Sender<u64>),
    SendLine { generation: u64, line: String, reply: Sender<Result<(), String>> },
    Displayed { url: String, reply: Sender<bool> },
}

struct Shared {
    status: Mutex<Status>,
    changed: Condvar,
    tail: Arc<Mutex<DiagnosticTail>>,
    pid: Mutex<Option<u32>>,
    /// The workspace exactly: what a second launch is compared with.
    workspace: Mutex<Option<PathBuf>>,
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// The running supervisor: one thread that owns the Core, and this handle to
/// it. Every call is answered by that thread, in order.
#[derive(Clone)]
pub struct Supervisor {
    events: Sender<Event>,
    shared: Arc<Shared>,
}

impl Supervisor {
    /// Start the supervisor's thread. Every Core is started from it, for the
    /// application's whole life (the parent-death signal follows it).
    pub fn launch(options: Options) -> Self {
        let (events, receiver) = channel();
        let shared = Arc::new(Shared {
            status: Mutex::new(Machine::new().status()),
            changed: Condvar::new(),
            tail: Arc::new(Mutex::new(DiagnosticTail::new())),
            pid: Mutex::new(None),
            workspace: Mutex::new(None),
        });
        let driver = Driver {
            machine: Machine::new(),
            options,
            events: events.clone(),
            shared: shared.clone(),
            running: HashMap::new(),
            page: None,
            pending: VecDeque::new(),
        };
        std::thread::Builder::new()
            .name("core-supervisor".into())
            .spawn(move || driver.run(receiver))
            .expect("start the supervisor thread");
        Self { events, shared }
    }

    fn input(&self, input: Input) -> Result<(), String> {
        let (reply, answer) = channel();
        self.events.send(Event::Input(input, Some(reply)))
            .map_err(|_| "the supervisor has stopped".to_string())?;
        answer.recv().map_err(|_| "the supervisor has stopped".to_string())?
    }

    pub fn start(&self, workspace: PathBuf) -> Result<(), String> {
        self.input(Input::Start { workspace })
    }

    pub fn no_workspace(&self, notice: String) {
        let _ = self.input(Input::NoWorkspace { notice });
    }

    pub fn retry(&self) -> Result<(), String> {
        self.input(Input::Retry)
    }

    /// Begin the stop sequence for `reason`.
    pub fn stop(&self, reason: StopReason) -> Result<(), String> {
        self.input(Input::Stop { reason })
    }

    /// The person's "Quit now".
    pub fn quit_now(&self) -> Result<(), String> {
        self.input(Input::QuitNow)
    }

    pub fn status(&self) -> Status {
        lock(&self.shared.status).clone()
    }

    /// The workspace exactly, as a path; `status().workspace` is lossy.
    pub fn workspace(&self) -> Option<PathBuf> {
        lock(&self.shared.workspace).clone()
    }

    /// Wait until the status satisfies `until`, or `deadline` passes. It
    /// returns as soon as the condition holds.
    pub fn wait_for(&self, until: impl Fn(&Status) -> bool, deadline: Duration) -> Option<Status> {
        let ends = Instant::now() + deadline;
        let mut status = lock(&self.shared.status);
        loop {
            if until(&status) {
                return Some(status.clone());
            }
            let now = Instant::now();
            if now >= ends {
                return None;
            }
            status = self.shared.changed.wait_timeout(status, ends - now)
                .unwrap_or_else(|poisoned| poisoned.into_inner()).0;
        }
    }

    pub fn diagnostics(&self) -> String {
        lock(&self.shared.tail).text()
    }

    pub fn core_pid(&self) -> Option<u32> {
        *lock(&self.shared.pid)
    }

    /// A page connects through `sink`: its generation. It is sent the status
    /// at once, and from then on every status change, line and closing.
    pub fn connect(&self, sink: Box<dyn PageSink>) -> u64 {
        let (reply, answer) = channel();
        if self.events.send(Event::Connect(sink, reply)).is_err() {
            return 0;
        }
        answer.recv().unwrap_or(0)
    }

    /// Was `url` a link in a line the current page was shown?
    pub fn displayed(&self, url: &str) -> bool {
        let (reply, answer) = channel();
        if self.events.send(Event::Displayed { url: url.to_string(), reply }).is_err() {
            return false;
        }
        answer.recv().unwrap_or(false)
    }

    pub fn send_line(&self, generation: u64, line: String) -> Result<(), String> {
        let (reply, answer) = channel();
        self.events.send(Event::SendLine { generation, line, reply })
            .map_err(|_| "the supervisor has stopped".to_string())?;
        answer.recv().map_err(|_| "the supervisor has stopped".to_string())?
    }
}

/// One Core process the driver started and has not yet seen exit.
struct Running {
    stdin: Option<ChildStdin>,
    stopper: Stopper,
}

struct Driver {
    machine: Machine,
    options: Options,
    events: Sender<Event>,
    shared: Arc<Shared>,
    running: HashMap<CoreId, Running>,
    page: Option<(u64, Box<dyn PageSink>)>,
    /// Inputs the driver itself produced (a spawn's result), handled after
    /// the effects that led to them, so status changes are told in order.
    pending: VecDeque<Input>,
}

impl Driver {
    fn run(mut self, events: Receiver<Event>) {
        while let Ok(event) = events.recv() {
            match event {
                Event::Input(input, reply) => {
                    if let Input::Exited { core, code } = &input {
                        if self.running.remove(core).is_some() {
                            self.log(Entry::Exited { code: *code });
                        }
                        // Only the last running Core's exit unpublishes it.
                        if self.running.is_empty() {
                            self.set_pid(None);
                        }
                    }
                    let outcome = self.machine.handle(input).map(|effects| self.apply(effects));
                    if let Some(reply) = reply {
                        let _ = reply.send(outcome);
                    }
                }
                Event::Connect(sink, reply) => {
                    let generation = self.machine.connect();
                    sink.send(json!({ "kind": "status", "status": self.machine.status() }));
                    self.page = Some((generation, sink));
                    let _ = reply.send(generation);
                }
                Event::Displayed { url, reply } => {
                    let _ = reply.send(self.machine.displayed(&url));
                }
                Event::SendLine { generation, line, reply } => {
                    let outcome = self.machine.send_line(generation, &line)
                        .map(|effects| self.apply(effects));
                    let _ = reply.send(outcome);
                }
            }
            while let Some(input) = self.pending.pop_front() {
                if let Ok(effects) = self.machine.handle(input) {
                    self.apply(effects);
                }
            }
            self.publish();
        }
    }

    fn apply(&mut self, effects: Vec<Effect>) {
        for effect in effects {
            match effect {
                Effect::Spawn { core, workspace } => {
                    self.log(Entry::Workspace(workspace.clone()));
                    let result = self.spawn(core, &workspace);
                    self.pending.push_back(result);
                }
                Effect::Write { core, line } => {
                    if let Some(stdin) = self.running.get_mut(&core).and_then(|r| r.stdin.as_mut()) {
                        // A broken pipe means the Core is going; its exit is
                        // observed by the waiter, not inferred here.
                        let _ = stdin.write_all(line.as_bytes())
                            .and_then(|()| stdin.write_all(b"\n"))
                            .and_then(|()| stdin.flush());
                    }
                }
                Effect::CloseStdin { core } => {
                    if let Some(running) = self.running.get_mut(&core) {
                        running.stdin = None;
                    }
                }
                Effect::ForceStop { core } => {
                    if let Some(running) = self.running.get(&core) {
                        let _ = running.stopper.terminate();
                    }
                }
                Effect::StatusChanged => {
                    self.publish();
                    let status = self.machine.status();
                    if let Some((_, sink)) = &self.page {
                        sink.send(json!({ "kind": "status", "status": status }));
                    }
                }
                Effect::ToPage { generation, line } => {
                    if let Some((current, sink)) = &self.page {
                        if *current == generation {
                            sink.send(json!({ "kind": "line", "line": line }));
                        }
                    }
                }
                Effect::Deadline { core, after } => {
                    // The grace bound (OD-2): the one timer in the supervisor.
                    let events = self.events.clone();
                    std::thread::Builder::new().name("stop-deadline".into()).spawn(move || {
                        std::thread::sleep(after);
                        let _ = events.send(Event::Input(Input::DeadlinePassed { core }, None));
                    }).expect("start the stop deadline");
                }
                Effect::Note(text) => self.log(Entry::Note(text)),
                Effect::Finished => {
                    self.publish();
                    if let Some(finished) = &self.options.on_finished {
                        finished();
                    }
                }
                Effect::PageClosed { generation, reason } => {
                    if let Some((current, sink)) = &self.page {
                        if *current == generation {
                            sink.send(json!({ "kind": "closed", "reason": reason }));
                        }
                    }
                }
            }
        }
    }

    /// Start a Core: the workspace is checked and the Core located first, so
    /// each of those failures has its own class.
    fn spawn(&mut self, core: CoreId, workspace: &Path) -> Input {
        // Each attempt's failure shows only its own diagnostics.
        lock(&self.shared.tail).clear();
        if let Err(failure) = workspace::check(workspace) {
            return Input::SpawnFailed { core, failure };
        }
        let command = match (self.options.locate)() {
            Ok(command) => command,
            Err(failure) => return Input::SpawnFailed { core, failure },
        };
        // The test build records what every Core was started with, for the
        // credential canary (FR-003).
        #[cfg(feature = "e2e")]
        crate::e2e::record("spawn", &json!({
            "program": command.program.to_string_lossy(),
            "args": command.full_args().iter().map(|arg| arg.to_string_lossy().into_owned())
                .collect::<Vec<_>>(),
            "workspace": workspace.display().to_string(),
        }));
        let mut spawned = match spawn_core(&command, workspace, &self.options.test_env) {
            Ok(spawned) => spawned,
            Err(problem) => return Input::SpawnFailed { core, failure: Failure::new(
                FailureClass::SpawnFailed,
                format!("Comodor could not be started from {}: {problem}",
                        Path::new(&command.program).display())) },
        };
        let (stdin, stdout, stderr) = spawned.take_streams();
        let stopper = spawned.stopper();
        let pid = spawned.pid;
        let mut child = spawned.child;

        let errors = diag::read_into(stderr, self.shared.tail.clone());
        let lines = self.events.clone();
        let output = std::thread::Builder::new().name("core-stdout".into()).spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut buffer = Vec::new();
            loop {
                buffer.clear();
                match reader.read_until(b'\n', &mut buffer) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {}
                }
                let end = buffer.iter().rposition(|&byte| byte != b'\n' && byte != b'\r').map_or(0, |at| at + 1);
                let line = decoded(&buffer[..end]);
                if lines.send(Event::Input(Input::Line { core, line }, None)).is_err() {
                    break;
                }
            }
        }).expect("start the stdout reader");

        // The exit is told only after every line the Core wrote, so a last
        // answer is never mistaken for an exit before it.
        let exits = self.events.clone();
        let leftovers = stopper.clone();
        std::thread::Builder::new().name("core-waiter".into()).spawn(move || {
            let code = child.wait().ok().and_then(|status| status.code());
            // Whatever the Core left running goes with it, which also closes
            // any copy of its pipes a descendant still held.
            let _ = leftovers.terminate();
            let _ = output.join();
            let _ = errors.join();
            let _ = exits.send(Event::Input(Input::Exited { core, code }, None));
        }).expect("start the exit waiter");

        self.running.insert(core, Running { stdin: Some(stdin), stopper });
        self.set_pid(Some(pid));
        self.log(Entry::Started { pid });
        Input::Spawned { core, pid }
    }

    fn set_pid(&self, pid: Option<u32>) {
        *lock(&self.shared.pid) = pid;
        #[cfg(feature = "e2e")]
        crate::e2e::set_core_pid(pid.unwrap_or(0));
    }

    fn log(&self, entry: Entry) {
        if let Some(log) = &self.options.log {
            log.record(entry);
        }
    }

    fn publish(&self) {
        *lock(&self.shared.workspace) = self.machine.workspace().map(Path::to_path_buf);
        let status = self.machine.status();
        let mut shared = lock(&self.shared.status);
        if shared.state != status.state {
            self.log(Entry::State(status.state));
            if let Some(failure) = &status.failure {
                self.log(Entry::Failure(failure.class));
            }
        }
        if *shared != status {
            *shared = status;
            self.shared.changed.notify_all();
        }
    }
}

#[allow(dead_code)]
fn args_of(command: &Command) -> Vec<OsString> {
    command.get_args().map(|arg| arg.to_owned()).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::collections::HashSet;

    const WS: &str = "/work/project";

    fn hello_answer(version: i64) -> String {
        json!({"version": 2, "type": "response", "id": relay::HELLO_ID,
               "result": {"protocol_version": version,
                          "core": {"name": "comodor-core", "version": "9.9"},
                          "capabilities": ["streaming"]}}).to_string()
    }

    fn refused(supported: Value) -> String {
        json!({"version": 2, "type": "error", "id": relay::HELLO_ID,
               "error": {"code": "unsupported_version", "message": "no",
                         "data": {"supported": supported}}}).to_string()
    }

    fn started() -> (Machine, CoreId) {
        let mut machine = Machine::new();
        let effects = machine.handle(Input::Start { workspace: WS.into() }).unwrap();
        let core = match effects.as_slice() {
            [Effect::Spawn { core, workspace }, Effect::StatusChanged] => {
                assert_eq!(workspace, Path::new(WS));
                *core
            }
            other => panic!("expected a spawn, then a status: {other:?}"),
        };
        assert_eq!(machine.state(), State::Starting);
        (machine, core)
    }

    fn handshaking() -> (Machine, CoreId) {
        let (mut machine, core) = started();
        let effects = machine.handle(Input::Spawned { core, pid: 41 }).unwrap();
        assert_eq!(machine.state(), State::Handshaking);
        match effects.as_slice() {
            [Effect::Write { core: to, line }, Effect::StatusChanged] => {
                assert_eq!(*to, core);
                assert_eq!(line, &relay::hello_request());
            }
            other => panic!("expected the hello, then a status: {other:?}"),
        }
        (machine, core)
    }

    fn ready() -> (Machine, CoreId) {
        let (mut machine, core) = handshaking();
        let effects = machine.handle(Input::Line { core, line: hello_answer(2) }).unwrap();
        assert_eq!(effects, vec![Effect::StatusChanged]);
        assert_eq!(machine.state(), State::Ready);
        (machine, core)
    }

    fn failed_with(mut machine: Machine, input: Input) -> (Machine, Failure, Vec<Effect>) {
        let effects = machine.handle(input).unwrap();
        assert_eq!(machine.state(), State::Failed);
        let failure = machine.status().failure.expect("a failure is reported");
        (machine, failure, effects)
    }

    // -- T019: the command ----------------------------------------------------

    #[test]
    fn the_command_is_exactly_the_located_one_plus_core_stdio_with_the_environment_inherited() {
        let located = CoreCommand { program: "/venv/bin/python".into(),
                                    args: vec!["/fixtures/core.py".into(), "echo".into()] };
        let command = core_command(&located, Path::new(WS));
        assert_eq!(command.get_program(), "/venv/bin/python");
        assert_eq!(args_of(&command),
                   ["/fixtures/core.py", "echo", "core", "--stdio"].map(OsString::from).to_vec());
        assert_eq!(command.get_envs().count(), 0,
                   "nothing is added to, changed in or removed from the environment");
        assert_eq!(command.get_current_dir(), Some(Path::new(WS)));
    }

    #[test]
    fn the_command_carries_nothing_from_the_core_home_configuration() {
        let home = std::env::temp_dir().join(format!("comodor-cmd-{}", std::process::id()));
        std::fs::create_dir_all(&home).unwrap();
        std::fs::write(home.join("config.json"),
                       r#"{"providers":{"fake":{"api_key":"CANARY-CMD-1"}}}"#).unwrap();
        let located = CoreCommand { program: "comodor".into(), args: vec![] };
        let command = core_command(&located, &home);
        let everything = format!("{:?} {:?}", command.get_program(), args_of(&command));
        std::fs::remove_dir_all(&home).unwrap();
        assert!(!everything.contains("CANARY-CMD-1"));
        assert_eq!(args_of(&command), ["core", "--stdio"].map(OsString::from).to_vec());
    }

    // -- T020: the states -----------------------------------------------------

    #[test]
    fn absent_starting_handshaking_ready() {
        let (machine, _) = ready();
        let status = machine.status();
        assert_eq!(status.state, State::Ready);
        assert_eq!(status.workspace.as_deref(), Some(WS));
        assert_eq!(status.core, Some(CoreIdentity { name: "comodor-core".into(), version: "9.9".into() }));
        assert_eq!(status.failure, None);
        assert_eq!(machine.handshake().unwrap()["protocol_version"], 2);
    }

    #[test]
    fn each_failure_class_lands_in_failed_with_its_own_message() {
        let mut messages = HashSet::new();
        for class in [FailureClass::NotFound, FailureClass::SpawnFailed,
                      FailureClass::WorkspaceUnavailable] {
            let (machine, core) = started();
            let given = Failure::new(class, format!("{class:?} happened"));
            let (_, failure, _) = failed_with(machine, Input::SpawnFailed { core, failure: given.clone() });
            assert_eq!(failure, given);
            messages.insert(failure.message);
        }

        let (machine, core) = handshaking();
        let (_, failure, _) = failed_with(machine, Input::Exited { core, code: Some(3) });
        assert_eq!(failure.class, FailureClass::ExitedBeforeReady);
        assert!(failure.message.contains('3'), "{}", failure.message);
        messages.insert(failure.message);

        let (machine, core) = handshaking();
        let (_, failure, effects) = failed_with(machine, Input::Line { core, line: hello_answer(3) });
        assert_eq!(failure.class, FailureClass::ProtocolMismatch);
        assert!(failure.message.contains('2') && failure.message.contains('3'), "{}", failure.message);
        assert!(effects.contains(&Effect::ForceStop { core }), "an incompatible Core is stopped");
        messages.insert(failure.message);

        let (machine, core) = handshaking();
        let (_, failure, _) = failed_with(machine, Input::Line { core, line: refused(json!([3])) });
        assert_eq!(failure.class, FailureClass::ProtocolMismatch);
        assert!(failure.message.contains("[3]"), "{}", failure.message);
        messages.insert(failure.message);

        let (machine, core) = handshaking();
        let (_, failure, effects) = failed_with(machine, Input::Line { core, line: "Traceback (most recent call last):".into() });
        assert_eq!(failure.class, FailureClass::ProtocolFault);
        assert!(effects.contains(&Effect::ForceStop { core }), "a faulty Core is stopped");
        messages.insert(failure.message);

        assert_eq!(messages.len(), 7, "every class has its own message");
    }

    #[test]
    fn a_bad_line_while_ready_is_a_protocol_fault_and_the_core_is_stopped() {
        let (mut machine, core) = ready();
        let effects = machine.handle(Input::Line { core, line: "{not json".into() }).unwrap();
        assert!(effects.contains(&Effect::ForceStop { core }));
        // A fault of a ready Core is a crash for the restart count (OD-1).
        assert_eq!(machine.state(), State::Restarting);
        let notice = machine.status().notice.expect("why it restarted");
        assert!(notice.contains("not protocol"), "{notice}");
    }

    /// Review finding (PR #62): an incomplete or other-version envelope
    /// from a ready Core is a protocol fault, not something to relay.
    #[test]
    fn a_malformed_envelope_while_ready_is_a_protocol_fault() {
        for line in [r#"{"version":3,"type":"event","event":"message.completed","seq":4,"params":{}}"#,
                     r#"{"version":2,"type":"event","event":"session.updated"}"#] {
            let (mut machine, core) = ready();
            let generation = machine.connect();
            let effects = machine.handle(Input::Line { core, line: line.into() }).unwrap();
            assert!(effects.contains(&Effect::ForceStop { core }), "{line}: {effects:?}");
            assert!(!effects.iter().any(|e| matches!(e, Effect::ToPage { generation: g, .. } if *g == generation)),
                    "never relayed: {line}");
        }
    }

    fn spawned(effects: &[Effect]) -> Option<CoreId> {
        effects.iter().find_map(|e| match e { Effect::Spawn { core, .. } => Some(*core), _ => None })
    }

    /// Review finding (PR #62): a line that is not UTF-8 is not protocol,
    /// even when its bytes would otherwise make a valid envelope — it is
    /// never relayed with its bytes replaced.
    #[test]
    fn a_line_that_is_not_utf8_is_a_protocol_fault() {
        let bytes = b"{\"version\":2,\"type\":\"event\",\"event\":\"x\",\"seq\":1,\"params\":{\"text\":\"\xff\"}}";
        let line = decoded(bytes);
        assert!(!relay::is_envelope(&line), "{line}");
        let (mut machine, core) = ready();
        let effects = machine.handle(Input::Line { core, line }).unwrap();
        assert!(effects.contains(&Effect::ForceStop { core }), "{effects:?}");
        assert_eq!(decoded(b"{\"ok\":true}"), "{\"ok\":true}", "a UTF-8 line is kept as it is");
    }

    /// Review finding (PR #62): a faulted Core is signalled, and its
    /// replacement starts only once it has exited — never two at once.
    #[test]
    fn a_faulted_core_is_replaced_only_after_it_has_exited() {
        let (mut machine, core) = ready();
        let effects = machine.handle(Input::Line { core, line: "garbage".into() }).unwrap();
        assert!(effects.contains(&Effect::ForceStop { core }), "{effects:?}");
        assert_eq!(spawned(&effects), None, "not while the faulted Core runs: {effects:?}");
        assert_eq!(machine.state(), State::Restarting);
        // Its last lines are not protocol to anyone.
        assert_eq!(machine.handle(Input::Line { core, line: "more".into() }).unwrap(), vec![]);
        let effects = machine.handle(Input::Exited { core, code: None }).unwrap();
        let next = spawned(&effects).expect("the restart, now");
        assert_ne!(next, core);
        assert_eq!(machine.state(), State::Restarting);
        assert_eq!(machine.status().restart_count, 1);
    }

    #[test]
    fn nothing_starts_while_a_core_that_failed_its_handshake_still_runs() {
        let (mut machine, core) = handshaking();
        machine.handle(Input::Line { core, line: "Traceback (most recent call last):".into() }).unwrap();
        assert_eq!(machine.state(), State::Failed);
        let effects = machine.handle(Input::Retry).unwrap();
        assert_eq!(spawned(&effects), None, "{effects:?}");
        assert_eq!(machine.state(), State::Starting);
        let next = spawned(&machine.handle(Input::Exited { core, code: None }).unwrap()).expect("then it starts");
        assert_ne!(next, core);
    }

    /// Review finding (PR #62): a faulted Core's last output is read only
    /// once it has exited, so the status is told again then, and the window
    /// fetches the now complete diagnostics.
    #[test]
    fn a_faulted_core_that_exits_after_its_failure_tells_the_status_again() {
        let (mut machine, core) = handshaking();
        machine.handle(Input::Line { core, line: "Traceback (most recent call last):".into() }).unwrap();
        assert_eq!(machine.state(), State::Failed);
        let effects = machine.handle(Input::Exited { core, code: Some(1) }).unwrap();
        assert_eq!(effects, vec![Effect::StatusChanged]);
        assert_eq!(machine.state(), State::Failed, "still failed, with its tail complete");
    }

    #[test]
    /// Review finding (PR #62): the application ends only once the faulted
    /// Core has exited — and nothing starts after it.
    fn a_window_closed_while_a_faulted_core_ends_starts_nothing_after() {
        let (mut machine, core) = ready();
        machine.handle(Input::Line { core, line: "garbage".into() }).unwrap();
        let effects = machine.handle(Input::Stop { reason: StopReason::WindowClosed }).unwrap();
        assert!(!effects.contains(&Effect::Finished), "not while the faulted Core runs: {effects:?}");
        assert_eq!(machine.state(), State::Stopping);
        let effects = machine.handle(Input::Exited { core, code: None }).unwrap();
        assert!(effects.contains(&Effect::Finished), "{effects:?}");
        assert_eq!(spawned(&effects), None, "nothing starts after: {effects:?}");
        assert_eq!(machine.state(), State::Stopped);
    }

    /// Review finding (PR #62): closing or quitting while a workspace change
    /// or "Check again" is stopping the Core ends the application then,
    /// rather than being lost to the restart.
    #[test]
    fn a_quit_during_a_restarting_stop_ends_the_application_instead() {
        for pending in [StopReason::WorkspaceChange("/elsewhere".into()), StopReason::CheckAgain] {
            for ending in [StopReason::WindowClosed, StopReason::Quit, StopReason::OsSessionEnd] {
                let (mut machine, core) = ready();
                machine.handle(Input::Stop { reason: pending.clone() }).unwrap();
                assert!(machine.handle(Input::Stop { reason: ending.clone() }).is_ok(), "{pending:?} then {ending:?}");
                let effects = machine.handle(Input::Exited { core, code: Some(0) }).unwrap();
                assert!(effects.contains(&Effect::Finished), "{pending:?} then {ending:?}: {effects:?}");
                assert_eq!(spawned(&effects), None);
                assert_eq!(machine.state(), State::Stopped);
                assert_eq!(machine.status().workspace.as_deref(), Some(WS), "no switch on the way out");
            }
        }
    }

    #[test]
    fn a_second_stop_that_would_not_end_the_application_is_refused() {
        let (mut machine, _) = ready();
        machine.handle(Input::Stop { reason: StopReason::Quit }).unwrap();
        assert!(machine.handle(Input::Stop { reason: StopReason::CheckAgain }).is_err());
        assert!(machine.handle(Input::Stop { reason: StopReason::WorkspaceChange("/x".into()) }).is_err());
        let (mut machine, _) = ready();
        machine.handle(Input::Stop { reason: StopReason::CheckAgain }).unwrap();
        assert!(machine.handle(Input::Stop { reason: StopReason::WorkspaceChange("/x".into()) }).is_err());
    }

    /// Review finding (PR #62): the page tells workspaces apart by an id
    /// that changes exactly when the folder does — never by the display
    /// string, which loses bytes that are not UTF-8.
    #[test]
    fn the_workspace_id_changes_exactly_when_the_folder_does() {
        let (mut machine, core) = ready();
        let first = machine.status().workspace_id.expect("an id with a workspace");
        // A restart, "Check again" and the same folder again keep it.
        let (_, next) = crash(&mut machine, core);
        assert_eq!(machine.status().workspace_id.as_ref(), Some(&first));
        machine.handle(Input::Stop { reason: StopReason::CheckAgain }).unwrap();
        machine.handle(Input::Exited { core: next.unwrap(), code: Some(0) }).unwrap();
        assert_eq!(machine.status().workspace_id.as_ref(), Some(&first));
        let current = spawned_core(&machine);
        machine.handle(Input::Stop { reason: StopReason::WorkspaceChange(WS.into()) }).unwrap();
        machine.handle(Input::Exited { core: current, code: Some(0) }).unwrap();
        assert_eq!(machine.status().workspace_id.as_ref(), Some(&first));

        // Another folder is another id, even when it displays the same.
        let current = spawned_core(&machine);
        machine.handle(Input::Stop { reason: StopReason::WorkspaceChange(lookalike(1)) }).unwrap();
        machine.handle(Input::Exited { core: current, code: Some(0) }).unwrap();
        let second = machine.status().workspace_id.unwrap();
        assert_ne!(second, first);
        let shown = machine.status().workspace;
        let current = spawned_core(&machine);
        machine.handle(Input::Stop { reason: StopReason::WorkspaceChange(lookalike(2)) }).unwrap();
        machine.handle(Input::Exited { core: current, code: Some(0) }).unwrap();
        assert_ne!(machine.status().workspace_id.unwrap(), second);
        if cfg!(unix) {
            assert_eq!(machine.status().workspace, shown, "the two folders display the same");
        }
        assert_eq!(Machine::new().status().workspace_id, None);
    }

    /// Review finding (PR #62): another spelling of the same folder is the
    /// same workspace, and keeps its id.
    #[test]
    fn another_spelling_of_the_same_folder_keeps_the_workspace_id() {
        let root = std::env::temp_dir().join(format!("comodor-alias-{}", std::process::id()));
        let folder = root.join("work");
        std::fs::create_dir_all(&folder).unwrap();
        let mut machine = Machine::new();
        machine.handle(Input::Start { workspace: folder.clone() }).unwrap();
        let first = machine.status().workspace_id;
        let core = spawned_core(&machine);
        machine.handle(Input::Stop { reason: StopReason::WorkspaceChange(folder.join("..").join("work")) }).unwrap();
        machine.handle(Input::Exited { core, code: Some(0) }).unwrap();
        let second = machine.status().workspace_id;
        std::fs::remove_dir_all(&root).unwrap();
        assert_eq!(second, first);
    }

    /// Two folders whose names differ only in a byte that is not UTF-8 (on
    /// Unix); elsewhere, simply two folders.
    fn lookalike(n: u8) -> PathBuf {
        #[cfg(unix)]
        {
            use std::os::unix::ffi::OsStrExt;
            PathBuf::from(std::ffi::OsStr::from_bytes(&[b'/', b'w', 0x7f + n]))
        }
        #[cfg(not(unix))]
        {
            PathBuf::from(format!("/w{n}"))
        }
    }

    /// The Core the machine started last.
    fn spawned_core(machine: &Machine) -> CoreId {
        machine.core.expect("a Core is running")
    }

    #[test]
    fn ready_needs_protocol_version_two_exactly() {
        for version in [1, 3, 20] {
            let (mut machine, core) = handshaking();
            machine.handle(Input::Line { core, line: hello_answer(version) }).unwrap();
            assert_eq!(machine.state(), State::Failed, "version {version}");
            assert_eq!(machine.handshake(), None);
        }
    }

    #[test]
    fn try_again_moves_failed_to_starting_in_the_same_workspace() {
        let (machine, core) = handshaking();
        let (mut machine, _, _) = failed_with(machine, Input::Exited { core, code: Some(1) });
        let effects = machine.handle(Input::Retry).unwrap();
        assert_eq!(machine.state(), State::Starting);
        match effects.as_slice() {
            [Effect::Spawn { core: next, workspace }, Effect::StatusChanged] => {
                assert_ne!(*next, core, "a new Core has a new id");
                assert_eq!(workspace, Path::new(WS));
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(machine.status().failure, None);
    }

    #[test]
    fn try_again_is_refused_unless_failed() {
        let (mut machine, _) = started();
        assert!(machine.handle(Input::Retry).is_err());
        let (mut machine, _) = handshaking();
        assert!(machine.handle(Input::Retry).is_err());
        let (mut machine, _) = ready();
        assert!(machine.handle(Input::Retry).is_err());
        assert_eq!(machine.state(), State::Ready);
    }

    #[test]
    fn there_is_no_handshake_timeout() {
        let (mut machine, core) = handshaking();
        // Lines that are protocol but not the answer leave it handshaking;
        // nothing but the answer, an exit or a bad line moves it.
        let event = json!({"version": 2, "type": "event", "event": "session.updated",
                           "seq": 1, "params": {}}).to_string();
        assert_eq!(machine.handle(Input::Line { core, line: event }).unwrap(), vec![]);
        assert_eq!(machine.state(), State::Handshaking);
        assert_eq!(machine.status().state, State::Handshaking);
    }

    #[test]
    fn a_stale_core_cannot_move_the_current_one() {
        let (machine, old) = handshaking();
        let (mut machine, _, _) = failed_with(machine, Input::Exited { core: old, code: None });
        machine.handle(Input::Retry).unwrap();
        assert_eq!(machine.handle(Input::Exited { core: old, code: Some(9) }).unwrap(), vec![]);
        assert_eq!(machine.handle(Input::Line { core: old, line: hello_answer(2) }).unwrap(), vec![]);
        assert_eq!(machine.state(), State::Starting);
    }

    #[test]
    fn a_dismissed_chooser_starts_nothing_and_says_so() {
        let mut machine = Machine::new();
        let effects = machine.handle(Input::NoWorkspace { notice: "No workspace chosen.".into() }).unwrap();
        assert_eq!(effects, vec![Effect::StatusChanged]);
        let status = machine.status();
        assert_eq!(status.state, State::Absent);
        assert_eq!(status.workspace, None);
        assert_eq!(status.notice.as_deref(), Some("No workspace chosen."));
        assert!(machine.handle(Input::Retry).is_err(), "there is nothing to try again");
    }

    // -- the page's connection through the machine ----------------------------

    const MODEL_GET: &str = r#"{"version":2,"type":"request","id":"1","method":"model.get","params":{}}"#;

    #[test]
    fn a_page_line_reaches_the_core_only_while_ready() {
        let (mut machine, core) = handshaking();
        let generation = machine.connect();
        assert!(machine.send_line(generation, MODEL_GET).is_err(), "not ready yet");
        machine.handle(Input::Line { core, line: hello_answer(2) }).unwrap();
        let effects = machine.send_line(generation, MODEL_GET).unwrap();
        match effects.as_slice() {
            [Effect::Write { core: to, line }] => {
                assert_eq!(*to, core);
                assert!(line.contains(&format!("\"g{generation}:1\"")), "{line}");
            }
            other => panic!("{other:?}"),
        }
        let answer = format!(r#"{{"version":2,"type":"response","id":"g{generation}:1","result":{{"model":"fake-1"}}}}"#);
        assert_eq!(machine.handle(Input::Line { core, line: answer }).unwrap(),
                   vec![Effect::ToPage { generation,
                                         line: r#"{"version":2,"type":"response","id":"1","result":{"model":"fake-1"}}"#.into() }]);
    }

    #[test]
    fn the_page_hello_is_answered_without_the_core() {
        let (mut machine, _) = ready();
        let generation = machine.connect();
        let hello = r#"{"version":2,"type":"request","id":"h","method":"client.hello","params":{}}"#;
        match machine.send_line(generation, hello).unwrap().as_slice() {
            [Effect::ToPage { generation: to, line }] => {
                assert_eq!(*to, generation);
                assert!(line.contains(r#""id":"h""#) && line.contains("comodor-core"), "{line}");
            }
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_failure_closes_the_page_connection_and_a_new_one_is_needed() {
        let (mut machine, core) = ready();
        let generation = machine.connect();
        let effects = machine.handle(Input::Line { core, line: "garbage".into() }).unwrap();
        assert!(effects.iter().any(|effect| matches!(effect,
            Effect::PageClosed { generation: g, .. } if *g == generation)), "{effects:?}");
        assert!(machine.send_line(generation, MODEL_GET).is_err());
        assert!(machine.connect() > generation, "generations only grow across Cores");
    }

    #[test]
    fn the_core_answers_to_the_native_side_never_reach_the_page() {
        let (mut machine, core) = ready();
        machine.connect();
        let native = format!(r#"{{"version":2,"type":"response","id":"{}","result":{{}}}}"#, relay::HELLO_ID);
        assert_eq!(machine.handle(Input::Line { core, line: native }).unwrap(), vec![]);
    }

    // -- restarts (OD-1) ------------------------------------------------------

    /// The ready Core `core` crashes; a new Core, if one starts, is answered.
    fn crash(machine: &mut Machine, core: CoreId) -> (Vec<Effect>, Option<CoreId>) {
        let effects = machine.handle(Input::Exited { core, code: Some(70) }).unwrap();
        let next = effects.iter().find_map(|effect| match effect {
            Effect::Spawn { core, workspace } => {
                assert_eq!(workspace, Path::new(WS), "restarted in the same workspace");
                Some(*core)
            }
            _ => None,
        });
        if let Some(next) = next {
            assert_eq!(machine.state(), State::Restarting);
            machine.handle(Input::Spawned { core: next, pid: 7 }).unwrap();
            assert_eq!(machine.state(), State::Handshaking);
            machine.handle(Input::Line { core: next, line: hello_answer(2) }).unwrap();
            assert_eq!(machine.state(), State::Ready);
        }
        (effects, next)
    }

    fn turn(machine: &mut Machine, core: CoreId, events: &[&str]) {
        let generation = machine.connect();
        machine.send_line(generation,
            r#"{"version":2,"type":"request","id":"s","method":"session.send","params":{"session_id":"x","text":"hi"}}"#).unwrap();
        let accepted = format!(
            r#"{{"version":2,"type":"response","id":"g{generation}:s","result":{{"accepted":true,"turn_id":"t1"}}}}"#);
        machine.handle(Input::Line { core, line: accepted }).unwrap();
        for event in events {
            machine.handle(Input::Line { core, line: (*event).to_string() }).unwrap();
        }
    }

    const COMPLETED: &str = r#"{"version":2,"type":"event","event":"message.completed","seq":1,"params":{"turn_id":"t1","status":"completed"}}"#;
    const WARNING: &str = r#"{"version":2,"type":"event","event":"notification.created","seq":2,"params":{"level":"warning","text":"Stopped: a decision is needed"}}"#;
    const IDLE: &str = r#"{"version":2,"type":"event","event":"session.updated","seq":3,"params":{"session":{"busy":false}}}"#;

    #[test]
    fn crashes_one_and_two_restart_and_the_third_waits_for_try_again() {
        let (mut machine, core) = ready();
        let generation = machine.connect();
        let (effects, second) = crash(&mut machine, core);
        assert!(effects.iter().any(|e| matches!(e, Effect::PageClosed { generation: g, .. } if *g == generation)),
                "the page is told its Core went: {effects:?}");
        assert_eq!(machine.status().restart_count, 1);
        let (_, third) = crash(&mut machine, second.expect("restart after crash 1"));
        assert_eq!(machine.status().restart_count, 2);
        let (effects, none) = crash(&mut machine, third.expect("restart after crash 2"));
        assert!(none.is_none(), "no restart after crash 3: {effects:?}");
        let status = machine.status();
        assert_eq!(status.state, State::Failed);
        assert_eq!(status.restart_count, 3);
        assert_eq!(status.failure.unwrap().class, FailureClass::Crashed);
    }

    /// The page hears that its Core is restarting (or failed) before its
    /// connection closes, so it never reconnects to a Core that is not ready.
    #[test]
    fn the_status_reaches_the_page_before_its_connection_closes() {
        for limit_reached in [false, true] {
            let (mut machine, mut core) = ready();
            if limit_reached {
                for _ in 0..2 {
                    core = crash(&mut machine, core).1.unwrap();
                }
            }
            machine.connect();
            let effects = machine.handle(Input::Exited { core, code: Some(70) }).unwrap();
            let status = effects.iter().position(|e| *e == Effect::StatusChanged).expect("a status");
            let closed = effects.iter().position(|e| matches!(e, Effect::PageClosed { .. })).expect("closed");
            assert!(status < closed, "{effects:?}");
        }
    }

    #[test]
    fn try_again_after_the_limit_keeps_the_count() {
        let (mut machine, mut core) = ready();
        for _ in 0..2 {
            core = crash(&mut machine, core).1.unwrap();
        }
        crash(&mut machine, core);
        machine.handle(Input::Retry).unwrap();
        assert_eq!(machine.status().restart_count, 3, "Try again does not reset (OD-1)");
    }

    #[test]
    fn a_completed_turn_resets_the_count() {
        let (mut machine, core) = ready();
        let core = crash(&mut machine, core).1.unwrap();
        assert_eq!(machine.status().restart_count, 1);
        turn(&mut machine, core, &[COMPLETED, IDLE]);
        assert_eq!(machine.status().restart_count, 0);
    }

    #[test]
    fn an_uncertain_turn_does_not_reset_the_count() {
        let (mut machine, core) = ready();
        let core = crash(&mut machine, core).1.unwrap();
        turn(&mut machine, core, &[COMPLETED, WARNING, IDLE]);
        assert_eq!(machine.status().restart_count, 1);
    }

    #[test]
    fn a_relayed_cancel_does_not_reset_the_count() {
        let (mut machine, core) = ready();
        let core = crash(&mut machine, core).1.unwrap();
        let generation = machine.connect();
        machine.send_line(generation,
            r#"{"version":2,"type":"request","id":"s","method":"session.send","params":{"session_id":"x","text":"hi"}}"#).unwrap();
        machine.handle(Input::Line { core, line: format!(
            r#"{{"version":2,"type":"response","id":"g{generation}:s","result":{{"accepted":true,"turn_id":"t1"}}}}"#) }).unwrap();
        machine.send_line(generation,
            r#"{"version":2,"type":"request","id":"c","method":"session.cancel","params":{"session_id":"x"}}"#).unwrap();
        machine.handle(Input::Line { core, line: COMPLETED.into() }).unwrap();
        machine.handle(Input::Line { core, line: IDLE.into() }).unwrap();
        assert_eq!(machine.status().restart_count, 1);
    }

    #[test]
    fn a_crash_while_handshaking_after_a_restart_is_not_restarted() {
        let (mut machine, core) = ready();
        let effects = machine.handle(Input::Exited { core, code: Some(70) }).unwrap();
        let next = effects.iter().find_map(|e| match e { Effect::Spawn { core, .. } => Some(*core), _ => None })
            .unwrap();
        machine.handle(Input::Spawned { core: next, pid: 8 }).unwrap();
        let effects = machine.handle(Input::Exited { core: next, code: Some(1) }).unwrap();
        assert!(!effects.iter().any(|e| matches!(e, Effect::Spawn { .. })));
        assert_eq!(machine.status().failure.unwrap().class, FailureClass::ExitedBeforeReady);
        assert_eq!(machine.status().restart_count, 1, "a failure before ready never counts");
    }

    #[test]
    fn status_reports_the_restart_limit() {
        let machine = Machine::new();
        assert_eq!(machine.status().restart_limit, RESTART_LIMIT);
        assert_eq!(RESTART_LIMIT, 3);
    }
}

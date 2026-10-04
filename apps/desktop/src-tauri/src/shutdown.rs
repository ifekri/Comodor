//! Stopping the Core (contracts/core-supervision.md §5, data-model.md §6,
//! OD-2, FR-017).
//!
//! For every reason the sequence is the same: send `shutdown`, close the
//! Core's stdin, and wait for the process to exit — for at most `GRACE` from
//! the stop request, or until the person chooses "Quit now". Then it is
//! forced: the Core and everything it started are ended. A forced stop is
//! reported as exactly that, and never as anything having been saved.

use std::path::PathBuf;
use std::time::Duration;

use serde::Serialize;

/// How long the Core is given to stop by itself (OD-2).
pub const GRACE: Duration = Duration::from_secs(10);

/// What the window says, and the log records, after a forced stop.
pub const FORCED_NOTICE: &str =
    "Comodor was stopped before it finished; work it had not saved may be lost.";

/// What the log records after a forced stop.
pub const FORCED_LOG: &str = "stopped before it finished";

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StopReason {
    WindowClosed,
    Quit,
    /// Stop, then start a Core in this folder.
    WorkspaceChange(PathBuf),
    /// Stop, then start a Core in the same folder (after `comodor setup`).
    CheckAgain,
    OsSessionEnd,
}

impl StopReason {
    /// Whether the application ends once the Core has stopped.
    pub fn ends_application(&self) -> bool {
        matches!(self, StopReason::WindowClosed | StopReason::Quit | StopReason::OsSessionEnd)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StopOutcome {
    /// The Core exited by itself within the grace.
    Orderly,
    /// The grace ran out, or the person chose "Quit now".
    Forced,
}

/// The id of the native side's own `shutdown` request.
pub const SHUTDOWN_ID: &str = "native:shutdown";

/// The native side's `shutdown`, as one line.
pub fn shutdown_request() -> String {
    serde_json::json!({
        "version": crate::relay::PROTOCOL_VERSION,
        "type": "request",
        "id": SHUTDOWN_ID,
        "method": "shutdown",
        "params": {},
    }).to_string()
}

/// Whole seconds left of the grace, rounded up, from `elapsed`.
pub fn seconds_remaining(elapsed: Duration) -> u64 {
    let left = GRACE.saturating_sub(elapsed);
    left.as_secs() + u64::from(left.subsec_nanos() > 0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::supervisor::{CoreId, Effect, Input, Machine, State};
    use serde_json::{json, Value};
    use std::path::Path;
    use std::sync::{Arc, Mutex};
    use std::time::Instant;

    const WS: &str = "/work/project";

    /// A clock the test moves by hand.
    #[derive(Clone)]
    struct Clock(Arc<Mutex<Instant>>);

    impl Clock {
        fn new() -> Self {
            Clock(Arc::new(Mutex::new(Instant::now())))
        }
        fn advance(&self, by: Duration) {
            *self.0.lock().unwrap() += by;
        }
        fn reader(&self) -> Arc<dyn Fn() -> Instant + Send + Sync> {
            let inner = self.0.clone();
            Arc::new(move || *inner.lock().unwrap())
        }
    }

    fn ready(clock: &Clock) -> (Machine, CoreId) {
        let mut machine = Machine::with_clock(clock.reader());
        let effects = machine.handle(Input::Start { workspace: WS.into() }).unwrap();
        let core = effects.iter().find_map(|e| match e { Effect::Spawn { core, .. } => Some(*core), _ => None })
            .unwrap();
        machine.handle(Input::Spawned { core, pid: 5 }).unwrap();
        let hello = json!({"version": 2, "type": "response", "id": crate::relay::HELLO_ID,
                           "result": {"protocol_version": 2, "core": {"name": "c", "version": "1"},
                                      "capabilities": []}}).to_string();
        machine.handle(Input::Line { core, line: hello }).unwrap();
        assert_eq!(machine.state(), State::Ready);
        (machine, core)
    }

    fn texts(effects: &[Effect]) -> String {
        format!("{effects:?}")
    }

    #[test]
    fn the_order_is_shutdown_then_stdin_closed_then_the_wait() {
        let clock = Clock::new();
        let (mut machine, core) = ready(&clock);
        let effects = machine.handle(Input::Stop { reason: StopReason::Quit }).unwrap();
        let shutdown = effects.iter().position(|e| matches!(e, Effect::Write { core: c, line }
            if *c == core && serde_json::from_str::<Value>(line).unwrap()["method"] == "shutdown")).expect("shutdown");
        let closed = effects.iter().position(|e| *e == Effect::CloseStdin { core }).expect("stdin closed");
        let deadline = effects.iter().position(|e| *e == Effect::Deadline { core, after: GRACE })
            .expect("one deadline, at the grace");
        assert!(shutdown < closed && closed < deadline, "{effects:?}");
        assert!(!effects.contains(&Effect::ForceStop { core }), "nothing is forced yet");
        assert_eq!(machine.state(), State::Stopping);
        assert_eq!(GRACE, Duration::from_secs(10));
    }

    #[test]
    fn closing_counts_down_from_the_injected_clock() {
        let clock = Clock::new();
        let (mut machine, _) = ready(&clock);
        machine.handle(Input::Stop { reason: StopReason::WindowClosed }).unwrap();
        assert_eq!(machine.status().closing, Some(json!({ "seconds_remaining": 10 })));
        clock.advance(Duration::from_millis(3_200));
        assert_eq!(machine.status().closing, Some(json!({ "seconds_remaining": 7 })));
        clock.advance(Duration::from_secs(20));
        assert_eq!(machine.status().closing, Some(json!({ "seconds_remaining": 0 })));
    }

    #[test]
    fn an_exit_within_the_grace_is_orderly_and_nothing_is_forced() {
        let clock = Clock::new();
        let (mut machine, core) = ready(&clock);
        machine.handle(Input::Stop { reason: StopReason::Quit }).unwrap();
        clock.advance(Duration::from_secs(9));
        let effects = machine.handle(Input::Exited { core, code: Some(0) }).unwrap();
        assert!(!effects.iter().any(|e| matches!(e, Effect::ForceStop { .. })));
        assert!(effects.contains(&Effect::Finished));
        assert_eq!(machine.state(), State::Stopped);
        assert_eq!(machine.status().stop_outcome, Some(StopOutcome::Orderly));
    }

    #[test]
    fn the_deadline_forces_the_stop_at_ten_seconds_and_not_before() {
        let clock = Clock::new();
        let (mut machine, core) = ready(&clock);
        machine.handle(Input::Stop { reason: StopReason::Quit }).unwrap();
        // Nothing but the deadline itself, or "Quit now", forces anything.
        clock.advance(Duration::from_millis(9_999));
        assert_eq!(machine.status().state, State::Stopping);
        let effects = machine.handle(Input::DeadlinePassed { core }).unwrap();
        assert!(effects.contains(&Effect::ForceStop { core }), "{effects:?}");
        assert!(effects.contains(&Effect::Note(FORCED_LOG)), "the log says so");
        let effects = machine.handle(Input::Exited { core, code: None }).unwrap();
        assert!(effects.contains(&Effect::Finished));
        assert_eq!(machine.status().stop_outcome, Some(StopOutcome::Forced));
    }

    #[test]
    fn quit_now_forces_the_stop_at_once_and_only_while_stopping() {
        let clock = Clock::new();
        let (mut machine, core) = ready(&clock);
        assert!(machine.handle(Input::QuitNow).is_err(), "not stopping yet");
        machine.handle(Input::Stop { reason: StopReason::WindowClosed }).unwrap();
        clock.advance(Duration::from_secs(1));
        let effects = machine.handle(Input::QuitNow).unwrap();
        assert!(effects.contains(&Effect::ForceStop { core }));
        machine.handle(Input::Exited { core, code: None }).unwrap();
        assert_eq!(machine.status().stop_outcome, Some(StopOutcome::Forced));
        // A deadline that arrives afterwards changes nothing.
        assert_eq!(machine.handle(Input::DeadlinePassed { core }).unwrap(), vec![]);
    }

    #[test]
    fn a_forced_workspace_change_says_so_in_the_window_and_starts_the_new_core() {
        for reason in [StopReason::WorkspaceChange("/work/other".into()), StopReason::CheckAgain] {
            let clock = Clock::new();
            let (mut machine, core) = ready(&clock);
            machine.handle(Input::Stop { reason: reason.clone() }).unwrap();
            machine.handle(Input::DeadlinePassed { core }).unwrap();
            let effects = machine.handle(Input::Exited { core, code: None }).unwrap();
            let spawn = effects.iter().find_map(|e| match e { Effect::Spawn { workspace, .. } => Some(workspace.clone()), _ => None })
                .expect("a new Core starts");
            let expected = match &reason { StopReason::WorkspaceChange(path) => path.clone(), _ => WS.into() };
            assert_eq!(spawn, expected);
            assert!(!effects.contains(&Effect::Finished), "the application stays open");
            assert_eq!(machine.status().notice.as_deref(), Some(FORCED_NOTICE));
            assert_eq!(machine.status().workspace.as_deref(), Some(Path::new(&expected).display().to_string().as_str()));
        }
    }

    #[test]
    fn no_forced_path_claims_anything_was_saved() {
        // The one sentence a forced stop shows says work may be lost.
        assert!(!FORCED_NOTICE.replace("had not saved", "").contains("saved"));
        assert!(!FORCED_LOG.contains("saved"));
        for reason in [StopReason::Quit, StopReason::WindowClosed, StopReason::CheckAgain,
                       StopReason::WorkspaceChange("/w2".into()), StopReason::OsSessionEnd] {
            let clock = Clock::new();
            let (mut machine, core) = ready(&clock);
            let mut seen = texts(&machine.handle(Input::Stop { reason }).unwrap());
            seen += &texts(&machine.handle(Input::QuitNow).unwrap());
            seen += &texts(&machine.handle(Input::Exited { core, code: None }).unwrap());
            seen += &format!("{:?}", machine.status());
            assert!(!seen.replace("had not saved", "").contains("saved"), "{seen}");
        }
    }

    #[test]
    fn stopping_with_no_core_running_ends_at_once() {
        let clock = Clock::new();
        let mut machine = Machine::with_clock(clock.reader());
        let effects = machine.handle(Input::Stop { reason: StopReason::WindowClosed }).unwrap();
        assert!(effects.contains(&Effect::Finished));
        assert_eq!(machine.status().stop_outcome, Some(StopOutcome::Orderly));
    }

    #[test]
    fn a_second_stop_while_stopping_is_refused() {
        let clock = Clock::new();
        let (mut machine, _) = ready(&clock);
        machine.handle(Input::Stop { reason: StopReason::Quit }).unwrap();
        assert!(machine.handle(Input::Stop { reason: StopReason::Quit }).is_err());
    }

    #[test]
    fn the_shutdown_request_is_one_protocol_line() {
        let line: Value = serde_json::from_str(&shutdown_request()).unwrap();
        assert_eq!(line["method"], "shutdown");
        assert_eq!(line["id"], SHUTDOWN_ID);
        assert_eq!(line["type"], "request");
        assert_eq!(seconds_remaining(Duration::ZERO), 10);
        assert_eq!(seconds_remaining(Duration::from_millis(9_001)), 1);
        assert_eq!(seconds_remaining(Duration::from_secs(10)), 0);
    }
}

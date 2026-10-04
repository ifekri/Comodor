//! T071: the stop sequence against real processes (OD-2, FR-017, SC-016).

mod support;

use std::ffi::OsString;
use std::sync::mpsc::channel;
use std::sync::Arc;
use std::time::{Duration, Instant};

use comodor_desktop::logfile::Log;
use comodor_desktop::platform::CoreCommand;
use comodor_desktop::shutdown::{StopOutcome, StopReason, FORCED_LOG, GRACE};
use comodor_desktop::supervisor::{Options, State, Supervisor};
use serde_json::json;
use support::{fixture_command, read_pid, request, wait_gone, CoreHome, HoldPoint, Page, Scratch, DEADLINE};

struct Run {
    supervisor: Supervisor,
    finished: std::sync::mpsc::Receiver<()>,
    log: Arc<Log>,
    _home: CoreHome,
}

fn run(command: CoreCommand, label: &str, extra: Vec<(OsString, OsString)>) -> Run {
    let home = CoreHome::new(label);
    let mut env = home.env();
    env.extend(extra);
    let log = Arc::new(Log::in_dir(&home.scratch.root.join("log")));
    let (done, finished) = channel();
    let supervisor = Supervisor::launch(Options {
        locate: Box::new(move || Ok(command.clone())),
        test_env: env,
        log: Some(log.clone()),
        on_finished: Some(Box::new(move || {
            let _ = done.send(());
        })),
    });
    supervisor.start(home.workspace.clone()).unwrap();
    supervisor.wait_for(|s| s.state == State::Ready, DEADLINE).expect("ready");
    Run { supervisor, finished, log, _home: home }
}

fn stopped(run: &Run) -> comodor_desktop::supervisor::Status {
    run.finished.recv_timeout(DEADLINE + GRACE).expect("the application is told it may end");
    run.supervisor.wait_for(|s| s.state == State::Stopped, DEADLINE).expect("stopped")
}

#[test]
fn a_core_stopped_mid_turn_exits_by_itself_within_the_grace() {
    let scratch = Scratch::new("shutdown-held");
    let hold = HoldPoint::new("shutdown", &scratch);
    let run = run(fixture_command("scripted_core.py", "hold-mid-turn"), "shutdown-held", vec![hold.env()]);
    let page = Page::new();
    let generation = run.supervisor.connect(page.sink());
    let line = |id: &str, method: &str, params| request(id, method, params);
    run.supervisor.send_line(generation, line("c", "session.create", json!({}))).unwrap();
    let session = page.answer("c")["result"]["session"]["id"].as_str().unwrap().to_string();
    run.supervisor.send_line(generation,
        line("s", "session.send", json!({ "session_id": session, "text": "go" }))).unwrap();
    page.event("message.delta", |_| true);
    let pid = run.supervisor.core_pid().unwrap();

    let asked = Instant::now();
    run.supervisor.stop(StopReason::Quit).unwrap();
    let status = stopped(&run);
    let took = asked.elapsed();
    assert_eq!(status.stop_outcome, Some(StopOutcome::Orderly), "no termination was needed");
    assert!(took < GRACE, "it exited by itself within the grace: {took:?}");
    assert!(wait_gone(pid));
    let log = std::fs::read_to_string(run.log.path()).unwrap();
    assert!(!log.contains(FORCED_LOG), "{log}");
    println!("orderly stop mid-turn took {} ms", took.as_millis());
}

#[test]
fn a_core_that_ignores_the_stop_is_ended_at_the_deadline_with_its_child() {
    let scratch = Scratch::new("shutdown-ignore");
    let child_file = scratch.root.join("child.pid");
    let run = run(fixture_command("doubles.py", "ignore-stop"), "shutdown-ignore",
                  vec![("COMODOR_TEST_CHILD_PID_FILE".into(), child_file.clone().into())]);
    let child = read_pid(&child_file, None);
    let pid = run.supervisor.core_pid().unwrap();

    let asked = Instant::now();
    run.supervisor.stop(StopReason::WindowClosed).unwrap();
    let closing = run.supervisor.status().closing.expect("closing is shown");
    assert!(closing["seconds_remaining"].as_u64().unwrap() <= 10);
    let status = stopped(&run);
    let took = asked.elapsed();
    assert_eq!(status.stop_outcome, Some(StopOutcome::Forced));
    assert!(took >= GRACE - Duration::from_millis(50), "not before the deadline: {took:?}");
    assert!(wait_gone(pid), "the Core is gone");
    assert!(wait_gone(child), "and so is its child");
    let log = std::fs::read_to_string(run.log.path()).unwrap();
    assert!(log.contains(FORCED_LOG), "{log}");
    println!("forced stop at the deadline took {} ms", took.as_millis());
}

#[test]
fn quit_now_ends_it_at_once() {
    let scratch = Scratch::new("shutdown-quit-now");
    let child_file = scratch.root.join("child.pid");
    let run = run(fixture_command("doubles.py", "ignore-stop"), "shutdown-quit-now",
                  vec![("COMODOR_TEST_CHILD_PID_FILE".into(), child_file.clone().into())]);
    let child = read_pid(&child_file, None);
    let pid = run.supervisor.core_pid().unwrap();
    run.supervisor.stop(StopReason::Quit).unwrap();
    let asked = Instant::now();
    run.supervisor.quit_now().unwrap();
    let status = stopped(&run);
    assert_eq!(status.stop_outcome, Some(StopOutcome::Forced));
    assert!(asked.elapsed() < GRACE / 2, "at once, not at the deadline: {:?}", asked.elapsed());
    assert!(wait_gone(pid) && wait_gone(child));
}

#[test]
fn quit_now_is_refused_unless_closing() {
    let run = run(fixture_command("scripted_core.py", "echo"), "shutdown-refuse", vec![]);
    assert!(run.supervisor.quit_now().is_err());
    assert_eq!(run.supervisor.status().state, State::Ready);
}

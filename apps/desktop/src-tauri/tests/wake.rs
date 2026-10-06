//! After the machine sleeps (spec: Machine sleep and wake), against real
//! processes: the Core is checked before the page may send to it again. A
//! test cannot put the machine to sleep, so the wake is told the way the
//! application's wake watch tells it (`Supervisor::woke`).

mod support;

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use comodor_desktop::commands::Desktop;
use comodor_desktop::shutdown::StopReason;
use comodor_desktop::wake::Watch;
use comodor_desktop::workspace::Chooser;
use comodor_desktop::supervisor::{State, CHECK_GRACE};
use serde_json::json;
use support::{fixture_command, launch, real_core_command, request, CoreHome, Page, DEADLINE};

struct NoChooser;

impl Chooser for NoChooser {
    fn choose(&mut self, _start: Option<&Path>) -> Option<PathBuf> {
        None
    }
}

/// A line the page sends right after a wake the watch has not reported yet
/// is held back as well: the wake is noticed first. The Core here never
/// answers, so the check stays pending for as long as the test looks.
#[test]
fn a_line_sent_before_the_wake_was_noticed_waits_for_the_check() {
    let home = CoreHome::new("wake-line");
    let supervisor = launch(fixture_command("doubles.py", "ignore-stop"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    supervisor.wait_for(|s| s.state == State::Ready, DEADLINE).expect("ready");
    let slept = Arc::new(Mutex::new(Some(Duration::ZERO)));
    let reading = slept.clone();
    let desktop = Desktop::new(supervisor.clone(), home.workspace.join("prefs.json"), Box::new(NoChooser))
        .with_wake(Watch::new(Box::new(move || *reading.lock().unwrap())));
    let page = Page::new();
    let generation = supervisor.connect(page.sink());
    desktop.send_line(generation, request("1", "session.list", json!({}))).expect("sent while awake");

    *slept.lock().unwrap() = Some(Duration::from_secs(600));
    assert!(desktop.send_line(generation, request("2", "session.list", json!({}))).is_err(),
            "held back: the Core is checked first");
    assert_eq!(supervisor.status().state, State::Checking);
    assert!(desktop.send_line(generation, request("3", "session.list", json!({}))).is_err(),
            "still held back while the check is pending");
    supervisor.stop(StopReason::Quit).unwrap();
    supervisor.quit_now().unwrap();
    supervisor.wait_for(|s| s.state == State::Stopped, DEADLINE).expect("stopped");
}

#[test]
fn the_real_core_answers_the_check_and_the_page_may_send_again() {
    let home = CoreHome::new("wake-real");
    let supervisor = launch(real_core_command(), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    supervisor.wait_for(|s| s.state == State::Ready, DEADLINE).expect("ready");
    let page = Page::new();
    let generation = supervisor.connect(page.sink());
    supervisor.send_line(generation, request("c", "session.create", json!({}))).unwrap();
    let session = page.answer("c")["result"]["session"]["id"].as_str().unwrap().to_string();

    supervisor.woke();
    let states = page.states_until(2, "ready");
    assert_eq!(&states[states.len() - 2..], ["checking", "ready"], "{states:?}");

    // The session is the Core's to tell, and it still has it.
    supervisor.send_line(generation, request("s", "session.snapshot", json!({ "session_id": session })))
        .unwrap();
    assert_eq!(page.answer("s")["result"]["snapshot"]["session"]["id"], session.as_str());
    supervisor.stop(StopReason::Quit).unwrap();
    supervisor.wait_for(|s| s.state == State::Stopped, DEADLINE).expect("stopped");
}

/// A Core that never answers (it reads and ignores every line) is taken for
/// hung once the check's deadline passes, ended, and started again.
#[test]
fn a_core_that_does_not_answer_after_a_wake_is_restarted() {
    let home = CoreHome::new("wake-deaf");
    let supervisor = launch(fixture_command("doubles.py", "ignore-stop"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    supervisor.wait_for(|s| s.state == State::Ready, DEADLINE).expect("ready");
    let page = Page::new();
    let generation = supervisor.connect(page.sink());

    supervisor.woke();
    supervisor.wait_for(|s| s.state == State::Checking, DEADLINE).expect("checking");
    assert!(supervisor.send_line(generation, request("1", "session.list", json!({}))).is_err(),
            "nothing reaches the Core before it has answered");
    let restarted = supervisor.wait_for(|s| s.restart_count == 1, CHECK_GRACE + DEADLINE)
        .expect("restarted after the check's deadline");
    assert!(restarted.notice.as_deref().is_some_and(|n| n.contains("did not answer")), "{restarted:?}");
    supervisor.wait_for(|s| s.state == State::Ready, DEADLINE).expect("ready again");

    supervisor.stop(StopReason::Quit).unwrap();
    supervisor.quit_now().unwrap();
    supervisor.wait_for(|s| s.state == State::Stopped, DEADLINE).expect("stopped");
}

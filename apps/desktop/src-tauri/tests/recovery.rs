//! T061: recovery against real processes (FR-004, FR-005, FR-011, FR-016,
//! OD-1; SC-003, SC-004, SC-006).
//!
//! Every Core here is killed or crashes on purpose. Waits have a failure
//! deadline and return as soon as their condition holds.

mod support;

use std::time::Instant;

use comodor_desktop::supervisor::{State, Status, Supervisor};
use serde_json::{json, Value};
use support::{fixture_command, kill, launch_with_env, request, CoreHome, HoldPoint, Page, Scratch, DEADLINE};

const QUESTION_PROMPT: &str = "Build the service. Which database: SQLite or PostgreSQL?";

/// One page on the current Core: a fresh connection, as the window makes
/// after every restart.
struct Window<'a> {
    supervisor: &'a Supervisor,
    page: Page,
    generation: u64,
    sends: u32,
}

impl<'a> Window<'a> {
    fn open(supervisor: &'a Supervisor) -> Self {
        let page = Page::new();
        let generation = supervisor.connect(page.sink());
        Window { supervisor, page, generation, sends: 0 }
    }

    fn call(&self, id: &str, method: &str, params: Value) -> Value {
        self.supervisor.send_line(self.generation, request(id, method, params)).expect("relayed");
        self.page.answer(id)
    }

    fn create(&self) -> String {
        self.call("create", "session.create", json!({}))["result"]["session"]["id"]
            .as_str().expect("a session").to_string()
    }

    /// The person sends one prompt; the turn it started.
    fn send(&mut self, session: &str, text: &str) -> (String, usize) {
        let mark = self.page.mark();
        self.sends += 1;
        let id = format!("send-{}", self.sends);
        let answer = self.call(&id, "session.send", json!({ "session_id": session, "text": text }));
        (answer["result"]["turn_id"].as_str().unwrap_or("").to_string(), mark)
    }

    fn idle_since(&self, mark: usize) {
        self.page.event_since(mark, "session.updated", |p| p["session"]["busy"] == false);
    }

    /// A round trip after everything seen so far, so the status the
    /// supervisor publishes has caught up with it.
    fn settle(&self) {
        self.call(&format!("settle-{}", self.page.mark()), "model.get", json!({}));
    }
}

/// Open the stored conversation `stored`; the live session's id.
fn reopen(window: &Window, stored: &str) -> String {
    let opened = window.call("open", "session.open", json!({ "session_id": stored }));
    opened["result"]["session"]["id"].as_str()
        .unwrap_or_else(|| panic!("the stored conversation opens: {opened}")).to_string()
}

fn ready(supervisor: &Supervisor, count: u32) -> Status {
    supervisor.wait_for(|s| s.state == State::Ready && s.restart_count == count, DEADLINE)
        .unwrap_or_else(|| panic!("ready at count {count}: {:?}\n{}", supervisor.status(),
                                  supervisor.diagnostics()))
}

fn stopped_at(supervisor: &Supervisor, count: u32) {
    supervisor.wait_for(|s| s.state == State::Failed && s.restart_count == count, DEADLINE)
        .unwrap_or_else(|| panic!("stopped at count {count}: {:?}", supervisor.status()));
}

fn kill_core(supervisor: &Supervisor) {
    kill(supervisor.core_pid().expect("a running Core"));
}

#[test]
fn a_kill_between_turns_restarts_in_the_same_workspace_and_the_transcript_is_back() {
    let home = CoreHome::new("recovery-between");
    let supervisor = launch_with_env(fixture_command("scripted_core.py", "echo"), &home, vec![]);
    supervisor.start(home.workspace.clone()).unwrap();
    let before = ready(&supervisor, 0);
    let mut window = Window::open(&supervisor);
    let session = window.create();
    let (turn, mark) = window.send(&session, "remember this line");
    window.page.event_since(mark, "message.completed", |p| p["turn_id"] == turn.as_str());
    window.idle_since(mark);

    let killed = Instant::now();
    kill_core(&supervisor);
    window.page.until(|m| m["kind"] == "closed");
    let after = ready(&supervisor, 1);
    assert_eq!(after.workspace, before.workspace, "the same workspace");

    let window = Window::open(&supervisor);
    let live = reopen(&window, &session);
    let snapshot = window.call("snap", "session.snapshot", json!({ "session_id": live }));
    let back = killed.elapsed();
    let messages = snapshot["result"]["snapshot"]["messages"].as_array().cloned().unwrap_or_default();
    assert!(messages.iter().any(|m| m["role"] == "user" && m["text"] == "remember this line"),
            "the person's message is back: {messages:?}");
    // Restored messages carry restored ids; what matters is the content.
    let _ = turn;
    let user = messages.iter().position(|m| m["role"] == "user" && m["text"] == "remember this line");
    let answer = messages.iter().position(|m| m["role"] == "assistant"
        && m["text"].as_str().is_some_and(|text| text.contains("remember this line")));
    assert!(matches!((user, answer), (Some(u), Some(a)) if a > u), "the answer is back: {messages:?}");
    assert!(back.as_secs_f64() < 10.0, "SC-003: back in {back:?}");
    println!("SC-003: transcript back {} ms after the kill", back.as_millis());
}

#[test]
fn a_kill_in_the_middle_of_a_turn_keeps_nothing_of_it_and_sends_nothing_again() {
    let home = CoreHome::new("recovery-held");
    let scratch = Scratch::new("recovery-held-hold");
    let hold = HoldPoint::new("held", &scratch);
    let supervisor = launch_with_env(fixture_command("scripted_core.py", "hold-mid-turn"), &home,
                                     vec![hold.env()]);
    supervisor.start(home.workspace.clone()).unwrap();
    ready(&supervisor, 0);
    let mut window = Window::open(&supervisor);
    let session = window.create();
    let (turn, mark) = window.send(&session, "start something long");
    window.page.event_since(mark, "message.delta", |p| p["turn_id"] == turn.as_str());
    kill_core(&supervisor);
    ready(&supervisor, 1);

    // The Core persists at turn boundaries, and this turn never reached one:
    // nothing of it was kept, so the stored conversation is not there.
    let window = Window::open(&supervisor);
    let opened = window.call("open", "session.open", json!({ "session_id": session }));
    assert_eq!(opened["error"]["code"], "not_allowed", "nothing was kept: {opened}");
    // And nothing runs again: the new Core is idle and this page sent nothing.
    let fresh = window.create();
    let snapshot = window.call("snap", "session.snapshot", json!({ "session_id": fresh }));
    assert_eq!(snapshot["result"]["snapshot"]["session"]["busy"], false);
    assert_eq!(snapshot["result"]["snapshot"]["messages"], json!([]));
    assert_eq!(window.sends, 0, "this page sent no prompt");
    let _ = turn;
}

/// A sequenced Core in a home of its own: one behaviour per launch.
fn sequenced(label: &str, sequence: Value, hold: Option<&HoldPoint>) -> (CoreHome, Supervisor) {
    let home = CoreHome::new(label);
    let file = home.scratch.root.join("sequence.json");
    std::fs::write(&file, sequence.to_string()).unwrap();
    let mut env = vec![("COMODOR_TEST_SEQUENCE".into(), file.into())];
    if let Some(hold) = hold {
        env.push(hold.env());
    }
    let supervisor = launch_with_env(fixture_command("doubles.py", "sequenced"), &home, env);
    supervisor.start(home.workspace.clone()).unwrap();
    (home, supervisor)
}

/// A launch that crashes when the person sends.
fn crash_on_send(supervisor: &Supervisor, count_before: u32) {
    ready(supervisor, count_before);
    let mut window = Window::open(supervisor);
    let session = window.create();
    let (_, _) = window.send(&session, "this crashes it");
}

#[test]
fn three_crashes_in_a_row_stop_and_wait_for_try_again() {
    let (_home, supervisor) = sequenced("recovery-three",
        json!(["crash-on-send", "crash-on-send", "crash-on-send"]), None);
    crash_on_send(&supervisor, 0);
    crash_on_send(&supervisor, 1);
    crash_on_send(&supervisor, 2);
    stopped_at(&supervisor, 3);
    assert!(supervisor.status().failure.unwrap().message.contains("3 times"));
    supervisor.retry().expect("Try again is the way on");
    assert_ne!(supervisor.status().state, State::Failed);
    assert_eq!(supervisor.status().restart_count, 3, "and it keeps the count");
}

#[test]
fn a_completed_turn_resets_the_count_between_crashes() {
    let (_home, supervisor) = sequenced("recovery-reset",
        json!(["crash-on-send", "complete-turn", "crash-on-send", "crash-on-send"]), None);
    crash_on_send(&supervisor, 0);
    ready(&supervisor, 1);
    let mut window = Window::open(&supervisor);
    let session = window.create();
    let (turn, mark) = window.send(&session, "a turn that completes");
    window.page.event_since(mark, "message.completed", |p| p["turn_id"] == turn.as_str());
    window.idle_since(mark);
    supervisor.wait_for(|s| s.restart_count == 0, DEADLINE).expect("the completed turn resets");
    kill_core(&supervisor);
    crash_on_send(&supervisor, 1);
    crash_on_send(&supervisor, 2);
    stopped_at(&supervisor, 3);
}

/// Each uncertain outcome leaves the count where it was (SC-006).
fn uncertain(scenario: &str) {
    let scratch = Scratch::new(&format!("recovery-{scenario}-hold"));
    let hold = HoldPoint::new(scenario, &scratch);
    let (_home, supervisor) = sequenced(&format!("recovery-{scenario}"),
        json!(["crash-on-send", format!("scripted:{scenario}"), "crash-on-send"]), Some(&hold));
    crash_on_send(&supervisor, 0);
    ready(&supervisor, 1);
    let mut window = Window::open(&supervisor);
    let session = window.create();
    let prompt = if scenario == "clarification-stop" { QUESTION_PROMPT } else { "go" };
    let (turn, mark) = window.send(&session, prompt);
    match scenario {
        "cancel-between-messages" => {
            window.page.event_since(mark, "tool.started", |p| p["name"] == "hold_step");
            window.call("cancel", "session.cancel", json!({ "session_id": session }));
            hold.release();
        }
        "cancel-mid-message" => {
            window.page.event_since(mark, "message.delta", |p| p["turn_id"] == turn.as_str());
            window.call("cancel", "session.cancel", json!({ "session_id": session }));
            hold.release();
        }
        "clarification-stop" => {
            let asked = window.page.event_since(mark, "question.requested", |_| true);
            window.call("dismiss", "question.answer", json!({ "id": asked["id"], "cancelled": true }));
        }
        _ => {}
    }
    window.idle_since(mark);
    window.settle();
    assert_eq!(supervisor.status().restart_count, 1, "{scenario} did not reset the count");
    kill_core(&supervisor);
    crash_on_send(&supervisor, 2);
    stopped_at(&supervisor, 3);
}

#[test]
fn cancel_between_messages_does_not_reset() {
    uncertain("cancel-between-messages");
}

#[test]
fn cancel_mid_message_does_not_reset() {
    uncertain("cancel-mid-message");
}

#[test]
fn a_failure_between_messages_does_not_reset() {
    uncertain("fail-between-messages");
}

#[test]
fn a_failure_mid_message_does_not_reset() {
    uncertain("fail-mid-message");
}

#[test]
fn a_clarification_stop_does_not_reset() {
    uncertain("clarification-stop");
}

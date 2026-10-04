//! T039: one conversation through the relay, against the scripted Core
//! (contracts/native-bridge.md §Relay guarantees, FR-013, FR-015, SC-014).

mod support;

use comodor_desktop::supervisor::{State, Supervisor};
use serde_json::{json, Value};
use support::{fixture_command, launch_with_env, request, CoreHome, HoldPoint, Page, DEADLINE};

const QUESTION_PROMPT: &str = "Build the service. Which database: SQLite or PostgreSQL?";

struct Session {
    supervisor: Supervisor,
    page: Page,
    generation: u64,
    id: String,
    // Kept alive for the test's length.
    _home: CoreHome,
}

impl Session {
    fn open(scenario: &str, hold: Option<&HoldPoint>) -> Self {
        let home = CoreHome::new(&format!("conversation-{scenario}"));
        let extra = hold.map(|hold| vec![hold.env()]).unwrap_or_default();
        let supervisor = launch_with_env(fixture_command("scripted_core.py", scenario), &home, extra);
        supervisor.start(home.workspace.clone()).unwrap();
        let status = supervisor.wait_for(|s| matches!(s.state, State::Ready | State::Failed), DEADLINE)
            .expect("settled");
        assert_eq!(status.state, State::Ready, "{status:?}\n{}", supervisor.diagnostics());
        let page = Page::new();
        let generation = supervisor.connect(page.sink());
        let mut session = Session { supervisor, page, generation, id: String::new(), _home: home };
        let made = session.call("create", "session.create", json!({}));
        session.id = made["result"]["session"]["id"].as_str().expect("a session").to_string();
        session
    }

    fn send(&self, id: &str, method: &str, params: Value) {
        self.supervisor.send_line(self.generation, request(id, method, params)).expect("relayed");
    }

    fn call(&self, id: &str, method: &str, params: Value) -> Value {
        self.send(id, method, params);
        self.page.answer(id)
    }

    fn prompt(&self, id: &str, text: &str) -> String {
        let accepted = self.call(id, "session.send", json!({ "session_id": self.id, "text": text }));
        accepted["result"]["turn_id"].as_str().expect("a turn").to_string()
    }
}

fn line_values(page: &Page) -> Vec<Value> {
    page.lines_until(|_| true)
}

#[test]
fn echo_streams_in_the_cores_order() {
    let session = Session::open("echo", None);
    let turn = session.prompt("send", "hello there");
    let done = session.page.event("message.completed", |p| p["turn_id"] == turn.as_str());
    assert_eq!(done["status"], "completed");
    let lines = line_values(&session.page);
    let seqs: Vec<i64> = lines.iter().filter(|l| l["type"] == "event")
        .map(|l| l["seq"].as_i64().unwrap()).collect();
    assert!(seqs.windows(2).all(|pair| pair[1] == pair[0] + 1), "contiguous, in order: {seqs:?}");
    // The Core answers a request before the events it caused, and the relay
    // keeps that order.
    let answered = lines.iter().position(|l| l["id"] == "send").unwrap();
    let started = lines.iter().position(|l| l["event"] == "message.started"
        && l["params"]["turn_id"] == turn.as_str()).unwrap();
    assert!(answered < started);
    let streamed: String = lines.iter().filter(|l| l["event"] == "message.delta"
        && l["params"]["turn_id"] == turn.as_str())
        .map(|l| l["params"]["text"].as_str().unwrap_or("")).collect();
    assert!(!streamed.is_empty());
}

#[test]
fn a_question_arrives_whole_and_the_answer_reaches_the_core_exactly() {
    let session = Session::open("question", None);
    session.prompt("send", QUESTION_PROMPT);
    let asked = session.page.event("question.requested", |_| true);
    let field = &asked["questions"][0];
    let options = field["options"].as_array().unwrap();
    let labels: Vec<&str> = options.iter().filter_map(|o| o["label"].as_str()).collect();
    assert!(labels.contains(&"SQLite") && labels.contains(&"PostgreSQL"), "{labels:?}");
    assert!(options.iter().any(|o| o["free"] == true), "the write-your-own row: {options:?}");
    let sqlite = options.iter().find(|o| o["label"] == "SQLite").unwrap()["id"].clone();
    let answers = json!([{ "header": field["header"], "chosen": [sqlite] }]);
    let ack = session.call("answer", "question.answer",
                           json!({ "id": asked["id"], "answers": answers }));
    assert!(ack.get("result").is_some(), "{ack}");
    let resolved = session.page.event("question.resolved", |p| p["id"] == asked["id"]);
    assert_eq!(resolved["answers"], answers, "the Core received exactly the answer sent");
}

#[test]
fn a_permission_arrives_whole_and_the_reply_reaches_the_core_exactly() {
    let session = Session::open("permission", None);
    session.prompt("send", "Write the file.");
    let asked = session.page.event("permission.requested", |_| true);
    let options: Vec<&str> = asked["options"].as_array().unwrap().iter()
        .filter_map(Value::as_str).collect();
    assert!(options.contains(&"allow") && options.contains(&"deny"), "{options:?}");
    assert_eq!(asked["tool"], "write_file");
    assert!(asked.get("risk").is_some(), "{asked}");
    session.call("reply", "permission.reply", json!({ "id": asked["id"], "choice": "deny" }));
    let resolved = session.page.event("permission.resolved", |p| p["id"] == asked["id"]);
    assert_eq!(resolved["choice"], "deny");
}

#[test]
fn an_unanswered_question_is_resolved_by_the_core_never_by_the_relay() {
    let session = Session::open("question", None);
    session.prompt("send", QUESTION_PROMPT);
    let asked = session.page.event("question.requested", |_| true);
    let cancel = session.call("cancel", "session.cancel", json!({ "session_id": session.id }));
    assert_eq!(cancel["result"]["cancelled"], true);
    let resolved = session.page.event("question.resolved", |p| p["id"] == asked["id"]);
    assert_eq!(resolved["cancelled"], true);
    // The page sent no answer; the only answer the Core saw was its own.
    let lines = line_values(&session.page);
    assert!(!lines.iter().any(|l| l["id"] == "answer"));
}

#[test]
fn cancel_in_the_middle_of_a_message_stops_the_turn() {
    let scratch = support::Scratch::new("conversation-hold");
    let hold = HoldPoint::new("cancel", &scratch);
    let session = Session::open("hold-mid-turn", Some(&hold));
    let turn = session.prompt("send", "Tell me something long.");
    session.page.event("message.delta", |p| p["turn_id"] == turn.as_str());
    let cancel = session.call("cancel", "session.cancel", json!({ "session_id": session.id }));
    assert_eq!(cancel["result"], json!({ "cancelled": true }));
    hold.release();
    let done = session.page.event("message.completed", |p| p["turn_id"] == turn.as_str());
    assert_ne!(done["status"], "completed", "the turn ended cancelled: {done}");
}

#[test]
fn cancel_while_idle_has_nothing_to_stop() {
    let session = Session::open("echo", None);
    let cancel = session.call("cancel", "session.cancel", json!({ "session_id": session.id }));
    assert_eq!(cancel["result"], json!({ "cancelled": false }));
}

#[test]
fn the_page_cannot_stop_the_core() {
    let session = Session::open("echo", None);
    let refused = session.supervisor.send_line(session.generation,
                                               request("bye", "shutdown", json!({})));
    assert!(refused.is_err());
    assert_eq!(session.supervisor.status().state, State::Ready);
    assert_eq!(session.call("again", "model.get", json!({}))["result"]["model"], "fake-1");
}

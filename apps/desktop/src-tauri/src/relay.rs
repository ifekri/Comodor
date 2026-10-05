//! The native handshake, and the relay between one page and the Core
//! (contracts/native-bridge.md, data-model.md §2).

use std::collections::{HashMap, HashSet};
use std::ops::Range;

use serde_json::{json, Value};

include!(concat!(env!("OUT_DIR"), "/protocol.rs"));

/// The id of the native side's own `client.hello`.
pub const HELLO_ID: &str = "native:hello";

/// The capabilities the desktop window renders — the same two the terminal
/// interface declares (contracts/core-supervision.md §3).
pub const CAPABILITIES: [&str; 2] = ["questions", "permissions"];

/// The native side's `client.hello`, as one line.
pub fn hello_request() -> String {
    json!({
        "version": PROTOCOL_VERSION,
        "type": "request",
        "id": HELLO_ID,
        "method": "client.hello",
        "params": {
            "protocol_version": PROTOCOL_VERSION,
            "client": { "name": "comodor-desktop", "version": env!("CARGO_PKG_VERSION") },
            "capabilities": CAPABILITIES,
        },
    }).to_string()
}

/// What one stdout line means while the Core is handshaking.
#[derive(Clone, Debug, PartialEq)]
pub enum Handshake {
    /// The answer, at this desktop's protocol version: the result to cache.
    Ready(Value),
    /// The answer names another version; the message names both.
    Mismatch(String),
    /// The Core refused the hello for another reason.
    Refused(String),
    /// A protocol line that is not the answer.
    NotYet,
    /// Not a protocol envelope at all (FR-007).
    Fault,
}

pub fn read_handshake(line: &str) -> Handshake {
    let Some(envelope) = envelope(line) else { return Handshake::Fault };
    if envelope.get("id").and_then(Value::as_str) != Some(HELLO_ID) {
        return Handshake::NotYet;
    }
    match envelope["type"].as_str() {
        Some("response") => {
            let result = envelope.get("result").cloned().unwrap_or(Value::Null);
            match result.get("protocol_version").and_then(Value::as_i64) {
                Some(PROTOCOL_VERSION) => Handshake::Ready(result),
                other => Handshake::Mismatch(format!(
                    "This window speaks protocol version {PROTOCOL_VERSION}; the Core answered \
                     with version {}.",
                    other.map_or_else(|| "none".to_string(), |v| v.to_string()))),
            }
        }
        Some("error") => {
            let error = &envelope["error"];
            if error["code"] == "unsupported_version" {
                let supported: Vec<String> = error["data"]["supported"].as_array()
                    .map(|all| all.iter().map(Value::to_string).collect())
                    .unwrap_or_default();
                Handshake::Mismatch(format!(
                    "This window speaks protocol version {PROTOCOL_VERSION}; the Core supports \
                     [{}].", supported.join(", ")))
            } else {
                Handshake::Refused(format!("The Core refused the handshake: {}",
                                           error["message"].as_str().unwrap_or("no reason given")))
            }
        }
        _ => Handshake::NotYet,
    }
}

/// Is this line a protocol v2 envelope the Core may send: a JSON object at
/// this protocol version, whose `type` is `response`, `error` or `event`,
/// carrying every field the schema requires of that type?
pub fn is_envelope(line: &str) -> bool {
    envelope(line).is_some()
}

fn envelope(line: &str) -> Option<Value> {
    let value: Value = serde_json::from_str(line).ok()?;
    let kind = value.get("type")?.as_str()?;
    if !matches!(kind, "response" | "error" | "event")
        || value.get("version").and_then(Value::as_i64) != Some(PROTOCOL_VERSION) {
        return None;
    }
    let (_, fields) = ENVELOPE_FIELDS.iter().find(|(shape, _)| *shape == kind)?;
    if !fields.iter().all(|field| value.get(*field).is_some()) {
        return None;
    }
    // The field types the page's client requires (`@comodor/protocol`'s
    // `decode`): a line it would drop is a fault here, not something relayed.
    let text = |key: &str| value[key].as_str().is_some_and(|text| !text.is_empty());
    let object = |key: &str| value[key].is_object();
    let typed = match kind {
        "response" => text("id") && object("result"),
        // An error answers its request's id, or null when the Core could
        // not read one; anything else would answer nothing.
        "error" => (value["id"].is_null() || text("id")) && value["error"]["code"].is_string(),
        _ => text("event") && value["seq"].is_number() && object("params"),
    };
    typed.then_some(value)
}

/// What the relay saw, for the restart counter (data-model.md §3). These are
/// the only fields it reads, and it changes none of them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Observation {
    /// A `session.send` the page sent was accepted with this `turn_id`.
    TurnStarted(String),
    /// `message.completed`: its `turn_id`, and whether `status` was
    /// `completed`.
    MessageCompleted { turn_id: String, completed: bool },
    /// `session.updated`: `session.busy`.
    Busy(bool),
    /// `notification.created` at level `warning` or `error`.
    Warning,
    /// The page sent `session.cancel`.
    Cancel,
}

/// One page line, relayed.
#[derive(Clone, Debug, PartialEq)]
pub enum FromPage {
    /// For the Core: the line with its id prefixed by the generation.
    ToCore { line: String, observed: Vec<Observation> },
    /// Answered here, never reaching the Core (`client.hello`).
    Answer(String),
}

/// One Core line, relayed.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct FromCore {
    /// For the page of this generation, with the page's own id restored.
    pub to_page: Option<(u64, String)>,
    pub observed: Vec<Observation>,
}

struct InFlight {
    page_id: String,
    method: String,
}

/// The relay between the current page and the Core.
#[derive(Default)]
pub struct Relay {
    handshake: Option<Value>,
    /// Every page load and every reconnect is a new generation; only the
    /// current one is live. It only grows, across every Core of the launch.
    generation: u64,
    live: bool,
    in_flight: HashMap<String, InFlight>,
    /// Every link in a line delivered to the current page: what `open_external`
    /// may open.
    links: HashSet<String>,
}

impl Relay {
    pub fn new() -> Self {
        Self::default()
    }

    /// Keep the Core's `client.hello` result for the pages that ask.
    pub fn cache_handshake(&mut self, result: Value) {
        self.handshake = Some(result);
    }

    pub fn handshake(&self) -> Option<&Value> {
        self.handshake.as_ref()
    }

    /// Was `url` among the links in lines delivered to the current page?
    pub fn displayed(&self, url: &str) -> bool {
        self.live && self.links.contains(url)
    }

    fn remember_links(&mut self, value: &Value) {
        match value {
            Value::String(text) => self.links.extend(links_in(text)),
            Value::Array(items) => items.iter().for_each(|item| self.remember_links(item)),
            Value::Object(fields) => fields.values().for_each(|item| self.remember_links(item)),
            _ => {}
        }
    }

    /// A page connects: a new generation, and nothing from an older one can
    /// reach it.
    pub fn connect(&mut self) -> u64 {
        self.generation += 1;
        self.live = true;
        self.in_flight.clear();
        self.links.clear();
        self.generation
    }

    /// The current generation, while a page is connected.
    pub fn current(&self) -> Option<u64> {
        self.live.then_some(self.generation)
    }

    /// The Core this relay served is gone: the page must reconnect, and
    /// nothing it had pending can be answered.
    pub fn core_gone(&mut self) -> Option<u64> {
        let was = self.current();
        self.live = false;
        self.handshake = None;
        self.in_flight.clear();
        self.links.clear();
        was
    }

    /// A line from the page of `generation`.
    pub fn from_page(&mut self, generation: u64, line: &str, ready: bool) -> Result<FromPage, String> {
        if self.current() != Some(generation) {
            return Err("this page's connection is no longer current".into());
        }
        let request: Value = serde_json::from_str(line)
            .map_err(|_| "the line is not a protocol request".to_string())?;
        if request.get("type").and_then(Value::as_str) != Some("request") {
            return Err("the line is not a protocol request".into());
        }
        let method = request.get("method").and_then(Value::as_str)
            .ok_or("the request names no method")?.to_string();
        if method == "shutdown" {
            return Err("stopping the Core is the native side's decision".into());
        }
        if !METHODS.contains(&method.as_str()) {
            return Err(format!("{method} is not a protocol v{PROTOCOL_VERSION} method"));
        }
        let span = id_span(line).ok_or("the request has no id")?;
        let page_id = line[span.clone()].to_string();
        if method == "client.hello" {
            let result = self.handshake.clone().ok_or("the Core is not ready")?;
            return Ok(FromPage::Answer(format!(
                r#"{{"version":{PROTOCOL_VERSION},"type":"response","id":{page_id},"result":{result}}}"#)));
        }
        if !ready {
            return Err("the Core is not ready".into());
        }
        let bare = match &request["id"] {
            Value::String(text) => text.clone(),
            other => other.to_string(),
        };
        let native = format!("g{generation}:{bare}");
        if self.in_flight.contains_key(&native) {
            return Err(format!("request id {page_id} is already waiting for an answer"));
        }
        let observed = if method == "session.cancel" { vec![Observation::Cancel] } else { vec![] };
        self.in_flight.insert(native.clone(), InFlight { page_id, method });
        let rewritten = format!("{}{}{}", &line[..span.start], Value::String(native), &line[span.end..]);
        Ok(FromPage::ToCore { line: rewritten, observed })
    }

    /// A protocol line from the Core (its own answers to the native side are
    /// handled before this).
    pub fn from_core(&mut self, line: &str) -> FromCore {
        let Ok(envelope) = serde_json::from_str::<Value>(line) else { return FromCore::default() };
        match envelope.get("type").and_then(Value::as_str) {
            Some("event") => {
                let to_page = self.current().map(|generation| (generation, line.to_string()));
                if to_page.is_some() {
                    self.remember_links(&envelope["params"]);
                }
                FromCore { to_page, observed: observe_event(&envelope) }
            }
            Some("response") | Some("error") => {
                let Some(native) = envelope.get("id").and_then(Value::as_str) else {
                    return FromCore::default();
                };
                // An answer for an older generation, or an id never sent:
                // dropped.
                let Some(waiting) = self.in_flight.remove(native) else { return FromCore::default() };
                let mut observed = vec![];
                if waiting.method == "session.send" {
                    if let Some(turn) = envelope["result"]["turn_id"].as_str() {
                        observed.push(Observation::TurnStarted(turn.to_string()));
                    }
                }
                let span = id_span(line).expect("a parsed answer with a string id has an id");
                let restored = format!("{}{}{}", &line[..span.start], waiting.page_id, &line[span.end..]);
                let to_page = self.current().map(|generation| (generation, restored));
                if to_page.is_some() {
                    self.remember_links(&envelope);
                }
                FromCore { to_page, observed }
            }
            _ => FromCore::default(),
        }
    }
}

/// The links in a text, by the rule the page's inert renderer uses too
/// (`src/text.ts`): `http://` or `https://`, up to whitespace, a quote, an
/// angle bracket or a control character, without trailing punctuation.
pub fn links_in(text: &str) -> Vec<String> {
    let mut found = Vec::new();
    let mut rest = text;
    while let Some(at) = ["http://", "https://"].iter().filter_map(|scheme| rest.find(scheme)).min() {
        let tail = &rest[at..];
        let end = tail.find(|c: char| c.is_whitespace() || c.is_control()
                                     || matches!(c, '"' | '\'' | '<' | '>'))
            .unwrap_or(tail.len());
        let link = tail[..end].trim_end_matches(['.', ',', ';', ':', '!', '?', ')', ']', '}']);
        if link.len() > link.find("://").unwrap() + 3 {
            found.push(link.to_string());
        }
        rest = &tail[end.max(1)..];
    }
    found
}

fn observe_event(envelope: &Value) -> Vec<Observation> {
    let params = &envelope["params"];
    match envelope["event"].as_str() {
        Some("message.completed") => params["turn_id"].as_str()
            .map(|turn| vec![Observation::MessageCompleted {
                turn_id: turn.to_string(),
                completed: params["status"] == "completed",
            }])
            .unwrap_or_default(),
        Some("session.updated") => params["session"]["busy"].as_bool()
            .map(|busy| vec![Observation::Busy(busy)]).unwrap_or_default(),
        Some("notification.created") => match params["level"].as_str() {
            Some("warning") | Some("error") => vec![Observation::Warning],
            _ => vec![],
        },
        _ => vec![],
    }
}

/// The byte range of the top-level `"id"` value in a JSON object, so the id
/// is the only thing ever rewritten and every other byte stays as it was.
/// Only called on text that already parsed as JSON.
fn id_span(text: &str) -> Option<Range<usize>> {
    let bytes = text.as_bytes();
    let mut at = skip_space(bytes, 0);
    if bytes.get(at) != Some(&b'{') {
        return None;
    }
    at += 1;
    loop {
        at = skip_space(bytes, at);
        if bytes.get(at) != Some(&b'"') {
            return None;
        }
        let key_end = string_end(bytes, at)?;
        let key = &text[at + 1..key_end - 1];
        at = skip_space(bytes, key_end);
        if bytes.get(at) != Some(&b':') {
            return None;
        }
        at = skip_space(bytes, at + 1);
        let value_end = value_end(bytes, at)?;
        if key == "id" {
            return Some(at..value_end);
        }
        at = skip_space(bytes, value_end);
        match bytes.get(at) {
            Some(b',') => at += 1,
            _ => return None,
        }
    }
}

fn skip_space(bytes: &[u8], mut at: usize) -> usize {
    while matches!(bytes.get(at), Some(b' ' | b'\t' | b'\n' | b'\r')) {
        at += 1;
    }
    at
}

/// Just past the closing quote of the string starting at `at`.
fn string_end(bytes: &[u8], mut at: usize) -> Option<usize> {
    at += 1;
    loop {
        match bytes.get(at)? {
            b'\\' => at += 2,
            b'"' => return Some(at + 1),
            _ => at += 1,
        }
    }
}

fn value_end(bytes: &[u8], at: usize) -> Option<usize> {
    match bytes.get(at)? {
        b'"' => string_end(bytes, at),
        b'{' | b'[' => {
            let mut depth = 0usize;
            let mut here = at;
            loop {
                match bytes.get(here)? {
                    b'"' => {
                        here = string_end(bytes, here)?;
                        continue;
                    }
                    b'{' | b'[' => depth += 1,
                    b'}' | b']' => {
                        depth -= 1;
                        if depth == 0 {
                            return Some(here + 1);
                        }
                    }
                    _ => {}
                }
                here += 1;
            }
        }
        _ => {
            let mut here = at;
            while !matches!(bytes.get(here), None | Some(b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r')) {
                here += 1;
            }
            Some(here)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn answer(version: i64) -> String {
        json!({"version": 2, "type": "response", "id": HELLO_ID,
               "result": {"protocol_version": version, "core": {"name": "c", "version": "1"},
                          "capabilities": []}}).to_string()
    }

    // -- T024 -----------------------------------------------------------------

    #[test]
    fn the_native_hello_declares_exactly_questions_and_permissions_at_version_two() {
        let hello: Value = serde_json::from_str(&hello_request()).expect("one JSON line");
        assert!(!hello_request().contains('\n'));
        assert_eq!(hello["version"], PROTOCOL_VERSION);
        assert_eq!(hello["type"], "request");
        assert_eq!(hello["id"], HELLO_ID);
        assert_eq!(hello["method"], "client.hello");
        assert_eq!(hello["params"]["protocol_version"], 2);
        assert_eq!(PROTOCOL_VERSION, 2, "D1 speaks protocol v2");
        assert_eq!(hello["params"]["capabilities"], json!(["questions", "permissions"]));
        assert_eq!(hello["params"]["client"]["name"], "comodor-desktop");
    }

    #[test]
    fn the_answer_at_version_two_is_ready_and_cached() {
        let Handshake::Ready(result) = read_handshake(&answer(2)) else { panic!("ready") };
        let mut relay = Relay::new();
        assert_eq!(relay.handshake(), None);
        relay.cache_handshake(result.clone());
        assert_eq!(relay.handshake(), Some(&result));
        assert_eq!(result["protocol_version"], 2);
    }

    #[test]
    fn another_version_is_a_mismatch_naming_both() {
        let Handshake::Mismatch(message) = read_handshake(&answer(3)) else { panic!("mismatch") };
        assert!(message.contains("version 2") && message.contains("version 3"), "{message}");
    }

    #[test]
    fn unsupported_version_names_what_the_core_supports() {
        let line = json!({"version": 2, "type": "error", "id": HELLO_ID,
                          "error": {"code": "unsupported_version", "message": "no",
                                    "data": {"supported": [3, 4]}}}).to_string();
        let Handshake::Mismatch(message) = read_handshake(&line) else { panic!("mismatch") };
        assert!(message.contains("[3, 4]") && message.contains("version 2"), "{message}");
    }

    #[test]
    fn another_refusal_is_reported_as_refused() {
        let line = json!({"version": 2, "type": "error", "id": HELLO_ID,
                          "error": {"code": "internal", "message": "boom"}}).to_string();
        assert!(matches!(read_handshake(&line), Handshake::Refused(m) if m.contains("boom")));
    }

    #[test]
    fn other_protocol_lines_are_not_the_answer_and_others_are_faults() {
        let event = json!({"version": 2, "type": "event", "event": "x", "seq": 1, "params": {}});
        assert_eq!(read_handshake(&event.to_string()), Handshake::NotYet);
        let other = json!({"version": 2, "type": "response", "id": "7", "result": {}});
        assert_eq!(read_handshake(&other.to_string()), Handshake::NotYet);
        for bad in ["", "hello", "[1,2]", "{\"type\":\"request\",\"id\":1,\"method\":\"x\"}",
                    "{\"version\":2}", "42", "{broken"] {
            assert_eq!(read_handshake(bad), Handshake::Fault, "{bad:?}");
            assert!(!is_envelope(bad), "{bad:?}");
        }
        assert!(is_envelope(&event.to_string()));
    }

    // -- T038 -----------------------------------------------------------------

    fn ready_relay() -> Relay {
        let mut relay = Relay::new();
        let Handshake::Ready(result) = read_handshake(&answer(2)) else { panic!() };
        relay.cache_handshake(result);
        relay
    }

    fn to_core(relay: &mut Relay, generation: u64, line: &str) -> String {
        match relay.from_page(generation, line, true).expect("relayed") {
            FromPage::ToCore { line, .. } => line,
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_page_id_gains_its_generation_and_the_answer_maps_back() {
        let mut relay = ready_relay();
        relay.connect();
        relay.connect();
        let generation = relay.connect();
        assert_eq!(generation, 3);
        for (page_id, native) in [("7", "g3:7"), ("\"7b\"", "g3:7b")] {
            let line = format!(r#"{{"version":2,"type":"request","id":{page_id},"method":"model.get","params":{{}}}}"#);
            let sent = to_core(&mut relay, 3, &line);
            let value: Value = serde_json::from_str(&sent).unwrap();
            assert_eq!(value["id"], native);
            let reply = format!(r#"{{"version":2,"type":"response","id":"{native}","result":{{"model":"m"}}}}"#);
            let back = relay.from_core(&reply).to_page.expect("delivered");
            assert_eq!(back, (3, format!(r#"{{"version":2,"type":"response","id":{page_id},"result":{{"model":"m"}}}}"#)));
        }
    }

    #[test]
    fn answers_for_a_stale_generation_or_an_unknown_id_are_dropped() {
        let mut relay = ready_relay();
        let old = relay.connect();
        to_core(&mut relay, old, r#"{"version":2,"type":"request","id":"1","method":"model.get","params":{}}"#);
        let new = relay.connect();
        assert!(relay.from_core(r#"{"version":2,"type":"response","id":"g1:1","result":{}}"#).to_page.is_none(),
                "a late answer to the old page never reaches the new one");
        assert!(relay.from_core(&format!(r#"{{"version":2,"type":"error","id":"g{new}:99","error":{{"code":"x","message":"y"}}}}"#)).to_page.is_none());
        assert!(relay.from_page(old, r#"{"version":2,"type":"request","id":"2","method":"model.get","params":{}}"#, true).is_err(),
                "the old page can no longer send");
    }

    #[test]
    fn a_page_hello_is_answered_from_the_cache_with_the_page_id() {
        let mut relay = ready_relay();
        let generation = relay.connect();
        let hello = r#"{"version":2,"type":"request","id":"h-1","method":"client.hello","params":{"protocol_version":2}}"#;
        let FromPage::Answer(line) = relay.from_page(generation, hello, true).unwrap() else { panic!("local") };
        let value: Value = serde_json::from_str(&line).unwrap();
        assert_eq!(value["id"], "h-1");
        assert_eq!(value["type"], "response");
        assert_eq!(value["result"], *relay.handshake().unwrap());
    }

    #[test]
    fn shutdown_a_non_v2_method_and_a_non_request_are_refused() {
        let mut relay = ready_relay();
        let generation = relay.connect();
        for line in [
            r#"{"version":2,"type":"request","id":"1","method":"shutdown","params":{}}"#,
            r#"{"version":2,"type":"request","id":"2","method":"fs.read","params":{}}"#,
            r#"{"version":2,"type":"response","id":"3","result":{}}"#,
            r#"{"version":2,"type":"event","event":"session.updated","seq":1,"params":{}}"#,
            "not json",
        ] {
            assert!(relay.from_page(generation, line, true).is_err(), "{line}");
        }
        assert!(relay.from_page(generation,
            r#"{"version":2,"type":"request","id":"4","method":"model.get","params":{}}"#, false).is_err(),
            "nothing reaches a Core that is not ready");
    }

    #[test]
    fn events_reach_the_current_generation_only_in_order() {
        let mut relay = ready_relay();
        let event = |n: u32| format!(r#"{{"version":2,"type":"event","event":"message.delta","seq":{n},"params":{{"text":"{n}"}}}}"#);
        assert!(relay.from_core(&event(1)).to_page.is_none(), "no page, no delivery");
        let generation = relay.connect();
        let delivered: Vec<String> = (2..6).map(|n| relay.from_core(&event(n)).to_page.unwrap())
            .map(|(to, line)| { assert_eq!(to, generation); line }).collect();
        assert_eq!(delivered, (2..6).map(event).collect::<Vec<_>>());
        relay.core_gone();
        assert!(relay.from_core(&event(6)).to_page.is_none());
    }

    #[test]
    fn every_envelope_is_byte_identical_except_its_id() {
        let mut relay = ready_relay();
        let generation = relay.connect();
        // Odd spacing, key order and a nested `id` that is not the envelope's.
        let request = "{ \"params\" : {\"id\":\"perm-1\",\"choice\":\"allow\"},\"method\":\"permission.reply\" , \"id\" : 12,\"type\":\"request\",\"version\":2}";
        let sent = to_core(&mut relay, generation, request);
        assert_eq!(sent, request.replace("\"id\" : 12", &format!("\"id\" : \"g{generation}:12\"")));
        let reply = format!("{{\"version\": 2,\"result\":{{\"id\":\"inner\",\"ok\":[1, {{\"id\":2}}]}}, \"type\":\"response\",\"id\":\"g{generation}:12\"}}");
        let (_, back) = relay.from_core(&reply).to_page.unwrap();
        assert_eq!(back, reply.replace(&format!("\"id\":\"g{generation}:12\""), "\"id\":12"));
        let event = "{\"type\":\"event\",  \"event\":\"tool.started\",\"seq\":3,\"params\":{\"id\":\"call-1\",\"text\":\"\\\"id\\\": x\"},\"version\":2}";
        assert_eq!(relay.from_core(event).to_page.unwrap().1, event, "events are untouched");
    }

    #[test]
    fn the_relay_reads_only_what_the_restart_counter_needs() {
        let mut relay = ready_relay();
        let generation = relay.connect();
        let send = r#"{"version":2,"type":"request","id":"5","method":"session.send","params":{"text":"hi"}}"#;
        to_core(&mut relay, generation, send);
        let accepted = relay.from_core(r#"{"version":2,"type":"response","id":"g1:5","result":{"accepted":true,"turn_id":"t9"}}"#);
        assert_eq!(accepted.observed, vec![Observation::TurnStarted("t9".into())]);
        let completed = relay.from_core(r#"{"version":2,"type":"event","event":"message.completed","seq":1,"params":{"turn_id":"t9","status":"completed"}}"#);
        assert_eq!(completed.observed, vec![Observation::MessageCompleted { turn_id: "t9".into(), completed: true }]);
        let other = relay.from_core(r#"{"version":2,"type":"event","event":"message.completed","seq":2,"params":{"turn_id":"t9","status":"cancelled"}}"#);
        assert_eq!(other.observed, vec![Observation::MessageCompleted { turn_id: "t9".into(), completed: false }]);
        let busy = relay.from_core(r#"{"version":2,"type":"event","event":"session.updated","seq":3,"params":{"session":{"busy":false}}}"#);
        assert_eq!(busy.observed, vec![Observation::Busy(false)]);
        for (level, seen) in [("warning", true), ("error", true), ("info", false)] {
            let note = format!(r#"{{"version":2,"type":"event","event":"notification.created","seq":4,"params":{{"level":"{level}"}}}}"#);
            assert_eq!(relay.from_core(&note).observed.contains(&Observation::Warning), seen, "{level}");
        }
        let cancel = r#"{"version":2,"type":"request","id":"6","method":"session.cancel","params":{}}"#;
        let FromPage::ToCore { observed, .. } = relay.from_page(generation, cancel, true).unwrap() else { panic!() };
        assert_eq!(observed, vec![Observation::Cancel]);
    }

    // -- T060 -----------------------------------------------------------------

    #[test]
    fn a_core_restart_closes_the_page_and_forgets_what_was_waiting() {
        let mut relay = ready_relay();
        let generation = relay.connect();
        to_core(&mut relay, generation, r#"{"version":2,"type":"request","id":"1","method":"model.get","params":{}}"#);
        assert_eq!(relay.core_gone(), Some(generation), "the page of this generation is told");
        assert_eq!(relay.core_gone(), None, "and only once");
        assert_eq!(relay.handshake(), None, "the old Core's handshake is gone with it");
        let next = relay.connect();
        assert!(next > generation);
        assert!(relay.from_core(&format!(
            r#"{{"version":2,"type":"response","id":"g{generation}:1","result":{{}}}}"#)).to_page.is_none(),
            "the old Core's late answer reaches nobody");
    }

    #[test]
    fn the_cached_handshake_is_the_new_cores() {
        let mut relay = ready_relay();
        relay.connect();
        relay.core_gone();
        let mut newer = serde_json::from_str::<Value>(&answer(2)).unwrap()["result"].clone();
        newer["core"]["version"] = "2".into();
        relay.cache_handshake(newer.clone());
        let generation = relay.connect();
        let FromPage::Answer(line) = relay.from_page(generation,
            r#"{"version":2,"type":"request","id":"h","method":"client.hello","params":{}}"#, true).unwrap()
            else { panic!("answered here") };
        assert_eq!(serde_json::from_str::<Value>(&line).unwrap()["result"], newer);
    }

    /// The same cases as `test/inert.test.tsx`: the page and the native side
    /// agree on what a link is.
    #[test]
    fn links_are_found_by_the_rule_the_page_uses() {
        assert_eq!(links_in("see https://example.com/docs, then javascript:alert(1)"),
                   ["https://example.com/docs"]);
        assert_eq!(links_in("<http://a.example/x>"), ["http://a.example/x"]);
        assert!(links_in("https:// alone").is_empty());
        assert_eq!(links_in("a\x1bhttps://b.example/c\x1b[2J"), ["https://b.example/c"]);
    }

    /// Review finding (PR #62): an envelope of another version, or missing a
    /// field its type requires, is not protocol v2 and is a fault (FR-007).
    #[test]
    fn only_complete_v2_envelopes_are_protocol() {
        for bad in [
            r#"{"version":3,"type":"event","event":"x","seq":1,"params":{}}"#,
            r#"{"version":"2","type":"event","event":"x","seq":1,"params":{}}"#,
            r#"{"version":2,"type":"event","event":"x","params":{}}"#,
            r#"{"version":2,"type":"event","event":"x","seq":1}"#,
            r#"{"version":2,"type":"event","seq":1,"params":{}}"#,
            r#"{"version":2,"type":"response","id":"1"}"#,
            r#"{"version":2,"type":"error","id":"1"}"#,
            r#"{"version":2,"type":"response","result":{}}"#,
            // Review finding (PR #62): present but of the wrong type, as the
            // shared client's `decode` would reject them.
            r#"{"version":2,"type":"event","event":"x","seq":"bad","params":{}}"#,
            r#"{"version":2,"type":"event","event":"x","seq":1,"params":[]}"#,
            r#"{"version":2,"type":"event","event":"","seq":1,"params":{}}"#,
            r#"{"version":2,"type":"event","event":7,"seq":1,"params":{}}"#,
            r#"{"version":2,"type":"response","id":1,"result":{}}"#,
            r#"{"version":2,"type":"response","id":"","result":{}}"#,
            r#"{"version":2,"type":"response","id":"1","result":[]}"#,
            r#"{"version":2,"type":"response","id":"1","result":null}"#,
            r#"{"version":2,"type":"error","id":"1","error":{"message":"y"}}"#,
            r#"{"version":2,"type":"error","id":"1","error":{"code":5}}"#,
            r#"{"version":2,"type":"error","id":"1","error":"x"}"#,
            // An error answers a request by its id, or by null when it could
            // not read one; anything else answers nothing.
            r#"{"version":2,"type":"error","id":7,"error":{"code":"x"}}"#,
            r#"{"version":2,"type":"error","id":"","error":{"code":"x"}}"#,
            r#"{"version":2,"type":"error","id":{},"error":{"code":"x"}}"#,
        ] {
            assert!(!is_envelope(bad), "{bad}");
        }
        for good in [
            r#"{"version":2,"type":"event","event":"x","seq":1,"params":{}}"#,
            r#"{"version":2,"type":"event","event":"x","seq":1.5,"params":{}}"#,
            r#"{"version":2,"type":"response","id":"1","result":{}}"#,
            r#"{"version":2,"type":"error","id":"1","error":{"code":"x","message":"y"}}"#,
            // An error may answer a request whose id could not be read.
            r#"{"version":2,"type":"error","id":null,"error":{"code":"parse_error"}}"#,
        ] {
            assert!(is_envelope(good), "{good}");
        }
    }

    #[test]
    fn the_method_list_comes_from_the_schema() {
        assert!(METHODS.contains(&"client.hello"));
        assert!(METHODS.contains(&"session.send"));
        assert!(METHODS.contains(&"shutdown"));
        assert!(!METHODS.contains(&"fs.read"));
    }
}

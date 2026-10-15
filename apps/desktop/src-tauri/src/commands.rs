//! Exactly the bridge's commands (contracts/native-bridge.md). Every name is
//! in `command_names::COMMANDS`; nothing else is registered.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::ipc::Channel;
use tauri::State;

use crate::instance::Confirm;
use crate::prefs::{self, Preferences, Stored};
use crate::shutdown::StopReason;
use crate::supervisor::{PageSink, State as CoreState, Status, Supervisor};
use crate::workspace::{self, Chooser, Resolution};

/// What the commands share: the supervisor, the preferences and the chooser.
pub struct Desktop {
    pub supervisor: Supervisor,
    prefs_path: PathBuf,
    /// D1's preferences and the D2 layout beside them, as the file holds them.
    preferences: Mutex<Stored>,
    chooser: Mutex<Box<dyn Chooser + Send>>,
    /// Only one chooser at a time (a workspace change in progress).
    choosing: Mutex<()>,
    /// Whether the machine has slept since the last look.
    pub wake: std::sync::Arc<crate::wake::Watch>,
    /// Only one link confirmation at a time.
    linking: Mutex<()>,
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

impl Desktop {
    pub fn new(supervisor: Supervisor, prefs_path: PathBuf, chooser: Box<dyn Chooser + Send>) -> Self {
        let preferences = prefs::load_stored(&prefs_path);
        Self { supervisor, prefs_path, preferences: Mutex::new(preferences),
               chooser: Mutex::new(chooser), choosing: Mutex::new(()),
               wake: std::sync::Arc::new(crate::wake::Watch::system()), linking: Mutex::new(()) }
    }

    /// The same, watching `wake` for the machine's sleep (tests move it by
    /// hand).
    pub fn with_wake(mut self, wake: crate::wake::Watch) -> Self {
        self.wake = std::sync::Arc::new(wake);
        self
    }

    /// One line from the page. A wake not yet noticed is noticed first,
    /// before anything reaches a Core that may not have survived the sleep:
    /// the line is then refused until the Core has answered the check.
    pub fn send_line(&self, generation: u64, line: String) -> Result<(), String> {
        if self.wake.woke() {
            self.supervisor.woke();
        }
        self.supervisor.send_line(generation, line)
    }

    pub fn preferences(&self) -> Preferences {
        lock(&self.preferences).preferences.clone()
    }

    pub fn save_preferences(&self, change: impl FnOnce(&mut Preferences)) {
        let mut stored = lock(&self.preferences);
        change(&mut stored.preferences);
        let _ = prefs::save_stored(&self.prefs_path, &stored);
    }

    /// The stored layout, or the defaults: `{layout, stored}` and nothing
    /// else from the file. Reads memory only; never writes
    /// (contracts/layout-persistence.md, `read_layout`).
    pub fn read_layout(&self) -> Value {
        let layout = lock(&self.preferences).layout;
        json!({ "layout": layout.unwrap_or_default(), "stored": layout.is_some() })
    }

    /// Validate `layout` completely before anything else; on refusal nothing
    /// is written and memory is unchanged. An accepted layout is saved with
    /// the rest of the file, under the same lock as every D1 save, and
    /// committed to memory only once the save succeeded.
    pub fn write_layout(&self, layout: &Value) -> Result<Value, String> {
        let layout = prefs::validate_layout(layout)?;
        let mut stored = lock(&self.preferences);
        let next = Stored { preferences: stored.preferences.clone(), layout: Some(layout) };
        prefs::save_stored(&self.prefs_path, &next)
            .map_err(|problem| format!("the layout could not be saved: {problem}"))?;
        *stored = next;
        Ok(json!({ "layout": layout }))
    }

    /// Decide this launch's workspace (OD-3) and start a Core there, or say
    /// that none was chosen. Runs off the main thread: the chooser blocks.
    pub fn launch(&self, command_line: Option<OsString>) {
        let _held = lock(&self.choosing);
        let resolution = {
            let mut stored = lock(&self.preferences);
            let before = stored.preferences.clone();
            let resolution = workspace::resolve_launch(command_line.as_deref(), &mut stored.preferences,
                                                       lock(&self.chooser).as_mut(),
                                                       &mut |report| self.supervisor.no_workspace(report.into()));
            if stored.preferences != before {
                let _ = prefs::save_stored(&self.prefs_path, &stored);
            }
            resolution
        };
        match resolution {
            Resolution::Chosen { path, .. } => {
                let _ = self.supervisor.start(path);
            }
            Resolution::Dismissed { notice } => self.supervisor.no_workspace(notice),
        }
    }
}

/// The page's IPC channel, as the supervisor's page sink.
struct ChannelSink(Channel<Value>);

impl PageSink for ChannelSink {
    fn send(&self, message: Value) {
        #[cfg(feature = "e2e")]
        crate::e2e::record("inbound", &message);
        let _ = self.0.send(message);
    }
}

#[cfg(feature = "e2e")]
fn recorded<T: serde::Serialize>(name: &str, args: Value, result: T) -> T {
    crate::e2e::record("command", &json!({
        "name": name, "args": args, "result": serde_json::to_value(&result).unwrap_or(Value::Null),
    }));
    result
}

#[cfg(not(feature = "e2e"))]
fn recorded<T>(_name: &str, _args: Value, result: T) -> T {
    result
}

#[tauri::command]
pub fn connect(desktop: State<'_, Desktop>, on: Channel<Value>) -> Value {
    let generation = desktop.supervisor.connect(Box::new(ChannelSink(on)));
    recorded("connect", json!({}), json!({ "generation": generation }))
}

#[tauri::command]
pub fn send_line(desktop: State<'_, Desktop>, generation: u64, line: String) -> Result<Value, String> {
    let args = json!({ "generation": generation, "line": line });
    let result = desktop.send_line(generation, line).map(|()| json!({}));
    recorded("send_line", args, result)
}

#[tauri::command]
pub fn status(desktop: State<'_, Desktop>) -> Status {
    recorded("status", json!({}), desktop.supervisor.status())
}

#[tauri::command]
pub fn diagnostics(desktop: State<'_, Desktop>) -> String {
    recorded("diagnostics", json!({}), desktop.supervisor.diagnostics())
}

#[tauri::command]
pub fn retry(desktop: State<'_, Desktop>) -> Result<Value, String> {
    recorded("retry", json!({}), desktop.supervisor.retry().map(|()| json!({})))
}

/// The person's "Quit now": the stop in progress is forced at once (OD-2).
#[tauri::command]
pub fn quit_now(desktop: State<'_, Desktop>) -> Result<Value, String> {
    recorded("quit_now", json!({}), desktop.supervisor.quit_now().map(|()| json!({})))
}

/// Opens a link the page was shown, outside the window, in the system's
/// browser — once the person has said yes to exactly that URL in a native
/// dialog. The page has no opener permission of its own, and its call is
/// never taken as proof of a click. The dialog blocks, so this runs off the
/// main thread.
#[tauri::command(async)]
pub fn open_external(app: tauri::AppHandle, desktop: State<'_, Desktop>, url: String)
                     -> Result<Value, String> {
    let args = json!({ "url": url });
    let result = match desktop.linking.try_lock() {
        Err(_) => Err("another link is waiting for the person's answer".to_string()),
        Ok(_one_at_a_time) => open_link(&url, &|candidate| desktop.supervisor.displayed(candidate),
                                        link_confirmer(&app).as_mut(), &mut |url| opener(&app, url)),
    }.map(|()| json!({}));
    recorded("open_external", args, result)
}

#[cfg(not(feature = "e2e"))]
fn link_confirmer(app: &tauri::AppHandle) -> Box<dyn ConfirmLink> {
    Box::new(SystemConfirm(app.clone()))
}

#[cfg(feature = "e2e")]
fn link_confirmer(_app: &tauri::AppHandle) -> Box<dyn ConfirmLink> {
    Box::new(ConfirmDouble)
}

#[cfg(not(feature = "e2e"))]
fn opener(app: &tauri::AppHandle, url: &str) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener().open_url(url, None::<&str>).map_err(|problem| problem.to_string())
}

/// The test build never starts a browser: it records what would open.
#[cfg(feature = "e2e")]
fn opener(_app: &tauri::AppHandle, url: &str) -> Result<(), String> {
    crate::e2e::record("opened", &json!({ "url": url }));
    Ok(())
}

/// The stored layout or the defaults (D2; contracts/layout-persistence.md).
#[tauri::command]
pub fn read_layout(desktop: State<'_, Desktop>) -> Value {
    recorded("read_layout", json!({}), desktop.read_layout())
}

/// Store a layout after validating it completely; a refusal changes nothing
/// (D2; contracts/layout-persistence.md).
#[tauri::command]
pub fn write_layout(desktop: State<'_, Desktop>, layout: Value) -> Result<Value, String> {
    let args = json!({ "layout": layout });
    let result = desktop.write_layout(&layout);
    recorded("write_layout", args, result)
}

/// Opens the chooser at the last selected folder; the chosen absolute path,
/// or `null` when the person dismissed it. Blocks on the chooser, so it runs
/// off the main thread.
#[tauri::command(async)]
pub fn choose_workspace(desktop: State<'_, Desktop>) -> Result<Option<String>, String> {
    let result = choose(&desktop);
    recorded("choose_workspace", json!({}), result)
}

fn choose(desktop: &Desktop) -> Result<Option<String>, String> {
    let Ok(_held) = desktop.choosing.try_lock() else {
        return Err("a workspace change is already in progress".into());
    };
    let chosen = {
        let mut stored = lock(&desktop.preferences);
        let chosen = workspace::choose(&mut stored.preferences, lock(&desktop.chooser).as_mut());
        if chosen.is_some() {
            let _ = prefs::save_stored(&desktop.prefs_path, &stored);
        }
        chosen
    };
    let Some(path) = chosen else { return Ok(None) };
    match desktop.supervisor.status().state {
        CoreState::Absent | CoreState::Failed | CoreState::Stopped => {
            desktop.supervisor.start(path.clone())?;
        }
        // A running Core is stopped first (10 s grace), then one starts in
        // the new folder (FR-021).
        _ => desktop.supervisor.stop(StopReason::WorkspaceChange(path.clone()))?,
    }
    Ok(Some(path.display().to_string()))
}

/// The application's chooser: the system folder chooser, through the dialog
/// plugin, used from the native side only.
pub struct SystemChooser(pub tauri::AppHandle);

impl Chooser for SystemChooser {
    fn choose(&mut self, start: Option<&Path>) -> Option<PathBuf> {
        use tauri_plugin_dialog::DialogExt;
        let mut dialog = self.0.dialog().file().set_title("Choose a workspace for Comodor");
        if let Some(start) = start {
            dialog = dialog.set_directory(start);
        }
        dialog.blocking_pick_folder()?.into_path().ok()
    }
}

/// The application's second-launch confirmation: a native dialog.
pub struct SystemConfirm(pub tauri::AppHandle);

impl Confirm for SystemConfirm {
    fn switch_workspace(&mut self, from: &Path, to: &Path) -> bool {
        use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
        self.0.dialog()
            .message(format!("Comodor is working in {}.\n\nStop it there and switch to {}?",
                             from.display(), to.display()))
            .title("Switch workspace?")
            .buttons(MessageDialogButtons::OkCancelCustom("Switch".into(), "Keep working here".into()))
            .blocking_show()
    }
}

impl ConfirmLink for SystemConfirm {
    fn open(&mut self, url: &str) -> bool {
        use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
        self.0.dialog()
            .message(format!("Open this link in your browser?\n\n{url}"))
            .title("Open link?")
            .buttons(MessageDialogButtons::OkCancelCustom("Open".into(), "Cancel".into()))
            .blocking_show()
    }
}

/// The test build's confirmation double (`e2e::confirm`).
#[cfg(feature = "e2e")]
pub struct ConfirmDouble;

#[cfg(feature = "e2e")]
impl ConfirmLink for ConfirmDouble {
    fn open(&mut self, url: &str) -> bool {
        crate::e2e::confirm(&format!("open {url}"))
    }
}

#[cfg(feature = "e2e")]
impl Confirm for ConfirmDouble {
    fn switch_workspace(&mut self, from: &Path, to: &Path) -> bool {
        crate::e2e::confirm(&format!("switch from {} to {}", from.display(), to.display()))
    }
}

/// The test build's chooser double (`e2e::choose_folder`).
#[cfg(feature = "e2e")]
pub struct ChooserDouble;

#[cfg(feature = "e2e")]
impl Chooser for ChooserDouble {
    fn choose(&mut self, start: Option<&Path>) -> Option<PathBuf> {
        crate::e2e::choose_folder(start)
    }
}

/// May `url` be opened outside the window? Only an `http` or `https` URL
/// the page of the current generation was shown (`displayed`), and never
/// anything else (contracts/native-bridge.md, `open_external`).
pub fn check_external(url: &str, displayed: &dyn Fn(&str) -> bool) -> Result<String, String> {
    let refused = || Err(format!("{url} is not a link this page was shown"));
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return refused();
    }
    // The whole URL must be exactly one link the page was shown.
    if crate::relay::links_in(url) != [url] || !displayed(url) {
        return refused();
    }
    Ok(url.to_string())
}

/// The person's answer, in a native dialog the page cannot reach, to
/// opening one exact URL outside the window.
pub trait ConfirmLink {
    fn open(&mut self, url: &str) -> bool;
}

/// `open_external`, apart from the platform: `url` must pass
/// `check_external`, and then the person must say yes to exactly it in
/// `confirm`, every time; only then is it handed to `open`.
pub fn open_link(url: &str, displayed: &dyn Fn(&str) -> bool, confirm: &mut dyn ConfirmLink,
                 open: &mut dyn FnMut(&str) -> Result<(), String>) -> Result<(), String> {
    let url = check_external(url, displayed)?;
    if !confirm.open(&url) {
        return Err(format!("{url} was not opened: the person did not confirm it"));
    }
    open(&url)
}

/// Whether "Check again" applies now: not while a Core is on its way up or
/// down, and not before there is a workspace (R11).
pub fn check_again_allowed(status: &Status) -> Result<(), String> {
    match status.state {
        CoreState::Starting | CoreState::Handshaking | CoreState::Restarting | CoreState::Stopping => {
            Err("the Core is already starting or stopping".into())
        }
        _ if status.workspace.is_none() => Err("there is no workspace yet".into()),
        _ => Ok(()),
    }
}

/// "Check again", after `comodor setup` (R11): the Core is stopped in the
/// orderly way and started again in the same workspace, so it reads the
/// configuration afresh. No application restart.
#[tauri::command]
pub fn check_again(desktop: State<'_, Desktop>) -> Result<Value, String> {
    let result = check_again_allowed(&desktop.supervisor.status())
        .and_then(|()| desktop.supervisor.stop(StopReason::CheckAgain))
        .map(|()| json!({}));
    recorded("check_again", json!({}), result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::command_names::COMMANDS;
    use crate::relay::Relay;
    use serde_json::Value;
    use std::collections::BTreeSet;

    /// The eleven of specs/004-workbench-shell/contracts/native-operations.md
    /// (D1's nine and D2's two layout operations), written out here on
    /// purpose: the constant is checked against the contract, not against
    /// itself.
    const CONTRACT: [&str; 11] = ["connect", "send_line", "status", "diagnostics",
                                  "choose_workspace", "retry", "check_again", "quit_now",
                                  "open_external", "read_layout", "write_layout"];

    fn json(text: &str) -> Value {
        serde_json::from_str(text).expect("JSON")
    }

    // -- T051 -----------------------------------------------------------------

    #[test]
    fn the_command_constant_names_nothing_outside_the_contract() {
        for name in COMMANDS {
            assert!(CONTRACT.contains(&name), "{name} is not in the contract (SC-011)");
        }
        let unique: BTreeSet<&str> = COMMANDS.iter().copied().collect();
        assert_eq!(unique.len(), COMMANDS.len(), "no name twice");
    }

    // -- T084 -----------------------------------------------------------------

    #[test]
    fn the_command_constant_is_exactly_the_contract() {
        let constant: BTreeSet<&str> = COMMANDS.iter().copied().collect();
        let contract: BTreeSet<&str> = CONTRACT.iter().copied().collect();
        assert_eq!(constant, contract, "FR-030, SC-011");
        assert_eq!(COMMANDS.len(), CONTRACT.len());
    }

    #[test]
    fn every_command_has_a_registered_handler_in_the_release_build() {
        let source = include_str!("lib.rs");
        let release = &source[source.find("#[cfg(not(feature = \"e2e\"))]\n    return tauri::generate_handler![")
            .expect("the release handler list")..];
        let release = &release[release.find("generate_handler![").unwrap() + "generate_handler![".len()..];
        let list = &release[..release.find(']').unwrap()];
        let registered: BTreeSet<&str> = list.split(',').map(str::trim).filter(|e| !e.is_empty())
            .map(|entry| entry.strip_prefix("commands::")
                .unwrap_or_else(|| panic!("{entry} is not a bridge command")))
            .collect();
        let constant: BTreeSet<&str> = COMMANDS.iter().copied().collect();
        assert_eq!(registered, constant);
    }

    #[test]
    fn every_registered_handler_comes_from_the_constant() {
        let source = include_str!("lib.rs");
        let start = source.find("fn handlers()").expect("the handler list");
        let body = &source[start..source[start..].find("\n}\n").map(|end| start + end).unwrap()];
        let mut registered = BTreeSet::new();
        for part in body.split("generate_handler![").skip(1) {
            let list = &part[..part.find(']').unwrap()];
            for entry in list.split(',').map(str::trim).filter(|e| !e.is_empty()) {
                registered.insert(entry.to_string());
            }
        }
        assert!(!registered.is_empty());
        for entry in &registered {
            let name = entry.rsplit("::").next().unwrap();
            if name == crate::command_names::E2E_COMMAND {
                assert_eq!(entry, "e2e::e2e_report", "the test command comes from the e2e module");
                continue;
            }
            assert!(COMMANDS.contains(&name), "{entry} is registered but not in COMMANDS");
        }
        // The test command is registered only in the test build's list.
        let release = &body[body.find("#[cfg(not(feature = \"e2e\"))]").expect("release list")..];
        assert!(!release.contains("e2e_report"), "the release list registers no test command");
    }

    #[test]
    fn the_generated_manifest_has_exactly_the_constants_permissions() {
        let acl = json(include_str!(concat!(env!("OUT_DIR"), "/acl-manifests.json")));
        let app = &acl["__app-acl__"];
        let permissions: BTreeSet<String> = app["permissions"].as_object().expect("app permissions")
            .keys().cloned().collect();
        let mut expected = BTreeSet::new();
        for name in COMMANDS.iter().copied()
            .chain(cfg!(feature = "e2e").then_some(crate::command_names::E2E_COMMAND)) {
            let id = name.replace('_', "-");
            expected.insert(format!("allow-{id}"));
            expected.insert(format!("deny-{id}"));
        }
        assert_eq!(permissions, expected);
        if !cfg!(feature = "e2e") {
            assert!(permissions.iter().all(|p| !p.contains("e2e")), "{permissions:?}");
        }
    }

    #[test]
    fn the_main_capability_grants_only_the_commands() {
        let capability = json(include_str!("../capabilities/main.json"));
        assert_eq!(capability["windows"], serde_json::json!(["main"]));
        let granted: BTreeSet<String> = capability["permissions"].as_array().unwrap().iter()
            .map(|p| p.as_str().expect("a plain identifier").to_string()).collect();
        let expected: BTreeSet<String> = COMMANDS.iter()
            .map(|name| format!("allow-{}", name.replace('_', "-"))).collect();
        assert_eq!(granted, expected, "no plugin permission and no core: permission (T003 (e))");
        assert!(granted.iter().all(|p| !p.contains(':') && !p.contains("e2e")));
        let generated = json(include_str!(concat!(env!("OUT_DIR"), "/capabilities.json")));
        let names: Vec<&String> = generated.as_object().unwrap().keys().collect();
        if !cfg!(feature = "e2e") {
            assert_eq!(names, vec!["main"], "only the main capability in a release build");
        }
    }

    #[test]
    fn the_configuration_keeps_the_csp_and_devtools_off() {
        let config = json(include_str!("../tauri.conf.json"));
        let security = &config["app"]["security"];
        assert_eq!(security["capabilities"], serde_json::json!(["main"]));
        assert_eq!(security["freezePrototype"], true);
        assert_eq!(security["csp"], serde_json::json!({
            "default-src": "'self'", "script-src": "'self'", "style-src": "'self'",
            "img-src": "'self'", "font-src": "'self'",
            "connect-src": "ipc: http://ipc.localhost",
            "object-src": "'none'", "base-uri": "'none'", "form-action": "'none'",
            "frame-src": "'none'",
        }));
        assert_eq!(config["app"]["withGlobalTauri"], false);
        for window in config["app"]["windows"].as_array().unwrap() {
            assert_eq!(window["devtools"], false);
        }
    }

    // -- T080 -----------------------------------------------------------------

    use crate::shutdown::StopReason;
    use crate::supervisor::{Effect, Input, Machine, State as CoreState};

    fn status_in(state: CoreState, workspace: Option<&str>) -> Status {
        let mut status = Machine::new().status();
        status.state = state;
        status.workspace = workspace.map(str::to_string);
        status
    }

    #[test]
    fn check_again_is_refused_while_a_core_is_on_its_way_up_or_down() {
        for state in [CoreState::Starting, CoreState::Handshaking, CoreState::Restarting, CoreState::Stopping] {
            assert!(check_again_allowed(&status_in(state, Some("/w"))).is_err(), "{state:?}");
        }
        assert!(check_again_allowed(&status_in(CoreState::Absent, None)).is_err(), "no workspace yet");
        for state in [CoreState::Ready, CoreState::Failed] {
            assert_eq!(check_again_allowed(&status_in(state, Some("/w"))), Ok(()), "{state:?}");
        }
    }

    #[test]
    fn check_again_stops_the_core_then_starts_one_in_the_same_workspace() {
        let mut machine = Machine::new();
        let effects = machine.handle(Input::Start { workspace: "/w".into() }).unwrap();
        let core = effects.iter().find_map(|e| match e { Effect::Spawn { core, .. } => Some(*core), _ => None }).unwrap();
        machine.handle(Input::Spawned { core, pid: 1 }).unwrap();
        machine.handle(Input::Line { core, line: serde_json::json!({"version": 2, "type": "response",
            "id": crate::relay::HELLO_ID, "result": {"protocol_version": 2, "core": {"name": "c", "version": "1"},
            "capabilities": []}}).to_string() }).unwrap();
        let stop = machine.handle(Input::Stop { reason: StopReason::CheckAgain }).unwrap();
        assert!(stop.contains(&Effect::Deadline { core, after: crate::shutdown::GRACE }), "{stop:?}");
        let after = machine.handle(Input::Exited { core, code: Some(0) }).unwrap();
        let next = after.iter().find_map(|e| match e { Effect::Spawn { workspace, .. } => Some(workspace.clone()), _ => None });
        assert_eq!(next, Some("/w".into()), "{after:?}");
        assert!(!after.contains(&Effect::Finished), "the application stays");
        assert_eq!(machine.status().restart_count, 0, "an orderly restart is not a crash");
    }

    // -- T052 -----------------------------------------------------------------

    fn shown(lines: &[&str]) -> Relay {
        let mut relay = Relay::new();
        relay.connect();
        for text in lines {
            let line = serde_json::json!({"version": 2, "type": "event", "event": "message.delta",
                                          "seq": 1, "params": {"text": text}}).to_string();
            relay.from_core(&line);
        }
        relay
    }

    #[test]
    fn a_displayed_http_or_https_link_is_opened() {
        let relay = shown(&["See https://example.com/docs, and http://example.org/a?b=1&c=2."]);
        let displayed = |url: &str| relay.displayed(url);
        assert_eq!(check_external("https://example.com/docs", &displayed),
                   Ok("https://example.com/docs".to_string()));
        assert_eq!(check_external("http://example.org/a?b=1&c=2", &displayed),
                   Ok("http://example.org/a?b=1&c=2".to_string()));
    }

    #[test]
    fn another_scheme_or_a_link_never_displayed_is_refused() {
        let relay = shown(&["file:///etc/passwd javascript:alert(1) https://shown.example/x"]);
        let displayed = |url: &str| relay.displayed(url);
        for refused in ["file:///etc/passwd", "javascript:alert(1)", "https://not-shown.example/",
                        "ftp://shown.example/x", "HTTPS://shown.example/x ", "", "https://"] {
            assert!(check_external(refused, &displayed).is_err(), "{refused:?}");
        }
    }

    /// What a person answered, and what was opened.
    struct Person {
        answer: bool,
        asked: Vec<String>,
    }

    impl ConfirmLink for Person {
        fn open(&mut self, url: &str) -> bool {
            self.asked.push(url.to_string());
            self.answer
        }
    }

    fn try_open(relay: &Relay, person: &mut Person, url: &str) -> (Result<(), String>, Vec<String>) {
        let mut opened = vec![];
        let result = open_link(url, &|candidate| relay.displayed(candidate), person,
                               &mut |url| { opened.push(url.to_string()); Ok(()) });
        (result, opened)
    }

    /// Review finding (PR #62): a link the page asks to open is opened only
    /// once the person has said yes to exactly that URL, natively.
    #[test]
    fn a_link_opens_only_after_the_person_says_yes_to_it() {
        let relay = shown(&["See https://example.com/docs."]);
        let mut person = Person { answer: true, asked: vec![] };
        let (result, opened) = try_open(&relay, &mut person, "https://example.com/docs");
        assert_eq!(result, Ok(()));
        assert_eq!(person.asked, ["https://example.com/docs"]);
        assert_eq!(opened, ["https://example.com/docs"]);
    }

    #[test]
    fn a_link_the_person_declines_is_not_opened() {
        let relay = shown(&["See https://example.com/docs."]);
        let mut person = Person { answer: false, asked: vec![] };
        let (result, opened) = try_open(&relay, &mut person, "https://example.com/docs");
        assert!(result.is_err());
        assert_eq!(person.asked, ["https://example.com/docs"]);
        assert!(opened.is_empty());
    }

    /// The page's call proves nothing about a click: each call is put to the
    /// person again, and a yes is never remembered for the next one.
    #[test]
    fn every_call_from_the_page_is_put_to_the_person() {
        let relay = shown(&["https://example.com/a"]);
        let mut person = Person { answer: true, asked: vec![] };
        try_open(&relay, &mut person, "https://example.com/a").0.unwrap();
        person.answer = false;
        let (result, opened) = try_open(&relay, &mut person, "https://example.com/a");
        assert!(result.is_err());
        assert!(opened.is_empty());
        assert_eq!(person.asked.len(), 2);
    }

    /// A URL that was only in a field the window never shows as a link
    /// (here, inside an event's metadata) authorizes nothing by being
    /// relayed: without the person's yes nothing opens.
    #[test]
    fn a_url_in_a_field_never_shown_as_a_link_opens_nothing_on_its_own() {
        let mut relay = Relay::new();
        relay.connect();
        relay.from_core(&serde_json::json!({"version": 2, "type": "event", "event": "session.updated",
            "seq": 1, "params": {"session": {"id": "s1", "meta": {"x": "https://hidden.example/run"}}}})
            .to_string());
        let mut person = Person { answer: false, asked: vec![] };
        let (result, opened) = try_open(&relay, &mut person, "https://hidden.example/run");
        assert!(result.is_err());
        assert!(opened.is_empty(), "never opened without the person's yes");
    }

    /// An older page's links are refused before anyone is asked.
    #[test]
    fn a_link_from_an_older_generation_is_refused_without_asking() {
        let mut relay = shown(&["https://old.example/page"]);
        relay.connect();
        let mut person = Person { answer: true, asked: vec![] };
        let (result, opened) = try_open(&relay, &mut person, "https://old.example/page");
        assert!(result.is_err());
        assert!(person.asked.is_empty() && opened.is_empty());
    }

    #[test]
    fn links_from_an_older_generation_are_forgotten() {
        let mut relay = shown(&["https://old.example/page"]);
        relay.connect();
        assert!(check_external("https://old.example/page", &|url| relay.displayed(url)).is_err());
    }
}

/// D2: `read_layout` and `write_layout` (contracts/layout-persistence.md).
#[cfg(test)]
mod layout_command_tests {
    use super::*;
    use crate::supervisor::{Failure, FailureClass, Options};
    use serde_json::json;

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("comodor-layout-cmd-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
        fn file(&self) -> PathBuf {
            prefs::path_in(&self.0)
        }
        fn entries(&self) -> Vec<std::ffi::OsString> {
            let mut names: Vec<_> = std::fs::read_dir(&self.0).unwrap()
                .map(|entry| entry.unwrap().file_name()).collect();
            names.sort();
            names
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// Answers the chooser with one folder.
    struct Answer(Option<PathBuf>);

    impl Chooser for Answer {
        fn choose(&mut self, _start: Option<&Path>) -> Option<PathBuf> {
            self.0.clone()
        }
    }

    /// A desktop over `file` whose Core can never be found: nothing here
    /// needs one, and a start fails at once instead of running anything.
    fn desktop_at(file: PathBuf, chooser: Option<PathBuf>) -> Desktop {
        let supervisor = Supervisor::launch(Options {
            locate: Box::new(|| Err(Failure::new(FailureClass::NotFound, "no Core in this test"))),
            test_env: vec![],
            log: None,
            on_finished: None,
        });
        Desktop::new(supervisor, file, Box::new(Answer(chooser)))
    }

    fn valid() -> Value {
        json!({"version": 1, "panel_open": true, "panel_surface": "shortcuts", "panel_width": 480})
    }

    /// Bytes any save would change: compact, an unknown top-level field D1
    /// never writes back, a stored layout, and a trailing newline. A save of
    /// any kind, even of the same values, therefore shows in the bytes.
    const SEEDED: &str = concat!(
        r#"{"version":1,"window":{"width":900,"height":700,"x":5,"y":6,"maximized":false},"#,
        r#""last_selected_folder":"/work/kept","token":"not-written-back","#,
        r#""layout":{"version":1,"panel_open":false,"panel_surface":"diagnostics","panel_width":300}}"#,
        "\n");

    fn seeded(label: &str) -> (Dir, Desktop) {
        let dir = Dir::new(label);
        std::fs::write(dir.file(), SEEDED).unwrap();
        let desktop = desktop_at(dir.file(), None);
        (dir, desktop)
    }

    fn refused_cases() -> Vec<(&'static str, Value)> {
        let mut over = valid();
        over["pad"] = json!("x".repeat(1100));
        let mut unknown = valid();
        unknown["token"] = json!("x");
        let mut missing = valid();
        missing.as_object_mut().unwrap().remove("panel_surface");
        let set = |field: &str, value: Value| {
            let mut layout = valid();
            layout[field] = value;
            layout
        };
        vec![
            ("unknown field", unknown),
            ("wrong type", set("panel_open", json!("yes"))),
            ("out-of-range width", set("panel_width", json!(961))),
            ("unknown surface", set("panel_surface", json!("terminal"))),
            ("another version", set("version", json!(2))),
            ("over 1 KiB", over),
            ("not an object", json!(["layout"])),
            ("missing field", missing),
        ]
    }

    // -- SC-017: a refused write leaves the whole file byte-identical ----------

    #[test]
    fn every_refused_write_leaves_the_file_byte_identical() {
        let (dir, desktop) = seeded("refused");
        let before_read = desktop.read_layout();
        for (case, layout) in refused_cases() {
            let reason = desktop.write_layout(&layout).expect_err(case);
            assert!(!reason.is_empty(), "{case}: a reason");
            assert_eq!(std::fs::read(dir.file()).unwrap(), SEEDED.as_bytes(), "{case}: the file's bytes");
            assert_eq!(dir.entries(), vec![std::ffi::OsString::from(prefs::FILE_NAME)],
                       "{case}: no temporary file");
            assert_eq!(desktop.read_layout(), before_read, "{case}: the stored layout in memory");
            assert_eq!(desktop.preferences(), prefs::load(&dir.file()), "{case}: D1's values in memory");
        }
    }

    #[test]
    fn an_accepted_write_is_stored_and_returned_exactly() {
        let (dir, desktop) = seeded("accepted");
        assert_eq!(desktop.write_layout(&valid()), Ok(json!({"layout": valid()})));
        let stored = prefs::load_stored(&dir.file());
        assert_eq!(serde_json::to_value(stored.layout).unwrap(), valid());
        assert_eq!(stored.preferences, prefs::load(&dir.file()), "D1's values are kept");
        assert_eq!(stored.preferences.last_selected_folder.as_deref(), Some(Path::new("/work/kept")));
        assert_eq!(desktop.read_layout(), json!({"layout": valid(), "stored": true}));
        assert_eq!(dir.entries(), vec![std::ffi::OsString::from(prefs::FILE_NAME)]);
    }

    #[test]
    fn a_failed_save_reports_and_keeps_the_layout_in_memory() {
        let dir = Dir::new("failed-save");
        // The preferences path is a folder: the rename onto it fails.
        std::fs::create_dir_all(dir.file()).unwrap();
        let desktop = desktop_at(dir.file(), None);
        let before = desktop.read_layout();
        assert!(desktop.write_layout(&valid()).is_err(), "the failure is reported");
        assert_eq!(desktop.read_layout(), before, "memory keeps its previous layout");
    }

    #[test]
    fn a_d1_save_after_an_accepted_write_keeps_the_layout() {
        let dir = Dir::new("d1-saves");
        let chosen = dir.0.join("chosen");
        std::fs::create_dir_all(&chosen).unwrap();
        let desktop = desktop_at(dir.file(), Some(chosen.clone()));
        desktop.write_layout(&valid()).unwrap();

        // The geometry, as `remember_geometry` saves it on close.
        desktop.save_preferences(|preferences| {
            preferences.window = Some(prefs::WindowGeometry { width: 1, height: 2, x: 3, y: 4, maximized: true });
        });
        assert_eq!(serde_json::to_value(prefs::load_stored(&dir.file()).layout).unwrap(), valid(), "geometry");

        // The launch, choosing a folder.
        desktop.launch(None);
        let stored = prefs::load_stored(&dir.file());
        assert_eq!(stored.preferences.last_selected_folder.as_deref(), Some(chosen.as_path()));
        assert_eq!(serde_json::to_value(stored.layout).unwrap(), valid(), "launch");

        // "Change workspace…".
        std::fs::write(dir.file(), "{}").unwrap();
        let again = desktop_at(dir.file(), Some(chosen.clone()));
        again.write_layout(&valid()).unwrap();
        assert!(choose(&again).is_ok());
        assert_eq!(serde_json::to_value(prefs::load_stored(&dir.file()).layout).unwrap(), valid(), "choose");
    }

    #[test]
    fn read_layout_returns_the_defaults_and_never_writes() {
        let dir = Dir::new("read-only");
        let desktop = desktop_at(dir.file(), None);
        let read = desktop.read_layout();
        assert_eq!(read, json!({"layout": {"version": 1, "panel_open": false, "panel_surface": "core",
                                           "panel_width": 320}, "stored": false}));
        assert_eq!(read.as_object().unwrap().len(), 2, "exactly `layout` and `stored`");
        assert_eq!(read["layout"].as_object().unwrap().len(), 4, "exactly the four fields");
        assert!(!dir.file().exists(), "an absent file stays absent");
        assert!(dir.entries().is_empty());
    }

    #[test]
    fn read_layout_exposes_nothing_else_from_the_file() {
        let (_dir, desktop) = seeded("nothing-else");
        let read = desktop.read_layout();
        let text = read.to_string();
        for private in ["/work/kept", "not-written-back", "\"window\"", "maximized"] {
            assert!(!text.contains(private), "{private} in {text}");
        }
        assert_eq!(read["stored"], true);
        assert_eq!(read["layout"]["panel_surface"], "diagnostics");
    }
}

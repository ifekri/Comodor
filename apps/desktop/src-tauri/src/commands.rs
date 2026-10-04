//! Exactly the bridge's commands (contracts/native-bridge.md). Every name is
//! in `command_names::COMMANDS`; nothing else is registered.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::ipc::Channel;
use tauri::State;

use crate::instance::Confirm;
use crate::prefs::{self, Preferences};
use crate::shutdown::StopReason;
use crate::supervisor::{PageSink, State as CoreState, Status, Supervisor};
use crate::workspace::{self, Chooser, Resolution};

/// What the commands share: the supervisor, the preferences and the chooser.
pub struct Desktop {
    pub supervisor: Supervisor,
    prefs_path: PathBuf,
    preferences: Mutex<Preferences>,
    chooser: Mutex<Box<dyn Chooser + Send>>,
    /// Only one chooser at a time (a workspace change in progress).
    choosing: Mutex<()>,
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

impl Desktop {
    pub fn new(supervisor: Supervisor, prefs_path: PathBuf, chooser: Box<dyn Chooser + Send>) -> Self {
        let preferences = prefs::load(&prefs_path);
        Self { supervisor, prefs_path, preferences: Mutex::new(preferences),
               chooser: Mutex::new(chooser), choosing: Mutex::new(()) }
    }

    pub fn preferences(&self) -> Preferences {
        lock(&self.preferences).clone()
    }

    pub fn save_preferences(&self, change: impl FnOnce(&mut Preferences)) {
        let mut preferences = lock(&self.preferences);
        change(&mut preferences);
        let _ = prefs::save(&self.prefs_path, &preferences);
    }

    /// Decide this launch's workspace (OD-3) and start a Core there, or say
    /// that none was chosen. Runs off the main thread: the chooser blocks.
    pub fn launch(&self, command_line: Option<OsString>) {
        let _held = lock(&self.choosing);
        let resolution = {
            let mut preferences = lock(&self.preferences);
            let before = preferences.clone();
            let resolution = workspace::resolve_launch(command_line.as_deref(), &mut preferences,
                                                       lock(&self.chooser).as_mut());
            if *preferences != before {
                let _ = prefs::save(&self.prefs_path, &preferences);
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
    let result = desktop.supervisor.send_line(generation, line).map(|()| json!({}));
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
/// browser. The page has no opener permission of its own.
#[tauri::command]
pub fn open_external(app: tauri::AppHandle, desktop: State<'_, Desktop>, url: String)
                     -> Result<Value, String> {
    let args = json!({ "url": url });
    let result = check_external(&url, &|candidate| desktop.supervisor.displayed(candidate))
        .and_then(|url| {
            use tauri_plugin_opener::OpenerExt;
            app.opener().open_url(url, None::<&str>).map_err(|problem| problem.to_string())
        })
        .map(|()| json!({}));
    recorded("open_external", args, result)
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
        let mut preferences = lock(&desktop.preferences);
        let chosen = workspace::choose(&mut preferences, lock(&desktop.chooser).as_mut());
        if chosen.is_some() {
            let _ = prefs::save(&desktop.prefs_path, &preferences);
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

/// The test build's confirmation double (`e2e::confirm`).
#[cfg(feature = "e2e")]
pub struct ConfirmDouble;

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

    /// The nine of contracts/native-bridge.md, written out here on purpose:
    /// the constant is checked against the contract, not against itself.
    const CONTRACT: [&str; 9] = ["connect", "send_line", "status", "diagnostics",
                                 "choose_workspace", "retry", "check_again", "quit_now",
                                 "open_external"];

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

    #[test]
    fn links_from_an_older_generation_are_forgotten() {
        let mut relay = shown(&["https://old.example/page"]);
        relay.connect();
        assert!(check_external("https://old.example/page", &|url| relay.displayed(url)).is_err());
    }
}

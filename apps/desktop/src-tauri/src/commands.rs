//! Exactly the bridge's commands (contracts/native-bridge.md). Every name is
//! in `command_names::COMMANDS`; nothing else is registered.

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::ipc::Channel;
use tauri::State;

use crate::prefs::{self, Preferences};
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
        _ => return Err("changing the workspace of a running Core is not available yet".into()),
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

/// The test build's chooser double (`e2e::choose_folder`).
#[cfg(feature = "e2e")]
pub struct ChooserDouble;

#[cfg(feature = "e2e")]
impl Chooser for ChooserDouble {
    fn choose(&mut self, start: Option<&Path>) -> Option<PathBuf> {
        crate::e2e::choose_folder(start)
    }
}

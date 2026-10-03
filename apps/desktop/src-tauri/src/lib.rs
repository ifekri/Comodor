//! Comodor desktop (D1): the native side.
//!
//! It owns one Comodor Core per window, speaks protocol v2 to it over the
//! Core's own standard streams, and relays protocol lines to the window's
//! content over in-process IPC. The Core stays the only authority: nothing
//! here decides what a mode permits or whether a tool may run.

pub mod command_names;
#[cfg(feature = "e2e")]
pub mod e2e;
pub mod platform;

use tauri::WebviewWindowBuilder;

/// The one window's label, as `tauri.conf.json` and the `main` capability
/// name it.
pub const MAIN_WINDOW: &str = "main";

/// Start the application.
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|_app, _args, _cwd| {}))
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(handlers())
        .setup(|app| {
            create_main_window(app.handle())?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("the Comodor desktop application failed to start");
}

/// The registered commands: only names from `COMMANDS`, plus `e2e_report`
/// in the test build (contracts/native-bridge.md §One source for the command
/// list).
fn handlers() -> impl Fn(tauri::ipc::Invoke) -> bool + Send + Sync + 'static {
    #[cfg(feature = "e2e")]
    return tauri::generate_handler![e2e::e2e_report];
    #[cfg(not(feature = "e2e"))]
    return tauri::generate_handler![];
}

/// The window is created here rather than from the configuration, so the
/// test build can hand the page its scenario before any script runs.
fn create_main_window(app: &tauri::AppHandle) -> tauri::Result<()> {
    let config = app.config().app.windows.iter()
        .find(|window| window.label == MAIN_WINDOW)
        .cloned()
        .expect("tauri.conf.json declares the main window");
    let builder = WebviewWindowBuilder::from_config(app, &config)?;
    #[cfg(feature = "e2e")]
    let builder = builder.initialization_script(e2e::init_script());
    builder.build()?;
    Ok(())
}

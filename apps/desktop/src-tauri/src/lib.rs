//! Comodor desktop (D1): the native side.
//!
//! It owns one Comodor Core per window, speaks protocol v2 to it over the
//! Core's own standard streams, and relays protocol lines to the window's
//! content over in-process IPC. The Core stays the only authority: nothing
//! here decides what a mode permits or whether a tool may run.

pub mod command_names;
pub mod commands;
pub mod diag;
#[cfg(feature = "e2e")]
pub mod e2e;
pub mod locate;
pub mod platform;
pub mod prefs;
pub mod relay;
pub mod supervisor;
pub mod workspace;

use std::ffi::OsString;
use std::path::PathBuf;

use tauri::{Manager, WebviewWindowBuilder};

use commands::Desktop;
use supervisor::{Options, Supervisor};

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
            let handle = app.handle().clone();
            let desktop = Desktop::new(
                Supervisor::launch(Options {
                    locate: Box::new(locate::locate_from_environment),
                    test_env: vec![],
                }),
                prefs::path_in(&data_dir(&handle)?),
                chooser(&handle),
            );
            app.manage(desktop);
            create_main_window(&handle)?;
            let launching = handle.clone();
            std::thread::Builder::new().name("launch-workspace".into()).spawn(move || {
                launching.state::<Desktop>().launch(command_line_workspace());
            })?;
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
    return tauri::generate_handler![
        commands::connect,
        commands::send_line,
        commands::status,
        commands::diagnostics,
        commands::choose_workspace,
        commands::retry,
        e2e::e2e_report
    ];
    #[cfg(not(feature = "e2e"))]
    return tauri::generate_handler![
        commands::connect,
        commands::send_line,
        commands::status,
        commands::diagnostics,
        commands::choose_workspace,
        commands::retry
    ];
}

/// The first argument that is not an option: an explicit workspace (OD-3).
fn command_line_workspace() -> Option<OsString> {
    std::env::args_os().skip(1).find(|arg| !arg.to_string_lossy().starts_with('-'))
}

/// The application's own per-user configuration directory. The test build
/// may be pointed elsewhere, so a scenario never touches a real profile.
fn data_dir(app: &tauri::AppHandle) -> tauri::Result<PathBuf> {
    #[cfg(feature = "e2e")]
    if let Some(dir) = std::env::var_os("COMODOR_DESKTOP_DATA_DIR") {
        return Ok(PathBuf::from(dir));
    }
    app.path().app_config_dir()
}

fn chooser(app: &tauri::AppHandle) -> Box<dyn workspace::Chooser + Send> {
    #[cfg(feature = "e2e")]
    {
        let _ = app;
        Box::new(commands::ChooserDouble)
    }
    #[cfg(not(feature = "e2e"))]
    Box::new(commands::SystemChooser(app.clone()))
}

/// The window is created here rather than from the configuration, so the
/// test build can hand the page its scenario before any script runs, and the
/// stored geometry is applied before it is shown.
fn create_main_window(app: &tauri::AppHandle) -> tauri::Result<()> {
    let config = app.config().app.windows.iter()
        .find(|window| window.label == MAIN_WINDOW)
        .cloned()
        .expect("tauri.conf.json declares the main window");
    let mut builder = WebviewWindowBuilder::from_config(app, &config)?;
    if let Some(geometry) = app.state::<Desktop>().preferences().window {
        builder = builder
            .inner_size(f64::from(geometry.width), f64::from(geometry.height))
            .position(f64::from(geometry.x), f64::from(geometry.y))
            .maximized(geometry.maximized);
    }
    #[cfg(feature = "e2e")]
    let builder = builder.initialization_script(e2e::init_script());
    let window = builder.build()?;
    let saving = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { .. } = event {
            remember_geometry(&saving);
        }
    });
    Ok(())
}

fn remember_geometry(app: &tauri::AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else { return };
    let scale = window.scale_factor().unwrap_or(1.0);
    let (Ok(size), Ok(position)) = (window.inner_size(), window.outer_position()) else { return };
    let size = size.to_logical::<f64>(scale);
    let position = position.to_logical::<f64>(scale);
    let maximized = window.is_maximized().unwrap_or(false);
    app.state::<Desktop>().save_preferences(|preferences| {
        preferences.window = Some(prefs::WindowGeometry {
            width: size.width.round() as u32,
            height: size.height.round() as u32,
            x: position.x.round() as i32,
            y: position.y.round() as i32,
            maximized,
        });
    });
}

//! Comodor desktop (D1): the native side.
//!
//! It owns one Comodor Core per window, speaks protocol v2 to it over the
//! Core's own standard streams, and relays protocol lines to the window's
//! content over in-process IPC. The Core stays the only authority: nothing
//! here decides what a mode permits or whether a tool may run.

pub mod command_names;
pub mod commands;
pub mod diag;
pub mod instance;
#[cfg(feature = "e2e")]
pub mod e2e;
pub mod locate;
pub mod logfile;
pub mod platform;
pub mod prefs;
pub mod relay;
pub mod restart;
pub mod shutdown;
pub mod supervisor;
pub mod workspace;

use std::ffi::OsString;
use std::path::PathBuf;

use tauri::{Manager, WebviewWindowBuilder};

use commands::Desktop;
use shutdown::StopReason;
use supervisor::{Options, State, Supervisor};

/// The one window's label, as `tauri.conf.json` and the `main` capability
/// name it.
pub const MAIN_WINDOW: &str = "main";

/// Start the application.
pub fn run() {
    let app = tauri::Builder::default()
        // A second launch reaches this one instead of starting another Core.
        .plugin(tauri_plugin_single_instance::init(second_launch))
        .plugin(tauri_plugin_dialog::init())
        // Used from the native side only: no capability grants the page any
        // opener permission, so `open_external` is the one way to a browser.
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(handlers())
        .setup(|app| {
            let handle = app.handle().clone();
            let data = data_dir(&handle)?;
            let finishing = handle.clone();
            let desktop = Desktop::new(
                Supervisor::launch(Options {
                    locate: Box::new(locate::locate_from_environment),
                    test_env: vec![],
                    log: Some(std::sync::Arc::new(logfile::Log::in_dir(&data))),
                    // The Core has stopped for a reason that ends the
                    // application: now it may.
                    on_finished: Some(Box::new(move || finishing.exit(0))),
                }),
                prefs::path_in(&data),
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
        .build(tauri::generate_context!())
        .expect("the Comodor desktop application failed to start");
    app.run(|app, event| {
        // A request to end the application that did not come from the stop
        // sequence (a menu's Quit, the system) becomes one: the Core is
        // stopped first, and the application ends when it has.
        if let tauri::RunEvent::ExitRequested { code: None, api, .. } = event {
            if stop_first(app, StopReason::Quit) {
                api.prevent_exit();
            }
        }
    });
}

/// Begin the stop sequence unless the Core has already stopped. True when
/// the caller must wait for it.
fn stop_first(app: &tauri::AppHandle, reason: StopReason) -> bool {
    let Some(desktop) = app.try_state::<Desktop>() else { return false };
    if desktop.supervisor.status().state == State::Stopped {
        return false;
    }
    // Already stopping is fine: the sequence in progress ends the application.
    let _ = desktop.supervisor.stop(reason);
    true
}

/// The single-instance plugin's callback: a second launch's arguments.
fn second_launch(app: &tauri::AppHandle, argv: Vec<String>, cwd: String) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
    let args: Vec<OsString> = argv.into_iter().skip(1).map(OsString::from).collect();
    let current = app.state::<Desktop>().supervisor.status().workspace.map(PathBuf::from);
    let decision = instance::decide(current.as_deref(), &args, std::path::Path::new(&cwd));
    if decision == instance::Decision::Focus {
        return;
    }
    // The confirmation blocks; never on the main thread.
    let asking = app.clone();
    let _ = std::thread::Builder::new().name("second-launch".into()).spawn(move || {
        let mut confirm = confirmer(&asking);
        if let instance::Action::Switch(path) = instance::resolve(decision, current.as_deref(), confirm.as_mut()) {
            let _ = asking.state::<Desktop>().supervisor.stop(StopReason::WorkspaceChange(path));
        }
    });
}

fn confirmer(app: &tauri::AppHandle) -> Box<dyn instance::Confirm> {
    #[cfg(feature = "e2e")]
    {
        let _ = app;
        Box::new(commands::ConfirmDouble)
    }
    #[cfg(not(feature = "e2e"))]
    Box::new(commands::SystemConfirm(app.clone()))
}

#[cfg(test)]
mod tests {
    use super::own_origin;

    fn allowed(url: &str) -> bool {
        own_origin(&tauri::Url::parse(url).unwrap())
    }

    #[test]
    fn only_the_applications_own_pages_are_navigable() {
        assert!(allowed("tauri://localhost/index.html"));
        assert!(allowed("http://tauri.localhost/"));
        assert!(allowed("https://tauri.localhost/assets/a.js"));
        for refused in ["https://example.com/", "http://tauri.localhost.example.com/",
                        "file:///C:/Windows/win.ini", "javascript:alert(1)", "data:text/html,x",
                        "tauri://evil/", "http://localhost/", "about:blank"] {
            assert!(!allowed(refused), "{refused}");
        }
    }
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
        commands::open_external,
        commands::quit_now,
        e2e::e2e_report
    ];
    #[cfg(not(feature = "e2e"))]
    return tauri::generate_handler![
        commands::connect,
        commands::send_line,
        commands::status,
        commands::diagnostics,
        commands::choose_workspace,
        commands::retry,
        commands::open_external,
        commands::quit_now
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
    // The window shows the application's own pages and nothing else: no
    // navigation away, no new windows (contracts/native-bridge.md).
    let builder = builder
        .on_navigation(|url| {
            let allowed = own_origin(url);
            #[cfg(feature = "e2e")]
            if !allowed {
                e2e::refused("navigation", url.as_str());
            }
            allowed
        })
        .on_new_window(|url, _features| {
            #[cfg(feature = "e2e")]
            e2e::refused("new_window", url.as_str());
            let _ = url;
            tauri::webview::NewWindowResponse::Deny
        });
    #[cfg(feature = "e2e")]
    let builder = builder.initialization_script(e2e::init_script());
    let window = builder.build()?;
    let saving = app.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            remember_geometry(&saving);
            // The close waits for the Core (OD-2): "Closing…" shows, and the
            // application ends when the stop sequence does.
            if stop_first(&saving, StopReason::WindowClosed) {
                api.prevent_close();
            }
        }
    });
    Ok(())
}

/// The application's own pages: the bundled assets (`tauri://localhost`, or
/// `http(s)://tauri.localhost` on Windows) and, in a debug build, the
/// development server.
pub fn own_origin(url: &tauri::Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => url.host_str() == Some("tauri.localhost")
            || (cfg!(debug_assertions) && url.host_str() == Some("127.0.0.1")
                && url.port() == Some(5173)),
        _ => false,
    }
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

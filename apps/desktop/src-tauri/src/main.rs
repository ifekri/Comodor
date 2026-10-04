// A release build is a windowed application with no console window.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // On Linux and macOS the same executable also runs each Core's watchdog.
    let args: Vec<std::ffi::OsString> = std::env::args_os().collect();
    if let Some(code) = comodor_desktop::platform::watchdog_main(&args) {
        std::process::exit(code);
    }
    comodor_desktop::run();
}

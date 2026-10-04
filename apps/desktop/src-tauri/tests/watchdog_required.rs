//! Review finding (PR #62): on macOS the watchdog is the only thing that
//! ends a Core that ignores EOF when the application dies outright, so a
//! Core is never left running without one. On Linux the parent-death signal
//! still ends the Core itself, and the watchdog stays best effort.
//!
//! Its own test binary: the watchdog program is set once per process.

#![cfg(unix)]

mod support;

use comodor_desktop::platform::{set_watchdog_program, spawn_core};
use support::{fixture_command, CoreHome};

#[test]
fn a_core_whose_watchdog_cannot_start() {
    set_watchdog_program("/nonexistent/comodor-watchdog".into());
    let home = CoreHome::new("watchdog-required");
    let started = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &home.env());
    if cfg!(target_os = "macos") {
        let problem = started.err().expect("no Core runs without its watchdog on macOS");
        assert!(problem.to_string().contains("watchdog"), "{problem}");
    } else {
        let mut core = started.expect("Linux keeps the parent-death signal");
        core.force_stop().unwrap();
        let _ = core.child.wait();
    }
}

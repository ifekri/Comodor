//! Review findings (PR #62): a Core is never left running without its
//! watchdog. On macOS nothing else ends a Core that ignores EOF when the
//! application dies outright; on Linux the parent-death signal reaches the
//! Core alone, not what it started.
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
    let problem = started.err().expect("no Core runs without its watchdog");
    assert!(problem.to_string().contains("watchdog"), "{problem}");
}

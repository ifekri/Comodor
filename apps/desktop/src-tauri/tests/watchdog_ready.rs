//! Review finding (PR #62): a watchdog that starts but does not get as far as
//! watching guards nothing, so it counts as no watchdog at all: the Core is
//! ended and the start fails.
//!
//! Its own test binary: the watchdog program is set once per process. The
//! stand-in here starts, ignores its arguments and exits without watching.

#![cfg(unix)]

mod support;

use comodor_desktop::platform::{set_watchdog_program, spawn_core};
use support::{fixture_command, CoreHome};

#[test]
fn a_core_whose_watchdog_never_watches() {
    set_watchdog_program("/usr/bin/true".into());
    let home = CoreHome::new("watchdog-ready");
    let started = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &home.env());
    let problem = started.err().expect("no Core runs with a watchdog that never watched");
    assert!(problem.to_string().contains("watchdog"), "{problem}");
}

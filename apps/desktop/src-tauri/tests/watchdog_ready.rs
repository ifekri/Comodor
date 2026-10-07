//! Review findings (PR #62): a Core runs only once its watchdog is watching.
//! A watchdog that starts but never gets as far as watching guards nothing:
//! the start fails, and the Core never ran a single instruction of its own.
//!
//! Its own test binary: the watchdog program is set once per process. The
//! stand-in here never reports that it is watching; it ends as soon as the
//! Core has left its mark — which only a Core that ran can do — or after a
//! bounded wait.

#![cfg(unix)]

mod support;

use std::os::unix::fs::PermissionsExt;

use comodor_desktop::platform::{set_watchdog_program, spawn_core, CoreCommand};
use support::{python, CoreHome, Scratch};

#[test]
fn a_core_does_not_run_before_its_watchdog_is_watching() {
    let scratch = Scratch::new("watchdog-ready");
    let mark = scratch.root.join("the-core-ran");
    let stand_in = scratch.root.join("watchdog");
    std::fs::write(&stand_in, format!(
        "#!/bin/sh\ni=0\nwhile [ ! -e '{}' ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i+1)); done\nexit 0\n",
        mark.display())).unwrap();
    std::fs::set_permissions(&stand_in, std::fs::Permissions::from_mode(0o755)).unwrap();
    set_watchdog_program(stand_in);

    let home = CoreHome::new("watchdog-ready");
    let command = CoreCommand {
        program: python(),
        args: vec!["-c".into(), format!("open({:?}, 'w').write('ran')", mark.display().to_string()).into()],
    };
    let started = spawn_core(&command, &home.workspace, &home.env());
    let problem = started.err().expect("no Core runs with a watchdog that never watched");
    assert!(problem.to_string().contains("watchdog"), "{problem}");
    assert!(!mark.exists(), "the Core ran before its watchdog was watching");
}

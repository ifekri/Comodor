//! T070: no Core outlives the application (FR-018, SC-007), per platform.

mod support;

use std::ffi::OsString;
use std::io::Write;

use comodor_desktop::platform::{spawn_core, SpawnedCore};
use support::{fixture_command, read_pid, wait_gone, CoreHome, Scratch};

/// The double starts its child once it has been greeted.
fn greet(core: &mut SpawnedCore) {
    let stdin = core.child.stdin.as_mut().expect("stdin is piped");
    stdin.write_all(comodor_desktop::relay::hello_request().as_bytes()).unwrap();
    stdin.write_all(b"\n").unwrap();
    stdin.flush().unwrap();
}

/// A double that ignores `shutdown` and EOF, and starts one child.
fn ignore_stop(label: &str) -> (CoreHome, Scratch, Vec<(OsString, OsString)>) {
    let home = CoreHome::new(label);
    let scratch = Scratch::new(&format!("{label}-pids"));
    let mut env = home.env();
    env.push(("COMODOR_TEST_CHILD_PID_FILE".into(), scratch.root.join("child.pid").into()));
    (home, scratch, env)
}

#[cfg(windows)]
#[test]
fn windows_closing_the_job_ends_the_core_and_its_child() {
    let (home, scratch, env) = ignore_stop("orphans-job");
    let mut core = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &env).unwrap();
    greet(&mut core);
    let pid = core.pid;
    let child = read_pid(&scratch.root.join("child.pid"), None);
    // The application going away closes its handle to the job; nothing else
    // is done here to the Core or its child.
    drop(core);
    assert!(wait_gone(pid), "the Core is gone");
    assert!(wait_gone(child), "and so is its child");
}

#[cfg(unix)]
#[test]
fn unix_a_forced_stop_signals_the_whole_process_group() {
    let (home, scratch, env) = ignore_stop("orphans-group");
    let mut core = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &env).unwrap();
    greet(&mut core);
    let pid = core.pid;
    let child = read_pid(&scratch.root.join("child.pid"), None);
    core.force_stop().unwrap();
    let _ = core.child.wait();
    assert!(wait_gone(pid), "the Core is gone");
    assert!(wait_gone(child), "and so is its child, through the group");
}

/// The "application" for the parent-death test: a copy of this test binary
/// that starts a Core, says which, and waits to be killed.
#[cfg(target_os = "linux")]
#[test]
#[ignore = "run only as the parent-death test's helper process"]
fn pdeathsig_helper() {
    let Some(out) = std::env::var_os("COMODOR_ORPHAN_HELPER") else { return };
    let (home, _scratch, env) = ignore_stop("orphans-helper");
    let mut core = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &env).unwrap();
    greet(&mut core);
    std::fs::write(&out, core.pid.to_string()).unwrap();
    // Blocks until this process is killed; the Core must not outlive it.
    loop {
        std::thread::park();
    }
}

#[cfg(target_os = "linux")]
#[test]
fn linux_the_core_ends_when_the_application_dies() {
    let scratch = Scratch::new("orphans-pdeathsig");
    let out = scratch.root.join("core.pid");
    let mut helper = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["pdeathsig_helper", "--exact", "--ignored", "--nocapture"])
        .env("COMODOR_ORPHAN_HELPER", &out)
        .spawn().unwrap();
    let core = read_pid(&out, None);
    helper.kill().unwrap();
    let _ = helper.wait();
    assert!(wait_gone(core), "the parent-death signal ended the Core");
}

#[cfg(target_os = "macos")]
#[test]
fn macos_closing_stdin_ends_the_real_core() {
    let home = CoreHome::new("orphans-eof");
    let mut core = spawn_core(&support::real_core_command(), &home.workspace, &home.env()).unwrap();
    let (stdin, _stdout, _stderr) = core.take_streams();
    drop(stdin);
    let status = core.child.wait().unwrap();
    assert!(status.success(), "the Core ended by itself on EOF: {status:?}");
}

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

/// Review finding (PR #62): the Core is in its job before it runs at all, so
/// nothing it starts, however early, is outside the job. It reports, as its
/// first act, whether it is in a job.
#[cfg(windows)]
#[test]
fn windows_the_core_is_in_its_job_before_it_runs() {
    let home = CoreHome::new("orphans-job-first");
    let report = "import ctypes, sys; k = ctypes.windll.kernel32; inside = ctypes.c_int(0); \
                  k.IsProcessInJob(ctypes.c_void_p(-1), None, ctypes.byref(inside)); \
                  sys.stdout.write(str(inside.value)); sys.stdout.flush()";
    let command = comodor_desktop::platform::CoreCommand {
        program: support::python(),
        args: vec!["-c".into(), report.into()],
    };
    let mut core = spawn_core(&command, &home.workspace, &home.env()).unwrap();
    let (_stdin, mut stdout, _stderr) = core.take_streams();
    let mut said = String::new();
    std::io::Read::read_to_string(&mut stdout, &mut said).unwrap();
    assert!(core.child.wait().unwrap().success());
    assert_eq!(said, "1", "the Core ran inside its job");
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

/// The "application" for the abrupt-death tests: a copy of this test binary
/// that starts a stubborn Core, says which (and its child), and waits to be
/// killed. The Core's watchdog is the real application binary.
#[cfg(unix)]
#[test]
#[ignore = "run only as the abrupt-death tests' helper process"]
fn abrupt_death_helper() {
    let Some(out) = std::env::var_os("COMODOR_ORPHAN_HELPER") else { return };
    comodor_desktop::platform::set_watchdog_program(env!("CARGO_BIN_EXE_comodor-desktop").into());
    let (home, scratch, env) = ignore_stop("orphans-helper");
    let mut core = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &env).unwrap();
    greet(&mut core);
    let child = read_pid(&scratch.root.join("child.pid"), None);
    // Renamed into place, so the test never reads half of it.
    let staging = std::path::PathBuf::from(&out).with_extension("tmp");
    std::fs::write(&staging, format!("{} {child}", core.pid)).unwrap();
    std::fs::rename(&staging, &out).unwrap();
    // Blocks until this process is killed; nothing of the Core may outlive it.
    loop {
        std::thread::park();
    }
}

/// Review finding (PR #62): an application killed outright leaves neither
/// its Core nor the Core's children, even when they ignore EOF — the
/// parent-death signal on Linux, the watchdog on Linux and macOS.
#[cfg(unix)]
#[test]
fn unix_a_killed_application_leaves_no_core_and_no_child() {
    let scratch = Scratch::new("orphans-abrupt");
    let out = scratch.root.join("pids");
    let mut helper = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["abrupt_death_helper", "--exact", "--ignored", "--nocapture"])
        .env("COMODOR_ORPHAN_HELPER", &out)
        .spawn().unwrap();
    let ends = std::time::Instant::now() + support::DEADLINE;
    let pids = loop {
        if let Ok(text) = std::fs::read_to_string(&out) {
            let pids: Vec<u32> = text.split_whitespace().filter_map(|p| p.parse().ok()).collect();
            if pids.len() == 2 {
                break pids;
            }
        }
        assert!(std::time::Instant::now() < ends, "the helper never named its Core");
        std::thread::yield_now();
    };
    helper.kill().unwrap();
    let _ = helper.wait();
    assert!(wait_gone(pids[0]), "the Core is gone");
    assert!(wait_gone(pids[1]), "and so is its child");
}

/// CI finding (PR #62, Linux): the parent-death signal can end the Core a
/// moment before the watchdog sees the application go, so the watchdog may
/// see the Core's exit first. Whichever it sees, the Core's children must not
/// survive it — here the Core is gone before the watchdog even starts, and
/// the application (this test) is still alive.
#[cfg(unix)]
#[test]
fn unix_the_watchdog_ends_the_group_when_the_core_goes_first() {
    let (home, scratch, env) = ignore_stop("orphans-core-first");
    let mut core = spawn_core(&fixture_command("doubles.py", "ignore-stop"), &home.workspace, &env).unwrap();
    greet(&mut core);
    let group = core.pid;
    let child = read_pid(&scratch.root.join("child.pid"), None);
    // The Core alone, not its group: the child stays behind in the group.
    assert_eq!(unsafe { libc::kill(group as libc::pid_t, libc::SIGKILL) }, 0);
    let _ = core.child.wait();
    let status = std::process::Command::new(env!("CARGO_BIN_EXE_comodor-desktop"))
        .args([comodor_desktop::platform::WATCHDOG_FLAG, &std::process::id().to_string(), &group.to_string()])
        .status()
        .unwrap();
    assert!(status.success(), "the watchdog ran: {status:?}");
    assert!(wait_gone(child), "the Core's child is gone with its group");
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

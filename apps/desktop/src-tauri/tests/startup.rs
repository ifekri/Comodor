//! T025: starting the Core, end to end against real processes
//! (contracts/core-supervision.md §1–§3, FR-006, FR-009, FR-022).
//!
//! Every wait has a failure deadline and returns as soon as its condition
//! holds; nothing here waits by elapsed time.

mod support;

use std::ffi::OsString;
use std::path::PathBuf;

use comodor_desktop::locate::{locate, Lookup};
use comodor_desktop::platform::CoreCommand;
use comodor_desktop::supervisor::{FailureClass, State, Status};
use support::{fixture_command, fixtures, launch, real_core_command, CoreHome, Page, DEADLINE};

fn settled(status: &Status) -> bool {
    matches!(status.state, State::Ready | State::Failed)
}

fn failure_of(status: &Status) -> (FailureClass, String) {
    let failure = status.failure.clone().unwrap_or_else(|| panic!("no failure in {status:?}"));
    (failure.class, failure.message)
}

#[test]
fn the_offline_core_reaches_ready_and_answers_through_the_relay() {
    let home = CoreHome::new("startup-ready");
    let supervisor = launch(real_core_command(), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let status = supervisor.wait_for(settled, DEADLINE).expect("settled");
    assert_eq!(status.state, State::Ready, "{status:?}\n{}", supervisor.diagnostics());
    assert_eq!(status.workspace.as_deref(), Some(home.workspace.display().to_string().as_str()));
    assert!(status.core.is_some());

    let page = Page::new();
    let generation = supervisor.connect(page.sink());
    supervisor.send_line(generation,
        r#"{"version":2,"type":"request","id":"m","method":"model.get","params":{}}"#.into()).unwrap();
    supervisor.send_line(generation,
        r#"{"version":2,"type":"request","id":"w","method":"workspace.get","params":{}}"#.into()).unwrap();
    let model = page.answer("m");
    assert_eq!(model["result"]["provider"], "fake");
    assert_eq!(model["result"]["model"], "fake-1");
    assert_eq!(model["result"]["configured"], true);
    let workspace = page.answer("w");
    let reported = PathBuf::from(workspace["result"]["path"].as_str().unwrap());
    assert_eq!(reported.canonicalize().unwrap(), home.workspace.canonicalize().unwrap());
}

#[test]
fn not_found_when_nothing_can_be_located() {
    let home = CoreHome::new("startup-not-found");
    let empty = home.scratch.root.join("empty-path");
    std::fs::create_dir_all(&empty).unwrap();
    let located = {
        let var = |name: &str| (name == "PATH").then(|| OsString::from(empty.clone()));
        let is_file = |path: &std::path::Path| path.is_file();
        locate(&Lookup { var: &var, is_file: &is_file })
    };
    let supervisor = support::launch_located(located, &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let status = supervisor.wait_for(settled, DEADLINE).expect("settled");
    let (class, message) = failure_of(&status);
    assert_eq!(class, FailureClass::NotFound);
    assert!(message.contains("COMODOR_BIN"), "{message}");
}

#[test]
fn spawn_failed_for_a_file_that_cannot_be_executed() {
    let home = CoreHome::new("startup-spawn-failed");
    let command = CoreCommand { program: fixtures().join("not-executable").into(), args: vec![] };
    let supervisor = launch(command, &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let (class, message) = failure_of(&supervisor.wait_for(settled, DEADLINE).expect("settled"));
    assert_eq!(class, FailureClass::SpawnFailed);
    assert!(message.contains("not-executable"), "{message}");
}

#[test]
fn exited_before_ready_keeps_the_tail() {
    let home = CoreHome::new("startup-exited");
    let supervisor = launch(fixture_command("doubles.py", "exit-immediately"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let (class, message) = failure_of(&supervisor.wait_for(settled, DEADLINE).expect("settled"));
    assert_eq!(class, FailureClass::ExitedBeforeReady, "{message}");
    assert!(supervisor.diagnostics().contains("doubles: this Core refuses to start"),
            "{}", supervisor.diagnostics());
}

#[test]
fn protocol_mismatch_names_both_versions() {
    let home = CoreHome::new("startup-mismatch");
    let supervisor = launch(fixture_command("doubles.py", "version-mismatch"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let (class, message) = failure_of(&supervisor.wait_for(settled, DEADLINE).expect("settled"));
    assert_eq!(class, FailureClass::ProtocolMismatch);
    assert!(message.contains("version 2") && message.contains("version 3"), "{message}");
}

#[test]
fn a_refused_version_names_what_the_core_supports() {
    let home = CoreHome::new("startup-refused");
    let supervisor = launch(fixture_command("doubles.py", "version-refused"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let (class, message) = failure_of(&supervisor.wait_for(settled, DEADLINE).expect("settled"));
    assert_eq!(class, FailureClass::ProtocolMismatch);
    assert!(message.contains("[3]"), "{message}");
}

#[test]
fn a_line_that_is_not_protocol_is_a_fault() {
    let home = CoreHome::new("startup-fault");
    let supervisor = launch(fixture_command("doubles.py", "bad-line"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    // Each fault of a ready Core counts as a crash: it is restarted twice,
    // and the third stops it, still named a protocol fault (OD-1).
    let status = supervisor.wait_for(|status| status.state == State::Failed, DEADLINE).expect("failed");
    assert_eq!(failure_of(&status).0, FailureClass::ProtocolFault);
    assert_eq!(status.restart_count, 3);
}

#[test]
fn an_unavailable_workspace_fails_before_any_spawn() {
    let home = CoreHome::new("startup-workspace");
    let argv = home.scratch.root.join("argv.json");
    let missing = home.scratch.root.join("no-such-folder");
    let supervisor = support::launch_with_env(fixture_command("scripted_core.py", "echo"), &home,
        vec![("COMODOR_TEST_ARGV_FILE".into(), argv.clone().into())]);
    supervisor.start(missing.clone()).unwrap();
    let (class, message) = failure_of(&supervisor.wait_for(settled, DEADLINE).expect("settled"));
    assert_eq!(class, FailureClass::WorkspaceUnavailable);
    assert!(message.contains(&missing.display().to_string()), "{message}");
    assert!(!argv.exists(), "no Core was started");
}

#[test]
fn a_flood_on_stderr_never_blocks_the_handshake() {
    let home = CoreHome::new("startup-flood");
    let supervisor = launch(fixture_command("doubles.py", "stderr-flood"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    let status = supervisor.wait_for(settled, DEADLINE).expect("settled");
    assert_eq!(status.state, State::Ready, "{status:?}");
    let tail = supervisor.diagnostics();
    assert!(tail.len() <= 64 * 1024 && tail.lines().count() <= 200);
    assert!(tail.contains("diagnostic line"), "the tail holds the latest lines");
}

/// Review finding (PR #62): each failure shows only its own attempt's
/// diagnostics: a later attempt that fails before a Core runs shows none of
/// the earlier Core's output.
#[test]
fn a_failure_before_a_core_runs_shows_no_earlier_diagnostics() {
    let home = CoreHome::new("startup-fresh-tail");
    let supervisor = launch(fixture_command("doubles.py", "exit-immediately"), &home);
    supervisor.start(home.workspace.clone()).unwrap();
    supervisor.wait_for(settled, DEADLINE).expect("settled");
    assert!(supervisor.diagnostics().contains("doubles: this Core refuses to start"));
    std::fs::remove_dir_all(&home.workspace).unwrap();
    supervisor.retry().unwrap();
    let status = supervisor.wait_for(|s| s.state == State::Failed
        && s.failure.as_ref().is_some_and(|f| f.class == FailureClass::WorkspaceUnavailable), DEADLINE)
        .expect("the workspace is unavailable");
    assert_eq!(status.state, State::Failed);
    assert_eq!(supervisor.diagnostics(), "", "nothing from the earlier Core");
}

#[test]
fn try_again_after_a_failure_starts_a_new_core_in_the_same_workspace() {
    let home = CoreHome::new("startup-retry");
    let supervisor = launch(fixture_command("doubles.py", "exit-immediately"), &home);
    let page = Page::new();
    supervisor.connect(page.sink());
    supervisor.start(home.workspace.clone()).unwrap();
    let first = supervisor.wait_for(settled, DEADLINE).expect("settled");
    assert_eq!(first.state, State::Failed);
    supervisor.retry().unwrap();
    // Every status change reaches the page in order: the second attempt is
    // seen starting again, then failing again.
    let states = page.states_until(2, "failed");
    let second_start = states.iter().position(|s| s == "failed").unwrap() + 1;
    assert!(states[second_start..].contains(&"starting".to_string()), "{states:?}");
    assert_eq!(supervisor.status().workspace, first.workspace);
}

/// Review finding (PR #62): the native side keeps the workspace exactly, so
/// a second launch is compared with the real folder — never with its display
/// string, which loses bytes that are not UTF-8.
#[cfg(unix)]
#[test]
fn the_supervisor_reports_the_workspace_exactly() {
    use std::os::unix::ffi::OsStrExt;
    let home = CoreHome::new("startup-exact-workspace");
    let odd = home.scratch.root.join(std::ffi::OsStr::from_bytes(b"caf\xe9"));
    std::fs::create_dir_all(&odd).unwrap();
    let supervisor = launch(fixture_command("doubles.py", "exit-immediately"), &home);
    supervisor.start(odd.clone()).unwrap();
    supervisor.wait_for(settled, DEADLINE).expect("settled");
    assert_eq!(supervisor.workspace(), Some(odd.clone()));
    assert_ne!(supervisor.status().workspace.map(PathBuf::from), Some(odd), "the display string is lossy");
}

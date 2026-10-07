//! T010: how the Core process is started (contracts/core-supervision.md §2).

mod support;

use std::io::{BufRead, BufReader, Read, Write};

use comodor_desktop::platform::spawn_core;
use support::{fixture_command, CoreHome, Scratch};

const HELLO: &str = r#"{"version":2,"type":"request","id":"1","method":"client.hello","params":{"protocol_version":2,"client":{"name":"spawn-test","version":"0"},"capabilities":["questions","permissions"]}}"#;

#[test]
fn the_core_starts_with_exact_arguments_in_the_workspace_with_the_environment_inherited() {
    let home = CoreHome::new("spawn");
    let record = Scratch::new("spawn-record");
    let argv_file = record.root.join("argv.json");

    let command = fixture_command("scripted_core.py", "echo");
    let mut env = home.env();
    env.push(("COMODOR_TEST_ARGV_FILE".into(), argv_file.clone().into()));
    env.push(("COMODOR_TEST_MARKER".into(), "inherited-1".into()));

    let mut core = spawn_core(&command, &home.workspace, &env).expect("spawn");
    let (mut stdin, stdout, stderr) = core.take_streams();

    // All three streams are piped: stdin and stdout carry the protocol...
    stdin.write_all(HELLO.as_bytes()).unwrap();
    stdin.write_all(b"\n").unwrap();
    stdin.flush().unwrap();
    let mut answer = String::new();
    BufReader::new(stdout).read_line(&mut answer).unwrap();
    let answer: serde_json::Value = serde_json::from_str(&answer).expect("a protocol line");
    assert_eq!(answer["result"]["protocol_version"], 2);

    // ...and closing stdin is how the Core is asked to stop.
    drop(stdin);
    let status = core.child.wait().unwrap();
    assert!(status.success(), "the Core exits cleanly on EOF: {status:?}");

    // ...and stderr is the diagnostic stream.
    let mut diagnostics = String::new();
    BufReader::new(stderr).read_to_string(&mut diagnostics).unwrap();
    assert!(diagnostics.contains("scripted core: scenario echo"), "{diagnostics}");

    let recorded: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&argv_file).unwrap()).unwrap();
    // The fixture sees `[<scenario>, core, --stdio]` after its own path: the
    // application appended exactly `core --stdio` and nothing else.
    assert_eq!(recorded["argv"], serde_json::json!(["echo", "core", "--stdio"]));
    assert_eq!(recorded["marker"], "inherited-1");
    // A variable nobody overrode arrives exactly as this process has it: the
    // environment is inherited, not rebuilt (FR-003).
    assert_eq!(recorded["path"].as_str(), std::env::var("PATH").ok().as_deref());
    let cwd = std::path::PathBuf::from(recorded["cwd"].as_str().unwrap()).canonicalize().unwrap();
    assert_eq!(cwd, home.workspace.canonicalize().unwrap());
}

#[test]
fn a_command_that_cannot_be_executed_is_a_spawn_error() {
    let home = CoreHome::new("spawn-fail");
    let command = comodor_desktop::platform::CoreCommand {
        program: support::fixtures().join("not-executable").into(),
        args: vec![],
    };
    assert!(spawn_core(&command, &home.workspace, &home.env()).is_err());
}

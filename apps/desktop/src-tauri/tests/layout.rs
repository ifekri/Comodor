//! D2: the layout preference through the library's public API, against a
//! real preferences file on disk (contracts/layout-persistence.md; FR-036,
//! SC-017).

use std::path::{Path, PathBuf};

use comodor_desktop::commands::Desktop;
use comodor_desktop::prefs;
use comodor_desktop::supervisor::{Failure, FailureClass, Options, Supervisor};
use comodor_desktop::workspace::Chooser;
use serde_json::{json, Value};

struct NoChooser;

impl Chooser for NoChooser {
    fn choose(&mut self, _start: Option<&Path>) -> Option<PathBuf> {
        None
    }
}

struct Dir(PathBuf);

impl Dir {
    fn new(label: &str) -> Self {
        let path = std::env::temp_dir().join(format!("comodor-layout-it-{label}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        Self(path)
    }
    fn file(&self) -> PathBuf {
        prefs::path_in(&self.0)
    }
}

impl Drop for Dir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn desktop_at(file: PathBuf) -> Desktop {
    let supervisor = Supervisor::launch(Options {
        locate: Box::new(|| Err(Failure::new(FailureClass::NotFound, "no Core in this test"))),
        test_env: vec![],
        log: None,
        on_finished: None,
    });
    Desktop::new(supervisor, file, Box::new(NoChooser))
}

const D1_FILE: &str = concat!(
    r#"{"version":1,"window":{"width":1000,"height":700,"x":1,"y":2,"maximized":false},"#,
    r#""last_selected_folder":"/work/on-disk"}"#, "\n");

fn layout() -> Value {
    json!({"version": 1, "panel_open": true, "panel_surface": "core", "panel_width": 360})
}

#[test]
fn an_accepted_write_keeps_d1s_values_on_disk() {
    let dir = Dir::new("accepted");
    std::fs::write(dir.file(), D1_FILE).unwrap();
    let before: Value = serde_json::from_str(D1_FILE).unwrap();
    let desktop = desktop_at(dir.file());
    desktop.write_layout(&layout()).expect("accepted");
    let after: Value = serde_json::from_str(&std::fs::read_to_string(dir.file()).unwrap()).unwrap();
    for field in ["version", "window", "last_selected_folder"] {
        assert_eq!(after[field], before[field], "{field}");
    }
    assert_eq!(after["layout"], layout());
}

#[test]
fn a_refused_write_leaves_the_file_on_disk_byte_identical() {
    let dir = Dir::new("refused");
    std::fs::write(dir.file(), D1_FILE).unwrap();
    let desktop = desktop_at(dir.file());
    let mut bad = layout();
    bad["panel_width"] = json!(10_000);
    assert!(desktop.write_layout(&bad).is_err());
    assert_eq!(std::fs::read(dir.file()).unwrap(), D1_FILE.as_bytes());
}

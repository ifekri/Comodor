//! The desktop's own preferences (data-model.md §5, FR-032).
//!
//! One small JSON file in the application's per-user configuration
//! directory: the window's geometry and the folder last chosen. It never
//! holds a credential, a token, the Core's environment or session content.

use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

pub const FILE_NAME: &str = "preferences.json";
pub const VERSION: u32 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct WindowGeometry {
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
    pub maximized: bool,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Preferences {
    pub version: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window: Option<WindowGeometry>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_selected_folder: Option<String>,
}

impl Default for Preferences {
    fn default() -> Self {
        Self { version: VERSION, window: None, last_selected_folder: None }
    }
}

/// Where the file lives under `config_dir`.
pub fn path_in(config_dir: &Path) -> PathBuf {
    config_dir.join(FILE_NAME)
}

/// The preferences in `path`; a missing or malformed file is treated as
/// absent.
pub fn load(path: &Path) -> Preferences {
    std::fs::read_to_string(path).ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

/// Write the preferences through a temporary file and a rename, so a crash
/// mid-write leaves the old file or the new one, never half of one.
pub fn save(path: &Path, preferences: &Preferences) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = serde_json::to_string_pretty(preferences).map_err(io::Error::other)?;
    let staging = path.with_extension("json.tmp");
    std::fs::write(&staging, text)?;
    std::fs::rename(&staging, path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("comodor-prefs-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
        fn file(&self) -> PathBuf {
            path_in(&self.0)
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn full() -> Preferences {
        Preferences {
            version: 1,
            window: Some(WindowGeometry { width: 1100, height: 760, x: 10, y: -20, maximized: false }),
            last_selected_folder: Some("/work/project".into()),
        }
    }

    #[test]
    fn the_serialised_type_has_exactly_three_fields() {
        let value = serde_json::to_value(full()).unwrap();
        let mut keys: Vec<&str> = value.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, ["last_selected_folder", "version", "window"]);
        assert_eq!(value["window"], json!({"width": 1100, "height": 760, "x": 10, "y": -20, "maximized": false}));
        assert_eq!(value["version"], 1);
        assert_eq!(Preferences::default().version, 1);
        let empty = serde_json::to_value(Preferences::default()).unwrap();
        assert_eq!(empty, json!({"version": 1}), "an absent folder is absent, not null");
    }

    #[test]
    fn a_missing_file_is_the_default() {
        let dir = Dir::new("missing");
        assert_eq!(load(&dir.file()), Preferences::default());
    }

    #[test]
    fn an_unknown_field_is_ignored_and_never_written_back() {
        let dir = Dir::new("unknown");
        std::fs::write(dir.file(), r#"{"version":1,"last_selected_folder":"/a","token":"CANARY-PREF"}"#).unwrap();
        let loaded = load(&dir.file());
        assert_eq!(loaded.last_selected_folder.as_deref(), Some("/a"));
        save(&dir.file(), &loaded).unwrap();
        let written = std::fs::read_to_string(dir.file()).unwrap();
        assert!(!written.contains("CANARY-PREF"), "{written}");
        let value: Value = serde_json::from_str(&written).unwrap();
        assert_eq!(value, json!({"version": 1, "last_selected_folder": "/a"}));
    }

    #[test]
    fn a_malformed_file_is_absent_and_replaced_on_save() {
        let dir = Dir::new("malformed");
        for bad in ["{not json", r#"{"version":"one"}"#, "[]", ""] {
            std::fs::write(dir.file(), bad).unwrap();
            assert_eq!(load(&dir.file()), Preferences::default(), "{bad:?}");
        }
        save(&dir.file(), &full()).unwrap();
        assert_eq!(load(&dir.file()), full());
        let leftovers: Vec<_> = std::fs::read_dir(&dir.0).unwrap()
            .map(|entry| entry.unwrap().file_name()).collect();
        assert_eq!(leftovers, vec![std::ffi::OsString::from(FILE_NAME)],
                   "the temporary file was renamed over the old one");
    }

    #[test]
    fn a_round_trip_writes_no_other_field() {
        let dir = Dir::new("round");
        save(&dir.file(), &full()).unwrap();
        let value: Value = serde_json::from_str(&std::fs::read_to_string(dir.file()).unwrap()).unwrap();
        assert_eq!(value, serde_json::to_value(full()).unwrap());
        assert_eq!(load(&dir.file()), full());
    }
}

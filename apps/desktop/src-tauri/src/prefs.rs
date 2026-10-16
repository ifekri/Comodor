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
    #[serde(default, skip_serializing_if = "Option::is_none",
            serialize_with = "folder::save", deserialize_with = "folder::load")]
    pub last_selected_folder: Option<PathBuf>,
}

/// The folder, stored losslessly: as text when its path is valid Unicode,
/// otherwise in the platform's own form (serde's `OsString` encoding), so a
/// path that is not UTF-8 comes back exactly. A stored form this platform
/// cannot read is an absent folder, not a malformed file.
mod folder {
    use std::ffi::OsString;
    use std::path::PathBuf;

    use serde::de::IgnoredAny;
    use serde::{Deserialize, Deserializer, Serialize, Serializer};

    pub fn save<S: Serializer>(folder: &Option<PathBuf>, out: S) -> Result<S::Ok, S::Error> {
        match folder.as_deref().map(|path| (path.to_str(), path.as_os_str())) {
            Some((Some(text), _)) => out.serialize_str(text),
            Some((None, native)) => native.serialize(out),
            None => out.serialize_none(),
        }
    }

    pub fn load<'de, D: Deserializer<'de>>(stored: D) -> Result<Option<PathBuf>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Stored {
            Text(String),
            Native(OsString),
            Other(IgnoredAny),
        }
        Ok(match Stored::deserialize(stored)? {
            Stored::Text(text) => Some(PathBuf::from(text)),
            Stored::Native(native) => Some(PathBuf::from(native)),
            Stored::Other(_) => None,
        })
    }
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
    let text = serde_json::to_string_pretty(preferences).map_err(io::Error::other)?;
    write_atomically(path, &text)
}

/// The one way the file is written: a temporary file beside it, then a
/// rename over it. A failed rename leaves the old file and no temporary one.
fn write_atomically(path: &Path, text: &str) -> io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let staging = path.with_extension("json.tmp");
    std::fs::write(&staging, text)?;
    std::fs::rename(&staging, path).inspect_err(|_| {
        let _ = std::fs::remove_file(&staging);
    })
}

// -- D2: the workbench layout (contracts/layout-persistence.md) --------------

/// The layout's own format version.
pub const LAYOUT_VERSION: u32 = 1;
/// The largest `layout` argument accepted, serialised as compact JSON.
pub const LAYOUT_MAX_BYTES: usize = 1024;
pub const PANEL_WIDTH_MIN: u32 = 240;
pub const PANEL_WIDTH_MAX: u32 = 960;

/// The surfaces the side panel can show. The conversation is the main area,
/// never a side-panel surface.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum PanelSurface {
    Core,
    Diagnostics,
    Shortcuts,
}

/// The one application-wide layout: presentation values only, never Core
/// state, a path, a message or a credential.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct LayoutPreference {
    pub version: u32,
    pub panel_open: bool,
    pub panel_surface: PanelSurface,
    pub panel_width: u32,
}

impl Default for LayoutPreference {
    fn default() -> Self {
        Self { version: LAYOUT_VERSION, panel_open: false, panel_surface: PanelSurface::Core, panel_width: 320 }
    }
}

const LAYOUT_FIELDS: [&str; 4] = ["version", "panel_open", "panel_surface", "panel_width"];

/// Validate a layout completely, before anything else happens: the rules of
/// contracts/layout-persistence.md in their order, refusing with a reason
/// that names the first problem.
pub fn validate_layout(layout: &serde_json::Value) -> Result<LayoutPreference, String> {
    let size = serde_json::to_vec(layout).map(|bytes| bytes.len()).unwrap_or(usize::MAX);
    if size > LAYOUT_MAX_BYTES {
        return Err(format!("the layout is larger than {LAYOUT_MAX_BYTES} bytes"));
    }
    let Some(fields) = layout.as_object() else {
        return Err("the layout is not an object".into());
    };
    if let Some(unknown) = fields.keys().find(|key| !LAYOUT_FIELDS.contains(&key.as_str())) {
        return Err(format!("unknown field `{unknown}`"));
    }
    if let Some(missing) = LAYOUT_FIELDS.iter().find(|field| !fields.contains_key(**field)) {
        return Err(format!("missing field `{missing}`"));
    }
    let version = &fields["version"];
    if !(version.is_u64() && version.as_u64() == Some(u64::from(LAYOUT_VERSION))) {
        return Err(format!("`version` must be the integer {LAYOUT_VERSION}"));
    }
    let Some(panel_open) = fields["panel_open"].as_bool() else {
        return Err("`panel_open` must be a boolean".into());
    };
    let panel_surface = match fields["panel_surface"].as_str() {
        Some("core") => PanelSurface::Core,
        Some("diagnostics") => PanelSurface::Diagnostics,
        Some("shortcuts") => PanelSurface::Shortcuts,
        _ => return Err("`panel_surface` must be one of core, diagnostics, shortcuts".into()),
    };
    let width = &fields["panel_width"];
    let panel_width = width.as_u64().filter(|_| width.is_u64())
        .filter(|width| (u64::from(PANEL_WIDTH_MIN)..=u64::from(PANEL_WIDTH_MAX)).contains(width));
    let Some(panel_width) = panel_width else {
        return Err(format!("`panel_width` must be an integer from {PANEL_WIDTH_MIN} to {PANEL_WIDTH_MAX}"));
    };
    Ok(LayoutPreference { version: LAYOUT_VERSION, panel_open, panel_surface, panel_width: panel_width as u32 })
}

/// Everything the file holds: D1's preferences, unchanged, and the layout
/// beside them (data-model §1). Every runtime save writes this, so a D1 save
/// never drops a stored layout.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Stored {
    pub preferences: Preferences,
    pub layout: Option<LayoutPreference>,
}

/// The file in `path`: D1's three values by D1's rules, and the layout read
/// on its own and leniently — a bad layout is no layout, never a bad file.
pub fn load_stored(path: &Path) -> Stored {
    let Some(text) = std::fs::read_to_string(path).ok() else { return Stored::default() };
    let Ok(preferences) = serde_json::from_str::<Preferences>(&text) else { return Stored::default() };
    let layout = serde_json::from_str::<serde_json::Value>(&text).ok()
        .and_then(|file| file.get("layout").and_then(|layout| validate_layout(layout).ok()));
    Stored { preferences, layout }
}

/// Write the whole file through the same temporary file and rename as D1.
pub fn save_stored(path: &Path, stored: &Stored) -> io::Result<()> {
    #[derive(Serialize)]
    struct File<'a> {
        #[serde(flatten)]
        preferences: &'a Preferences,
        #[serde(skip_serializing_if = "Option::is_none")]
        layout: Option<&'a LayoutPreference>,
    }
    let file = File { preferences: &stored.preferences, layout: stored.layout.as_ref() };
    let text = serde_json::to_string_pretty(&file).map_err(io::Error::other)?;
    write_atomically(path, &text)
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
            last_selected_folder: Some(PathBuf::from("/work/project")),
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

    /// Review finding (PR #62): the folder comes back exactly, even when its
    /// path is not valid Unicode; a Unicode path is still stored as text.
    #[test]
    fn the_last_folder_round_trips_losslessly() {
        let dir = Dir::new("lossless");
        #[cfg(unix)]
        let odd: PathBuf = {
            use std::os::unix::ffi::OsStrExt;
            std::ffi::OsStr::from_bytes(b"/work/caf\xe9").into()
        };
        #[cfg(windows)]
        let odd: PathBuf = {
            use std::os::windows::ffi::OsStringExt;
            std::ffi::OsString::from_wide(&[0x43, 0x3a, 0x5c, 0xd800]).into()
        };
        assert!(odd.to_str().is_none(), "the path is not valid Unicode");
        let stored = Preferences { last_selected_folder: Some(odd.clone()), ..full() };
        save(&dir.file(), &stored).unwrap();
        assert_eq!(load(&dir.file()).last_selected_folder, Some(odd));

        save(&dir.file(), &full()).unwrap();
        let value: Value = serde_json::from_str(&std::fs::read_to_string(dir.file()).unwrap()).unwrap();
        assert_eq!(value["last_selected_folder"], "/work/project", "a Unicode path stays text");
    }

    #[test]
    fn a_folder_this_platform_cannot_read_is_absent_and_the_rest_is_kept() {
        let dir = Dir::new("other-platform");
        let foreign = if cfg!(windows) { r#"{"Unix":[47,119]}"# } else { r#"{"Windows":[67,58]}"# };
        std::fs::write(dir.file(), format!(
            r#"{{"version":1,"window":{{"width":1,"height":2,"x":3,"y":4,"maximized":true}},"last_selected_folder":{foreign}}}"#))
            .unwrap();
        let loaded = load(&dir.file());
        assert_eq!(loaded.last_selected_folder, None);
        assert!(loaded.window.is_some(), "the window geometry survives");
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
        assert_eq!(loaded.last_selected_folder.as_deref(), Some(Path::new("/a")));
        save(&dir.file(), &loaded).unwrap();
        let written = std::fs::read_to_string(dir.file()).unwrap();
        assert!(!written.contains("CANARY-PREF"), "{written}");
        let value: Value = serde_json::from_str(&written).unwrap();
        assert_eq!(value, json!({"version": 1, "last_selected_folder": "/a"}));
    }

    /// Review question (PR #62): a later save replaces the file on every
    /// platform (`std::fs::rename` replaces an existing file on Windows too).
    #[test]
    fn a_second_save_replaces_the_first() {
        let dir = Dir::new("second-save");
        save(&dir.file(), &full()).unwrap();
        let changed = Preferences { last_selected_folder: Some(PathBuf::from("/elsewhere")), ..full() };
        save(&dir.file(), &changed).unwrap();
        assert_eq!(load(&dir.file()), changed);
        let leftovers: Vec<_> = std::fs::read_dir(&dir.0).unwrap()
            .map(|entry| entry.unwrap().file_name()).collect();
        assert_eq!(leftovers, vec![std::ffi::OsString::from(FILE_NAME)], "no temporary file is left");
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

/// D2: the workbench layout (contracts/layout-persistence.md).
#[cfg(test)]
mod layout_tests {
    use super::*;
    use serde_json::{json, Value};

    struct Dir(PathBuf);

    impl Dir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("comodor-layout-{label}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
        fn file(&self) -> PathBuf {
            path_in(&self.0)
        }
        fn entries(&self) -> Vec<std::ffi::OsString> {
            std::fs::read_dir(&self.0).unwrap().map(|entry| entry.unwrap().file_name()).collect()
        }
    }

    impl Drop for Dir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn valid() -> Value {
        json!({"version": 1, "panel_open": true, "panel_surface": "diagnostics", "panel_width": 400})
    }

    fn with(field: &str, value: Value) -> Value {
        let mut layout = valid();
        layout[field] = value;
        layout
    }

    fn without(field: &str) -> Value {
        let mut layout = valid();
        layout.as_object_mut().unwrap().remove(field);
        layout
    }

    fn refusal(layout: &Value) -> String {
        validate_layout(layout).expect_err(&format!("{layout} is refused"))
    }

    // -- T005: validation, rule by rule -----------------------------------------

    #[test]
    fn a_valid_layout_is_accepted_exactly() {
        assert_eq!(validate_layout(&valid()), Ok(LayoutPreference {
            version: 1, panel_open: true, panel_surface: PanelSurface::Diagnostics, panel_width: 400,
        }));
    }

    #[test]
    fn every_boundary_is_accepted() {
        for width in [240, 960] {
            assert!(validate_layout(&with("panel_width", json!(width))).is_ok(), "{width}");
        }
        for (surface, expected) in [("core", PanelSurface::Core), ("diagnostics", PanelSurface::Diagnostics),
                                    ("shortcuts", PanelSurface::Shortcuts)] {
            assert_eq!(validate_layout(&with("panel_surface", json!(surface))).unwrap().panel_surface, expected);
        }
        for open in [true, false] {
            assert_eq!(validate_layout(&with("panel_open", json!(open))).unwrap().panel_open, open);
        }
    }

    /// Rule 1: the argument, serialised as compact JSON, is at most 1024 bytes.
    #[test]
    fn rule_1_the_serialised_layout_is_at_most_1024_bytes() {
        // An object whose only extra weight is padding inside a string value:
        // the size rule is checked first, so the oversized case is refused for
        // its size, not for its unknown field.
        let sized = |bytes: usize| {
            let base = serde_json::to_vec(&with("pad", json!(""))).unwrap().len();
            with("pad", json!("x".repeat(bytes - base)))
        };
        let at_limit = sized(1024);
        assert_eq!(serde_json::to_vec(&at_limit).unwrap().len(), 1024);
        assert!(!refusal(&at_limit).contains("1024"), "1024 bytes pass the size rule");
        let over = sized(1025);
        assert_eq!(serde_json::to_vec(&over).unwrap().len(), 1025);
        assert!(refusal(&over).contains("1024 bytes"), "{}", refusal(&over));
        assert!(refusal(&json!("x".repeat(2000))).contains("1024 bytes"), "size comes before the type");
    }

    /// Rule 2: the layout is a JSON object.
    #[test]
    fn rule_2_the_layout_is_an_object() {
        for not_an_object in [json!(null), json!([valid()]), json!("layout"), json!(320), json!(true)] {
            assert!(refusal(&not_an_object).contains("object"), "{not_an_object}");
        }
    }

    /// Rule 3: exactly the four fields; an unknown or a missing one is refused.
    #[test]
    fn rule_3_exactly_the_four_fields() {
        let unknown = refusal(&with("token", json!("CANARY")));
        assert!(unknown.contains("unknown field") && unknown.contains("token"), "{unknown}");
        for field in ["version", "panel_open", "panel_surface", "panel_width"] {
            let missing = refusal(&without(field));
            assert!(missing.contains("missing field") && missing.contains(field), "{missing}");
        }
        assert!(refusal(&json!({})).contains("missing field"));
    }

    /// Rule 4: `version` is the integer 1.
    #[test]
    fn rule_4_version_is_the_integer_1() {
        for bad in [json!(2), json!(0), json!(1.0), json!("1"), json!(null), json!(-1)] {
            assert!(refusal(&with("version", bad.clone())).contains("`version`"), "{bad}");
        }
    }

    /// Rule 5: `panel_open` is a boolean.
    #[test]
    fn rule_5_panel_open_is_a_boolean() {
        for bad in [json!("true"), json!(1), json!(null)] {
            assert!(refusal(&with("panel_open", bad.clone())).contains("`panel_open`"), "{bad}");
        }
    }

    /// Rule 6: `panel_surface` is one of core, diagnostics, shortcuts.
    #[test]
    fn rule_6_panel_surface_is_one_of_the_three() {
        for bad in [json!("conversation"), json!("Core"), json!("editor"), json!(""), json!(1), json!(null)] {
            assert!(refusal(&with("panel_surface", bad.clone())).contains("`panel_surface`"), "{bad}");
        }
    }

    /// Rule 7: `panel_width` is an integer from 240 to 960 inclusive.
    #[test]
    fn rule_7_panel_width_is_an_integer_from_240_to_960() {
        for bad in [json!(239), json!(961), json!(0), json!(-320), json!(320.5), json!(320.0),
                    json!("320"), json!(null)] {
            assert!(refusal(&with("panel_width", bad.clone())).contains("`panel_width`"), "{bad}");
        }
    }

    /// The first problem is the one named, in the contract's order.
    #[test]
    fn the_first_problem_is_named() {
        let mut both = with("version", json!(2));
        both["panel_width"] = json!(10);
        assert!(refusal(&both).contains("`version`"));
        assert!(refusal(&with("extra", json!(1))).contains("unknown field"),
                "a field problem comes before a value problem");
    }

    #[test]
    fn the_defaults_are_the_contracts() {
        assert_eq!(serde_json::to_value(LayoutPreference::default()).unwrap(),
                   json!({"version": 1, "panel_open": false, "panel_surface": "core", "panel_width": 320}));
    }

    // -- T006: the stored file -------------------------------------------------

    fn d1_file() -> &'static str {
        r#"{"version":1,"window":{"width":900,"height":700,"x":5,"y":6,"maximized":false},"last_selected_folder":"/work/kept"}"#
    }

    fn d1_values() -> Preferences {
        Preferences {
            version: 1,
            window: Some(WindowGeometry { width: 900, height: 700, x: 5, y: 6, maximized: false }),
            last_selected_folder: Some(PathBuf::from("/work/kept")),
        }
    }

    #[test]
    fn a_d1_file_loads_with_no_layout_and_its_values() {
        let dir = Dir::new("d1-file");
        std::fs::write(dir.file(), d1_file()).unwrap();
        assert_eq!(load_stored(&dir.file()), Stored { preferences: d1_values(), layout: None });
    }

    #[test]
    fn a_bad_layout_loads_as_none_and_keeps_d1s_values() {
        let dir = Dir::new("bad-layout");
        let bad_layouts = [
            json!("not an object"),
            json!([1, 2]),
            with("version", json!(2)),
            with("token", json!("x")),
            without("panel_width"),
            with("panel_open", json!("yes")),
            with("panel_width", json!(4000)),
            with("panel_surface", json!("terminal")),
            json!(null),
        ];
        for layout in bad_layouts {
            let mut file: Value = serde_json::from_str(d1_file()).unwrap();
            file["layout"] = layout.clone();
            std::fs::write(dir.file(), file.to_string()).unwrap();
            assert_eq!(load_stored(&dir.file()), Stored { preferences: d1_values(), layout: None }, "{layout}");
            assert_eq!(load(&dir.file()), d1_values(), "D1's own load ignores the layout: {layout}");
        }
    }

    #[test]
    fn a_valid_stored_layout_loads() {
        let dir = Dir::new("valid-layout");
        let mut file: Value = serde_json::from_str(d1_file()).unwrap();
        file["layout"] = valid();
        std::fs::write(dir.file(), file.to_string()).unwrap();
        let stored = load_stored(&dir.file());
        assert_eq!(stored.preferences, d1_values());
        assert_eq!(stored.layout, validate_layout(&valid()).ok());
    }

    #[test]
    fn a_malformed_whole_file_is_the_default() {
        let dir = Dir::new("malformed-whole");
        for bad in ["{not json", r#"{"version":"one","layout":{"version":1}}"#, "[]", ""] {
            std::fs::write(dir.file(), bad).unwrap();
            assert_eq!(load_stored(&dir.file()), Stored::default(), "{bad:?}");
        }
        let missing = Dir::new("missing-whole");
        assert_eq!(load_stored(&missing.file()), Stored::default());
    }

    #[test]
    fn save_stored_round_trips_the_layout_and_writes_no_other_field() {
        let dir = Dir::new("round-stored");
        let stored = Stored { preferences: d1_values(), layout: validate_layout(&valid()).ok() };
        save_stored(&dir.file(), &stored).unwrap();
        assert_eq!(load_stored(&dir.file()), stored);
        let value: Value = serde_json::from_str(&std::fs::read_to_string(dir.file()).unwrap()).unwrap();
        let mut keys: Vec<&str> = value.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, ["last_selected_folder", "layout", "version", "window"]);
        assert_eq!(value["layout"], valid());
        assert_eq!(dir.entries(), vec![std::ffi::OsString::from(FILE_NAME)], "no temporary file is left");
    }

    #[test]
    fn save_stored_without_a_layout_writes_what_d1_writes() {
        let dir = Dir::new("no-layout");
        save_stored(&dir.file(), &Stored { preferences: d1_values(), layout: None }).unwrap();
        let ours = std::fs::read_to_string(dir.file()).unwrap();
        save(&dir.file(), &d1_values()).unwrap();
        assert_eq!(ours, std::fs::read_to_string(dir.file()).unwrap());
    }

    #[test]
    fn an_unknown_top_level_field_is_still_dropped() {
        let dir = Dir::new("unknown-top");
        let mut file: Value = serde_json::from_str(d1_file()).unwrap();
        file["token"] = json!("CANARY-TOP");
        file["layout"] = valid();
        std::fs::write(dir.file(), file.to_string()).unwrap();
        let stored = load_stored(&dir.file());
        save_stored(&dir.file(), &stored).unwrap();
        let written = std::fs::read_to_string(dir.file()).unwrap();
        assert!(!written.contains("CANARY-TOP"), "{written}");
        assert!(written.contains("\"layout\""), "{written}");
    }

    #[test]
    fn the_preferences_type_still_has_exactly_three_fields() {
        let value = serde_json::to_value(d1_values()).unwrap();
        let mut keys: Vec<&str> = value.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, ["last_selected_folder", "version", "window"]);
    }
}

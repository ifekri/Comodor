/// Every command the window's content may call, and no other
/// (contracts/native-bridge.md). One list, used twice: `build.rs` declares it
/// in the app manifest, so the build generates an allow/deny permission pair
/// per command and a command is usable only where a capability grants it;
/// `lib.rs` registers handlers only for names in it.
pub const COMMANDS: [&str; 9] = [
    "connect",
    "send_line",
    "status",
    "diagnostics",
    "choose_workspace",
    "retry",
    "check_again",
    "quit_now",
    "open_external",
];

/// The test build's one extra command. Declared only when the `e2e` feature
/// is on, and granted only by the test build's own inline capability.
pub const E2E_COMMAND: &str = "e2e_report";

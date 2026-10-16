# Contract: the native operation set (D2)

The window's content may call exactly these eleven native operations, and no
other. D1's record of nine operations
(`specs/003-desktop-foundation/contracts/native-bridge.md`) is history and is
not edited; this contract supersedes it for D2 and later.

| # | Operation | Since | Contract |
| --- | --- | --- | --- |
| 1 | `connect` | D1 | `specs/003-desktop-foundation/contracts/native-bridge.md` (unchanged) |
| 2 | `send_line` | D1 | same (unchanged) |
| 3 | `status` | D1 | same, plus `check_epoch` as merged in PR #62 (unchanged by D2) |
| 4 | `diagnostics` | D1 | same (unchanged) |
| 5 | `choose_workspace` | D1 | same (unchanged) |
| 6 | `retry` | D1 | same (unchanged) |
| 7 | `check_again` | D1 | same (unchanged) |
| 8 | `quit_now` | D1 | same (unchanged) |
| 9 | `open_external` | D1 | same (unchanged) |
| 10 | `read_layout` | D2 | [layout-persistence.md](./layout-persistence.md) |
| 11 | `write_layout` | D2 | [layout-persistence.md](./layout-persistence.md) |

Not added in D2, by the owner's decision (spec FR-031): any quit,
reload-window, open-log-folder or other application-level operation. Quitting
stays with the window's close control and the operating system, through D1's
stop sequence.

## One source

The eleven names live in `COMMANDS` in `src-tauri/src/command_names.rs` (type
`[&str; 11]`). As in D1, it feeds the build's app manifest (`build.rs`) and the
handler registration (`lib.rs`); `capabilities/main.json` grants exactly the
eleven allow permissions; the test build adds only `e2e_report` and its
`e2e-test` capability.

## Verification

- **Unit (native)**: the constant equals this table exactly — the test's own
  written-out list cites this file; every name has a registered handler in the
  release build; every registered handler comes from the constant; the main
  capability grants exactly the eleven allow identifiers; the generated
  manifest has exactly eleven allow/deny pairs (plus `e2e_report`'s only in
  the test build).
- **Release build (CI, all three platforms)**: `npm run -w apps/desktop
  release-manifest` builds the release configuration and asserts, from the
  generated `acl-manifests.json` and `capabilities.json`: exactly eleven
  allow/deny pairs and nothing for `e2e_report`; only the `main` capability;
  exactly the eleven allow identifiers plus the recorded `core:` minimum; no
  plugin permission; the `e2e` build differs only by `e2e_report`. A mutation
  check: removing `write_layout` from the capability, or adding a twelfth name,
  fails the check (spec SC-016).

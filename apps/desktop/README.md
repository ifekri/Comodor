# Comodor desktop (D1)

The desktop application: a Tauri 2 window that starts and supervises one
Comodor Core (`comodor core --stdio`) and speaks protocol v2 to it. The Core
stays the only authority; the window presents what it reports. Specification,
plan and contracts: [`specs/003-desktop-foundation/`](../../specs/003-desktop-foundation/).

This is **not** the computer-control backend in `src/comodor/desktop/` — that
is a Core capability the agent's computer-use tool drives. Nothing here
imports or changes it.

## Pinned versions

| Component | Version |
| --- | --- |
| Rust toolchain (`src-tauri/rust-toolchain.toml`) | 1.99.0 |
| `tauri` | 2.12.1 |
| `tauri-build` | 2.7.1 |
| `tauri-plugin-single-instance` | 2.5.2 |
| `tauri-plugin-dialog` | 2.8.1 |
| `tauri-plugin-opener` | 2.7.0 (used from the native side only) |
| `@tauri-apps/api`, `@tauri-apps/cli` | 2.12.1 |
| `react`, `react-dom` | 19.2.8 (the same React the terminal interface resolves) |

## Command boundary — verified on these exact versions (T003)

Measured with a throwaway probe app built from the same pinned crates on
Windows, 2026-10-03, not inferred from documentation:

- **(a) Default without an app manifest:** every registered command is
  callable from the window, even with a capability that grants nothing.
  The probe's ungranted command returned its result.
- **(b) With the app manifest** (`tauri_build::AppManifest::new().commands(…)`
  in `build.rs`): a registered command that no enabled capability grants is
  refused — `Command ungranted_cmd not allowed by ACL`. A plugin command the
  capability does not grant is refused the same way.
- **(c) Generated permission identifiers:** `allow-<command>` and
  `deny-<command>`, with the command's underscores turned into hyphens
  (`send_line` → `allow-send-line`). The tauri-build documentation says
  snake_case; the generated files say kebab-case, and the files are what
  `src-tauri/capabilities/main.json` and the release-manifest check use.
- **(d) Generated files:** `src-tauri/gen/schemas/acl-manifests.json`, with
  the app's permissions under the key `__app-acl__`, and
  `src-tauri/gen/schemas/capabilities.json`, the resolved capabilities. `gen/`
  is git-ignored, because release and `e2e` builds generate different files.
- **(e) `core:` permissions:** none are needed. An IPC channel passed to an
  app command delivers messages with a capability that grants no `core:`
  permission at all, so `main` grants the nine app commands and nothing else.
- **(f) Single instance (`tauri-plugin-single-instance` 2.5.2 source):**
  - Windows: a named mutex plus a hidden message window, through which the
    second launch's arguments are passed with `WM_COPYDATA`.
  - Linux: a well-known name on the D-Bus session bus (`zbus`). CI runs the
    Linux leg inside `dbus-run-session`.
  - macOS: a Unix domain socket under `/tmp`.

  None of these is a network (TCP/UDP) listener. The macOS socket can be
  written to by other processes of the same user, which can only hand the
  application a workspace path; a different path is never switched to
  without the person's confirmation (FR-019).

## Running from source

Prerequisites on every platform: Python 3.11+ with Comodor installed
(`pip install -e ".[dev]"` at the repository root), Node 22.6+, Bun, and the
pinned Rust toolchain (`rustup` installs it from `rust-toolchain.toml`). Then
the platform's own:

| Platform | Also needed |
| --- | --- |
| Windows | the MSVC build tools and the WebView2 runtime (present on Windows 11) |
| Linux | WebKitGTK 4.1 and its build dependencies: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libsoup-3.0-dev libxdo-dev libssl-dev pkg-config build-essential` |
| macOS | the Xcode command-line tools |

```sh
npm ci                                   # at the repository root
cd apps/desktop
npm run tauri -- dev                     # development window
npm run tauri -- build --no-bundle       # a local release build, not packaged
```

The application finds the Core the way the terminal interface does:

1. `COMODOR_BIN`, with `COMODOR_ARGS` split on whitespace as leading
   arguments — for example `COMODOR_BIN=python`, `COMODOR_ARGS="-m comodor"`.
   A path containing spaces belongs in `COMODOR_BIN`, never in `COMODOR_ARGS`.
2. `comodor` on `PATH`.

D1 is not packaged: no installer, signing or auto-update (that is D6).

## Tests

```sh
cd apps/desktop
npm test                                 # window logic (Bun + happy-dom)
cargo test --manifest-path src-tauri/Cargo.toml          # native unit + integration
npm run e2e                              # in-application scenarios (test build)
npm run lifetime                         # process-lifetime cases
npm run canary                           # every flow with a unique credential
npm run release-manifest                 # the release build's permission boundary
```

Every test is offline: the Core runs with the scripted `fake` provider, the
scripted Core fixture or a Core double, and no test needs a credential. Set
`COMODOR_PYTHON` to the interpreter that has Comodor installed when it is not
`python` (`python3` on Linux and macOS); on Linux the scenario harness runs
itself inside `dbus-run-session` and `xvfb-run`.

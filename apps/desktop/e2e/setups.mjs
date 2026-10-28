/**
 * How the harness prepares each scenario's launch (T016).
 *
 * Every field is optional:
 * - `core`: `[fixture file, argument]` under `src-tauri/tests/fixtures`; the
 *   application appends `core --stdio` itself. Default: the scripted `echo`.
 * - `realCore`: true runs the real Core (`python -m comodor`) instead.
 * - `configured`: false for a Core home with no provider (default true).
 * - `apiKey`: the fake provider's key, such as the credential canary.
 * - `hold`: true gives the fixture a hold point (`COMODOR_TEST_HOLD`).
 * - `sequence`: the `sequenced` double's per-launch behaviours, written to
 *   the file `COMODOR_TEST_SEQUENCE` names.
 * - `workspaceArgument`: true passes the workspace on the command line;
 *   `"inner"` makes the workspace a project (a `.git` marker) and passes a
 *   folder inside it.
 * - `choose`: the chooser double's answers in order (a path, a placeholder,
 *   or `null` for a dismissal).
 * - `lastSelectedFolder`: a stored preference, a placeholder or a path.
 * - `confirm`: the second-launch confirmation double's answer.
 * - `params`: handed to the scenario in the page.
 * - `canary`: true gives the fake provider a unique key, then searches every
 *   recorded message and command, the page's own holdings (the result), the
 *   Core's recorded arguments, the application's output, log and
 *   preferences for it. Any occurrence fails the scenario (SC-009).
 * - `lifetime`: a case that ends the application itself (`npm run lifetime`);
 *   it names its Cores, and passes when the application ended as the case
 *   ends it and no named Core is left.
 * - `childPid`: the double writes its child's pid, which must be gone too —
 *   everywhere (`true`), or only on the listed platforms.
 * - `forced`: whether the log must say the stop was forced (OD-2).
 * - `platforms`: where the case applies; elsewhere it is reported N/A.
 * - `maxReadyMs`: the result's `readyAt` must come this soon after the
 *   process started (SC-001).
 * - `preferencesText` (D2): the preferences file's exact text before launch.
 * - `relaunch` (D2): `{ workspace: "same" | "other" }` — after the first
 *   launch ends itself, launch again with the same data folder, in the same
 *   workspace or a new one; the scenario runs again with
 *   `params.phase === "relaunched"`.
 * - `reducedMotion` (D2): set the operating system's reduced-motion
 *   preference for this run and restore it after, with
 *   COMODOR_E2E_OS_LEVEL=1 only (e2e/os-preferences.mjs).
 * - `motionTransition` (D2 follow-up, macOS): switch reduced motion off,
 *   then on, each in a fresh launch, and restore the exact original after,
 *   with COMODOR_E2E_OS_LEVEL=1 only.
 *
 * - `files` (D3a): the workspace's files before launch, by workspace-relative
 *   path: a string, `{ base64 }`, `{ size }` (sparse) or `{ many }` (a folder
 *   of that many empty files).
 *
 * Placeholders, anywhere above: `$workspace` (the launch's workspace folder)
 * and `$stored` (another existing folder, standing for the last one chosen).
 */

export const SETUPS = {
  "lifetime-close": { lifetime: true, workspaceArgument: true, forced: false },
  "lifetime-quit-held": {
    lifetime: true, core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true,
    forced: false,
  },
  "lifetime-quit-now": {
    lifetime: true, core: ["doubles.py", "ignore-stop"], childPid: true, workspaceArgument: true, forced: true,
  },
  "lifetime-kill": { lifetime: true, workspaceArgument: true },
  // A Core that ignores EOF, with a child: only the job object (Windows) or
  // the Core's watchdog (Linux, macOS) ends them both when the application
  // is killed outright (FR-018).
  "lifetime-kill-stubborn": {
    lifetime: true, core: ["doubles.py", "ignore-stop"], childPid: true, workspaceArgument: true,
  },
  "lifetime-second-same": { lifetime: true, workspaceArgument: true },
  "lifetime-second-declined": { lifetime: true, workspaceArgument: true, confirm: false },
  "lifetime-second-confirmed": {
    lifetime: true, workspaceArgument: true, confirm: true, params: { stored: "$stored" },
  },
  empty: { workspaceArgument: true },
  // D3a: the explorer and the read-only viewer over the real Core.
  explorer: {
    realCore: true, workspaceArgument: true, canary: true,
    files: {
      "src/app.ts": "// D3a viewer\nexport async function load(path: string): Promise<number> {\n  return path.length;\n}\n",
      "src/token.ts": "export const token = \"ghp_D3aSpikeTokenAbCdEfGhIjKlMnOp1234\";\n",
      ".env": "API_KEY=ENV-SECRET-D3A-7f3c91\n",
      "notes/bom.txt": { base64: Buffer.from("﻿with a byte-order mark\n", "utf-8").toString("base64") },
      "notes/crlf.txt": "one\r\ntwo\r\n",
      "notes/persian.md": "# سلام mixed متن text \u{1F600}\n",
      "media/logo.bin": { base64: Buffer.from([0x89, 0x50, 0x4e, 0x47, 0, 0, 0, 1, 2, 3]).toString("base64") },
      "media/huge.txt": { size: 2_000_001 },
      "big": { many: 600 },
    },
  },
  boundary: { core: ["scripted_core.py", "adversarial"], workspaceArgument: true },
  "canary-early": { core: ["scripted_core.py", "adversarial"], workspaceArgument: true, canary: true },
  conversation: { core: ["scripted_core.py", "question"], workspaceArgument: true },
  "conversation-permission": { core: ["scripted_core.py", "permission"], workspaceArgument: true },
  "conversation-cancel": {
    core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true,
  },
  reload: { core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true },
  // Spec: Machine sleep and wake — the turn goes on while the Core is checked.
  wake: { core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true, wake: true },
  crash: {
    core: ["doubles.py", "sequenced"],
    sequence: ["complete-turn", "scripted:hold-mid-turn", "crash-on-send"],
    hold: true,
    workspaceArgument: true,
  },
  unconfigured: { realCore: true, configured: false, workspaceArgument: true },
  ready: {
    realCore: true,
    workspaceArgument: true,
    params: { workspace: "$workspace" },
    maxReadyMs: 10_000,
  },
  // FR-021: changed later from the ready window, to the folder last chosen.
  "workspace-change": {
    lastSelectedFolder: "$stored",
    workspaceArgument: true,
    choose: ["$stored"],
    params: { workspace: "$workspace", stored: "$stored" },
  },
  "workspace-launch": {
    lastSelectedFolder: "$stored",
    choose: [null, "$workspace"],
    params: { workspace: "$workspace", stored: "$stored" },
  },
  "workspace-launch-path": {
    lastSelectedFolder: "$stored",
    workspaceArgument: true,
    params: { workspace: "$workspace" },
  },
  // FR-020: started in a folder inside a project, the Core works in the
  // project's root, and the window shows the Core's report.
  "workspace-project-root": {
    workspaceArgument: "inner",
    params: { root: "$workspace", inner: "$inner" },
  },
  // D2: the workbench shell around the conversation, and around a failure.
  shell: { workspaceArgument: true },
  "shell-failure": { core: ["doubles.py", "version-mismatch"], workspaceArgument: true },
  // D2: the command palette in each state it can be reached in.
  palette: { workspaceArgument: true },
  "palette-failure": { core: ["doubles.py", "version-mismatch"], workspaceArgument: true },
  "palette-unconfigured": { realCore: true, configured: false, workspaceArgument: true },
  // D2: the keyboard, with keys dispatched in the page.
  keyboard: { workspaceArgument: true },
  // D2: keys delivered by the operating system (COMODOR_E2E_OS_LEVEL=1 only).
  "key-delivery": { workspaceArgument: true },
  // D2: the operating system's reduced-motion preference, set for the run and
  // restored after (COMODOR_E2E_OS_LEVEL=1 only; the stylesheet check always).
  "reduced-motion": { workspaceArgument: true, reducedMotion: true },
  // D2 follow-up: on macOS, the preference switched off and then on, each
  // confirmed by the effective value, and the exact original put back.
  "reduced-motion-transition": { workspaceArgument: true, platforms: ["darwin"], motionTransition: true },
  // D2: the layout through the real bridge, kept across a reload, a crash and
  // a workspace change; a refused write leaves the file byte-identical.
  layout: { workspaceArgument: true, choose: ["$stored"], params: { stored: "$stored" } },
  // D2: zero WCAG 2.1 A/AA violations in every window state (axe-core).
  accessibility: { workspaceArgument: true },
  "accessibility-starting": {
    core: ["doubles.py", "silent"], workspaceArgument: true, params: { state: "starting|handshaking" },
  },
  "accessibility-restarting": {
    core: ["doubles.py", "sequenced"], sequence: ["scripted:echo", "silent"], workspaceArgument: true,
    params: { state: "restarting|handshaking|starting", then: "crash" },
  },
  "accessibility-checking": {
    core: ["doubles.py", "ignore-stop"], workspaceArgument: true, params: { state: "checking", then: "wake" },
  },
  "accessibility-failed": {
    core: ["doubles.py", "version-mismatch"], workspaceArgument: true, params: { state: "failed" },
  },
  "accessibility-unconfigured": {
    realCore: true, configured: false, workspaceArgument: true, params: { state: "ready" },
  },
  "accessibility-absent": { choose: [null], params: { state: "absent" } },
  "accessibility-closing": {
    lifetime: true, core: ["doubles.py", "ignore-stop"], childPid: true, workspaceArgument: true, forced: true,
  },
  // D2: narrow windows, sized in physical pixels from the scale factor.
  narrow: { workspaceArgument: true },
  // D2 (SC-018): the real window captured at the reference's sizes and states,
  // with the question fixture for the question card.
  visual: { core: ["scripted_core.py", "question"], workspaceArgument: true },
  // D2: the Core panel across a crash and a workspace change, and the
  // diagnostics panel over a real Core's stderr.
  "core-panel": { workspaceArgument: true, choose: ["$stored"], params: { stored: "$stored" } },
  "diagnostics-panel": { core: ["doubles.py", "stderr-flood"], workspaceArgument: true },
  // D2: the layout across a relaunch with the same data folder, in the same
  // workspace and in another one (the first launch quits; see `relaunch`).
  "layout-relaunch-same": { lifetime: true, workspaceArgument: true, relaunch: { workspace: "same" } },
  "layout-relaunch-other": { lifetime: true, workspaceArgument: true, relaunch: { workspace: "other" } },
  // D2: seeded layouts — invalid ones mean the defaults, with D1's values intact.
  "layout-seeded-unreadable": {
    workspaceArgument: true,
    preferencesText: '{"version":1,"window":{"width":1100,"height":760,"x":40,"y":40,"maximized":false},"last_selected_folder":"/work/seeded","layout":"junk"}',
    params: { expect: "defaults", folder: "/work/seeded", window: {"width":1100,"height":760,"x":40,"y":40,"maximized":false} },
  },
  "layout-seeded-version": {
    workspaceArgument: true,
    preferencesText: '{"version":1,"window":{"width":1100,"height":760,"x":40,"y":40,"maximized":false},"last_selected_folder":"/work/seeded","layout":{"version":2,"panel_open":true,"panel_surface":"core","panel_width":320}}',
    params: { expect: "defaults", folder: "/work/seeded", window: {"width":1100,"height":760,"x":40,"y":40,"maximized":false} },
  },
  "layout-seeded-range": {
    workspaceArgument: true,
    preferencesText: '{"version":1,"window":{"width":1100,"height":760,"x":40,"y":40,"maximized":false},"last_selected_folder":"/work/seeded","layout":{"version":1,"panel_open":true,"panel_surface":"core","panel_width":4000}}',
    params: { expect: "defaults", folder: "/work/seeded", window: {"width":1100,"height":760,"x":40,"y":40,"maximized":false} },
  },
  "layout-seeded-valid": {
    workspaceArgument: true,
    preferencesText: '{"version":1,"window":{"width":1100,"height":760,"x":40,"y":40,"maximized":false},"last_selected_folder":"/work/seeded","layout":{"version":1,"panel_open":true,"panel_surface":"shortcuts","panel_width":300}}',
    params: { expect: "restored", folder: "/work/seeded", window: {"width":1100,"height":760,"x":40,"y":40,"maximized":false} },
  },
  "palette-closing": {
    lifetime: true, core: ["doubles.py", "ignore-stop"], childPid: true, workspaceArgument: true, forced: true,
  },
};

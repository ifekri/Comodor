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
 * - `workspaceArgument`: true passes the workspace on the command line.
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
 * - `childPid`: the double writes its child's pid, which must be gone too.
 * - `forced`: whether the log must say the stop was forced (OD-2).
 * - `platforms`: where the case applies; elsewhere it is reported N/A.
 * - `maxReadyMs`: the result's `readyAt` must come this soon after the
 *   process started (SC-001).
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
  // A Core that ignores EOF: only the job object (Windows) or the
  // parent-death signal (Linux) ends it. macOS has neither (FR-018).
  "lifetime-kill-stubborn": {
    lifetime: true, core: ["doubles.py", "ignore-stop"], childPid: true, workspaceArgument: true,
    platforms: ["win32", "linux"],
  },
  "lifetime-second-same": { lifetime: true, workspaceArgument: true },
  "lifetime-second-declined": { lifetime: true, workspaceArgument: true, confirm: false },
  "lifetime-second-confirmed": {
    lifetime: true, workspaceArgument: true, confirm: true, params: { stored: "$stored" },
  },
  empty: { workspaceArgument: true },
  boundary: { core: ["scripted_core.py", "adversarial"], workspaceArgument: true },
  "canary-early": { core: ["scripted_core.py", "adversarial"], workspaceArgument: true, canary: true },
  conversation: { core: ["scripted_core.py", "question"], workspaceArgument: true },
  "conversation-permission": { core: ["scripted_core.py", "permission"], workspaceArgument: true },
  "conversation-cancel": {
    core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true,
  },
  reload: { core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true },
  crash: {
    core: ["doubles.py", "sequenced"],
    sequence: ["complete-turn", "scripted:hold-mid-turn", "crash-on-send"],
    hold: true,
    workspaceArgument: true,
  },
  ready: {
    realCore: true,
    workspaceArgument: true,
    params: { workspace: "$workspace" },
    maxReadyMs: 10_000,
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
};

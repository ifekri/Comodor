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
 * - `maxReadyMs`: the result's `readyAt` must come this soon after the
 *   process started (SC-001).
 *
 * Placeholders, anywhere above: `$workspace` (the launch's workspace folder)
 * and `$stored` (another existing folder, standing for the last one chosen).
 */

export const SETUPS = {
  empty: { workspaceArgument: true },
  conversation: { core: ["scripted_core.py", "question"], workspaceArgument: true },
  "conversation-permission": { core: ["scripted_core.py", "permission"], workspaceArgument: true },
  "conversation-cancel": {
    core: ["scripted_core.py", "hold-mid-turn"], hold: true, workspaceArgument: true,
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

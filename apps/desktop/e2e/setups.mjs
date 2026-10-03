/**
 * How the harness prepares each scenario's launch (T016).
 *
 * Every field is optional:
 * - `core`: `[fixture file, argument]` under `src-tauri/tests/fixtures`; the
 *   application appends `core --stdio` itself. Default: the scripted `echo`.
 * - `configured`: false for a Core home with no provider (default true).
 * - `apiKey`: the fake provider's key, such as the credential canary.
 * - `hold`: true gives the fixture a hold point (`COMODOR_TEST_HOLD`).
 * - `sequence`: the `sequenced` double's per-launch behaviours, written to
 *   the file `COMODOR_TEST_SEQUENCE` names.
 * - `workspaceArgument`: true passes the workspace on the command line.
 * - `choose`: the chooser double's answers in order (a path, `"$workspace"`,
 *   or `null` for a dismissal).
 * - `lastSelectedFolder`: a stored preference, `"$workspace"` or a path.
 * - `confirm`: the second-launch confirmation double's answer.
 * - `params`: handed to the scenario in the page.
 */

export const SETUPS = {
  empty: { workspaceArgument: true },
};

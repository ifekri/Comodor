/**
 * T028: deciding the workspace at launch, with the chooser double (OD-3,
 * SC-017 automated part).
 */

import { expect, type Scenario } from "../runner.ts";

/**
 * A fresh launch without a path: the chooser is given exactly the stored
 * folder, and no Core starts before a choice. The first chooser is
 * dismissed — "no workspace chosen" — then "Choose workspace…" picks the
 * workspace and the Core starts there.
 */
export const workspaceLaunch: Scenario = async (context) => {
  const stored = String(context.params["stored"]);
  const workspace = String(context.params["workspace"]);

  const gate = await context.element('[data-testid="workspace-gate"]');
  await context.waitFor(() => gate.textContent?.includes("No workspace chosen."));
  const { pid } = await context.query("core_pid");
  expect(pid === 0, `no Core runs before a choice (pid ${String(pid)})`);
  const before = (await context.query("chooser"))["starts"] as (string | null)[];
  expect(before.length === 1 && before[0] === stored,
         `the launch chooser starts at the stored folder: ${JSON.stringify(before)} vs ${stored}`);

  const choose = await context.waitFor(() => [...gate.querySelectorAll("button")]
    .find((button) => button.textContent === "Choose workspace…"));
  choose.click();

  const strip = await context.element('[data-testid="status-strip"][data-state="ready"]');
  const shown = strip.querySelector(".status-workspace")?.textContent ?? "";
  expect(shown === workspace, `the Core runs in the chosen workspace: ${shown} vs ${workspace}`);
  const after = (await context.query("chooser"))["starts"] as (string | null)[];
  expect(after.length === 2 && after[1] === stored,
         `"Choose workspace…" also starts at the stored folder: ${JSON.stringify(after)}`);
  return { starts: after };
};

/** A valid command-line path: the Core starts there, with no chooser. */
export const workspaceLaunchPath: Scenario = async (context) => {
  const workspace = String(context.params["workspace"]);
  const strip = await context.element('[data-testid="status-strip"][data-state="ready"]');
  const shown = strip.querySelector(".status-workspace")?.textContent ?? "";
  expect(shown === workspace, `the Core runs in the given path: ${shown} vs ${workspace}`);
  const { starts } = await context.query("chooser");
  expect(Array.isArray(starts) && starts.length === 0,
         `no chooser opened: ${JSON.stringify(starts)}`);
  return { starts };
};

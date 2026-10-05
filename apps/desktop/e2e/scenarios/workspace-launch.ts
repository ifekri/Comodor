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

/**
 * Review finding (PR #62): the workspace changed later, from the ready
 * window (FR-021). "Change workspace…" opens the chooser at the last chosen
 * folder; the choice stops the Core and starts one there.
 */
export const workspaceChange: Scenario = async (context) => {
  const workspace = String(context.params["workspace"]);
  const stored = String(context.params["stored"]);
  const shown = () => document.querySelector(".status-workspace")?.textContent ?? "";
  const ready = () => document.querySelector('[data-testid="status-strip"][data-state="ready"]');

  await context.waitFor(() => ready() && shown() === workspace);
  const { pid: first } = await context.query("core_pid");
  expect(typeof first === "number" && first > 0, `a Core runs: ${String(first)}`);
  await context.checkpoint("remember-core", { pid: first });

  const change = await context.waitFor(() => [...document.querySelectorAll("button")]
    .find((button) => button.textContent === "Change workspace…"));
  change.click();

  await context.waitFor(() => ready() && shown() === stored);
  const { pid: second } = await context.query("core_pid");
  expect(typeof second === "number" && second > 0 && second !== first, `a new Core: ${String(second)}`);
  await context.checkpoint("remember-core", { pid: second });
  const starts = (await context.query("chooser"))["starts"] as (string | null)[];
  expect(starts.length === 1 && starts[0] === stored,
         `the chooser starts at the last chosen folder: ${JSON.stringify(starts)}`);
  expect(document.querySelector('[data-testid="stop-outcome"]') === null, "the stop was orderly");
  return { switchedTo: shown() };
};

/**
 * Review finding (PR #62): started in a folder inside a project, the Core
 * works in the project's root, and the window shows where the Core works —
 * not the folder it was started in (FR-020).
 */
export const workspaceProjectRoot: Scenario = async (context) => {
  const root = String(context.params["root"]);
  const inner = String(context.params["inner"]);
  const shown = () => document.querySelector(".status-workspace")?.textContent ?? "";
  await context.waitFor(() => document.querySelector('[data-testid="status-strip"][data-state="ready"]')
    && shown() === root);
  expect(root !== inner && inner.startsWith(root), `started inside the project: ${inner} in ${root}`);
  return { shown: shown() };
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

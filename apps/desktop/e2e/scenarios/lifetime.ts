/**
 * T074: the application's lifetime, case by case (SC-007, SC-008, SC-016).
 *
 * Each case names its Core to the harness first; once the application has
 * ended, the harness waits for every named Core to be gone. The cases that
 * end the application send no result: the harness judges them by how the
 * application ended and by what is left.
 */

import { expect, pressKey, type Scenario, type ScenarioContext, typeInto, withText } from "../runner.ts";

/** The status strip says ready, and the Core is named to the harness. */
async function named(context: ScenarioContext): Promise<number> {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  const { pid } = await context.query("core_pid");
  expect(typeof pid === "number" && pid > 0, `a running Core: ${String(pid)}`);
  await context.checkpoint("remember-core", { pid });
  return pid as number;
}

function workspace(): string {
  return document.querySelector('[data-testid="status-strip"] .status-workspace')?.textContent ?? "";
}

/** The rest of a case that ends the application happens outside the page. */
function ending(): Promise<never> {
  return new Promise(() => {});
}

/** A normal close of the window. */
export const lifetimeClose: Scenario = async (context) => {
  await named(context);
  await context.checkpoint("close-window");
  return ending();
};

/** Quit while a turn is held mid-message: the Core still stops by itself. */
export const lifetimeQuitHeld: Scenario = async (context) => {
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  const field = await context.element('[data-testid="composer"] textarea');
  typeInto(field, "Tell me something long.");
  pressKey(field, "Enter");
  await context.waitFor(() => withText('[data-testid="line"][data-state="streaming"]', "The first words"));
  await named(context);
  await context.checkpoint("quit");
  return ending();
};

/** A Core that ignores the stop, ended at once by the person's "Quit now". */
export const lifetimeQuitNow: Scenario = async (context) => {
  await named(context);
  await context.checkpoint("close-window");
  const closing = await context.element('[data-testid="closing"]');
  expect((closing.textContent ?? "").includes("Closing…"), "Closing… is shown");
  withText("button", "Quit now", closing)!.click();
  return ending();
};

/** The application is killed outright. */
export const lifetimeKill: Scenario = async (context) => {
  await named(context);
  await context.checkpoint("kill-app");
  return ending();
};

/** A second launch with the same path: focus only, still one Core. */
export const lifetimeSecondSame: Scenario = async (context) => {
  const pid = await named(context);
  const before = workspace();
  const second = await context.checkpoint("second-launch", { path: "$workspace" });
  expect(second["code"] === 0, `the second launch handed over and ended: ${JSON.stringify(second)}`);
  const { pid: after } = await context.query("core_pid");
  expect(after === pid, `still the one Core: ${String(after)} vs ${pid}`);
  expect(workspace() === before, "the workspace is unchanged");
  const { confirmations } = await context.query("confirmations");
  expect(Array.isArray(confirmations) && confirmations.length === 0, "nothing to confirm");
  return { second };
};

async function confirmed(context: ScenarioContext): Promise<Record<string, unknown>> {
  for (;;) {
    const { confirmations } = await context.query("confirmations");
    const list = confirmations as Record<string, unknown>[];
    if (list.length > 0) return list[0]!;
  }
}

/** A second launch with another folder, declined: everything stays. */
export const lifetimeSecondDeclined: Scenario = async (context) => {
  const pid = await named(context);
  const before = workspace();
  const second = await context.checkpoint("second-launch", { path: "$stored" });
  expect(second["code"] === 0, `the second launch handed over and ended: ${JSON.stringify(second)}`);
  const asked = await confirmed(context);
  expect(asked["answer"] === false, "declined");
  const { pid: after } = await context.query("core_pid");
  expect(after === pid, `the same Core: ${String(after)} vs ${pid}`);
  expect(workspace() === before, `the workspace is kept: ${workspace()}`);
  return { asked };
};

/** The same, confirmed: an orderly stop, then one Core in the new folder. */
export const lifetimeSecondConfirmed: Scenario = async (context) => {
  const pid = await named(context);
  const stored = String(context.params["stored"]);
  const second = await context.checkpoint("second-launch", { path: "$stored" });
  expect(second["code"] === 0, `the second launch handed over and ended: ${JSON.stringify(second)}`);
  const asked = await confirmed(context);
  expect(asked["answer"] === true, "confirmed");
  await context.waitFor(() => workspace() === stored
    && document.querySelector('[data-testid="status-strip"][data-state="ready"]'));
  const { pid: after } = await context.query("core_pid");
  expect(typeof after === "number" && after !== pid, `a new Core: ${String(after)}`);
  await context.checkpoint("remember-core", { pid: after });
  expect(document.querySelector('[data-testid="stop-outcome"]') === null, "the stop was orderly");
  return { switchedTo: workspace() };
};

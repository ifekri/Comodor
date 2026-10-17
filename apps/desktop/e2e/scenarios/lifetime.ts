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

/**
 * D2 T059: the layout across an application relaunch with the same data
 * folder (SC-008, FR-024). The harness runs this twice (`relaunch` in
 * setups.mjs): first arrange a layout and quit; then, relaunched in the same
 * workspace or another one, find it restored, and the file holding the
 * layout beside D1's values.
 */
async function relaunchCase(context: ScenarioContext): Promise<Record<string, unknown>> {
  const panel = () => document.querySelector<HTMLElement>('[role="dialog"].modal-panel');
  if (context.params["phase"] !== "relaunched") {
    await named(context);
    document.querySelector<HTMLButtonElement>("footer.status-bar .status-diagnostics")!.click();
    await context.waitFor(() => panel()?.getAttribute("aria-label") === "Diagnostics");
    // The write follows the click: read the file frame by frame, within a bound.
    let stored = false;
    for (let frame = 0; frame < 600 && !stored; frame += 1) {
      const bytes = (await context.checkpoint("read-preferences"))["bytes"] as string | null;
      stored = bytes !== null && atob(bytes).includes('"panel_surface": "diagnostics"');
      if (!stored) await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)));
    }
    expect(stored, "the layout was written before quitting");
    // Closed the way a person closes it: D1 saves the window's geometry on
    // close, through the same file, and the layout must survive that save.
    await context.checkpoint("close-window");
    return ending();
  }
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => panel()?.getAttribute("aria-label") === "Diagnostics");
  const reply = await context.checkpoint("read-preferences");
  const file = JSON.parse(atob(reply["bytes"] as string)) as Record<string, unknown>;
  expect(JSON.stringify(file["layout"]) !== undefined
    && (file["layout"] as Record<string, unknown>)["panel_surface"] === "diagnostics", "the layout is in the file");
  expect(file["version"] === 1 && typeof file["window"] === "object", "D1's values are in the file beside it");
  await named(context);
  return { restored: panel()!.getAttribute("aria-label"), workspace: workspace(), file };
}

export const layoutRelaunchSame: Scenario = relaunchCase;
export const layoutRelaunchOther: Scenario = relaunchCase;

/**
 * D2 T074: zero WCAG 2.1 Level A and AA violations an automated checker
 * (`axe-core`) finds, in every window state, in the real WebView (SC-006,
 * FR-020). States a running Core passes through quickly are held for the
 * check: a Core that never answers the handshake ("Starting…"), a restart
 * into such a Core, a wake check a Core never answers, and a stop it ignores.
 */

import { expect, expectAccessible, type Scenario, type ScenarioContext, withText } from "../runner.ts";

async function ready(context: ScenarioContext): Promise<void> {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
}

function stripState(): string | null {
  return document.querySelector('[data-testid="status-strip"]')?.getAttribute("data-state") ?? null;
}

const rail = (name: string) =>
  document.querySelector<HTMLButtonElement>(`nav[aria-label="Workbench"] button[aria-label="${name}"]`)!;

/** Ready, with the palette open, with each side panel, and in covering mode. */
export const accessibilityReady: Scenario = async (context) => {
  await ready(context);
  const checked: string[] = [];
  await expectAccessible("ready");
  checked.push("ready");

  document.querySelector<HTMLButtonElement>('footer.status-bar button[aria-label="Commands"]')!.click();
  const input = await context.element('[role="dialog"][aria-label="Commands"] [role="combobox"]');
  await expectAccessible("the palette open");
  checked.push("palette");
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  await context.waitFor(() => document.querySelector('[role="dialog"]') === null);

  for (const surface of ["Core", "Diagnostics", "Keyboard shortcuts"]) {
    rail(surface).click();
    await context.element(`aside[aria-label="${surface}"]`);
    await expectAccessible(`the ${surface} panel`);
    checked.push(surface);
  }

  const { scale_factor: scale } = await context.query("window" as never) as unknown as { scale_factor: number };
  await context.checkpoint("resize", { width: Math.ceil(800 * scale), height: Math.ceil(600 * scale) });
  await context.waitFor(() => document.querySelector("aside.side-panel-covering"));
  await expectAccessible("covering mode");
  checked.push("covering");
  return { checked };
};

/** One state, held: the scenario's params name it. */
export const accessibilityState: Scenario = async (context) => {
  const wanted = String(context.params["state"]);
  if (context.params["then"] === "wake") {
    // This Core answers the handshake and then nothing, the wake check included,
    // so the session is never listed: ready is the strip's state alone.
    await context.element('[data-testid="status-strip"][data-state="ready"]');
    await context.checkpoint("wake");
  }
  if (context.params["then"] === "crash") {
    await ready(context);
    const { pid } = await context.query("core_pid");
    await context.checkpoint("kill-core", { pid });
  }
  const accepted = wanted.split("|");
  await context.waitFor(() => accepted.includes(stripState() ?? ""));
  await expectAccessible(wanted);
  return { state: stripState() };
};

/** "Closing…", held by a Core that ignores the stop; then "Quit now". */
export const accessibilityClosing: Scenario = async (context) => {
  // This Core answers the handshake and then nothing, so the session is never
  // listed: ready is the strip's state alone.
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  const { pid } = await context.query("core_pid");
  expect(typeof pid === "number" && pid > 0, `a running Core: ${String(pid)}`);
  await context.checkpoint("remember-core", { pid });
  await context.checkpoint("close-window");
  const closing = await context.element('[data-testid="closing"]');
  await expectAccessible("closing");
  withText("button", "Quit now", closing)!.click();
  return new Promise(() => {});
};

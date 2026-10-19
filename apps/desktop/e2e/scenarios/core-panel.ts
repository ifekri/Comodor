/**
 * D2 T064: the Core and diagnostics panels in the real window (US5; FR-008,
 * FR-009, FR-028, SC-010). Adversarial text in the diagnostic tail is proven
 * inert by the window test (test/diagnostics-panel.test.tsx) and by D1's
 * `boundary` scenario; here a real Core's stderr is shown as plain text.
 */

import { expect, type Scenario, type ScenarioContext, withText } from "../runner.ts";
import { panel, showSurface } from "./workbench.ts";

const NOT_REPORTED = "not reported yet";

function value(label: string): string | null {
  const term = [...(panel("Core")?.querySelectorAll("dt") ?? [])].find((element) => element.textContent === label);
  return term?.nextElementSibling?.textContent?.trim() ?? null;
}

/** Every Model value the panel showed, in order, from now on. */
function watchModel(): string[] {
  const seen: string[] = [];
  new MutationObserver(() => {
    const now = value("Model");
    if (now !== null && seen.at(-1) !== now) seen.push(now);
  }).observe(document.body, { subtree: true, childList: true, characterData: true });
  return seen;
}

async function ready(context: ScenarioContext): Promise<void> {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));
}

/** Wait, frame by frame, for a Core other than `pid`; a bound, not a delay. */
async function anotherCore(context: ScenarioContext, pid: number): Promise<boolean> {
  for (let frame = 0; frame < 1200; frame += 1) {
    const now = Number((await context.query("core_pid"))["pid"]);
    if (now > 0 && now !== pid) return true;
    await new Promise((resolve) => requestAnimationFrame(() => resolve(undefined)));
  }
  return false;
}

export const corePanel: Scenario = async (context) => {
  await ready(context);
  await showSurface(context, "Core");
  await context.waitFor(() => value("Model") !== null && value("Model") !== NOT_REPORTED);
  const first = { model: value("Model"), core: value("Core"), protocol: value("Protocol version"),
                  restarts: value("Restarts") };
  expect(first.restarts === "0 of 3", `no restart yet: ${String(first.restarts)}`);
  expect(first.protocol === "2", `the protocol version the Core reported: ${String(first.protocol)}`);

  // A crash: the old values go at once; the new Core's come back when it reports.
  const crash = watchModel();
  const { pid } = await context.query("core_pid");
  await context.checkpoint("kill-core", { pid });
  expect(await anotherCore(context, Number(pid)), "a new Core after the crash");
  await ready(context);
  await context.waitFor(() => value("Restarts") === "1 of 3" && value("Model") !== NOT_REPORTED);
  expect(crash.includes(NOT_REPORTED), `cleared during the restart: ${crash.join(" → ")}`);

  // A workspace change: the same.
  const change = watchModel();
  withText("footer.status-bar button", "Change workspace…")!.click();
  const stored = String(context.params["stored"]);
  await context.waitFor(() => value("Workspace") === stored && value("Model") !== NOT_REPORTED);
  expect(change.includes(NOT_REPORTED), `cleared for the new workspace: ${change.join(" → ")}`);
  return { first, crash, change };
};

export const diagnosticsPanel: Scenario = async (context) => {
  await ready(context);
  const shown = await showSurface(context, "Diagnostics");
  const tail = await context.element('[role="dialog"][aria-label="Diagnostics"] [data-testid="diagnostics-tail"]');
  await context.waitFor(() => (tail.textContent ?? "").includes("doubles: diagnostic line"));
  expect(shown.querySelector("a, script, img, iframe, object, embed, button.link") === null, "nothing but text");
  expect(!(tail.textContent ?? "").includes("\x1b"), "no raw control character");
  return { length: (tail.textContent ?? "").length };
};

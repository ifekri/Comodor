/**
 * D2 T028: the workbench shell in the real window (US1; FR-001, FR-002,
 * FR-003). The third-crash failure path is D1's own `crash` scenario, which
 * runs inside the shell unchanged; here a Core that fails before ready shows
 * the failure view inside the shell.
 */

import { expect, pressKey, type Scenario, typeInto, withText } from "../runner.ts";

function regions(): void {
  expect(document.querySelector('nav[aria-label="Workbench"]') !== null, "the rail is there");
  const mains = document.querySelectorAll("main");
  expect(mains.length === 1 && mains[0]!.getAttribute("data-testid") === "window",
         `one main, D1's: ${mains.length}`);
  const bar = document.querySelector("footer.status-bar");
  expect(bar !== null, "the status bar is there");
  expect(bar!.querySelector('[role="status"]') !== null, "the status bar announces the Core state");
  const strips = document.querySelectorAll('[data-testid="status-strip"]');
  expect(strips.length === 1 && bar!.contains(strips[0]!), "one status strip, in the status bar");
  expect(bar!.querySelector('button[aria-label="Commands"]') !== null, "the palette control");
}

export const shell: Scenario = async (context) => {
  await context.waitFor(() => document.querySelector('[data-testid="status-strip"][data-state="ready"]'));
  regions();
  await context.waitFor(() => {
    const send = withText('[data-testid="composer"] button', "Send") as HTMLButtonElement | null;
    return send !== null && !send.disabled;
  });
  const field = await context.element('[data-testid="composer"] textarea');
  typeInto(field, "hello shell");
  pressKey(field, "Enter");
  const reply = await context.waitFor(() =>
    [...document.querySelectorAll<HTMLElement>('main [data-testid="line"]')]
      .find((line) => line.querySelector(".speaker")?.textContent === "Comodor"
        && (line.textContent ?? "").includes("hello shell")));
  expect(reply.closest("main")?.getAttribute("data-testid") === "window", "the reply streams in main");
  expect(document.querySelector(".status-state")?.textContent === "Ready", "still Ready, D1's label");
  return { reply: reply.textContent };
};

export const shellFailure: Scenario = async (context) => {
  const failure = await context.element('[data-testid="failure-view"]');
  expect(failure.closest("main")?.getAttribute("data-testid") === "window", "the failure view is in main");
  regions();
  const rail = document.querySelector('nav[aria-label="Workbench"]')!;
  const diagnostics = [...rail.querySelectorAll<HTMLButtonElement>("button")]
    .find((button) => button.getAttribute("aria-label") === "Diagnostics")!;
  expect(!diagnostics.disabled, "the rail stays usable");
  diagnostics.click();
  await context.waitFor(() => document.querySelector('aside[aria-label="Diagnostics"]'));
  return { state: document.querySelector('[data-testid="status-strip"]')?.getAttribute("data-state") };
};

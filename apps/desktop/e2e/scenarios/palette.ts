/**
 * D2 T042: the command palette in the real window (US2; FR-011–FR-015,
 * SC-004). Keys here are dispatched in the page; delivery by the operating
 * system is the `key-delivery` scenario's.
 */

import { expect, type Scenario, type ScenarioContext, typeInto } from "../runner.ts";

const MAC = /Mac/i.test(navigator.userAgent);

/** The primary modifier with `key`, dispatched on the focused element. */
function modKey(key: string): void {
  const target = document.activeElement ?? document.body;
  target.dispatchEvent(new KeyboardEvent("keydown", {
    key, bubbles: true, cancelable: true, ctrlKey: !MAC, metaKey: MAC,
  }));
}

function key(target: Element, key: string): void {
  target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
}

function dialog(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[role="dialog"][aria-label="Commands"]');
}

function ids(): string[] {
  return [...document.querySelectorAll<HTMLElement>('[role="option"]')]
    .map((option) => option.getAttribute("data-command") ?? "");
}

async function openWithControl(context: ScenarioContext): Promise<HTMLInputElement> {
  document.querySelector<HTMLButtonElement>('footer.status-bar button[aria-label="Commands"]')!.click();
  await context.waitFor(() => dialog());
  return dialog()!.querySelector<HTMLInputElement>('[role="combobox"]')!;
}

export const palette: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  await context.waitFor(() => document.querySelector('[data-testid="session"]'));

  modKey("k");
  await context.waitFor(() => dialog());
  const input = dialog()!.querySelector<HTMLInputElement>('[role="combobox"]')!;
  expect(document.activeElement === input, "the palette's input has focus");
  typeInto(input, "dia");
  await context.waitFor(() => ids()[0] === "view.diagnostics");
  key(input, "Enter");
  await context.waitFor(() => dialog() === null && document.querySelector('aside[aria-label="Diagnostics"]'));

  const second = await openWithControl(context);
  typeInto(second, "core panel");
  const core = await context.waitFor(() =>
    document.querySelector<HTMLElement>('[role="option"][data-command="view.core"]'));
  core.click();
  await context.waitFor(() => dialog() === null && document.querySelector('aside[aria-label="Core"]'));
  return { opened: ["view.diagnostics", "view.core"] };
};

export const paletteFailure: Scenario = async (context) => {
  await context.element('[data-testid="failure-view"]');
  await openWithControl(context);
  const listed = ids();
  expect(listed.includes("core.retry"), `"Try again" is listed: ${listed.join(", ")}`);
  for (const absent of ["conversation.send", "conversation.cancel", "mode.next", "app.quit_now"]) {
    expect(!listed.includes(absent), `${absent} is not listed`);
  }
  return { listed };
};

export const paletteUnconfigured: Scenario = async (context) => {
  await context.element('[data-testid="setup-notice"]');
  await openWithControl(context);
  const listed = ids();
  expect(listed.includes("core.check_again"), `"Check again" is listed: ${listed.join(", ")}`);
  expect(!listed.includes("conversation.send"), "Send is not listed");
  return { listed };
};

/** Closing: only "Quit now" and the shell's own commands; then run it from the palette. */
export const paletteClosing: Scenario = async (context) => {
  await context.element('[data-testid="status-strip"][data-state="ready"]');
  const { pid } = await context.query("core_pid");
  expect(typeof pid === "number" && pid > 0, `a running Core: ${String(pid)}`);
  await context.checkpoint("remember-core", { pid });
  await context.checkpoint("close-window");
  await context.element('[data-testid="closing"]');
  const input = await openWithControl(context);
  const listed = ids();
  expect(listed.includes("app.quit_now"), `"Quit now" is listed: ${listed.join(", ")}`);
  for (const absent of ["workspace.change", "core.retry", "conversation.send", "mode.next"]) {
    expect(!listed.includes(absent), `${absent} is not listed while closing`);
  }
  typeInto(input, "quit");
  await context.waitFor(() => ids()[0] === "app.quit_now");
  key(input, "Enter");
  // The application ends; the harness judges what is left.
  return new Promise(() => {});
};

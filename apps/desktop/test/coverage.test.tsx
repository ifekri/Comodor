/**
 * T046: every action has a mouse path and a keyboard path (FR-016, SC-002).
 *
 * The palette is both: it opens by a key (Ctrl+K) and by a visible control,
 * and its entries are run by Enter and by a click. So a command is reachable
 * both ways once it is listed in the palette in some state. Across the
 * states below, every command but "Commands" itself is listed; "Commands"
 * has its key and its two controls.
 */

import { afterEach, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { byText, click, render, type Rendered, typeInto, until } from "./render.ts";
import { key, openPalette, optionIds, palette, paletteInput, showSurface } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

async function listedNow(container: HTMLElement): Promise<string[]> {
  await openPalette(container);
  const ids = optionIds(container);
  await key("Escape", {}, paletteInput(container));
  await until(() => palette(container) === null, "closed");
  return ids;
}

async function fresh(): Promise<void> {
  await rendered?.unmount();
  rendered = undefined;
}

test("every command is reachable from the palette in some state, by key and by click", async () => {
  const seen = new Set<string>();
  const add = (ids: string[]) => ids.forEach((id) => seen.add(id));

  // Ready, then with a draft, then busy, then with each panel open beside.
  const native = new FakeNative();
  const { container } = await openWindow(show, until, native);
  add(await listedNow(container));
  await typeInto(container.querySelector('[data-testid="composer"] textarea')!, "a draft");
  add(await listedNow(container));
  native.core.emit("session.updated", { session: { ...native.core.session, busy: true } });
  await until(() => byText(container, '[data-testid="composer"] button', "Cancel"), "busy");
  add(await listedNow(container));
  await showSurface(container, "Diagnostics");
  await until(() => container.querySelector('[role="dialog"][aria-label="Diagnostics"]'), "diagnostics");
  add(await listedNow(container));
  await fresh();

  // A session in PLAN, so "Mode: ACT" applies.
  const planning = new FakeNative();
  const inPlan = await openWindow(show, until, planning);
  planning.core.emit("mode.changed", { session_id: "s1", mode: "plan" });
  await until(() => inPlan.container.querySelector('[data-testid="mode"] [data-current]')?.textContent === "PLAN",
              "PLAN confirmed");
  add(await listedNow(inPlan.container));
  await fresh();

  // Unconfigured, failed and closing.
  const unconfigured = new FakeNative();
  unconfigured.core.model = { provider: "fake", model: "fake-1", configured: false };
  let view = await show(unconfigured);
  await until(() => view.container.querySelector('[data-testid="setup-notice"]'), "unconfigured");
  add(await listedNow(view.container));
  await fresh();
  for (const overrides of [
    { state: "failed" as const, core: null, failure: { class: "crashed" as const, message: "stopped" } },
    { state: "stopping" as const, closing: { seconds_remaining: 7 } },
  ]) {
    view = await show(new FakeNative(status(overrides)));
    await until(() => view.container.querySelector('[data-testid="status-strip"]'), "the strip");
    add(await listedNow(view.container));
    await fresh();
  }

  const every = commands.all().map((command) => command.id).filter((id) => id !== "palette.open").sort();
  expect([...seen].sort()).toEqual(every);
});

test("the palette itself has a key and visible controls, and every key resolves to a command", async () => {
  const bindings = commands.allBindings();
  expect(bindings.some((binding) => binding.key === "mod+k" && binding.command === "palette.open")).toBe(true);
  for (const binding of bindings) expect(commands.get(binding.command)).toBeDefined();
  const { container } = await openWindow(show, until);
  expect(container.querySelector('header.top-bar button[data-focus-key="palette-control"]')).not.toBeNull();
  expect(container.querySelector('[data-testid="composer"] button[data-focus-key="prompt-commands"]')).not.toBeNull();
});

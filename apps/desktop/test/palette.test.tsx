/**
 * T035: the command palette (US2; FR-011, FR-013, FR-014).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { commands } from "../src/commands.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, typeInto, until } from "./render.ts";
import { highlighted, key, openPalette, optionIds, options, palette, paletteControl, paletteInput } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

describe("opening", () => {
  test("Ctrl+K opens the palette with its input focused", async () => {
    const { container } = await openWindow(show, until);
    await key("k", { ctrlKey: true }, document.body);
    const dialog = await until(() => palette(container), "the palette");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.activeElement).toBe(paletteInput(container));
  });

  test("the visible control opens it too", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    expect(document.activeElement).toBe(paletteInput(container));
  });
});

describe("the results", () => {
  test("are the registry's search over the commands that apply, each with its group and shortcut", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    const ids = optionIds(container);
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      const command = commands.get(id);
      expect(command).toBeDefined();
      const option = options(container).find((element) => element.getAttribute("data-command") === id)!;
      expect(option.textContent).toContain(command!.title);
      if (command!.group) expect(option.querySelector(".palette-group")?.textContent).toBe(command!.group);
    }
    const diagnostics = options(container).find((option) => option.getAttribute("data-command") === "view.diagnostics")!;
    expect(diagnostics.querySelector(".palette-key")?.textContent).toBe("Ctrl+3");
    expect(highlighted(container)).toBe(ids[0]!);
  });

  test("typing narrows and ranks them, and the highlight returns to the first after every change", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    await typeInto(paletteInput(container), "diag");
    await until(() => optionIds(container)[0] === "view.diagnostics", "diagnostics first");
    expect(highlighted(container)).toBe("view.diagnostics");
    expect(paletteInput(container).getAttribute("aria-activedescendant"))
      .toBe(options(container)[0]!.id);
    await key("ArrowDown", {}, paletteInput(container));
    expect(highlighted(container)).toBe(optionIds(container)[1] ?? optionIds(container)[0]!);
    await typeInto(paletteInput(container), "diagn");
    expect(highlighted(container)).toBe(optionIds(container)[0]!);
    await typeInto(paletteInput(container), "no such command at all");
    await until(() => options(container).length === 0, "no result");
    expect(paletteInput(container).getAttribute("aria-activedescendant")).toBeNull();
  });
});

describe("running", () => {
  test("Enter closes the palette and runs the highlighted command", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    await typeInto(paletteInput(container), "diag");
    await until(() => highlighted(container) === "view.diagnostics", "diagnostics highlighted");
    await key("Enter", {}, paletteInput(container));
    await until(() => palette(container) === null, "the palette closed");
    await until(() => container.querySelector('[role="dialog"][aria-label="Diagnostics"]'), "diagnostics shown");
  });

  test("a click runs a result, with the same effect as its button", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await openPalette(container);
    await typeInto(paletteInput(container), "plan");
    const plan = await until(() => options(container).find((option) => option.getAttribute("data-command") === "mode.plan"),
                             "Mode: PLAN");
    await click(plan);
    await until(() => palette(container) === null, "the palette closed");
    await until(() => native.core.requests("session.set_mode").length === 1, "the mode request");
    expect(native.core.requests("session.set_mode")[0]!.params["mode"]).toBe("plan");
  });

  test("Escape closes without running anything and focus returns where it was", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const opener = container.querySelector<HTMLButtonElement>('header.top-bar button[data-focus-key="palette-control"]')!;
    opener.focus();
    await click(opener);
    await until(() => palette(container), "the palette");
    const before = native.calls.length;
    await key("Escape", {}, paletteInput(container));
    await until(() => palette(container) === null, "closed");
    // The search is drawn anew once the palette is gone: focus is on it again.
    await until(() => document.activeElement === paletteControl(container), "focus back on the search");
    expect(native.calls.length).toBe(before);
    expect(container.querySelector('[role="dialog"].modal-panel')).toBeNull();
  });

  test("a click outside closes it without running anything", async () => {
    const { container } = await openWindow(show, until);
    await openPalette(container);
    await click(container.querySelector('[data-testid="palette-backdrop"]')!);
    await until(() => palette(container) === null, "closed");
    expect(container.querySelector('[role="dialog"].modal-panel')).toBeNull();
  });
});

describe("while open", () => {
  test("a Core restart changes the list to what applies, and nothing runs by itself", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await openPalette(container);
    expect(optionIds(container)).toContain("mode.plan");
    const calls = native.calls.length;
    native.push(status({ state: "restarting", restart_count: 1, core: null }));
    await until(() => !optionIds(container).includes("mode.plan"), "mode commands gone");
    expect(palette(container)).not.toBeNull();
    expect(native.calls.slice(calls).map((call) => call.command)).not.toContain("retry");
    expect(native.core.requests("session.set_mode").length).toBe(0);
  });
});

describe("Escape with focus outside the palette", () => {
  // The palette does not trap focus: Tab from its field reaches the shell.
  // Escape still closes it, and focus returns to where it was before.
  test("closes the palette and returns focus to its opener", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    const opener = container.querySelector<HTMLButtonElement>('header.top-bar button[data-focus-key="palette-control"]')!;
    opener.focus();
    await click(opener);
    await until(() => palette(container), "the palette");
    const before = native.calls.length;
    const outside = container.querySelector<HTMLButtonElement>('nav[aria-label="Workbench"] button')!;
    outside.focus();
    await key("Escape", {}, outside);
    await until(() => palette(container) === null, "closed");
    // The search is drawn anew once the palette is gone: focus is on it again.
    await until(() => document.activeElement === paletteControl(container), "focus back on the search");
    expect(native.calls.length).toBe(before);
  });
});

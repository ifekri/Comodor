/**
 * T056: the layout preference in the window (US4; FR-021–FR-024): read once
 * per page load, after `connect`; anything that is not a valid answer means
 * the defaults; written after each completed change; a refused write keeps
 * the window's layout and says so once; never sent to the Core.
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeCore } from "./fake-core.ts";
import { FakeNative, openWindow, status } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { key, openPalette, paletteInput, showSurface } from "./shell-helpers.ts";
import { typeInto } from "./render.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const STORED = { version: 1, panel_open: true, panel_surface: "diagnostics", panel_width: 400 };

function panel(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>('[role="dialog"].modal-panel');
}

async function runFromPalette(container: HTMLElement, query: string, id: string): Promise<void> {
  await openPalette(container);
  await typeInto(paletteInput(container), query);
  await until(() => container.querySelector(`[role="option"][data-command="${id}"]`), id);
  await click(container.querySelector(`[role="option"][data-command="${id}"]`)!);
}

describe("reading", () => {
  test("once per page load, after connect, restoring what was stored", async () => {
    const native = new FakeNative();
    native.layoutAnswer = { layout: STORED, stored: true };
    const { container } = await openWindow(show, until, native);
    await until(() => panel(container)?.getAttribute("aria-label") === "Diagnostics", "the stored panel");
    expect(native.commands("read_layout").length).toBe(1);
    expect(native.calls[0]!.command).toBe("connect");
  });

  test("an answer that is not a valid layout means the defaults, without an error", async () => {
    const answers: unknown[] = [
      {}, null, "layout", { layout: { ...STORED, panel_width: 5000 }, stored: true },
      { layout: { ...STORED, panel_surface: "terminal" }, stored: true },
      { layout: { ...STORED, extra: 1 }, stored: true }, { layout: STORED }, { layout: STORED, stored: "yes" },
    ];
    for (const answer of answers) {
      const native = new FakeNative();
      native.layoutAnswer = answer;
      const { container } = await openWindow(show, until, native);
      await until(() => native.commands("read_layout").length === 1, "the read");
      expect([JSON.stringify(answer), panel(container)]).toEqual([JSON.stringify(answer), null]);
      expect(container.querySelector('[data-testid="layout-notice"]')).toBeNull();
      await rendered!.unmount();
      rendered = undefined;
    }
  });

  test("a read that fails means the defaults, without an error", async () => {
    const native = new FakeNative();
    const invoke = native.api.invoke;
    native.api.invoke = async (command, args) => {
      if (command === "read_layout") throw new Error("native refused");
      return invoke(command, args);
    };
    const { container } = await openWindow(show, until, native);
    expect(panel(container)).toBeNull();
    expect(container.querySelector('[data-testid="layout-notice"]')).toBeNull();
  });
});

describe("writing", () => {
  test("after each completed change: open, surface, close, reset; the stored width is carried, not drawn", async () => {
    const native = new FakeNative();
    native.layoutAnswer = { layout: { ...STORED, panel_open: false }, stored: true };
    const { container } = await openWindow(show, until, native);
    await until(() => native.commands("read_layout").length === 1, "the read");
    await showSurface(container, "Core");
    await until(() => native.writtenLayouts.length === 1, "open written");
    expect(native.writtenLayouts[0]).toEqual({ version: 1, panel_open: true, panel_surface: "core", panel_width: 400 });
    await showSurface(container, "Diagnostics");
    await until(() => native.writtenLayouts.length === 2, "surface written");
    await showSurface(container, "Diagnostics");
    await until(() => native.writtenLayouts.length === 3, "close written");
    expect(native.writtenLayouts[2]).toEqual({ version: 1, panel_open: false, panel_surface: "diagnostics", panel_width: 400 });
    await runFromPalette(container, "reset", "layout.reset");
    await until(() => native.writtenLayouts.length === 4, "reset written");
    expect(native.writtenLayouts[3]).toEqual({ version: 1, panel_open: false, panel_surface: "core", panel_width: 320 });
    expect(native.writtenLayouts.length).toBe(4);
  });

  test("a refused write keeps the window's layout, says so once, and the next change writes again", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    native.refuseNextWrite = "the layout is larger than 1024 bytes";
    await showSurface(container, "Core");
    const notice = await until(() => container.querySelector<HTMLElement>('[data-testid="layout-notice"]'), "the notice");
    expect(notice.textContent).toContain("the layout is larger than 1024 bytes");
    expect(panel(container)?.getAttribute("aria-label")).toBe("Core");
    await showSurface(container, "Diagnostics");
    await until(() => native.writtenLayouts.length === 1, "the next write");
    await until(() => container.querySelector('[data-testid="layout-notice"]') === null, "the notice cleared");
  });

  test("nothing about the layout reaches the Core", async () => {
    const native = new FakeNative();
    const { container } = await openWindow(show, until, native);
    await showSurface(container, "Core");
    await until(() => native.writtenLayouts.length === 1, "written");
    for (const request of native.core.sent) {
      expect(JSON.stringify(request)).not.toMatch(/panel_(open|surface|width)/);
    }
  });
});

describe("across the Core's life", () => {
  test("a Core restart, a new workspace and a new client keep the layout; it is read only once", async () => {
    const native = new FakeNative();
    native.layoutAnswer = { layout: STORED, stored: true };
    const { container } = await openWindow(show, until, native);
    await until(() => panel(container)?.getAttribute("aria-label") === "Diagnostics", "restored");
    native.restart(new FakeCore());
    await until(() => container.querySelector('[data-testid="status-strip"][data-state="ready"]'), "ready again");
    native.push(status({ workspace: "/work/other", workspace_id: "launch:2" }));
    await until(() => container.querySelector('[data-testid="status-strip"]'), "the new workspace");
    expect(panel(container)?.getAttribute("aria-label")).toBe("Diagnostics");
    expect(native.commands("read_layout").length).toBe(1);
  });

  test("Escape on nothing writes nothing", async () => {
    const native = new FakeNative();
    await openWindow(show, until, native);
    await key("Escape", {}, document.body);
    expect(native.writtenLayouts.length).toBe(0);
  });
});

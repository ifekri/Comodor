/**
 * T069, corrected 2026-10-17: the sidebar beside the canvas from 900 px up
 * and covering it below (FR-026); the panel the same at every width, never
 * resized (FR-025 withdrawn).
 */

import { afterEach, describe, expect, test } from "bun:test";

import { App } from "../src/app.tsx";
import { FakeNative, openWindow } from "./fake-native.ts";
import { click, render, type Rendered, until } from "./render.ts";
import { key, panelOf, resizeTo, showSurface, WIDE } from "./shell-helpers.ts";

let rendered: Rendered | undefined;

afterEach(async () => {
  await rendered?.unmount();
  rendered = undefined;
  await resizeTo(WIDE);
});

async function show(native: FakeNative): Promise<Rendered> {
  rendered = await render(<App api={native.api} />);
  return rendered;
}

const sidebar = (container: HTMLElement) => container.querySelector<HTMLElement>('nav[aria-label="Workbench"]');
const toggle = (container: HTMLElement) => container.querySelector<HTMLButtonElement>("button.sidebar-toggle")!;
const shell = (container: HTMLElement) => container.querySelector<HTMLElement>('[data-testid="shell"]')!;

describe("beside and covering", () => {
  test("beside at 900 and above; hidden at 899, covering when opened, closed by Escape and a click outside", async () => {
    const { container } = await openWindow(show, until);
    await resizeTo(900);
    await until(() => sidebar(container)?.classList.contains("sidebar-beside"), "beside at 900");
    expect(shell(container).getAttribute("data-mode")).toBe("beside");
    expect(container.querySelector('[data-testid="sidebar-backdrop"]')).toBeNull();

    await resizeTo(899);
    await until(() => sidebar(container) === null, "hidden at 899");
    expect(shell(container).getAttribute("data-mode")).toBe("covering");
    expect(toggle(container).getAttribute("aria-expanded")).toBe("false");

    await click(toggle(container));
    await until(() => sidebar(container)?.classList.contains("sidebar-covering"), "covering when opened");
    expect(container.querySelector('[data-testid="sidebar-backdrop"]')).not.toBeNull();
    await key("Escape");
    await until(() => sidebar(container) === null, "closed by Escape");

    await click(toggle(container));
    await until(() => sidebar(container)?.classList.contains("sidebar-covering"), "covering again");
    await click(container.querySelector<HTMLElement>('[data-testid="sidebar-backdrop"]')!);
    await until(() => sidebar(container) === null, "closed by a click outside");
  });

  test("widening past 900 puts it back beside; a covering sidebar does not stay covering", async () => {
    const { container } = await openWindow(show, until);
    await resizeTo(700);
    await until(() => shell(container).getAttribute("data-mode") === "covering", "covering mode");
    await click(toggle(container));
    await until(() => sidebar(container)?.classList.contains("sidebar-covering"), "covering");
    await resizeTo(1200);
    await until(() => sidebar(container)?.classList.contains("sidebar-beside"), "beside again");
    expect(container.querySelector('[data-testid="sidebar-backdrop"]')).toBeNull();
    await resizeTo(700);
    await until(() => sidebar(container) === null, "hidden again below 900, not covering");
  });

  test("hiding it while it holds the focus gives the focus to its toggle, by key and from the palette", async () => {
    const { container } = await openWindow(show, until);
    const inside = () => sidebar(container)!.querySelector<HTMLButtonElement>('[role="tab"][aria-selected="true"]')!;
    inside().focus();
    await key("b", { ctrlKey: true }, inside());
    await until(() => sidebar(container) === null, "hidden by Ctrl+B");
    expect(document.activeElement).toBe(toggle(container));
    await key("b", { ctrlKey: true });
    await until(() => sidebar(container), "shown again");
    inside().focus();
    await key("k", { ctrlKey: true }, inside());
    await until(() => container.querySelector('[role="dialog"][aria-label="Commands"]'), "the palette");
    await click(container.querySelector<HTMLElement>('[role="option"][data-command="sidebar.toggle"]')!);
    await until(() => sidebar(container) === null, "hidden from the palette");
    expect(document.activeElement).toBe(toggle(container));
  });

  test("beside, the toggle and its shortcut hide and show it", async () => {
    const { container } = await openWindow(show, until);
    await click(toggle(container));
    await until(() => sidebar(container) === null, "hidden by the toggle");
    expect(shell(container).getAttribute("data-sidebar")).toBe("hidden");
    await key("b", { ctrlKey: true });
    await until(() => sidebar(container)?.classList.contains("sidebar-beside"), "shown by Ctrl+B");
  });
});

describe("the panel", () => {
  test("is the same centred panel at every width, with no edge to resize", async () => {
    const native = new FakeNative();
    native.layoutAnswer = { layout: { version: 1, panel_open: true, panel_surface: "core", panel_width: 400 },
                            stored: true };
    const { container } = await openWindow(show, until, native);
    for (const width of [1440, 900, 899, 520]) {
      await resizeTo(width);
      const panel = await until(() => panelOf(container, "Core"), `the panel at ${width}`);
      expect(panel.querySelector('[role="separator"]')).toBeNull();
      expect(panel.style.width).toBe("");
      expect(panel.closest(".modal-layer")).not.toBeNull();
    }
  });
});

describe("going to the message box", () => {
  // The composer may be behind the panel and the covering sidebar: it is
  // shown before it takes focus, as "Show the conversation" does.
  test("closes the panel and the covering sidebar and focuses the composer", async () => {
    const { container } = await openWindow(show, until);
    await resizeTo(899);
    await until(() => shell(container).getAttribute("data-mode") === "covering", "covering mode");
    await click(toggle(container));
    await until(() => sidebar(container)?.classList.contains("sidebar-covering"), "covering");
    await showSurface(container, "Core");
    await until(() => panelOf(container, "Core"), "the panel");
    await key("k", { ctrlKey: true });
    await until(() => container.querySelector('[role="dialog"][aria-label="Commands"]'), "the palette");
    await click(container.querySelector<HTMLElement>('[role="option"][data-command="composer.focus"]')!);
    await until(() => panelOf(container, "Core") === null, "the panel closed");
    expect(sidebar(container)).toBeNull();
    expect(document.activeElement).toBe(container.querySelector('[data-testid="composer"] textarea'));
  });
});
